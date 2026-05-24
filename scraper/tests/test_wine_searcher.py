"""
Unit tests for the Wine-Searcher Pro API scraper.

Tests use an in-memory SQLite DB and mock httpx so no real HTTP calls are made.

Covered:
  1.  No API key → single scraper_not_applicable DLQ row, 0 fetched
  2.  Missing dim_source row → ScrapeResult.error set, no crash
  3.  401 response → auth_error DLQ
  4.  403 response → auth_error DLQ
  5.  429 response → auth_error DLQ
  6.  Non-success 5xx → network_error DLQ
  7.  Malformed JSON → parse_error DLQ
  8.  Empty price_list → rows_skipped_unchanged, no DLQ
  9.  Valid offers → staging candidates inserted, deduplication on second insert
  10. Non-EUR currency offers are skipped
"""
import os
import sqlite3
import unittest
from unittest.mock import MagicMock, patch

from achilles_scraper.scrapers.wine_searcher import WineSearcherScraper, _build_url, _parse_price_list


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = OFF")   # relaxed for unit tests
    conn.executescript("""
        CREATE TABLE dim_source (
            source_key  INTEGER PRIMARY KEY AUTOINCREMENT,
            source_code TEXT NOT NULL UNIQUE
        );
        CREATE TABLE dim_producer (
            producer_key   INTEGER PRIMARY KEY AUTOINCREMENT,
            producer_name  TEXT NOT NULL,
            producer_norm  TEXT NOT NULL,
            country_code   TEXT NOT NULL DEFAULT 'FR',
            coverage_tier  TEXT,
            allowed_appellations TEXT DEFAULT '[]',
            aliases        TEXT DEFAULT '[]',
            status         TEXT DEFAULT 'active'
        );
        CREATE TABLE dim_appellation (
            appellation_key  INTEGER PRIMARY KEY AUTOINCREMENT,
            appellation_norm TEXT NOT NULL,
            appellation_name TEXT NOT NULL,
            country_code     TEXT NOT NULL DEFAULT 'FR'
        );
        CREATE TABLE dim_wine (
            wine_key       TEXT PRIMARY KEY,
            producer_key   INTEGER NOT NULL,
            appellation_key INTEGER,
            cuvee_name     TEXT,
            cuvee_norm     TEXT,
            color          TEXT,
            vintage        INTEGER,
            is_non_vintage INTEGER DEFAULT 0,
            bottle_ml      INTEGER DEFAULT 750,
            canonical_name TEXT
        );
        CREATE TABLE staging_price_candidates (
            candidate_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            wine_key       TEXT    NOT NULL,
            source_key     INTEGER NOT NULL,
            retailer       TEXT,
            recorded_at    INTEGER,
            currency_code  TEXT    DEFAULT 'EUR',
            amount_local   REAL,
            amount_eur     REAL,
            source_url     TEXT,
            content_hash   TEXT,
            batch_id       TEXT,
            needs_review   INTEGER DEFAULT 1
        );
        CREATE UNIQUE INDEX uix_staging_wine_source_hash
            ON staging_price_candidates (wine_key, source_key, content_hash);
        CREATE TABLE ops_dead_letter (
            dlq_key        INTEGER PRIMARY KEY AUTOINCREMENT,
            source_key     INTEGER,
            batch_id       TEXT,
            error_class    TEXT,
            error_message  TEXT,
            raw_record     TEXT,
            source_record_id TEXT,
            raw_object_path  TEXT,
            created_at     INTEGER
        );
    """)
    # Seed: wine_searcher source + one notable French wine
    conn.execute("INSERT INTO dim_source (source_code) VALUES ('wine_searcher')")
    conn.execute(
        "INSERT INTO dim_producer (producer_name, producer_norm, country_code, coverage_tier) "
        "VALUES ('Chateau Margaux', 'chateau margaux', 'FR', 'notable')"
    )
    conn.execute(
        "INSERT INTO dim_appellation (appellation_norm, appellation_name, country_code) "
        "VALUES ('margaux', 'Margaux', 'FR')"
    )
    conn.execute(
        "INSERT INTO dim_wine (wine_key, producer_key, appellation_key, cuvee_name, "
        "cuvee_norm, color, vintage) "
        "VALUES ('abc123def456abc1', 1, 1, 'Chateau Margaux', 'chateau margaux', 'red', 2015)"
    )
    conn.commit()
    return conn


def _make_resp(status: int, body: str | dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.is_success = (200 <= status < 300)
    if isinstance(body, dict):
        resp.json.return_value = body
        resp.text = str(body)
    elif isinstance(body, str):
        resp.json.side_effect = ValueError("bad json")
        resp.text = body
    else:
        resp.json.return_value = {}
        resp.text = ""
    return resp


# ---------------------------------------------------------------------------
# URL + parser helpers
# ---------------------------------------------------------------------------

class BuildUrlTests(unittest.TestCase):
    def test_vintage_encoded(self):
        url = _build_url("Chateau Margaux", "", 2015, "TESTKEY")
        self.assertIn("Chateau+Margaux", url)
        self.assertIn("/2015/", url)
        self.assertIn("apikey=TESTKEY", url)

    def test_nv_wine(self):
        url = _build_url("Krug", "Grande Cuvee", None, "KEY")
        self.assertIn("/NV/", url)

    def test_format_json_present(self):
        url = _build_url("X", "Y", 2020, "K")
        self.assertIn("format=json", url)


class ParsePriceListTests(unittest.TestCase):
    def test_top_level_price_list(self):
        raw = {"price_list": [{"store_name": "A", "price": 10}]}
        self.assertEqual(len(_parse_price_list(raw)), 1)

    def test_nested_product_price_list(self):
        raw = {"product": {"price_list": [{"store_name": "B", "price": 20}]}}
        self.assertEqual(len(_parse_price_list(raw)), 1)

    def test_empty_raw(self):
        self.assertEqual(_parse_price_list({}), [])


# ---------------------------------------------------------------------------
# Scraper integration tests
# ---------------------------------------------------------------------------

class WineSearcherScraperTests(unittest.TestCase):
    def setUp(self):
        self.conn = _make_db()

    def _scraper(self):
        s = WineSearcherScraper(self.conn)
        s.batch_id = "batch_test"
        return s

    # 1. No API key
    def test_no_api_key_logs_not_applicable(self):
        env = {k: v for k, v in os.environ.items() if k != "ACHILLES_WINESEARCHER_API_KEY"}
        with patch.dict(os.environ, env, clear=True):
            result = self._scraper().run(limit=10)
        self.assertEqual(result.rows_dlq, 1)
        self.assertEqual(result.rows_fetched, 0)
        dlq_row = self.conn.execute(
            "SELECT error_class FROM ops_dead_letter"
        ).fetchone()
        self.assertIsNotNone(dlq_row)
        self.assertEqual(dlq_row[0], "scraper_not_applicable")

    # 2. Missing dim_source row
    def test_missing_dim_source_returns_error(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE dim_source (source_key INTEGER PRIMARY KEY, source_code TEXT UNIQUE)"
        )
        conn.commit()
        s = WineSearcherScraper(conn)
        with patch.dict(os.environ, {"ACHILLES_WINESEARCHER_API_KEY": "KEY"}):
            result = s.run()
        self.assertIsNotNone(result.error)

    # 3. 401 → auth_error DLQ
    def test_401_logs_auth_error(self):
        resp = _make_resp(401)
        with patch("httpx.Client") as MockClient, \
             patch.dict(os.environ, {"ACHILLES_WINESEARCHER_API_KEY": "BADKEY"}):
            MockClient.return_value.__enter__.return_value.get.return_value = resp
            result = self._scraper().run(limit=1)
        self.assertGreater(result.rows_dlq, 0)
        row = self.conn.execute(
            "SELECT error_class FROM ops_dead_letter WHERE error_class='auth_error'"
        ).fetchone()
        self.assertIsNotNone(row)

    # 4. 403 → auth_error DLQ
    def test_403_logs_auth_error(self):
        resp = _make_resp(403)
        with patch("httpx.Client") as MockClient, \
             patch.dict(os.environ, {"ACHILLES_WINESEARCHER_API_KEY": "KEY"}):
            MockClient.return_value.__enter__.return_value.get.return_value = resp
            result = self._scraper().run(limit=1)
        self.assertGreater(result.rows_dlq, 0)

    # 5. 429 → auth_error DLQ
    def test_429_logs_rate_limit(self):
        resp = _make_resp(429)
        with patch("httpx.Client") as MockClient, \
             patch.dict(os.environ, {"ACHILLES_WINESEARCHER_API_KEY": "KEY"}):
            MockClient.return_value.__enter__.return_value.get.return_value = resp
            result = self._scraper().run(limit=1)
        self.assertGreater(result.rows_dlq, 0)

    # 6. 5xx → network_error DLQ
    def test_5xx_logs_network_error(self):
        resp = _make_resp(503)
        with patch("httpx.Client") as MockClient, \
             patch.dict(os.environ, {"ACHILLES_WINESEARCHER_API_KEY": "KEY"}):
            MockClient.return_value.__enter__.return_value.get.return_value = resp
            result = self._scraper().run(limit=1)
        row = self.conn.execute(
            "SELECT error_class FROM ops_dead_letter"
        ).fetchone()
        self.assertEqual(row[0], "network_error")

    # 7. Malformed JSON → parse_error DLQ
    def test_malformed_json_logs_parse_error(self):
        resp = _make_resp(200, "NOT JSON {{{{")
        with patch("httpx.Client") as MockClient, \
             patch.dict(os.environ, {"ACHILLES_WINESEARCHER_API_KEY": "KEY"}):
            MockClient.return_value.__enter__.return_value.get.return_value = resp
            result = self._scraper().run(limit=1)
        row = self.conn.execute(
            "SELECT error_class FROM ops_dead_letter"
        ).fetchone()
        self.assertEqual(row[0], "parse_error")

    # 8. Empty price_list → skipped, no DLQ
    def test_empty_price_list_skipped(self):
        resp = _make_resp(200, {"price_list": []})
        with patch("httpx.Client") as MockClient, \
             patch.dict(os.environ, {"ACHILLES_WINESEARCHER_API_KEY": "KEY"}):
            MockClient.return_value.__enter__.return_value.get.return_value = resp
            result = self._scraper().run(limit=1)
        self.assertEqual(result.rows_dlq, 0)
        self.assertEqual(result.rows_inserted, 0)
        self.assertGreater(result.rows_skipped_unchanged, 0)

    # 9. Valid offers → inserted; second run → deduped
    def test_valid_offer_inserted_and_deduped(self):
        payload = {
            "price_list": [
                {"store_name": "Chateau Direct", "price": 550.00, "currency": "EUR",
                 "link": "https://example.com/bottle"},
                {"store_name": "Le Sommelier", "price": 570.00, "currency": "EUR",
                 "link": "https://example2.com/bottle"},
            ]
        }
        resp = _make_resp(200, payload)
        env = {"ACHILLES_WINESEARCHER_API_KEY": "KEY"}
        with patch("httpx.Client") as MockClient, patch.dict(os.environ, env):
            MockClient.return_value.__enter__.return_value.get.return_value = resp
            result1 = self._scraper().run(limit=1)

        self.assertEqual(result1.rows_inserted, 2)
        self.assertEqual(result1.rows_dlq, 0)

        # Second run — same hash → deduped
        with patch("httpx.Client") as MockClient, patch.dict(os.environ, env):
            MockClient.return_value.__enter__.return_value.get.return_value = resp
            result2 = self._scraper().run(limit=1)

        self.assertEqual(result2.rows_inserted, 0)
        self.assertEqual(result2.rows_skipped_unchanged, 2)
        total = self.conn.execute(
            "SELECT COUNT(*) FROM staging_price_candidates"
        ).fetchone()[0]
        self.assertEqual(total, 2)

    # 10. Non-EUR currency → skipped
    def test_non_eur_currency_skipped(self):
        payload = {
            "price_list": [
                {"store_name": "US Store", "price": 600.00, "currency": "USD",
                 "link": "https://us.example.com"},
            ]
        }
        resp = _make_resp(200, payload)
        with patch("httpx.Client") as MockClient, \
             patch.dict(os.environ, {"ACHILLES_WINESEARCHER_API_KEY": "KEY"}):
            MockClient.return_value.__enter__.return_value.get.return_value = resp
            result = self._scraper().run(limit=1)
        self.assertEqual(result.rows_inserted, 0)
        self.assertEqual(result.rows_dlq, 0)
        self.assertGreater(result.rows_skipped_unchanged, 0)


if __name__ == "__main__":
    unittest.main()
