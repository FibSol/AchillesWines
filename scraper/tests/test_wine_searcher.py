"""
Unit tests for the Wine-Searcher scraper (Firecrawl CLI markdown approach).

These tests target the CURRENT implementation, which scrapes
wine-searcher.com via the `firecrawl` CLI (subprocess) and parses the
returned markdown into per-merchant listings.  The CLI seam (`_scrape_page`)
and the FX HTTP client (`httpx.Client`) are mocked — no real subprocess, no
real network.

NOTE: an earlier `fcc2ff0` rework briefly used the Firecrawl *search API*
(httpx POST, HTTP status taxonomy, no FX). The module was reworked again to
the CLI/markdown approach since; these tests assert that current behaviour:

  DLQ taxonomy (the only paths that exist now):
    - scraper_not_applicable : firecrawl CLI not found in PATH
    - network_error          : scrape returned no markdown content
    - (ScrapeResult.error)   : dim_source row missing

  Pricing:
    - listings are parsed from markdown by `_parse_listings`
    - prices are FX-converted to EUR via the Frankfurter client
    - EUR prices need no FX call; non-EUR are converted
    - FX unavailable → listing skipped (rows_skipped_unchanged), NOT a DLQ

  Other:
    - empty / no-listing pages → rows_skipped_unchanged
    - vintage not present in the cuvée's DB rows → skipped
    - price outside [_PRICE_MIN_EUR, _PRICE_MAX_EUR] → skipped
    - duplicate listing (same content_hash) → inserted once, then skipped
    - `_build_ws_url` slug construction
    - `_progress_key` / `_mark_attempted` resume bookkeeping
"""
import sqlite3
import unittest
from unittest.mock import MagicMock, patch

from achilles_scraper.scrapers import wine_searcher as ws
from achilles_scraper.scrapers.wine_searcher import (
    WineSearcherScraper,
    _build_ws_url,
    _parse_listings,
    _progress_key,
    _PRICE_MIN_EUR,
)


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
        CREATE TABLE ops_content_hashes (
            url             TEXT PRIMARY KEY,
            source_key      INTEGER,
            last_hash       TEXT,
            last_fetched_at INTEGER,
            fetch_count     INTEGER DEFAULT 0
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
    # Only the 2015 vintage exists in the DB for this cuvée.
    conn.execute(
        "INSERT INTO dim_wine (wine_key, producer_key, appellation_key, "
        "cuvee_name, cuvee_norm, color, vintage) "
        "VALUES ('abc123def456abc1', 1, 1, 'Chateau Margaux', 'chateau margaux', 'red', 2015)"
    )
    conn.commit()
    return conn


def _fx_resp(rate: float) -> MagicMock:
    """Mock a successful Frankfurter response: 1 unit of `from` = `rate` EUR."""
    resp = MagicMock()
    resp.is_success = True
    resp.json.return_value = {"rates": {"EUR": rate}}
    return resp


def _listing_md(merchant: str, price_str: str, vintage="2015",
                offer="Retail", shop="https://shop.example.com/x") -> str:
    """
    Build one Wine-Searcher-style merchant block as it appears in the scraped
    markdown.  `_parse_listings` reads a 35-line window after the merchant link,
    so each field sits on its own line.
    """
    return "\n".join([
        f"[{merchant}](https://www.wine-searcher.com/merchant/1000)",
        "",
        "France",
        "",
        price_str,
        "",
        str(vintage),
        "",
        offer,
        "",
        f"[Go to shop]({shop})",
        "",
    ])


def _page_md(*blocks: str) -> str:
    """Wrap merchant blocks in some page chrome."""
    return "Find the best price on Chateau Margaux\n\n" + "\n".join(blocks) + "\n"


# ---------------------------------------------------------------------------
# Scraper integration tests (current Firecrawl-CLI behaviour)
# ---------------------------------------------------------------------------

class WineSearcherScraperTests(unittest.TestCase):

    def setUp(self):
        self.conn = _make_db()
        # Avoid the 1s inter-request sleep in every loop-reaching test.
        sleep_patch = patch.object(ws.time, "sleep", lambda *_: None)
        sleep_patch.start()
        self.addCleanup(sleep_patch.stop)

    def _scraper(self):
        s = WineSearcherScraper(self.conn)
        s.batch_id = "batch_test"
        return s

    def _run_with_markdown(self, markdown, fx=None, limit=1):
        """
        Run the scraper with the CLI seam (`_scrape_page`) mocked to return
        `markdown` (str or None), the CLI presence forced true, and httpx.Client
        mocked for FX (its .get returns `fx` if provided).
        """
        mock_fx_client = MagicMock()
        if fx is not None:
            mock_fx_client.get.return_value = fx
        with patch.object(ws.shutil, "which", return_value="/usr/bin/firecrawl"), \
             patch.object(ws, "_scrape_page", return_value=markdown), \
             patch("httpx.Client", return_value=mock_fx_client):
            result = self._scraper().run(limit=limit)
        return result, mock_fx_client

    # 1. firecrawl CLI not found → scraper_not_applicable, nothing fetched
    def test_no_firecrawl_cli_logs_not_applicable(self):
        with patch.object(ws.shutil, "which", return_value=None):
            result = self._scraper().run(limit=10)
        self.assertEqual(result.rows_dlq, 1)
        self.assertEqual(result.rows_fetched, 0)
        row = self.conn.execute("SELECT error_class FROM ops_dead_letter").fetchone()
        self.assertEqual(row[0], "scraper_not_applicable")

    # 2. Missing dim_source row → ScrapeResult.error, no crash
    def test_missing_dim_source_returns_error(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE dim_source (source_key INTEGER PRIMARY KEY, source_code TEXT UNIQUE)"
        )
        conn.commit()
        result = WineSearcherScraper(conn).run()
        self.assertIsNotNone(result.error)

    # 3. Scrape returned no content → network_error DLQ
    def test_scrape_no_content_logs_network_error(self):
        result, _ = self._run_with_markdown(None)
        self.assertEqual(result.rows_fetched, 1)
        self.assertGreater(result.rows_dlq, 0)
        row = self.conn.execute("SELECT error_class FROM ops_dead_letter").fetchone()
        self.assertEqual(row[0], "network_error")

    # 4. Page with no merchant listings → skipped, no DLQ, no insert
    def test_empty_page_skipped(self):
        result, _ = self._run_with_markdown(_page_md())
        self.assertEqual(result.rows_dlq, 0)
        self.assertEqual(result.rows_inserted, 0)
        self.assertGreater(result.rows_skipped_unchanged, 0)

    # 5. EUR listing → direct insert, no FX call
    def test_eur_listing_inserted_no_fx(self):
        md = _page_md(_listing_md("Millesima", "€ 152.95 / 750ml"))
        result, fx_client = self._run_with_markdown(md)
        self.assertEqual(result.rows_inserted, 1)
        self.assertEqual(result.rows_dlq, 0)
        fx_client.get.assert_not_called()  # EUR needs no Frankfurter lookup
        row = self.conn.execute(
            "SELECT amount_eur, currency_code, retailer FROM staging_price_candidates"
        ).fetchone()
        self.assertAlmostEqual(row[0], 152.95)
        self.assertEqual(row[1], "EUR")
        self.assertEqual(row[2], "Millesima")

    # 6. USD listing → FX-converted to EUR + insert
    def test_usd_listing_converted_and_inserted(self):
        md = _page_md(_listing_md("Wine.com", "$ 200.00 / 750ml"))
        # 1 USD = 0.9 EUR → 200 * 0.9 = 180 EUR
        result, fx_client = self._run_with_markdown(md, fx=_fx_resp(0.9))
        self.assertEqual(result.rows_inserted, 1)
        self.assertEqual(result.rows_dlq, 0)
        fx_client.get.assert_called()  # non-EUR triggers a Frankfurter lookup
        row = self.conn.execute(
            "SELECT amount_eur, currency_code FROM staging_price_candidates"
        ).fetchone()
        self.assertAlmostEqual(row[0], 180.0)
        self.assertEqual(row[1], "EUR")

    # 7. FX unavailable → listing skipped (NOT a DLQ)
    def test_fx_unavailable_skips_listing(self):
        md = _page_md(_listing_md("Wine.com", "$ 500.00 / 750ml"))
        bad_fx = MagicMock()
        bad_fx.is_success = False
        bad_fx.json.return_value = {}
        result, _ = self._run_with_markdown(md, fx=bad_fx)
        self.assertEqual(result.rows_inserted, 0)
        self.assertEqual(result.rows_dlq, 0)
        self.assertGreater(result.rows_skipped_unchanged, 0)

    # 8. Vintage not present in the cuvée's DB rows → skipped
    def test_vintage_not_in_db_skipped(self):
        # DB only has 2015; this listing is 2010.
        md = _page_md(_listing_md("Millesima", "€ 300.00 / 750ml", vintage="2010"))
        result, _ = self._run_with_markdown(md)
        self.assertEqual(result.rows_inserted, 0)
        self.assertEqual(result.rows_dlq, 0)
        self.assertGreater(result.rows_skipped_unchanged, 0)

    # 9. Price below the EUR floor → skipped
    def test_price_below_floor_skipped(self):
        self.assertGreater(_PRICE_MIN_EUR, 1.0)  # guard the fixture's intent
        md = _page_md(_listing_md("Millesima", "€ 1.00 / 750ml"))
        result, _ = self._run_with_markdown(md)
        self.assertEqual(result.rows_inserted, 0)
        self.assertGreater(result.rows_skipped_unchanged, 0)

    # 10. Duplicate listing (same content_hash) → inserted once, then skipped
    def test_dedup_same_content_hash(self):
        block = _listing_md("Millesima", "€ 152.95 / 750ml")
        md = _page_md(block, block)  # identical listing twice
        result, _ = self._run_with_markdown(md)
        self.assertEqual(result.rows_inserted, 1)
        self.assertEqual(result.rows_skipped_unchanged, 1)
        total = self.conn.execute(
            "SELECT COUNT(*) FROM staging_price_candidates"
        ).fetchone()[0]
        self.assertEqual(total, 1)

    # 11. _mark_attempted bookkeeping excludes the cuvée on the next load
    def test_attempt_recorded_and_resumes(self):
        md = _page_md(_listing_md("Millesima", "€ 152.95 / 750ml"))
        self._run_with_markdown(md)
        # The cuvée is now recorded in ops_content_hashes …
        hashes = self.conn.execute(
            "SELECT url, last_hash FROM ops_content_hashes"
        ).fetchall()
        self.assertEqual(len(hashes), 1)
        self.assertTrue(hashes[0][0].startswith("ws_cuvee:"))
        self.assertEqual(hashes[0][1], "attempted")
        # … so a second run finds nothing to scrape (resume cursor advanced).
        result2, _ = self._run_with_markdown(md)
        self.assertEqual(result2.rows_fetched, 0)
        self.assertEqual(result2.rows_inserted, 0)


# ---------------------------------------------------------------------------
# Pure-function unit tests
# ---------------------------------------------------------------------------

class BuildWsUrlTests(unittest.TestCase):

    def test_producer_only(self):
        url = _build_ws_url({"producer_norm": "chateau margaux", "cuvee_norm": None})
        self.assertEqual(url, "https://www.wine-searcher.com/find/chateau+margaux?sl-cur=EUR")

    def test_cuvee_same_as_producer_not_duplicated(self):
        url = _build_ws_url(
            {"producer_norm": "chateau margaux", "cuvee_norm": "chateau margaux"}
        )
        self.assertEqual(url, "https://www.wine-searcher.com/find/chateau+margaux?sl-cur=EUR")

    def test_cuvee_tokens_appended(self):
        url = _build_ws_url(
            {"producer_norm": "domaine leflaive", "cuvee_norm": "les pucelles"}
        )
        self.assertEqual(
            url,
            "https://www.wine-searcher.com/find/domaine+leflaive+les+pucelles?sl-cur=EUR",
        )


class ProgressKeyTests(unittest.TestCase):

    def test_key_format(self):
        self.assertEqual(
            _progress_key({"producer_norm": "chateau margaux", "cuvee_norm": "grand vin"}),
            "ws_cuvee:chateau margaux|grand vin",
        )

    def test_key_handles_missing_cuvee(self):
        self.assertEqual(
            _progress_key({"producer_norm": "chateau margaux", "cuvee_norm": None}),
            "ws_cuvee:chateau margaux|",
        )


class ParseListingsTests(unittest.TestCase):

    def test_extracts_all_fields(self):
        md = (
            "[Millesima](https://www.wine-searcher.com/merchant/1000)\n"
            "\nFrance\n\n"
            "€ 152.95 / 750ml\n"
            "\n2015\n\nRetail\n\n"
            "[Go to shop](https://www.millesima.com/x)\n"
        )
        listings = _parse_listings(md)
        self.assertEqual(len(listings), 1)
        lst = listings[0]
        self.assertEqual(lst["retailer"], "Millesima")
        self.assertAlmostEqual(lst["price_local"], 152.95)
        self.assertEqual(lst["currency"], "EUR")
        self.assertEqual(lst["vintage"], 2015)
        self.assertEqual(lst["offer_type"], "Retail")
        self.assertEqual(lst["source_url"], "https://www.millesima.com/x")

    def test_usd_currency_and_comma_thousands(self):
        md = (
            "[Wine.com](https://www.wine-searcher.com/merchant/1000)\n"
            "$ 2,000.00 / 750ml\n2015\n"
            "[Go to shop](https://wine.com/x)\n"
        )
        listings = _parse_listings(md)
        self.assertEqual(len(listings), 1)
        self.assertEqual(listings[0]["currency"], "USD")
        self.assertAlmostEqual(listings[0]["price_local"], 2000.0)

    def test_merchant_without_price_is_skipped(self):
        md = (
            "[Millesima](https://www.wine-searcher.com/merchant/1000)\n"
            "France\nNo price here\n"
        )
        self.assertEqual(_parse_listings(md), [])

    def test_empty_markdown(self):
        self.assertEqual(_parse_listings(""), [])


if __name__ == "__main__":
    unittest.main()
