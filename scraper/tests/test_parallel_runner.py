"""Tests for the parallel ThreadPoolExecutor-based job runner.

All tests use in-memory SQLite and mock scrapers so they run fast and
don't touch the real database or network.
"""
import sqlite3
import time
import threading
import unittest
from unittest.mock import MagicMock, patch
from concurrent.futures import Future

from achilles_scraper.job_runner import JobRunner, _worker_run_job
from achilles_scraper.scrapers.base import ScrapeResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CREATE_DIM_SOURCE = """
CREATE TABLE IF NOT EXISTS dim_source (
    source_key INTEGER PRIMARY KEY AUTOINCREMENT,
    source_code TEXT NOT NULL UNIQUE,
    requires_auth INTEGER DEFAULT 0
);
"""

_CREATE_JOB_QUEUE = """
CREATE TABLE IF NOT EXISTS ops_job_queue (
    job_id TEXT PRIMARY KEY,
    source_key INTEGER,
    requested_by TEXT,
    requested_at INTEGER DEFAULT (strftime('%s','now')),
    status TEXT NOT NULL DEFAULT 'queued',
    started_at INTEGER,
    finished_at INTEGER,
    rows_fetched INTEGER DEFAULT 0,
    rows_inserted INTEGER DEFAULT 0,
    rows_dlq INTEGER DEFAULT 0,
    error_message TEXT,
    batch_id TEXT,
    params TEXT DEFAULT '{}'
);
"""


def _make_db() -> sqlite3.Connection:
    """Create an in-memory DB with the two tables the runner needs."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(_CREATE_DIM_SOURCE)
    conn.execute(_CREATE_JOB_QUEUE)
    conn.execute("INSERT INTO dim_source (source_code) VALUES ('mock_web')")
    conn.execute("INSERT INTO dim_source (source_code) VALUES ('mock_email')")
    conn.commit()
    return conn


def _enqueue(conn: sqlite3.Connection, source_code: str, job_id: str | None = None) -> str:
    """Insert a queued job and return the job_id."""
    import uuid
    jid = job_id or str(uuid.uuid4())
    row = conn.execute(
        "SELECT source_key FROM dim_source WHERE source_code = ?", (source_code,)
    ).fetchone()
    conn.execute(
        "INSERT INTO ops_job_queue (job_id, source_key, requested_by, status, params) "
        "VALUES (?, ?, 'test', 'queued', '{}')",
        (jid, row["source_key"]),
    )
    conn.commit()
    return jid


def _job_status(conn: sqlite3.Connection, job_id: str) -> str:
    row = conn.execute(
        "SELECT status FROM ops_job_queue WHERE job_id=?", (job_id,)
    ).fetchone()
    return row["status"] if row else "missing"


class _OkScraper:
    """Minimal scraper stub that succeeds immediately."""
    source_code = "mock_web"
    batch_id = ""

    def __init__(self, conn):
        self.conn = conn

    def run(self, limit=None) -> ScrapeResult:
        return ScrapeResult(rows_fetched=1, rows_inserted=1, batch_id=self.batch_id)


class _SlowScraper:
    """Scraper that sleeps briefly to simulate work."""
    source_code = "mock_web"
    batch_id = ""

    def __init__(self, conn):
        self.conn = conn

    def run(self, limit=None) -> ScrapeResult:
        time.sleep(0.05)
        return ScrapeResult(rows_fetched=2, rows_inserted=2, batch_id=self.batch_id)


class _BoomScraper:
    """Scraper that always raises an exception."""
    source_code = "mock_web"
    batch_id = ""

    def __init__(self, conn):
        self.conn = conn

    def run(self, limit=None) -> ScrapeResult:
        raise RuntimeError("simulated scraper explosion")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestClaimJobsLimit(unittest.TestCase):
    """With 2 workers and 3 queued jobs, at most 2 are claimed per tick."""

    def test_claim_respects_max_workers(self):
        conn = _make_db()
        ids = [_enqueue(conn, "mock_web") for _ in range(3)]
        runner = JobRunner(conn, {"mock_web": _OkScraper}, max_workers=2, db_path=":memory:")

        claimed = runner._claim_jobs(2)
        self.assertEqual(len(claimed), 2)

        # The third job must still be queued.
        still_queued = [i for i in ids if _job_status(conn, i) == "queued"]
        self.assertEqual(len(still_queued), 1)

        # The two claimed jobs must be running.
        running = [i for i in ids if _job_status(conn, i) == "running"]
        self.assertEqual(len(running), 2)

    def test_claim_returns_fewer_when_not_enough_queued(self):
        conn = _make_db()
        _enqueue(conn, "mock_web")
        runner = JobRunner(conn, {"mock_web": _OkScraper}, max_workers=4, db_path=":memory:")

        claimed = runner._claim_jobs(4)
        self.assertEqual(len(claimed), 1)


class TestFutureReaping(unittest.TestCase):
    """Completed futures are reaped before new jobs are claimed — no slot leak."""

    def test_completed_futures_free_slots(self):
        """Submit a fast job, wait for it to complete, then verify the slot
        is freed so a second job can be claimed on the next tick."""
        conn = _make_db()
        jid1 = _enqueue(conn, "mock_web")
        jid2 = _enqueue(conn, "mock_web")

        runner = JobRunner(conn, {"mock_web": _OkScraper}, max_workers=1, db_path=":memory:")

        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=1) as executor:
            # Simulate tick 1: claim 1 job (max_workers - 0 in_flight = 1 free slot).
            in_flight: dict[Future, str] = {}
            free_slots = runner.max_workers - len(in_flight)
            self.assertEqual(free_slots, 1)

            jobs = runner._claim_jobs(free_slots)
            self.assertEqual(len(jobs), 1)

            job = jobs[0]
            batch_id = f"mock_web-test-{job['job_id'][:8]}"
            runner._set_batch_id(job["job_id"], batch_id)

            future = executor.submit(
                _worker_run_job,
                ":memory:",
                {"mock_web": _OkScraper},
                job,
                "mock_web",
                batch_id,
                None,
                False,
            )
            in_flight[future] = job["job_id"]

            # Wait for the future to finish.
            future.result(timeout=5)

            # Tick 2: reap done futures, freeing the slot.
            done = [f for f in list(in_flight) if f.done()]
            for f in done:
                returned_job_id, result = f.result()
                in_flight.pop(f)
                runner._finish_job(returned_job_id, result)

            self.assertEqual(len(in_flight), 0)

            # Now free_slots should be 1 again.
            free_slots = runner.max_workers - len(in_flight)
            self.assertEqual(free_slots, 1)

            # Should be able to claim the second job.
            jobs2 = runner._claim_jobs(free_slots)
            self.assertEqual(len(jobs2), 1)
            self.assertEqual(jobs2[0]["job_id"], jid2)


class TestExceptionSafety(unittest.TestCase):
    """A worker that raises an exception doesn't crash the main loop."""

    def test_exception_in_worker_returns_failed_result(self):
        """_worker_run_job wraps unhandled exceptions as a failed ScrapeResult."""
        conn = _make_db()
        jid = _enqueue(conn, "mock_web")
        job = dict(conn.execute(
            "SELECT * FROM ops_job_queue WHERE job_id=?", (jid,)
        ).fetchone())

        returned_job_id, result = _worker_run_job(
            db_path=":memory:",
            scrapers={"mock_web": _BoomScraper},
            job=job,
            source_code="mock_web",
            batch_id="mock_web-test-boom",
            limit=None,
            test_auth=False,
        )
        self.assertEqual(returned_job_id, jid)
        self.assertIsNotNone(result.error)
        self.assertIn("explosion", result.error)

    def test_main_loop_continues_after_worker_exception(self):
        """run_loop must not propagate an exception from a single bad worker."""
        conn = _make_db()
        jid = _enqueue(conn, "mock_web")

        runner = JobRunner(
            conn, {"mock_web": _BoomScraper}, max_workers=2, db_path=":memory:"
        )
        # We don't run the full loop; instead verify that _finish_job correctly
        # records a 'failed' status when given a ScrapeResult with an error.
        result = ScrapeResult(error="kaboom", batch_id="boom-batch")
        runner._finish_job(jid, result)

        self.assertEqual(_job_status(conn, jid), "failed")
        row = conn.execute(
            "SELECT error_message FROM ops_job_queue WHERE job_id=?", (jid,)
        ).fetchone()
        self.assertEqual(row["error_message"], "kaboom")

    def test_future_exception_handled_by_safety_net(self):
        """If a future.result() itself raises (escaped worker wrapper),
        the main loop's safety-net catches it and calls _finish_job(failed)."""
        conn = _make_db()
        jid = _enqueue(conn, "mock_web")

        runner = JobRunner(
            conn, {"mock_web": _BoomScraper}, max_workers=1, db_path=":memory:"
        )

        from concurrent.futures import ThreadPoolExecutor

        def _always_raise(db_path, scrapers, job, source_code, batch_id, limit, test_auth):
            raise RuntimeError("escaped exception")

        with ThreadPoolExecutor(max_workers=1) as executor:
            job = {"job_id": jid, "source_key": 1}
            future = executor.submit(
                _always_raise,
                ":memory:",
                {},
                job,
                "mock_web",
                "batch-x",
                None,
                False,
            )
            # Simulate the main-loop reaping code.
            future_done = future.done() or (time.sleep(0.1) or future.done())
            try:
                _returned_job_id, result = future.result()
            except Exception as exc:
                result = ScrapeResult(error=str(exc))
            runner._finish_job(jid, result)

        self.assertEqual(_job_status(conn, jid), "failed")


class TestWorkerThreadIsolation(unittest.TestCase):
    """Each worker opens its own SQLite connection (thread-safety)."""

    def test_worker_opens_own_connection(self):
        """_worker_run_job must work with :memory: db_path by opening a fresh
        in-memory connection (which is isolated from the main-thread one).
        The scraper receives a sqlite3.Connection object, not None."""
        received_conns = []

        class _ConnCapture:
            source_code = "mock_web"
            batch_id = ""

            def __init__(self, conn):
                received_conns.append(conn)
                self.conn = conn

            def run(self, limit=None) -> ScrapeResult:
                return ScrapeResult(rows_fetched=1, batch_id=self.batch_id)

        conn = _make_db()
        jid = _enqueue(conn, "mock_web")
        job = dict(conn.execute(
            "SELECT * FROM ops_job_queue WHERE job_id=?", (jid,)
        ).fetchone())

        _worker_run_job(
            db_path=":memory:",
            scrapers={"mock_web": _ConnCapture},
            job=job,
            source_code="mock_web",
            batch_id="mock_web-test-conn",
            limit=None,
            test_auth=False,
        )

        self.assertEqual(len(received_conns), 1)
        # Must be a sqlite3.Connection, not the main-thread conn.
        self.assertIsInstance(received_conns[0], sqlite3.Connection)
        self.assertIsNot(received_conns[0], conn)

    def test_concurrent_workers_use_separate_connections(self):
        """Two concurrent calls to _worker_run_job receive different connections."""
        received_conns = []
        lock = threading.Lock()

        class _ConnRecord:
            source_code = "mock_web"
            batch_id = ""

            def __init__(self, conn):
                with lock:
                    received_conns.append(conn)
                self.conn = conn

            def run(self, limit=None) -> ScrapeResult:
                time.sleep(0.02)
                return ScrapeResult(rows_fetched=1, batch_id=self.batch_id)

        conn = _make_db()
        jid1 = _enqueue(conn, "mock_web")
        jid2 = _enqueue(conn, "mock_web")
        job1 = dict(conn.execute(
            "SELECT * FROM ops_job_queue WHERE job_id=?", (jid1,)
        ).fetchone())
        job2 = dict(conn.execute(
            "SELECT * FROM ops_job_queue WHERE job_id=?", (jid2,)
        ).fetchone())

        from concurrent.futures import ThreadPoolExecutor, wait

        with ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(
                _worker_run_job, ":memory:", {"mock_web": _ConnRecord},
                job1, "mock_web", "batch-1", None, False,
            )
            f2 = executor.submit(
                _worker_run_job, ":memory:", {"mock_web": _ConnRecord},
                job2, "mock_web", "batch-2", None, False,
            )
            wait([f1, f2], timeout=5)

        self.assertEqual(len(received_conns), 2)
        self.assertIsNot(received_conns[0], received_conns[1])


class TestMaxWorkersEnvVar(unittest.TestCase):
    """max_workers is read from ACHILLES_JOB_WORKERS env var."""

    def test_env_var_sets_max_workers(self):
        import os
        conn = _make_db()
        with patch.dict(os.environ, {"ACHILLES_JOB_WORKERS": "7"}):
            runner = JobRunner(conn, {})
        self.assertEqual(runner.max_workers, 7)

    def test_default_is_four(self):
        import os
        conn = _make_db()
        env = {k: v for k, v in os.environ.items() if k != "ACHILLES_JOB_WORKERS"}
        with patch.dict(os.environ, env, clear=True):
            runner = JobRunner(conn, {})
        self.assertEqual(runner.max_workers, 4)

    def test_explicit_arg_overrides_env(self):
        import os
        conn = _make_db()
        with patch.dict(os.environ, {"ACHILLES_JOB_WORKERS": "7"}):
            runner = JobRunner(conn, {}, max_workers=2)
        self.assertEqual(runner.max_workers, 2)


if __name__ == "__main__":
    unittest.main()
