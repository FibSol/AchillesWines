"""
Unit tests for the Vivino tiebreaker scraper and promote_vivino_tiebreakers().

Covers:
  1. Score normalization: /5 → /100
  2. Staging insert: Vivino row lands in staging_rating_candidates with needs_review=1
  3. Tiebreaker gate — 0 pro sources: Vivino stays in staging
  4. Tiebreaker gate — 1 pro source: Vivino stays in staging
  5. Tiebreaker gate — ≥2 pro sources: Vivino promoted to fact_rating
  6. ratings_count < 10 rows are skipped (unit test on the constant)
  7. Idempotent promotion: promoting twice yields one fact_rating row
"""
import sqlite3
import time
import unittest

from achilles_scraper.identity import normalize_score_to_100
from achilles_scraper.promoter import promote_vivino_tiebreakers, RatingPromotionResult


# ---------------------------------------------------------------------------
# Helpers — minimal in-memory DB
# ---------------------------------------------------------------------------

def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript("""
        CREATE TABLE dim_wine (
            wine_key TEXT PRIMARY KEY
        );

        CREATE TABLE dim_source (
            source_key   INTEGER PRIMARY KEY AUTOINCREMENT,
            source_code  TEXT NOT NULL UNIQUE
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
            content_hash         TEXT,
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
            content_hash                 TEXT,
            batch_id                     TEXT    NOT NULL,
            needs_review                 INTEGER NOT NULL DEFAULT 1,
            promoted_to_fact_rating_key  INTEGER,
            promoted_at                  INTEGER
        );
    """)
    # Seed: one wine, vivino source, two pro critic sources
    conn.execute("INSERT INTO dim_wine (wine_key) VALUES ('wine_aaa')")
    conn.execute("INSERT INTO dim_source (source_code) VALUES ('vivino')")   # source_key=1
    conn.execute("INSERT INTO dim_source (source_code) VALUES ('rvf')")      # source_key=2
    conn.execute("INSERT INTO dim_source (source_code) VALUES ('wa')")       # source_key=3
    conn.commit()
    return conn


def _insert_staging_vivino(
    conn: sqlite3.Connection,
    wine_key: str = "wine_aaa",
    score: float = 4.2,
    content_hash: str = "vi_hash_1",
    batch_id: str = "batch_vi",
) -> int:
    vivino_sk = conn.execute(
        "SELECT source_key FROM dim_source WHERE source_code='vivino'"
    ).fetchone()[0]
    cur = conn.execute(
        """INSERT INTO staging_rating_candidates
           (wine_key, source_key, critic_code, reviewer_type,
            score, scale, score_normalized_100, rating_count,
            content_hash, batch_id, needs_review)
           VALUES (?, ?, 'VI', 'user_aggregate', ?, '/5', ?, 42, ?, ?, 1)""",
        (wine_key, vivino_sk, score, round(score / 5 * 100, 2), content_hash, batch_id),
    )
    conn.commit()
    return cur.lastrowid  # type: ignore[return-value]


def _insert_fact_pro(
    conn: sqlite3.Connection,
    wine_key: str = "wine_aaa",
    source_code: str = "rvf",
    critic_code: str = "RVF",
    score: float = 15.0,
    content_hash: str | None = None,
    batch_id: str = "batch_pro",
) -> None:
    sk = conn.execute(
        "SELECT source_key FROM dim_source WHERE source_code=?", (source_code,)
    ).fetchone()[0]
    conn.execute(
        """INSERT INTO fact_rating
           (wine_key, source_key, critic_code, reviewer_type,
            score, scale, score_normalized_100, batch_id, content_hash)
           VALUES (?, ?, ?, 'critic', ?, '/20', ?, ?, ?)""",
        (wine_key, sk, critic_code, score, round(score / 20 * 100, 2), batch_id, content_hash),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class NormalizationTests(unittest.TestCase):
    """Score normalization helpers."""

    def test_vivino_5_to_100(self):
        self.assertAlmostEqual(normalize_score_to_100(5.0, "/5"), 100.0)

    def test_vivino_2_5_to_50(self):
        self.assertAlmostEqual(normalize_score_to_100(2.5, "/5"), 50.0)

    def test_vivino_4_2_to_84(self):
        self.assertAlmostEqual(normalize_score_to_100(4.2, "/5"), 84.0)


class VivinoMinRatingsConstantTest(unittest.TestCase):
    """The _MIN_RATINGS threshold is set correctly."""

    def test_min_ratings_is_10(self):
        from achilles_scraper.scrapers.vivino import _MIN_RATINGS
        self.assertEqual(_MIN_RATINGS, 10)


class VivinoTiebreakerGateTests(unittest.TestCase):
    """promote_vivino_tiebreakers() gate logic."""

    def setUp(self):
        self.conn = _make_db()

    def test_no_pro_sources_stays_pending(self):
        """0 pro sources in fact_rating → Vivino row stays in staging."""
        _insert_staging_vivino(self.conn)

        result = promote_vivino_tiebreakers(self.conn)

        self.assertEqual(result.promoted, 0)
        self.assertEqual(result.pending, 1)
        fact_count = self.conn.execute("SELECT COUNT(*) FROM fact_rating").fetchone()[0]
        self.assertEqual(fact_count, 0)

    def test_one_pro_source_stays_pending(self):
        """1 pro source in fact_rating → Vivino row stays in staging."""
        _insert_staging_vivino(self.conn)
        _insert_fact_pro(self.conn, source_code="rvf", critic_code="RVF")

        result = promote_vivino_tiebreakers(self.conn)

        self.assertEqual(result.promoted, 0)
        self.assertEqual(result.pending, 1)

    def test_two_pro_sources_promotes_vivino(self):
        """≥2 pro sources in fact_rating → Vivino row is promoted."""
        _insert_staging_vivino(self.conn)
        _insert_fact_pro(self.conn, source_code="rvf",  critic_code="RVF", content_hash="h_rvf")
        _insert_fact_pro(self.conn, source_code="wa",   critic_code="WA",  content_hash="h_wa")

        result = promote_vivino_tiebreakers(self.conn)

        self.assertEqual(result.promoted, 1)
        self.assertEqual(result.pending, 0)
        fact_count = self.conn.execute("SELECT COUNT(*) FROM fact_rating").fetchone()[0]
        self.assertEqual(fact_count, 3)  # 2 pro + 1 Vivino

    def test_staging_row_marked_promoted(self):
        """After promotion the staging row has needs_review=0 and promoted_at set."""
        cid = _insert_staging_vivino(self.conn)
        _insert_fact_pro(self.conn, source_code="rvf", content_hash="h1")
        _insert_fact_pro(self.conn, source_code="wa",  content_hash="h2")

        promote_vivino_tiebreakers(self.conn)

        row = self.conn.execute(
            "SELECT needs_review, promoted_at, promoted_to_fact_rating_key "
            "FROM staging_rating_candidates WHERE candidate_id = ?",
            (cid,),
        ).fetchone()
        self.assertEqual(row["needs_review"], 0)
        self.assertIsNotNone(row["promoted_at"])
        self.assertIsNotNone(row["promoted_to_fact_rating_key"])

    def test_idempotent_promotion(self):
        """Running promote_vivino_tiebreakers() twice yields one fact_rating row."""
        _insert_staging_vivino(self.conn, content_hash="vi_hash_idem")
        _insert_fact_pro(self.conn, source_code="rvf", content_hash="h1")
        _insert_fact_pro(self.conn, source_code="wa",  content_hash="h2")

        result1 = promote_vivino_tiebreakers(self.conn)
        result2 = promote_vivino_tiebreakers(self.conn)

        fact_count = self.conn.execute("SELECT COUNT(*) FROM fact_rating").fetchone()[0]
        self.assertEqual(fact_count, 3)   # 2 pro + 1 Vivino
        # Second pass: no unpromoted rows remain
        self.assertEqual(result2.promoted, 0)
        self.assertEqual(result2.pending, 0)

    def test_no_vivino_source_returns_empty_result(self):
        """If dim_source has no 'vivino' row, function returns empty result gracefully."""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE dim_source (source_key INTEGER PRIMARY KEY, source_code TEXT UNIQUE);
            CREATE TABLE staging_rating_candidates (
                candidate_id INTEGER PRIMARY KEY,
                wine_key TEXT, source_key INTEGER, critic_code TEXT,
                reviewer_type TEXT, score REAL, scale TEXT,
                score_normalized_100 REAL, rating_count INTEGER,
                recorded_at INTEGER DEFAULT (strftime('%s','now')),
                source_url TEXT, content_hash TEXT, batch_id TEXT,
                needs_review INTEGER DEFAULT 1,
                promoted_to_fact_rating_key INTEGER, promoted_at INTEGER
            );
            CREATE TABLE fact_rating (
                rating_event_key INTEGER PRIMARY KEY, wine_key TEXT,
                source_key INTEGER, critic_code TEXT, reviewer_type TEXT,
                score REAL, scale TEXT, score_normalized_100 REAL,
                rating_count INTEGER, recorded_at INTEGER DEFAULT (strftime('%s','now')),
                source_url TEXT, content_hash TEXT, batch_id TEXT
            );
        """)

        result = promote_vivino_tiebreakers(conn)

        self.assertEqual(result.promoted, 0)
        self.assertEqual(result.pending, 0)


if __name__ == "__main__":
    unittest.main()
