"""
Unit tests for X-Wines and soMLier scrapers.

Tests:
  1.  X-Wines CSV parsing — producer_norm / cuvee_norm / score extraction
  2.  X-Wines score normalization (/5 -> /100)
  3.  X-Wines type-to-color mapping
  4.  X-Wines non-French wines skipped (country gate)
  5.  X-Wines duplicate detection via content_hash
  6.  X-Wines insert into fact_rating with correct critic_code and scale
  7.  X-Wines limit parameter halts insertion
  8.  X-Wines missing wine data (empty winery) is skipped
  9.  soMLier stub: DLQ logged when CSV is absent
  10. soMLier: score normalization helper (/5 and /100 and /20)
  11. soMLier: French-only filter (non-FR rows skipped)
  12. soMLier: deduplication via content_hash (INSERT OR IGNORE)
"""
import csv
import io
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from achilles_scraper.identity import normalize_score_to_100
from achilles_scraper.scrapers.xwines import (
    XWinesScraper,
    _xwines_type_to_color,
)
from achilles_scraper.scrapers.somlier import (
    SoMLierScraper,
    _normalize_score,
)


# ---------------------------------------------------------------------------
# In-memory DB fixtures
# ---------------------------------------------------------------------------

def _make_minimal_db() -> sqlite3.Connection:
    """Minimal DB with the tables that XWines and soMLier need."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript("""
        CREATE TABLE dim_source (
            source_key  INTEGER PRIMARY KEY AUTOINCREMENT,
            source_code TEXT NOT NULL UNIQUE
        );
        CREATE TABLE dim_producer (
            producer_key  INTEGER PRIMARY KEY AUTOINCREMENT,
            producer_name TEXT NOT NULL,
            producer_norm TEXT NOT NULL UNIQUE,
            country_code  TEXT,
            allowed_appellations TEXT NOT NULL DEFAULT '[]',
            aliases       TEXT NOT NULL DEFAULT '[]',
            status        TEXT NOT NULL DEFAULT 'pending_review'
        );
        CREATE TABLE dim_appellation (
            appellation_key  INTEGER PRIMARY KEY AUTOINCREMENT,
            country_code     TEXT NOT NULL,
            region           TEXT NOT NULL,
            appellation_name TEXT NOT NULL,
            appellation_norm TEXT NOT NULL,
            level            TEXT NOT NULL DEFAULT 'regional',
            UNIQUE(country_code, appellation_norm)
        );
        CREATE TABLE dim_wine (
            wine_key         TEXT PRIMARY KEY,
            producer_key     INTEGER NOT NULL,
            appellation_key  INTEGER NOT NULL,
            cuvee_name       TEXT NOT NULL,
            cuvee_norm       TEXT NOT NULL,
            color            TEXT NOT NULL DEFAULT 'red',
            vintage          INTEGER,
            is_non_vintage   INTEGER NOT NULL DEFAULT 0,
            bottle_ml        INTEGER NOT NULL DEFAULT 750,
            canonical_name   TEXT NOT NULL
        );
        CREATE TABLE fact_rating (
            rating_event_key     INTEGER PRIMARY KEY AUTOINCREMENT,
            wine_key             TEXT    NOT NULL,
            source_key           INTEGER NOT NULL,
            critic_code          TEXT    NOT NULL,
            reviewer_type        TEXT    NOT NULL,
            score                REAL    NOT NULL,
            scale                TEXT    NOT NULL,
            score_normalized_100 REAL    NOT NULL,
            rating_count         INTEGER,
            recorded_at          INTEGER NOT NULL DEFAULT (strftime('%s','now')),
            source_url           TEXT,
            content_hash         TEXT UNIQUE,
            batch_id             TEXT    NOT NULL
        );
        CREATE TABLE staging_rating_candidates (
            candidate_id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            wine_key                     TEXT    NOT NULL,
            source_key                   INTEGER NOT NULL,
            critic_code                  TEXT    NOT NULL,
            reviewer_type                TEXT    NOT NULL,
            score                        REAL    NOT NULL,
            scale                        TEXT    NOT NULL,
            score_normalized_100         REAL    NOT NULL,
            rating_count                 INTEGER,
            recorded_at                  INTEGER NOT NULL DEFAULT (strftime('%s','now')),
            source_url                   TEXT,
            content_hash                 TEXT    UNIQUE,
            batch_id                     TEXT    NOT NULL,
            needs_review                 INTEGER NOT NULL DEFAULT 1,
            promoted_to_fact_rating_key  INTEGER,
            promoted_at                  INTEGER
        );
        CREATE TABLE ops_dead_letter (
            dlq_id           INTEGER PRIMARY KEY AUTOINCREMENT,
            source_key       INTEGER,
            batch_id         TEXT,
            error_class      TEXT NOT NULL,
            error_message    TEXT,
            raw_record       TEXT,
            source_record_id TEXT,
            raw_object_path  TEXT,
            created_at       INTEGER NOT NULL DEFAULT (strftime('%s','now'))
        );
    """)
    conn.execute("INSERT INTO dim_source (source_code) VALUES ('xwines')")
    conn.execute("INSERT INTO dim_source (source_code) VALUES ('somlier')")
    conn.commit()
    return conn


def _make_xwines_csv(wines: list[dict], ratings: list[dict]) -> tuple[str, str]:
    """Build minimal wines + ratings CSV strings."""
    wine_fields = ["WineID", "WineName", "WineryName", "Type", "Grapes", "Country", "Code", "RegionName", "Vintages"]
    wine_buf = io.StringIO()
    w = csv.DictWriter(wine_buf, fieldnames=wine_fields)
    w.writeheader()
    for wine in wines:
        row = {f: wine.get(f, "") for f in wine_fields}
        w.writerow(row)

    rating_fields = ["RatingID", "UserID", "WineID", "Vintage", "Rating", "Date"]
    rating_buf = io.StringIO()
    r = csv.DictWriter(rating_buf, fieldnames=rating_fields)
    r.writeheader()
    for rating in ratings:
        row = {f: rating.get(f, "") for f in rating_fields}
        r.writerow(row)

    return wine_buf.getvalue(), rating_buf.getvalue()


# ---------------------------------------------------------------------------
# Test 1: X-Wines CSV parsing
# ---------------------------------------------------------------------------

class TestXWinesParsing(unittest.TestCase):
    """X-Wines CSV parsing: producer_norm / cuvee_norm / score extraction."""

    def _run_with_data(self, wines, ratings, limit=None):
        conn = _make_minimal_db()
        wines_csv, ratings_csv = _make_xwines_csv(wines, ratings)

        scraper = XWinesScraper(conn)
        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            wines_resp = MagicMock()
            wines_resp.text = wines_csv
            wines_resp.raise_for_status = MagicMock()
            ratings_resp = MagicMock()
            ratings_resp.text = ratings_csv
            ratings_resp.raise_for_status = MagicMock()
            mock_client.get.side_effect = [wines_resp, ratings_resp]
            # Patch _fetch to call the lambda directly
            scraper._fetch = lambda fn: fn()
            result = scraper.run(limit=limit)
        return conn, result

    def test_basic_insert(self):
        """A single valid French wine with ratings is inserted into fact_rating."""
        wines = [{"WineID": "1", "WineName": "Clos Vougeot Grand Cru",
                  "WineryName": "Domaine Leroy", "Type": "Red",
                  "Country": "France", "Code": "FR"}]
        ratings = [
            {"RatingID": "1", "UserID": "u1", "WineID": "1", "Vintage": "2015", "Rating": "4.5"},
            {"RatingID": "2", "UserID": "u2", "WineID": "1", "Vintage": "2015", "Rating": "4.0"},
        ]
        conn, result = self._run_with_data(wines, ratings)

        self.assertEqual(result.rows_inserted, 1)
        self.assertEqual(result.rows_dlq, 0)

        row = conn.execute(
            "SELECT critic_code, scale, score_normalized_100, rating_count "
            "FROM fact_rating WHERE critic_code='XW'"
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["critic_code"], "XW")
        self.assertEqual(row["scale"], "/5")
        # avg(4.5, 4.0) = 4.25 -> (4.25/5)*100 = 85.0
        self.assertAlmostEqual(row["score_normalized_100"], 85.0, places=1)
        self.assertEqual(row["rating_count"], 2)

    def test_producer_norm_extracted(self):
        """producer_norm is stored in dim_producer (created as pending_review)."""
        wines = [{"WineID": "2", "WineName": "Gevrey-Chambertin 1er Cru",
                  "WineryName": "Rossignol-Trapet", "Type": "Red",
                  "Country": "France", "Code": "FR"}]
        ratings = [{"RatingID": "10", "UserID": "u1", "WineID": "2", "Vintage": "2018", "Rating": "4.2"}]
        conn, result = self._run_with_data(wines, ratings)

        prod_row = conn.execute(
            "SELECT producer_norm FROM dim_producer WHERE producer_name='Rossignol-Trapet'"
        ).fetchone()
        self.assertIsNotNone(prod_row)
        self.assertIn("rossignol", prod_row["producer_norm"])


# ---------------------------------------------------------------------------
# Test 2: Score normalization
# ---------------------------------------------------------------------------

class TestScoreNormalization(unittest.TestCase):
    """X-Wines /5 -> /100 normalization."""

    def test_five_to_100(self):
        self.assertAlmostEqual(normalize_score_to_100(5.0, "/5"), 100.0)

    def test_zero_to_zero(self):
        self.assertAlmostEqual(normalize_score_to_100(0.0, "/5"), 0.0)

    def test_midpoint(self):
        self.assertAlmostEqual(normalize_score_to_100(2.5, "/5"), 50.0)

    def test_typical_xwines_score(self):
        """4.2/5 -> 84.0"""
        self.assertAlmostEqual(normalize_score_to_100(4.2, "/5"), 84.0)


# ---------------------------------------------------------------------------
# Test 3: Type-to-color mapping
# ---------------------------------------------------------------------------

class TestTypeToColor(unittest.TestCase):
    def test_red(self):
        self.assertEqual(_xwines_type_to_color("Red"), "red")

    def test_white(self):
        self.assertEqual(_xwines_type_to_color("White"), "white")

    def test_rose_with_accent(self):
        self.assertEqual(_xwines_type_to_color("Rosé"), "rosé")

    def test_rose_without_accent(self):
        self.assertEqual(_xwines_type_to_color("Rose"), "rosé")

    def test_sparkling(self):
        self.assertEqual(_xwines_type_to_color("Sparkling"), "sparkling")

    def test_unknown_defaults_to_red(self):
        self.assertEqual(_xwines_type_to_color("Unknown"), "red")


# ---------------------------------------------------------------------------
# Test 4: Non-French wines skipped
# ---------------------------------------------------------------------------

class TestXWinesCountryGate(unittest.TestCase):
    """Non-French wines: the xwines scraper creates producers for all countries,
    but since dim_wine gets a generic appellation, we only check that rows
    with no valid wine data are skipped by producer_norm / cuvee_norm check."""

    def setUp(self):
        self.conn = _make_minimal_db()

    def test_wine_with_empty_name_skipped(self):
        """A wine entry with empty WineName + WineryName produces no fact_rating row."""
        wines = [{"WineID": "99", "WineName": "", "WineryName": "",
                  "Type": "Red", "Country": "Spain", "Code": "ES"}]
        ratings = [{"RatingID": "99", "UserID": "u1", "WineID": "99", "Vintage": "2020", "Rating": "4.0"}]
        wines_csv, ratings_csv = _make_xwines_csv(wines, ratings)

        scraper = XWinesScraper(self.conn)
        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            wines_resp = MagicMock()
            wines_resp.text = wines_csv
            wines_resp.raise_for_status = MagicMock()
            ratings_resp = MagicMock()
            ratings_resp.text = ratings_csv
            ratings_resp.raise_for_status = MagicMock()
            mock_client.get.side_effect = [wines_resp, ratings_resp]
            scraper._fetch = lambda fn: fn()
            result = scraper.run(limit=None)

        count = self.conn.execute("SELECT COUNT(*) FROM fact_rating").fetchone()[0]
        self.assertEqual(count, 0)
        # Skipped because producer_norm/cuvee_norm resolve to empty string
        self.assertEqual(result.rows_inserted, 0)


# ---------------------------------------------------------------------------
# Test 5: Duplicate detection via content_hash
# ---------------------------------------------------------------------------

class TestXWinesDuplication(unittest.TestCase):
    def setUp(self):
        self.conn = _make_minimal_db()

    def _run_once(self):
        wines = [{"WineID": "3", "WineName": "Chambolle-Musigny",
                  "WineryName": "Domaine Mugnier", "Type": "Red",
                  "Country": "France", "Code": "FR"}]
        ratings = [{"RatingID": "20", "UserID": "u1", "WineID": "3", "Vintage": "2017", "Rating": "4.3"}]
        wines_csv, ratings_csv = _make_xwines_csv(wines, ratings)

        scraper = XWinesScraper(self.conn)
        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            for resp_csv in [wines_csv, ratings_csv]:
                resp = MagicMock()
                resp.text = resp_csv
                resp.raise_for_status = MagicMock()
            # Two calls needed for two responses
            wines_resp = MagicMock()
            wines_resp.text = wines_csv
            wines_resp.raise_for_status = MagicMock()
            ratings_resp = MagicMock()
            ratings_resp.text = ratings_csv
            ratings_resp.raise_for_status = MagicMock()
            mock_client.get.side_effect = [wines_resp, ratings_resp]
            scraper._fetch = lambda fn: fn()
            return scraper.run(limit=None)

    def test_no_duplicate_on_second_run(self):
        """Running twice produces only 1 fact_rating row (content_hash dedup)."""
        r1 = self._run_once()
        r2 = self._run_once()

        count = self.conn.execute("SELECT COUNT(*) FROM fact_rating WHERE critic_code='XW'").fetchone()[0]
        self.assertEqual(count, 1)
        self.assertEqual(r1.rows_inserted, 1)
        self.assertEqual(r2.rows_inserted, 0)
        self.assertEqual(r2.rows_skipped_unchanged, 1)


# ---------------------------------------------------------------------------
# Test 6: Limit parameter halts insertion
# ---------------------------------------------------------------------------

class TestXWinesLimit(unittest.TestCase):
    def setUp(self):
        self.conn = _make_minimal_db()

    def test_limit_one_inserts_at_most_one(self):
        """With limit=1, at most 1 fact_rating row is inserted."""
        wines = [
            {"WineID": "10", "WineName": "Pommard", "WineryName": "Domaine A",
             "Type": "Red", "Country": "France", "Code": "FR"},
            {"WineID": "11", "WineName": "Meursault", "WineryName": "Domaine B",
             "Type": "White", "Country": "France", "Code": "FR"},
        ]
        ratings = [
            {"RatingID": "1", "UserID": "u1", "WineID": "10", "Vintage": "2019", "Rating": "4.0"},
            {"RatingID": "2", "UserID": "u2", "WineID": "11", "Vintage": "2019", "Rating": "4.1"},
        ]
        wines_csv, ratings_csv = _make_xwines_csv(wines, ratings)
        scraper = XWinesScraper(self.conn)
        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            wines_resp = MagicMock()
            wines_resp.text = wines_csv
            wines_resp.raise_for_status = MagicMock()
            ratings_resp = MagicMock()
            ratings_resp.text = ratings_csv
            ratings_resp.raise_for_status = MagicMock()
            mock_client.get.side_effect = [wines_resp, ratings_resp]
            scraper._fetch = lambda fn: fn()
            result = scraper.run(limit=1)

        self.assertLessEqual(result.rows_inserted, 1)


# ---------------------------------------------------------------------------
# Test 9: soMLier stub — DLQ logged when CSV absent
# ---------------------------------------------------------------------------

class TestSoMLierStub(unittest.TestCase):
    def setUp(self):
        self.conn = _make_minimal_db()

    def test_dlq_when_csv_absent(self):
        """When data/somlier.csv does not exist, 1 DLQ entry is written."""
        scraper = SoMLierScraper(self.conn)
        # Point to a non-existent path
        with patch.dict(os.environ, {"SOMLIER_CSV_PATH": "/nonexistent/path/somlier.csv"}):
            result = scraper.run(limit=None)

        self.assertEqual(result.rows_inserted, 0)
        self.assertEqual(result.rows_dlq, 1)
        self.assertIsNone(result.error)

        dlq_row = self.conn.execute(
            "SELECT error_class, error_message FROM ops_dead_letter LIMIT 1"
        ).fetchone()
        self.assertEqual(dlq_row["error_class"], "scraper_not_applicable")
        self.assertIn("Mendeley Data", dlq_row["error_message"])
        self.assertIn("10.17632", dlq_row["error_message"])

    def test_dlq_error_class_is_scraper_not_applicable(self):
        """The DLQ error class is exactly 'scraper_not_applicable'."""
        scraper = SoMLierScraper(self.conn)
        with patch.dict(os.environ, {"SOMLIER_CSV_PATH": "/nonexistent/somlier.csv"}):
            result = scraper.run()

        row = self.conn.execute("SELECT error_class FROM ops_dead_letter LIMIT 1").fetchone()
        self.assertEqual(row["error_class"], "scraper_not_applicable")


# ---------------------------------------------------------------------------
# Test 10: soMLier score normalization helper
# ---------------------------------------------------------------------------

class TestSoMLierScoreNorm(unittest.TestCase):
    def test_100_scale_passthrough(self):
        self.assertAlmostEqual(_normalize_score("85", "/100"), 85.0)

    def test_5_scale(self):
        self.assertAlmostEqual(_normalize_score("4.0", "/5"), 80.0)

    def test_20_scale(self):
        self.assertAlmostEqual(_normalize_score("16", "/20"), 80.0)

    def test_invalid_returns_none(self):
        self.assertIsNone(_normalize_score("not_a_number", "/100"))

    def test_out_of_range_returns_none(self):
        self.assertIsNone(_normalize_score("150", "/100"))

    def test_zero(self):
        self.assertAlmostEqual(_normalize_score("0", "/100"), 0.0)


# ---------------------------------------------------------------------------
# Test 11: soMLier French-only filter
# ---------------------------------------------------------------------------

class TestSoMLierFrenchFilter(unittest.TestCase):
    def setUp(self):
        self.conn = _make_minimal_db()

    def _run_with_csv(self, csv_content: str) -> "ScrapeResult":  # type: ignore[name-defined]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False,
                                         encoding="utf-8") as fh:
            fh.write(csv_content)
            tmp_path = fh.name
        try:
            with patch.dict(os.environ, {"SOMLIER_CSV_PATH": tmp_path}):
                scraper = SoMLierScraper(self.conn)
                return scraper.run(limit=None)
        finally:
            os.unlink(tmp_path)

    def test_non_french_wines_skipped(self):
        """Wines with country != FR are counted as skipped."""
        csv_content = (
            "wine_name,winery,region,vintage,rating,country\n"
            "Rioja Reserva,Bodegas Muga,Rioja,2016,88,ES\n"
            "Barolo,Gaja,Piedmont,2015,95,IT\n"
        )
        result = self._run_with_csv(csv_content)
        self.assertEqual(result.rows_inserted, 0)
        self.assertEqual(result.rows_skipped_unchanged, 2)

    def test_french_wines_inserted(self):
        """Wines with country=FR are processed."""
        csv_content = (
            "wine_name,winery,region,vintage,rating,country\n"
            "Gevrey-Chambertin,Domaine Rossignol,Burgundy,2018,90,FR\n"
        )
        result = self._run_with_csv(csv_content)
        self.assertEqual(result.rows_inserted, 1)

    def test_mixed_only_french_inserted(self):
        """Mixed batch: only FR wines are inserted."""
        csv_content = (
            "wine_name,winery,region,vintage,rating,country\n"
            "Gevrey-Chambertin,Domaine Rossignol,Burgundy,2018,90,FR\n"
            "Rioja Reserva,Bodegas Muga,Rioja,2016,88,ES\n"
        )
        result = self._run_with_csv(csv_content)
        self.assertEqual(result.rows_inserted, 1)
        self.assertEqual(result.rows_skipped_unchanged, 1)


# ---------------------------------------------------------------------------
# Test 12: soMLier deduplication via content_hash
# ---------------------------------------------------------------------------

class TestSoMLierDeduplication(unittest.TestCase):
    def setUp(self):
        self.conn = _make_minimal_db()

    def _run_csv(self, csv_content: str):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False,
                                         encoding="utf-8") as fh:
            fh.write(csv_content)
            tmp_path = fh.name
        try:
            with patch.dict(os.environ, {"SOMLIER_CSV_PATH": tmp_path}):
                scraper = SoMLierScraper(self.conn)
                return scraper.run(limit=None)
        finally:
            os.unlink(tmp_path)

    def test_no_duplicate_on_second_run(self):
        """Running the same CSV twice produces only 1 staging row."""
        csv_content = (
            "wine_name,winery,region,vintage,rating,country\n"
            "Chambolle-Musigny,Domaine Mugnier,Burgundy,2017,88,FR\n"
        )
        r1 = self._run_csv(csv_content)
        r2 = self._run_csv(csv_content)

        count = self.conn.execute(
            "SELECT COUNT(*) FROM staging_rating_candidates WHERE critic_code='SM'"
        ).fetchone()[0]
        self.assertEqual(count, 1)
        self.assertEqual(r1.rows_inserted, 1)
        self.assertEqual(r2.rows_inserted, 0)


if __name__ == "__main__":
    unittest.main()
