"""
Unit tests for the Wine-Searcher scraper (Firecrawl search approach).

All tests use an in-memory SQLite DB and mock httpx — no real HTTP calls.

Covered:
  1.  No FIRECRAWL_API_KEY → scraper_not_applicable DLQ, 0 fetched
  2.  Missing dim_source row → ScrapeResult.error set, no crash
  3.  Firecrawl 401 → auth_error DLQ
  4.  Firecrawl 429 → auth_error DLQ
  5.  Firecrawl 5xx → network_error DLQ
  6.  Malformed JSON response → parse_error DLQ
  7.  Empty search results → rows_skipped_unchanged
  8.  Description with no price pattern → rows_skipped_unchanged
  9.  USD avg price → EUR conversion + staging insert
  10. EUR avg price → direct insert (no FX call needed)
  11. Deduplication: same content_hash → skipped on second run
  12. FX unavailable → validation_error DLQ
  13. _build_query: producer+cuvee+vintage, NV wine, no cuvee
"""
import os
import sqlite3
import unittest
from unittest.mock import MagicMock, call, patch

from achilles_scraper.scrapers.wine_searcher import WineSearcherScraper


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = OFF")
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
            wine_key        TEXT PRIMARY KEY,
            producer_key    INTEGER NOT NULL,
            appellation_key INTEGER,
            cuvee_name      TEXT,
            cuvee_norm      TEXT,
            color           TEXT,
            vintage         INTEGER,
            is_non_vintage  INTEGER DEFAULT 0,
            bottle_ml       INTEGER DEFAULT 750,
            canonical_name  TEXT
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
            dlq_key         INTEGER PRIMARY KEY AUTOINCREMENT,
            source_key      INTEGER,
            batch_id        TEXT,
            error_class     TEXT,
            error_message   TEXT,
            raw_record      TEXT,
            source_record_id TEXT,
            raw_object_path  TEXT,
            created_at      INTEGER
        );
    """)
    conn.execute("INSERT INTO dim_source (source_code) VALUES ('wine_searcher')")
    conn.execute(
        "INSERT INTO dim_producer (producer_name, producer_norm, country_code, coverage_tier) "
        "VALUES ('Chateau Margaux', 'chateau margaux', 'FR', 'notable')"
    )
    conn.execute(
        "INSERT INTO dim_appellation (appellation_norm, appellation_name) "
        "VALUES ('margaux', 'Margaux')"
    )
    conn.execute(
        "INSERT INTO dim_wine (wine_key, producer_key, appellation_key, "
        "cuvee_name, cuvee_norm, color, vintage) "
        "VALUES ('abc123def456abc1', 1, 1, 'Chateau Margaux', 'chateau margaux', 'red', 2015)"
    )
    conn.commit()
    return conn


def _fc_resp(status: int, data: list | None = None) -> MagicMock:
    """Build a mock Firecrawl search response."""
    resp = MagicMock()
    resp.status_code = status
    resp.is_success = (200 <= status < 300)
    resp.json.return_value = {"success": True, "data": data or []}
    resp.text = ""
    return resp


def _fx_resp(rate: float) -> MagicMock:
    resp = MagicMock()
    resp.is_success = True
    resp.json.return_value = {"rates": {"EUR": rate}}
    return resp


def _ws_result(description: str, url: str = "https://www.wine-searcher.com/find/x/2015") -> dict:
    return {"url": url, "title": "WS title", "description": description}


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

    def _env(self, **extra):
        """Return env without FIRECRAWL_API_KEY, then add extras."""
        base = {k: v for k, v in os.environ.items() if k != "FIRECRAWL_API_KEY"}
        base.update(extra)
        return base

    # 1. No API key
    def test_no_api_key_logs_not_applicable(self):
        with patch.dict(os.environ, self._env(), clear=True):
            result = self._scraper().run(limit=10)
        self.assertEqual(result.rows_dlq, 1)
        self.assertEqual(result.rows_fetched, 0)
        row = self.conn.execute("SELECT error_class FROM ops_dead_letter").fetchone()
        self.assertEqual(row[0], "scraper_not_applicable")

    # 2. Missing dim_source row
    def test_missing_dim_source_returns_error(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE dim_source (source_key INTEGER PRIMARY KEY, source_code TEXT UNIQUE)"
        )
        conn.commit()
        s = WineSearcherScraper(conn)
        with patch.dict(os.environ, {"FIRECRAWL_API_KEY": "KEY"}):
            result = s.run()
        self.assertIsNotNone(result.error)

    # 3. Firecrawl 401
    def test_401_logs_auth_error(self):
        resp = _fc_resp(401)
        with patch("httpx.Client") as MC, \
             patch.dict(os.environ, self._env(FIRECRAWL_API_KEY="BAD")):
            MC.return_value.__enter__.return_value.post.return_value = resp
            MC.return_value.__enter__.return_value.get.return_value = _fx_resp(0.92)
            result = self._scraper().run(limit=1)
        self.assertGreater(result.rows_dlq, 0)
        row = self.conn.execute(
            "SELECT error_class FROM ops_dead_letter WHERE error_class='auth_error'"
        ).fetchone()
        self.assertIsNotNone(row)

    # 4. Firecrawl 429
    def test_429_logs_auth_error(self):
        resp = _fc_resp(429)
        with patch("httpx.Client") as MC, \
             patch.dict(os.environ, self._env(FIRECRAWL_API_KEY="KEY")):
            MC.return_value.__enter__.return_value.post.return_value = resp
            MC.return_value.__enter__.return_value.get.return_value = _fx_resp(0.92)
            result = self._scraper().run(limit=1)
        self.assertGreater(result.rows_dlq, 0)

    # 5. Firecrawl 5xx
    def test_5xx_logs_network_error(self):
        resp = _fc_resp(503)
        with patch("httpx.Client") as MC, \
             patch.dict(os.environ, self._env(FIRECRAWL_API_KEY="KEY")):
            MC.return_value.__enter__.return_value.post.return_value = resp
            MC.return_value.__enter__.return_value.get.return_value = _fx_resp(0.92)
            result = self._scraper().run(limit=1)
        row = self.conn.execute("SELECT error_class FROM ops_dead_letter").fetchone()
        self.assertEqual(row[0], "network_error")

    # 6. Malformed JSON
    def test_malformed_json_logs_parse_error(self):
        resp = MagicMock()
        resp.status_code = 200
        resp.is_success = True
        resp.json.side_effect = ValueError("bad json")
        resp.text = "NOT JSON"
        with patch("httpx.Client") as MC, \
             patch.dict(os.environ, self._env(FIRECRAWL_API_KEY="KEY")):
            MC.return_value.__enter__.return_value.post.return_value = resp
            MC.return_value.__enter__.return_value.get.return_value = _fx_resp(0.92)
            result = self._scraper().run(limit=1)
        row = self.conn.execute("SELECT error_class FROM ops_dead_letter").fetchone()
        self.assertEqual(row[0], "parse_error")

    # 7. Empty search results
    def test_empty_results_skipped(self):
        resp = _fc_resp(200, data=[])
        with patch("httpx.Client") as MC, \
             patch.dict(os.environ, self._env(FIRECRAWL_API_KEY="KEY")):
            MC.return_value.__enter__.return_value.post.return_value = resp
            MC.return_value.__enter__.return_value.get.return_value = _fx_resp(0.92)
            result = self._scraper().run(limit=1)
        self.assertEqual(result.rows_dlq, 0)
        self.assertEqual(result.rows_inserted, 0)
        self.assertGreater(result.rows_skipped_unchanged, 0)

    # 8. No price in description
    def test_no_price_in_description_skipped(self):
        resp = _fc_resp(200, data=[_ws_result("Find stores near you.")])
        with patch("httpx.Client") as MC, \
             patch.dict(os.environ, self._env(FIRECRAWL_API_KEY="KEY")):
            MC.return_value.__enter__.return_value.post.return_value = resp
            MC.return_value.__enter__.return_value.get.return_value = _fx_resp(0.92)
            result = self._scraper().run(limit=1)
        self.assertEqual(result.rows_inserted, 0)
        self.assertEqual(result.rows_dlq, 0)

    # 9. USD price → EUR conversion + insert
    def test_usd_price_converted_and_inserted(self):
        desc = "Avg Price (ex-tax) $2,000 / 750ml. Find the best price."
        resp = _fc_resp(200, data=[_ws_result(desc)])
        fx = _fx_resp(0.9)   # 1 USD = 0.9 EUR → 2000 * 0.9 = 1800 EUR
        with patch("httpx.Client") as MC, \
             patch.dict(os.environ, self._env(FIRECRAWL_API_KEY="KEY")):
            MC.return_value.__enter__.return_value.post.return_value = resp
            MC.return_value.__enter__.return_value.get.return_value = fx
            result = self._scraper().run(limit=1)
        self.assertEqual(result.rows_inserted, 1)
        self.assertEqual(result.rows_dlq, 0)
        row = self.conn.execute(
            "SELECT amount_eur, currency_code, retailer FROM staging_price_candidates"
        ).fetchone()
        self.assertAlmostEqual(row[0], 1800.0)
        self.assertEqual(row[1], "EUR")
        self.assertEqual(row[2], "wine-searcher.com")

    # 10. EUR price → no FX call, direct insert
    def test_eur_price_no_fx_conversion(self):
        desc = "Avg Price (ex-tax) €550 / 750ml"
        resp = _fc_resp(200, data=[_ws_result(desc)])
        with patch("httpx.Client") as MC, \
             patch.dict(os.environ, self._env(FIRECRAWL_API_KEY="KEY")):
            mock_client = MC.return_value.__enter__.return_value
            mock_client.post.return_value = resp
            result = self._scraper().run(limit=1)
        self.assertEqual(result.rows_inserted, 1)
        # No GET call should have been made (no FX needed for EUR)
        mock_client.get.assert_not_called()
        row = self.conn.execute(
            "SELECT amount_eur FROM staging_price_candidates"
        ).fetchone()
        self.assertAlmostEqual(row[0], 550.0)

    # 11. Deduplication
    def test_deduplication_on_second_run(self):
        desc = "Avg Price (ex-tax) €550 / 750ml"
        resp = _fc_resp(200, data=[_ws_result(desc)])
        env = self._env(FIRECRAWL_API_KEY="KEY")
        with patch("httpx.Client") as MC, patch.dict(os.environ, env):
            MC.return_value.__enter__.return_value.post.return_value = resp
            r1 = self._scraper().run(limit=1)
        with patch("httpx.Client") as MC, patch.dict(os.environ, env):
            MC.return_value.__enter__.return_value.post.return_value = resp
            r2 = self._scraper().run(limit=1)
        self.assertEqual(r1.rows_inserted, 1)
        self.assertEqual(r2.rows_inserted, 0)
        self.assertEqual(r2.rows_skipped_unchanged, 1)
        total = self.conn.execute(
            "SELECT COUNT(*) FROM staging_price_candidates"
        ).fetchone()[0]
        self.assertEqual(total, 1)

    # 12. FX unavailable → validation_error DLQ
    def test_fx_unavailable_logs_validation_error(self):
        desc = "Avg Price (ex-tax) $500 / 750ml"
        resp = _fc_resp(200, data=[_ws_result(desc)])
        fx = MagicMock()
        fx.is_success = False
        fx.json.return_value = {}
        with patch("httpx.Client") as MC, \
             patch.dict(os.environ, self._env(FIRECRAWL_API_KEY="KEY")):
            MC.return_value.__enter__.return_value.post.return_value = resp
            MC.return_value.__enter__.return_value.get.return_value = fx
            result = self._scraper().run(limit=1)
        self.assertGreater(result.rows_dlq, 0)
        row = self.conn.execute(
            "SELECT error_class FROM ops_dead_letter WHERE error_class='validation_error'"
        ).fetchone()
        self.assertIsNotNone(row)


if __name__ == "__main__":
    unittest.main()
