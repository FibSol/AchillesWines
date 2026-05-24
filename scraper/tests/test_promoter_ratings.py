"""
Unit tests for promote_ratings() in achilles_scraper.promoter.

Tests use an in-memory SQLite database with the minimum schema needed:
  dim_wine, dim_source, fact_rating, staging_rating_candidates.

Covers:
  1. Mono-source stays in staging with needs_review=1.
  2. Bi-source promotes both rows to fact_rating.
  3. Idempotent second promotion — no duplicate fact_rating rows.
"""
import sqlite3
import time
import unittest

from achilles_scraper.promoter import promote_ratings, RatingPromotionResult


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
            source_key INTEGER PRIMARY KEY AUTOINCREMENT
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
    # Seed one wine and two sources
    conn.execute("INSERT INTO dim_wine (wine_key) VALUES ('wine_aaa')")
    conn.execute("INSERT INTO dim_source DEFAULT VALUES")  # source_key=1
    conn.execute("INSERT INTO dim_source DEFAULT VALUES")  # source_key=2
    conn.commit()
    return conn


def _insert_candidate(
    conn: sqlite3.Connection,
    wine_key: str = "wine_aaa",
    source_key: int = 1,
    critic_code: str = "WA",
    score: float = 92.0,
    scale: str = "/100",
    score_normalized_100: float = 92.0,
    content_hash: str | None = None,
    batch_id: str = "batch_test",
    needs_review: int = 1,
) -> int:
    cur = conn.execute(
        """INSERT INTO staging_rating_candidates
           (wine_key, source_key, critic_code, reviewer_type, score, scale,
            score_normalized_100, content_hash, batch_id, needs_review)
           VALUES (?, ?, ?, 'critic', ?, ?, ?, ?, ?, ?)""",
        (wine_key, source_key, critic_code, score, scale, score_normalized_100,
         content_hash, batch_id, needs_review),
    )
    conn.commit()
    return cur.lastrowid  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class MonoSourceGateTests(unittest.TestCase):
    """Mono-source entries must stay in staging with needs_review=1."""

    def setUp(self):
        self.conn = _make_db()

    def test_mono_source_stays_pending(self):
        """Single source_key for wine → not promoted, needs_review=1."""
        cid = _insert_candidate(self.conn, source_key=1)

        result = promote_ratings(self.conn)

        self.assertEqual(result.promoted, 0)
        self.assertEqual(result.pending, 1)

    def test_mono_source_fact_rating_empty(self):
        """fact_rating must remain empty after failed mono-source promotion."""
        _insert_candidate(self.conn, source_key=1)

        promote_ratings(self.conn)

        count = self.conn.execute("SELECT COUNT(*) FROM fact_rating").fetchone()[0]
        self.assertEqual(count, 0)

    def test_mono_source_needs_review_flag_set(self):
        """The staging row keeps needs_review=1 after a promotion pass."""
        cid = _insert_candidate(self.conn, source_key=1)

        promote_ratings(self.conn)

        row = self.conn.execute(
            "SELECT needs_review, promoted_at FROM staging_rating_candidates WHERE candidate_id = ?",
            (cid,)
        ).fetchone()
        self.assertEqual(row["needs_review"], 1)
        self.assertIsNone(row["promoted_at"])

    def test_same_source_twice_not_promoted(self):
        """Two rows from the *same* source_key must not satisfy the ≥2 gate."""
        _insert_candidate(self.conn, source_key=1, content_hash="hash_a")
        _insert_candidate(self.conn, source_key=1, content_hash="hash_b")

        result = promote_ratings(self.conn)

        self.assertEqual(result.promoted, 0)
        self.assertEqual(result.pending, 2)
        fact_count = self.conn.execute("SELECT COUNT(*) FROM fact_rating").fetchone()[0]
        self.assertEqual(fact_count, 0)


class BiSourcePromotionTests(unittest.TestCase):
    """Two distinct sources → rows promoted to fact_rating."""

    def setUp(self):
        self.conn = _make_db()

    def test_bi_source_promotes_both_rows(self):
        """Two distinct sources for wine_aaa → both promoted."""
        _insert_candidate(self.conn, source_key=1, critic_code="WA",  content_hash="h1")
        _insert_candidate(self.conn, source_key=2, critic_code="RVF", content_hash="h2")

        result = promote_ratings(self.conn)

        self.assertEqual(result.promoted, 2)
        self.assertEqual(result.pending, 0)

    def test_bi_source_inserts_fact_rating_rows(self):
        """fact_rating should have 2 new rows after bi-source promotion."""
        _insert_candidate(self.conn, source_key=1, score=91.0, content_hash="h1")
        _insert_candidate(self.conn, source_key=2, score=93.0, content_hash="h2")

        promote_ratings(self.conn)

        rows = self.conn.execute(
            "SELECT score FROM fact_rating ORDER BY score"
        ).fetchall()
        self.assertEqual(len(rows), 2)
        self.assertAlmostEqual(rows[0]["score"], 91.0)
        self.assertAlmostEqual(rows[1]["score"], 93.0)

    def test_staging_rows_marked_promoted(self):
        """Staging rows must have promoted_at set and needs_review=0 after promotion."""
        c1 = _insert_candidate(self.conn, source_key=1, content_hash="h1")
        c2 = _insert_candidate(self.conn, source_key=2, content_hash="h2")

        promote_ratings(self.conn)

        for cid in (c1, c2):
            row = self.conn.execute(
                "SELECT needs_review, promoted_at, promoted_to_fact_rating_key "
                "FROM staging_rating_candidates WHERE candidate_id = ?",
                (cid,)
            ).fetchone()
            self.assertEqual(row["needs_review"], 0)
            self.assertIsNotNone(row["promoted_at"])
            self.assertIsNotNone(row["promoted_to_fact_rating_key"])


class IdempotentPromotionTests(unittest.TestCase):
    """Running promote_ratings() twice must not create duplicate fact_rating rows."""

    def setUp(self):
        self.conn = _make_db()

    def test_second_promotion_no_duplicates(self):
        """Promoting the same bi-source wine twice yields only 2 fact_rating rows."""
        _insert_candidate(self.conn, source_key=1, content_hash="h1")
        _insert_candidate(self.conn, source_key=2, content_hash="h2")

        result1 = promote_ratings(self.conn)
        result2 = promote_ratings(self.conn)

        fact_count = self.conn.execute("SELECT COUNT(*) FROM fact_rating").fetchone()[0]
        self.assertEqual(fact_count, 2)
        # Second pass finds no unpromoted rows → both counters zero
        self.assertEqual(result2.promoted, 0)
        self.assertEqual(result2.pending, 0)

    def test_new_mono_source_after_promotion_stays_pending(self):
        """A new mono-source row added after an earlier promotion stays pending."""
        _insert_candidate(self.conn, source_key=1, content_hash="h1")
        _insert_candidate(self.conn, source_key=2, content_hash="h2")
        promote_ratings(self.conn)

        # Add a third wine that only has one source
        self.conn.execute("INSERT INTO dim_wine (wine_key) VALUES ('wine_bbb')")
        self.conn.commit()
        _insert_candidate(self.conn, wine_key="wine_bbb", source_key=1, content_hash="h3")

        result = promote_ratings(self.conn)

        self.assertEqual(result.promoted, 0)
        self.assertEqual(result.pending, 1)
        fact_count = self.conn.execute("SELECT COUNT(*) FROM fact_rating").fetchone()[0]
        self.assertEqual(fact_count, 2)  # unchanged from first promotion


if __name__ == "__main__":
    unittest.main()
