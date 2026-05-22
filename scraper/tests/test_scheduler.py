"""
Unit tests for APScheduler integration in job_runner.

Tests cover:
  - _should_enqueue() duplicate-check logic
  - _read_schedule_env() cron env-var parsing
  - JobRunner.start_scheduler() schedule registration
"""
import os
import sqlite3
import unittest
from unittest.mock import MagicMock, patch

from achilles_scraper.job_runner import (
    JobRunner,
    _read_schedule_env,
    _should_enqueue,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_conn() -> sqlite3.Connection:
    """In-memory SQLite with row_factory and the minimal schema needed."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE dim_source (
            source_key INTEGER PRIMARY KEY AUTOINCREMENT,
            source_code TEXT NOT NULL UNIQUE
        )
    """)
    conn.execute("""
        CREATE TABLE ops_job_queue (
            job_id       TEXT PRIMARY KEY,
            source_key   INTEGER,
            requested_by TEXT,
            status       TEXT NOT NULL DEFAULT 'queued',
            params       TEXT DEFAULT '{}',
            requested_at INTEGER DEFAULT (strftime('%s','now'))
        )
    """)
    conn.commit()
    return conn


def _insert_source(conn: sqlite3.Connection, source_code: str) -> int:
    cur = conn.execute(
        "INSERT INTO dim_source (source_code) VALUES (?)", (source_code,)
    )
    conn.commit()
    return cur.lastrowid


def _insert_job(conn: sqlite3.Connection, source_key: int, status: str) -> None:
    import uuid
    conn.execute(
        "INSERT INTO ops_job_queue (job_id, source_key, status) VALUES (?, ?, ?)",
        (str(uuid.uuid4()), source_key, status),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# _should_enqueue tests
# ---------------------------------------------------------------------------

class ShouldEnqueueTests(unittest.TestCase):

    def setUp(self):
        self.conn = _make_conn()
        self.source_key = _insert_source(self.conn, "millesima")

    def test_returns_true_when_queue_is_empty(self):
        """No existing rows → safe to enqueue."""
        self.assertTrue(_should_enqueue(self.source_key, self.conn))

    def test_returns_false_when_queued_job_exists(self):
        """A job in 'queued' state blocks a new enqueue."""
        _insert_job(self.conn, self.source_key, "queued")
        self.assertFalse(_should_enqueue(self.source_key, self.conn))

    def test_returns_false_when_running_job_exists(self):
        """A job in 'running' state blocks a new enqueue."""
        _insert_job(self.conn, self.source_key, "running")
        self.assertFalse(_should_enqueue(self.source_key, self.conn))

    def test_returns_true_when_only_done_jobs_exist(self):
        """Completed jobs must not block re-scheduling."""
        _insert_job(self.conn, self.source_key, "done")
        self.assertTrue(_should_enqueue(self.source_key, self.conn))

    def test_returns_true_when_only_failed_jobs_exist(self):
        """Failed jobs must not block re-scheduling."""
        _insert_job(self.conn, self.source_key, "failed")
        self.assertTrue(_should_enqueue(self.source_key, self.conn))

    def test_different_source_key_does_not_block(self):
        """A queued job for source A must not block source B."""
        other_key = _insert_source(self.conn, "idealwine")
        _insert_job(self.conn, other_key, "queued")
        self.assertTrue(_should_enqueue(self.source_key, self.conn))


# ---------------------------------------------------------------------------
# _read_schedule_env tests
# ---------------------------------------------------------------------------

class ReadScheduleEnvTests(unittest.TestCase):

    def test_empty_environment_returns_empty_dict(self):
        with patch.dict(os.environ, {}, clear=True):
            result = _read_schedule_env()
        self.assertEqual(result, {})

    def test_single_source_parsed_correctly(self):
        with patch.dict(os.environ, {"ACHILLES_SCHEDULE_MILLESIMA": "0 3 * * *"}, clear=True):
            result = _read_schedule_env()
        self.assertEqual(result, {"millesima": "0 3 * * *"})

    def test_multiple_sources_all_parsed(self):
        env = {
            "ACHILLES_SCHEDULE_MILLESIMA": "0 3 * * *",
            "ACHILLES_SCHEDULE_IDEALWINE_EMAIL": "30 2 * * 1",
            "UNRELATED_VAR": "ignore_me",
        }
        with patch.dict(os.environ, env, clear=True):
            result = _read_schedule_env()
        self.assertIn("millesima", result)
        self.assertIn("idealwine_email", result)
        self.assertNotIn("unrelated_var", result)
        self.assertEqual(result["millesima"], "0 3 * * *")
        self.assertEqual(result["idealwine_email"], "30 2 * * 1")

    def test_source_key_is_lowercased(self):
        with patch.dict(os.environ, {"ACHILLES_SCHEDULE_LAVINIA": "0 4 * * *"}, clear=True):
            result = _read_schedule_env()
        self.assertIn("lavinia", result)
        self.assertNotIn("LAVINIA", result)

    def test_blank_value_is_skipped(self):
        with patch.dict(os.environ, {"ACHILLES_SCHEDULE_MILLESIMA": "   "}, clear=True):
            result = _read_schedule_env()
        self.assertEqual(result, {})

    def test_whitespace_is_stripped_from_cron(self):
        with patch.dict(os.environ, {"ACHILLES_SCHEDULE_MILLESIMA": "  0 3 * * *  "}, clear=True):
            result = _read_schedule_env()
        self.assertEqual(result["millesima"], "0 3 * * *")


# ---------------------------------------------------------------------------
# JobRunner.start_scheduler integration tests
# ---------------------------------------------------------------------------

class StartSchedulerTests(unittest.TestCase):

    def setUp(self):
        self.conn = _make_conn()
        _insert_source(self.conn, "millesima")
        self.scrapers = {"millesima": MagicMock()}

    def test_no_schedule_env_does_not_start_scheduler(self):
        """With no env vars no scheduler should be created."""
        with patch.dict(os.environ, {}, clear=True):
            runner = JobRunner(self.conn, self.scrapers)
            runner.start_scheduler()
        self.assertIsNone(runner._scheduler)

    @unittest.skipUnless(
        __import__("importlib").util.find_spec("apscheduler") is not None,
        "apscheduler not installed",
    )
    def test_valid_schedule_env_starts_scheduler(self):
        """A valid ACHILLES_SCHEDULE_MILLESIMA should wire up a BackgroundScheduler."""
        env = {"ACHILLES_SCHEDULE_MILLESIMA": "0 3 * * *"}
        with patch.dict(os.environ, env, clear=True):
            runner = JobRunner(self.conn, self.scrapers)
            runner.start_scheduler()
        try:
            self.assertIsNotNone(runner._scheduler)
            self.assertTrue(runner._scheduler.running)
        finally:
            if runner._scheduler is not None:
                runner._scheduler.shutdown(wait=False)

    @unittest.skipUnless(
        __import__("importlib").util.find_spec("apscheduler") is not None,
        "apscheduler not installed",
    )
    def test_invalid_cron_expression_does_not_crash(self):
        """A malformed cron string (wrong field count) must not crash start_scheduler."""
        env = {"ACHILLES_SCHEDULE_MILLESIMA": "not_a_cron"}
        with patch.dict(os.environ, env, clear=True):
            runner = JobRunner(self.conn, self.scrapers)
            # Should not raise — bad cron is logged as an error row in the table.
            try:
                runner.start_scheduler()
            except Exception as exc:
                self.fail(f"start_scheduler raised unexpectedly: {exc}")
        # No scheduler started because the only registered source failed to parse.
        self.assertIsNone(runner._scheduler)


# ---------------------------------------------------------------------------
# _enqueue_scheduled_job tests
# ---------------------------------------------------------------------------

class EnqueueScheduledJobTests(unittest.TestCase):

    def setUp(self):
        self.conn = _make_conn()
        self.source_key = _insert_source(self.conn, "millesima")
        self.scrapers = {"millesima": MagicMock()}
        self.runner = JobRunner(self.conn, self.scrapers)

    def test_enqueues_job_when_queue_is_empty(self):
        self.runner._enqueue_scheduled_job("millesima")
        row = self.conn.execute(
            "SELECT * FROM ops_job_queue WHERE source_key = ? AND requested_by = 'scheduler'",
            (self.source_key,),
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "queued")

    def test_skips_enqueue_when_job_already_queued(self):
        _insert_job(self.conn, self.source_key, "queued")
        self.runner._enqueue_scheduled_job("millesima")
        count = self.conn.execute(
            "SELECT COUNT(*) AS cnt FROM ops_job_queue WHERE source_key = ?",
            (self.source_key,),
        ).fetchone()["cnt"]
        # Still only one row — no duplicate was added.
        self.assertEqual(count, 1)

    def test_skips_enqueue_for_unknown_source(self):
        """Source not in dim_source should log a warning and not crash."""
        try:
            self.runner._enqueue_scheduled_job("nonexistent_source")
        except Exception as exc:
            self.fail(f"_enqueue_scheduled_job raised unexpectedly: {exc}")
        count = self.conn.execute(
            "SELECT COUNT(*) AS cnt FROM ops_job_queue"
        ).fetchone()["cnt"]
        self.assertEqual(count, 0)

    def test_enqueues_after_done_job(self):
        """After a completed run the scheduler should be able to enqueue again."""
        _insert_job(self.conn, self.source_key, "done")
        self.runner._enqueue_scheduled_job("millesima")
        row = self.conn.execute(
            "SELECT * FROM ops_job_queue WHERE status = 'queued'",
        ).fetchone()
        self.assertIsNotNone(row)


if __name__ == "__main__":
    unittest.main()
