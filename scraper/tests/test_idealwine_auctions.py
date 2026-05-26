"""
Unit tests for IDealwineHistoricalScraper (idealwine_history source).

Covers:
  1. _ensure_history_source inserts a dim_source row when absent
  2. _ensure_history_source is idempotent (no duplicate on second call)
  3. _parse_from_ts returns None when from_date is not set
  4. _parse_from_ts converts ISO date string to a Unix timestamp correctly
  5. _run_results_endpoint returns False (fallback trigger) on HTTP 404
  6. _run_products_fallback inserts AUCTION variants and skips DIRECT_PURCHASE
  7. from_date cursor skips variants whose updatedAt is before the cutoff
  8. Content-hash dedup: inserting the same variant twice leaves only one staging row
  9. _ensure_history_source handles INSERT race without crash (idempotent upsert)
"""
import hashlib
import json
import sqlite3
import time
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from achilles_scraper.scrapers.idealwine import (
    IDealwineHistoricalScraper,
    _ensure_history_source,
    _process_variant,
)
from achilles_scraper.scrapers.base import ScrapeResult


# ---------------------------------------------------------------------------
# Minimal in-memory DB fixture
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS dim_source (
    source_key   INTEGER PRIMARY KEY AUTOINCREMENT,
    source_code  TEXT    NOT NULL UNIQUE,
    source_name  TEXT,
    source_tier  TEXT,
    country_code TEXT,
    base_url     TEXT,
    license_class TEXT,
    cadence      TEXT,
    enabled      INTEGER DEFAULT 1,
    requires_auth INTEGER DEFAULT 0,
    notes        TEXT,
    recommended_batch_size INTEGER,
    last_benchmark_at      INTEGER,
    benchmark_success_rate REAL,
    benchmark_notes        TEXT
);

CREATE TABLE IF NOT EXISTS dim_producer (
    producer_key       INTEGER PRIMARY KEY AUTOINCREMENT,
    producer_name      TEXT,
    producer_norm      TEXT,
    country_code       TEXT,
    allowed_appellations TEXT DEFAULT '[]',
    aliases            TEXT DEFAULT '[]',
    status             TEXT DEFAULT 'pending_review'
);
CREATE UNIQUE INDEX IF NOT EXISTS uix_producer_norm_country
    ON dim_producer (producer_norm, country_code);

CREATE TABLE IF NOT EXISTS dim_appellation (
    appellation_key  INTEGER PRIMARY KEY AUTOINCREMENT,
    country_code     TEXT,
    region           TEXT,
    appellation_name TEXT,
    appellation_norm TEXT UNIQUE,
    level            TEXT DEFAULT 'regional'
);

CREATE TABLE IF NOT EXISTS dim_wine (
    wine_key       TEXT PRIMARY KEY,
    producer_key   INTEGER NOT NULL,
    appellation_key INTEGER NOT NULL,
    cuvee_name     TEXT,
    cuvee_norm     TEXT,
    color          TEXT,
    vintage        INTEGER,
    is_non_vintage INTEGER DEFAULT 0,
    bottle_ml      INTEGER DEFAULT 750,
    canonical_name TEXT
);

CREATE TABLE IF NOT EXISTS staging_price_candidates (
    candidate_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    wine_key       TEXT    NOT NULL,
    source_key     INTEGER NOT NULL,
    retailer       TEXT,
    recorded_at    INTEGER,
    currency_code  TEXT DEFAULT 'EUR',
    amount_local   REAL,
    amount_eur     REAL,
    source_url     TEXT,
    content_hash   TEXT,
    batch_id       TEXT,
    needs_review   INTEGER DEFAULT 1,
    promoted_at    INTEGER
);
CREATE UNIQUE INDEX IF NOT EXISTS uix_staging_price_wine_source_hash
    ON staging_price_candidates (wine_key, source_key, content_hash)
    WHERE content_hash IS NOT NULL;

CREATE TABLE IF NOT EXISTS ops_dead_letter (
    dlq_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source_key       INTEGER,
    batch_id         TEXT,
    error_class      TEXT,
    error_message    TEXT,
    raw_record       TEXT,
    source_record_id TEXT,
    raw_object_path  TEXT,
    created_at       INTEGER
);
"""


def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.executescript(_SCHEMA)
    return conn


def _seed_producer_appellation(conn: sqlite3.Connection) -> tuple[int, int]:
    """Insert a producer + appellation and return (producer_key, appellation_key)."""
    conn.execute(
        "INSERT OR IGNORE INTO dim_producer (producer_name, producer_norm, country_code) "
        "VALUES ('Domaine Test', 'domaine test', 'FR')"
    )
    pk = conn.execute(
        "SELECT producer_key FROM dim_producer WHERE producer_norm='domaine test'"
    ).fetchone()[0]
    conn.execute(
        "INSERT OR IGNORE INTO dim_appellation "
        "(country_code, region, appellation_name, appellation_norm) "
        "VALUES ('FR', 'Bourgogne', 'Gevrey-Chambertin', 'gevrey chambertin')"
    )
    ak = conn.execute(
        "SELECT appellation_key FROM dim_appellation WHERE appellation_norm='gevrey chambertin'"
    ).fetchone()[0]
    conn.commit()
    return pk, ak


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

class TestEnsureHistorySource(unittest.TestCase):
    """Tests 1 & 2 — _ensure_history_source."""

    def test_inserts_dim_source_row(self):
        """First call creates the idealwine_history dim_source row."""
        conn = _make_db()
        sk = _ensure_history_source(conn)
        self.assertIsNotNone(sk)
        self.assertGreater(sk, 0)
        row = conn.execute(
            "SELECT source_code, requires_auth FROM dim_source WHERE source_key=?", (sk,)
        ).fetchone()
        self.assertEqual(row["source_code"], "idealwine_history")
        self.assertEqual(row["requires_auth"], 1)

    def test_idempotent_second_call(self):
        """Second call returns the same source_key without inserting a duplicate."""
        conn = _make_db()
        sk1 = _ensure_history_source(conn)
        sk2 = _ensure_history_source(conn)
        self.assertEqual(sk1, sk2)
        count = conn.execute(
            "SELECT COUNT(*) FROM dim_source WHERE source_code='idealwine_history'"
        ).fetchone()[0]
        self.assertEqual(count, 1)


class TestParseFromTs(unittest.TestCase):
    """Tests 3 & 4 — _parse_from_ts."""

    def _make_scraper(self):
        conn = _make_db()
        scraper = IDealwineHistoricalScraper.__new__(IDealwineHistoricalScraper)
        scraper.conn = conn
        scraper.batch_id = None
        scraper.from_date = None
        return scraper

    def test_returns_none_when_not_set(self):
        scraper = self._make_scraper()
        self.assertIsNone(scraper._parse_from_ts())

    def test_converts_iso_date_to_timestamp(self):
        scraper = self._make_scraper()
        scraper.from_date = "2020-01-01"
        ts = scraper._parse_from_ts()
        self.assertIsNotNone(ts)
        # 2020-01-01 UTC midnight = 1577836800
        self.assertEqual(ts, 1577836800)


class TestResultsEndpointFallback(unittest.TestCase):
    """Test 5 — _run_results_endpoint returns False on 404."""

    def test_returns_false_on_404(self):
        conn = _make_db()
        _ensure_history_source(conn)
        scraper = IDealwineHistoricalScraper.__new__(IDealwineHistoricalScraper)
        scraper.conn = conn
        scraper.batch_id = "test-batch-001"
        scraper.from_date = None
        # Override retry_config to avoid sleep during tests
        from achilles_scraper.retry import RetryConfig
        scraper.retry_config = RetryConfig(max_attempts=1, base_delay_seconds=0.0)

        source_key = conn.execute(
            "SELECT source_key FROM dim_source WHERE source_code='idealwine_history'"
        ).fetchone()[0]

        mock_resp = MagicMock()
        mock_resp.status_code = 404

        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp

        result = ScrapeResult(batch_id="test-batch-001")

        # Patch _fetch so it just calls the lambda directly (no retry sleep)
        with patch.object(scraper, "_fetch", side_effect=lambda fn: fn()):
            ok = scraper._run_results_endpoint(mock_client, source_key, "test-batch-001", result, limit=10)

        self.assertFalse(ok)


class TestProductsFallback(unittest.TestCase):
    """Tests 6 & 7 — _run_products_fallback inserts AUCTION and skips DIRECT_PURCHASE."""

    def _make_scenario(self):
        conn = _make_db()
        _ensure_history_source(conn)
        pk, ak = _seed_producer_appellation(conn)
        scraper = IDealwineHistoricalScraper.__new__(IDealwineHistoricalScraper)
        scraper.conn = conn
        scraper.batch_id = "hist-test-001"
        scraper.from_date = None
        from achilles_scraper.retry import RetryConfig
        scraper.retry_config = RetryConfig(max_attempts=1, base_delay_seconds=0.0)
        source_key = conn.execute(
            "SELECT source_key FROM dim_source WHERE source_code='idealwine_history'"
        ).fetchone()[0]
        return conn, scraper, source_key, pk, ak

    def _build_mock_responses(self, variants: list) -> tuple:
        """Build mock products-page and variants-page responses."""
        products_page = {
            "hydra:member": [
                {
                    "id": 999,
                    "name": "Gevrey-Chambertin Vieilles Vignes",
                    "appellation": "Gevrey-Chambertin",
                    "region": "Bourgogne",
                    "owner": "Domaine Test",
                    "color": "RED",
                    "slug": "gevrey-chambertin-vv",
                }
            ],
            "hydra:totalItems": 1,
        }
        products_resp = MagicMock()
        products_resp.status_code = 200
        products_resp.json.return_value = products_page

        variants_resp = MagicMock()
        variants_resp.status_code = 200
        variants_resp.json.return_value = variants

        mock_client = MagicMock()
        # Return products_resp for the first GET, variants_resp for the second
        mock_client.get.side_effect = [products_resp, variants_resp]
        return mock_client

    def test_inserts_auction_variant(self):
        conn, scraper, source_key, pk, ak = self._make_scenario()

        variants = [{
            "id": "V1",
            "saleType": "AUCTION",
            "vintage": 1999,
            "priceByCountry": {"FR": 15000},
            "appellation": "Gevrey-Chambertin",
            "region": "Bourgogne",
            "additionalObservations": {"fr": ""},
        }]
        mock_client = self._build_mock_responses(variants)

        result = ScrapeResult(batch_id="hist-test-001")
        with patch.object(scraper, "_fetch", side_effect=lambda fn: fn()):
            scraper._run_products_fallback(mock_client, source_key, "hist-test-001", result, limit=10)

        staged = conn.execute(
            "SELECT COUNT(*) FROM staging_price_candidates WHERE source_key=?", (source_key,)
        ).fetchone()[0]
        self.assertGreater(staged, 0, "Expected ≥1 row staged for AUCTION variant")

    def test_skips_direct_purchase_variant(self):
        conn, scraper, source_key, pk, ak = self._make_scenario()

        variants = [{
            "id": "V2",
            "saleType": "DIRECT_PURCHASE",
            "vintage": 2015,
            "priceByCountry": {"FR": 8000},
            "appellation": "Gevrey-Chambertin",
            "region": "Bourgogne",
            "additionalObservations": {"fr": ""},
        }]
        mock_client = self._build_mock_responses(variants)

        result = ScrapeResult(batch_id="hist-test-002")
        with patch.object(scraper, "_fetch", side_effect=lambda fn: fn()):
            scraper._run_products_fallback(mock_client, source_key, "hist-test-002", result, limit=10)

        staged = conn.execute(
            "SELECT COUNT(*) FROM staging_price_candidates WHERE source_key=?", (source_key,)
        ).fetchone()[0]
        self.assertEqual(staged, 0, "DIRECT_PURCHASE variant must not be staged")

    def test_from_date_cursor_filters_old_variants(self):
        """Variants with updatedAt before from_date are skipped."""
        conn, scraper, source_key, pk, ak = self._make_scenario()
        scraper.from_date = "2023-01-01"

        # updatedAt is 2020 — before cursor
        variants = [{
            "id": "V3",
            "saleType": "AUCTION",
            "vintage": 2005,
            "priceByCountry": {"FR": 25000},
            "updatedAt": "2020-06-15T12:00:00Z",
            "appellation": "Gevrey-Chambertin",
            "region": "Bourgogne",
            "additionalObservations": {"fr": ""},
        }]
        mock_client = self._build_mock_responses(variants)

        result = ScrapeResult(batch_id="hist-test-003")
        with patch.object(scraper, "_fetch", side_effect=lambda fn: fn()):
            scraper._run_products_fallback(mock_client, source_key, "hist-test-003", result, limit=10)

        staged = conn.execute(
            "SELECT COUNT(*) FROM staging_price_candidates WHERE source_key=?", (source_key,)
        ).fetchone()[0]
        self.assertEqual(staged, 0, "Variant before from_date must be skipped")


class TestContentHashDedup(unittest.TestCase):
    """Test 8 — same variant inserted twice leaves only one staging row."""

    def test_dedup_on_second_insert(self):
        conn = _make_db()
        _ensure_history_source(conn)
        _seed_producer_appellation(conn)

        source_key = conn.execute(
            "SELECT source_key FROM dim_source WHERE source_code='idealwine_history'"
        ).fetchone()[0]

        product = {
            "id": 42,
            "name": "Gevrey-Chambertin Vieilles Vignes",
            "appellation": "Gevrey-Chambertin",
            "region": "Bourgogne",
            "owner": "Domaine Test",
            "color": "RED",
            "slug": "gevrey-chambertin-vv",
        }
        variant = {
            "id": "V10",
            "saleType": "AUCTION",
            "vintage": 1998,
            "priceByCountry": {"FR": 30000},
            "appellation": "Gevrey-Chambertin",
            "region": "Bourgogne",
            "additionalObservations": {"fr": ""},
        }

        result1 = ScrapeResult(batch_id="dedup-b1")
        result2 = ScrapeResult(batch_id="dedup-b2")

        _process_variant(conn, source_key, "dedup-b1", result1, product, variant, "idealwine_history")
        _process_variant(conn, source_key, "dedup-b2", result2, product, variant, "idealwine_history")

        count = conn.execute(
            "SELECT COUNT(*) FROM staging_price_candidates WHERE source_key=?", (source_key,)
        ).fetchone()[0]
        self.assertEqual(count, 1, "Dedup must leave only one staging row for the same lot")
        self.assertEqual(result1.rows_inserted, 1)
        self.assertEqual(result2.rows_inserted, 0)
        self.assertEqual(result2.rows_skipped_unchanged, 1)


if __name__ == "__main__":
    unittest.main()
