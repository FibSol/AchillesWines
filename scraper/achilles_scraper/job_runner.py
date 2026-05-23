import logging
import os
import sqlite3
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, Future
from datetime import datetime
from pathlib import Path
from rich.console import Console
from rich.table import Table

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    HAS_APSCHEDULER = True
except ImportError:
    HAS_APSCHEDULER = False

from .scrapers.base import ScrapeResult

console = Console()

# Environment variable prefix for per-source cron schedules.
# Example: ACHILLES_SCHEDULE_MILLESIMA=0 3 * * *
_SCHEDULE_ENV_PREFIX = "ACHILLES_SCHEDULE_"

# Per-batch logs live at <project_root>/logs/<batch_id>.log so the
# JobLogsDrawer at /admin/jobs can tail them via GET /api/jobs/[jobId]/logs.
# Use __file__ so the path is always correct regardless of cwd at startup.
LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"

# Thread-local storage for per-thread log files.
# Each worker thread stores its open log file here so _TeeWriter can find it.
_thread_local = threading.local()


class _TeeWriter:
    """Write to both the original stream and an open file. Best-effort flush.

    In multi-threaded mode each worker thread stores its log file in
    ``_thread_local.log_file``.  When accessed from the main thread that
    attribute is absent, so writes go only to the primary stream.
    """

    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        # Write to all registered primary streams.
        for s in self.streams:
            try:
                s.write(data)
            except Exception:
                pass
        # Also write to the per-thread log file if one is active.
        thread_log = getattr(_thread_local, "log_file", None)
        if thread_log is not None:
            try:
                thread_log.write(data)
                thread_log.flush()
            except Exception:
                pass
        self.flush()
        return len(data) if isinstance(data, str) else 0

    def flush(self):
        for s in self.streams:
            try:
                s.flush()
            except Exception:
                pass

    def isatty(self):
        return False


def _make_batch_id(source_code: str) -> str:
    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    return f"{source_code}-{ts}-{uuid.uuid4().hex[:8]}"


def _read_schedule_env() -> dict[str, str]:
    """Return {source_code: cron_expression} for every ACHILLES_SCHEDULE_<CODE> env var."""
    schedules: dict[str, str] = {}
    for key, value in os.environ.items():
        if key.startswith(_SCHEDULE_ENV_PREFIX):
            source_key = key[len(_SCHEDULE_ENV_PREFIX):].lower()
            cron_expr = value.strip()
            if source_key and cron_expr:
                schedules[source_key] = cron_expr
    return schedules


def _read_schedules_from_db(conn: sqlite3.Connection) -> dict[str, str]:
    """Return {source_code: cron_expression} from ops_scraper_schedule table."""
    try:
        rows = conn.execute(
            "SELECT source_code, cron_expr FROM ops_scraper_schedule "
            "WHERE cron_expr IS NOT NULL AND cron_expr != ''"
        ).fetchall()
        return {row["source_code"]: row["cron_expr"] for row in rows}
    except Exception:
        return {}


def _merge_schedules(db_schedules: dict[str, str], env_schedules: dict[str, str]) -> dict[str, str]:
    """Merge DB schedules with env var overrides. Env vars take priority."""
    return {**db_schedules, **env_schedules}



def _should_enqueue(source_key: int, conn: sqlite3.Connection) -> bool:
    """Return True only when there is no queued or running job for *source_key*.

    Prevents pile-up when a long scrape overlaps with the next scheduled tick.
    """
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM ops_job_queue "
        "WHERE source_key = ? AND status IN ('queued', 'running')",
        (source_key,),
    ).fetchone()
    return (row["cnt"] if row else 0) == 0


def _worker_run_job(
    db_path: str,
    scrapers: dict,
    job: dict,
    source_code: str,
    batch_id: str,
    limit: int | None,
    test_auth: bool,
) -> tuple[str, ScrapeResult]:
    """Run one scraper job in a worker thread.

    Opens its own SQLite connection so it never shares the main-thread
    connection.  Returns ``(job_id, ScrapeResult)`` so the main thread
    can call ``_finish_job`` with its own connection.
    """
    thread_name = threading.current_thread().name
    console.print(
        f"[cyan][{thread_name}] Job {job['job_id'][:8]}… source={source_code} batch={batch_id}[/cyan]"
    )

    # Each worker opens its own connection — SQLite connections are not
    # thread-safe across threads.
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"{batch_id}.log"

    # Line-buffered so the drawer's 3-second tail picks up fresh lines.
    log_file = open(log_path, "w", encoding="utf-8", buffering=1)
    # Store in thread-local so _TeeWriter picks it up for any print() calls.
    _thread_local.log_file = log_file

    try:
        scraper_cls = scrapers[source_code]

        if test_auth:
            result = _worker_run_auth_test(conn, scraper_cls, batch_id, source_code, log_file)
        else:
            result = _worker_run_scraper(conn, scraper_cls, batch_id, limit, log_file)
        return job["job_id"], result
    except Exception as exc:
        # Safety-net: if anything above leaked an exception, wrap it.
        return job["job_id"], ScrapeResult(error=str(exc), batch_id=batch_id)
    finally:
        _thread_local.log_file = None
        try:
            log_file.flush()
            log_file.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass


def _worker_run_scraper(
    conn: sqlite3.Connection,
    scraper_cls,
    batch_id: str,
    limit: int | None,
    log_file,
) -> ScrapeResult:
    """Run a scraper inside the worker thread, writing output to log_file."""
    # Attach a FileHandler to the root logger so every _logger.info/warning/error
    # call inside any scraper is captured to the per-batch log file.
    # Suppress noisy HTTP internals — keep only WARNING+ from httpcore/httpx.
    for _noisy in ("httpcore", "httpx", "hpack", "h2"):
        logging.getLogger(_noisy).setLevel(logging.WARNING)
    file_handler = logging.FileHandler(log_file.name, mode="a", encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(levelname)s %(message)s"))
    file_handler.setLevel(logging.DEBUG)
    root_logger = logging.getLogger()
    root_logger.addHandler(file_handler)
    # Ensure root logger level allows DEBUG through (scrapers use INFO/DEBUG)
    if root_logger.level == logging.NOTSET or root_logger.level > logging.DEBUG:
        root_logger.setLevel(logging.DEBUG)

    try:
        _log(log_file, f"[batch {batch_id}] starting")
        scraper = scraper_cls(conn)
        scraper.batch_id = batch_id
        try:
            result = scraper.run(limit=limit)
            if not result.batch_id:
                result.batch_id = batch_id
        except Exception as e:
            result = ScrapeResult(error=str(e), batch_id=batch_id)
        _log(
            log_file,
            f"[batch {batch_id}] finished fetched={result.rows_fetched} "
            f"inserted={result.rows_inserted} dlq={result.rows_dlq} "
            f"error={result.error or 'none'}",
        )
        return result
    except Exception as exc:
        return ScrapeResult(error=str(exc), batch_id=batch_id)
    finally:
        root_logger.removeHandler(file_handler)
        file_handler.close()


def _worker_run_auth_test(
    conn: sqlite3.Connection,
    scraper_cls,
    batch_id: str,
    source_code: str,
    log_file,
) -> ScrapeResult:
    """Run test_login() inside the worker thread."""
    try:
        _log(log_file, f"[batch {batch_id}] test_login for {source_code}")
        scraper = scraper_cls(conn)
        scraper.batch_id = batch_id

        test_login = getattr(scraper, "test_login", None)
        if not callable(test_login):
            msg = (
                f"scraper {source_code} does not support test_login "
                "(not an AuthenticatedScraper subclass)"
            )
            _log(log_file, msg)
            return ScrapeResult(error=msg, batch_id=batch_id)

        try:
            ok, message = test_login()
        except Exception as e:
            ok, message = False, f"unexpected: {e}"

        _log(log_file, f"test_login result: ok={ok} message={message}")
        if ok:
            return ScrapeResult(batch_id=batch_id, error=None)
        return ScrapeResult(batch_id=batch_id, error=message)
    except Exception as exc:
        return ScrapeResult(error=str(exc), batch_id=batch_id)


def _log(log_file, message: str) -> None:
    """Write *message* to both the log file and console."""
    try:
        log_file.write(message + "\n")
        log_file.flush()
    except Exception:
        pass
    print(message)


class JobRunner:
    def __init__(
        self,
        conn: sqlite3.Connection,
        scrapers: dict,
        max_workers: int | None = None,
        db_path: str | None = None,
    ):
        self.conn = conn
        self.scrapers = scrapers
        self._scheduler: "BackgroundScheduler | None" = None
        self._active_schedules: dict[str, str] = {}

        # max_workers: prefer explicit arg, then env var, then default 4.
        if max_workers is not None:
            self.max_workers = max_workers
        else:
            env_val = os.environ.get("ACHILLES_JOB_WORKERS", "").strip()
            self.max_workers = int(env_val) if env_val.isdigit() else 4

        # db_path is needed so worker threads can open their own connections.
        # Try to derive from the conn's database attribute if not provided.
        if db_path is not None:
            self.db_path = db_path
        else:
            # sqlite3.Connection.database_name is only available in newer
            # Python versions. Fallback to inspecting PRAGMA database_list.
            try:
                row = conn.execute("PRAGMA database_list").fetchone()
                # row: (seq, name, file); file is empty for :memory:
                self.db_path = row[2] if row and row[2] else ":memory:"
            except Exception:
                self.db_path = ":memory:"

    def _get_source_code(self, source_key: int) -> str | None:
        row = self.conn.execute(
            "SELECT source_code FROM dim_source WHERE source_key = ?", (source_key,)
        ).fetchone()
        return row["source_code"] if row else None

    def _get_source_key(self, source_code: str) -> int | None:
        row = self.conn.execute(
            "SELECT source_key FROM dim_source WHERE source_code = ?", (source_code,)
        ).fetchone()
        return row["source_key"] if row else None

    def _enqueue_scheduled_job(self, source_code: str) -> None:
        """APScheduler callback: insert a queued job for *source_code* unless one is already active."""
        source_key = self._get_source_key(source_code)
        if source_key is None:
            console.print(f"[yellow]Scheduler: source '{source_code}' not found in dim_source — skipping.[/yellow]")
            return
        if not _should_enqueue(source_key, self.conn):
            console.print(f"[dim]Scheduler: {source_code} already queued/running — skipping duplicate enqueue.[/dim]")
            return
        job_id = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO ops_job_queue (job_id, source_key, requested_by, status, params) "
            "VALUES (?, ?, 'scheduler', 'queued', '{}')",
            (job_id, source_key),
        )
        self.conn.commit()
        console.print(f"[green]Scheduler: enqueued {source_code} (job_id={job_id[:8]}…)[/green]")

    def start_scheduler(self) -> None:
        """Create and start a BackgroundScheduler.

        Reads cron schedules from ops_scraper_schedule DB table (primary) and
        ACHILLES_SCHEDULE_<SOURCE_CODE> env vars (override). The scheduler is
        always started so live schedule updates from the web UI take effect
        within 60 s without restarting the add-on.
        """
        if not HAS_APSCHEDULER:
            console.print("[yellow]APScheduler not installed — cron scheduling disabled.[/yellow]")
            return

        db_schedules = _read_schedules_from_db(self.conn)
        env_schedules = _read_schedule_env()
        schedules = _merge_schedules(db_schedules, env_schedules)

        # Build a rich table showing schedule status for every known scraper.
        t = Table(title="Scraper Schedule", show_header=True)
        t.add_column("Source")
        t.add_column("Schedule")
        t.add_column("Status")

        if not schedules:
            console.print("[dim]No ACHILLES_SCHEDULE_* env vars found — all sources are manual-only.[/dim]")

        scheduler = BackgroundScheduler(timezone="UTC")
        registered: list[str] = []

        for source_code in sorted(self.scrapers.keys()):
            cron_expr = schedules.get(source_code)
            if cron_expr:
                try:
                    parts = cron_expr.split()
                    if len(parts) != 5:
                        raise ValueError(f"Expected 5 cron fields, got {len(parts)}")
                    minute, hour, day, month, day_of_week = parts
                    trigger = CronTrigger(
                        minute=minute, hour=hour, day=day,
                        month=month, day_of_week=day_of_week,
                    )
                    scheduler.add_job(
                        self._enqueue_scheduled_job,
                        trigger=trigger,
                        args=[source_code],
                        id=f"schedule_{source_code}",
                        name=f"Auto-enqueue {source_code}",
                        replace_existing=True,
                    )
                    t.add_row(source_code, cron_expr, "[green]scheduled[/green]")
                    registered.append(source_code)
                except Exception as exc:
                    t.add_row(source_code, cron_expr, f"[red]ERROR: {exc}[/red]")
            else:
                t.add_row(source_code, "—", "[dim]manual only[/dim]")

        console.print(t)

        if not registered:
            # No valid cron jobs — leave _scheduler as None.
            return

        scheduler.start()
        self._scheduler = scheduler
        self._active_schedules = dict(schedules)
        console.print(f"[bold green]Scheduler started:[/bold green] {len(registered)} source(s) on cron.")

    def _refresh_schedules(self) -> None:
        """Re-read schedules from DB + env and update APScheduler live.

        Called from run_loop every 60 s. Adds/removes/updates jobs without
        requiring an add-on restart.
        """
        if not HAS_APSCHEDULER or self._scheduler is None:
            return

        db_schedules = _read_schedules_from_db(self.conn)
        env_schedules = _read_schedule_env()
        new_schedules = _merge_schedules(db_schedules, env_schedules)

        if new_schedules == self._active_schedules:
            return  # nothing changed

        console.print("[dim]Scraper schedules changed — refreshing APScheduler…[/dim]")

        # Remove jobs that were dropped
        for source_code in list(self._active_schedules.keys()):
            if source_code not in new_schedules:
                try:
                    self._scheduler.remove_job(f"schedule_{source_code}")
                    console.print(f"[yellow]Scheduler: removed cron for {source_code}[/yellow]")
                except Exception:
                    pass

        # Add or update changed jobs
        for source_code, cron_expr in new_schedules.items():
            if self._active_schedules.get(source_code) != cron_expr:
                try:
                    parts = cron_expr.split()
                    if len(parts) == 5:
                        minute, hour, day, month, dow = parts
                        trigger = CronTrigger(
                            minute=minute, hour=hour, day=day,
                            month=month, day_of_week=dow,
                        )
                        self._scheduler.add_job(
                            self._enqueue_scheduled_job,
                            trigger=trigger,
                            args=[source_code],
                            id=f"schedule_{source_code}",
                            name=f"Auto-enqueue {source_code}",
                            replace_existing=True,
                        )
                        console.print(f"[green]Scheduler: (re)scheduled {source_code} → {cron_expr}[/green]")
                except Exception as exc:
                    console.print(f"[red]Scheduler refresh error for {source_code}: {exc}[/red]")

        self._active_schedules = dict(new_schedules)

    def _claim_jobs(self, n: int) -> list[dict]:
        """Claim up to *n* queued jobs atomically. Returns the claimed job rows."""
        rows = self.conn.execute(
            "SELECT * FROM ops_job_queue WHERE status='queued' ORDER BY requested_at ASC LIMIT ?",
            (n,),
        ).fetchall()
        claimed = []
        for row in rows:
            affected = self.conn.execute(
                "UPDATE ops_job_queue SET status='running', started_at=? WHERE job_id=? AND status='queued'",
                (int(time.time()), row["job_id"]),
            ).rowcount
            if affected > 0:
                claimed.append(dict(row))
        if claimed:
            self.conn.commit()
        return claimed

    # Keep legacy single-job claim for backward compatibility with tests/code
    # that may call it directly.
    def _claim_job(self) -> dict | None:
        jobs = self._claim_jobs(1)
        return jobs[0] if jobs else None

    def _set_batch_id(self, job_id: str, batch_id: str):
        """Pin the batch_id on ops_job_queue right at job start so the UI can
        tail logs/<batch_id>.log via the drawer immediately, not only at finish.
        """
        self.conn.execute(
            "UPDATE ops_job_queue SET batch_id=? WHERE job_id=?", (batch_id, job_id)
        )
        self.conn.commit()

    def _finish_job(self, job_id: str, result: ScrapeResult):
        status = "failed" if result.error else "done"
        self.conn.execute(
            "UPDATE ops_job_queue SET status=?, finished_at=?, rows_fetched=?, rows_inserted=?, rows_dlq=?, error_message=?, batch_id=? WHERE job_id=?",
            (
                status,
                int(time.time()),
                result.rows_fetched,
                result.rows_inserted,
                result.rows_dlq,
                result.error,
                result.batch_id,
                job_id,
            ),
        )
        self.conn.commit()

    def _run_scraper_with_logs(self, scraper_cls, batch_id: str, limit: int | None) -> ScrapeResult:
        """Run scraper inside stdout/stderr tee so output also lands in
        logs/<batch_id>.log. Returns the ScrapeResult; on exception, wraps
        it as a failed result with the same batch_id.

        NOTE: This method is used only when running on the main thread (e.g.
        single-threaded mode or direct calls from tests). In the parallel
        run_loop the worker thread uses _worker_run_scraper() instead.
        """
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = LOG_DIR / f"{batch_id}.log"

        # Line-buffered so the drawer's 3-second tail picks up fresh lines.
        log_file = open(log_path, "w", encoding="utf-8", buffering=1)
        orig_stdout, orig_stderr = sys.stdout, sys.stderr
        sys.stdout = _TeeWriter(orig_stdout, log_file)
        sys.stderr = _TeeWriter(orig_stderr, log_file)

        # rich.Console caches sys.stdout at construction time. Swap its file so
        # console.print() from inside the scraper run also hits the log.
        console.file = sys.stdout

        try:
            print(f"[batch {batch_id}] starting")
            scraper = scraper_cls(self.conn)
            # Inject batch_id so the scraper uses ours instead of generating its own.
            scraper.batch_id = batch_id
            try:
                result = scraper.run(limit=limit)
                if not result.batch_id:
                    result.batch_id = batch_id
            except Exception as e:
                result = ScrapeResult(error=str(e), batch_id=batch_id)
            print(
                f"[batch {batch_id}] finished fetched={result.rows_fetched} "
                f"inserted={result.rows_inserted} dlq={result.rows_dlq} "
                f"error={result.error or 'none'}"
            )
            return result
        finally:
            sys.stdout = orig_stdout
            sys.stderr = orig_stderr
            console.file = orig_stdout
            try:
                log_file.flush()
                log_file.close()
            except Exception:
                pass

    def _run_auth_test_with_logs(
        self, scraper_cls, batch_id: str, source_code: str,
    ) -> ScrapeResult:
        """Special path for `params.test_auth=true` jobs from /admin/auth.
        Calls scraper.test_login() — no scraping, just a login dance — and
        encodes the (ok, message) outcome as a ScrapeResult.
        """
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = LOG_DIR / f"{batch_id}.log"

        log_file = open(log_path, "w", encoding="utf-8", buffering=1)
        orig_stdout, orig_stderr = sys.stdout, sys.stderr
        sys.stdout = _TeeWriter(orig_stdout, log_file)
        sys.stderr = _TeeWriter(orig_stderr, log_file)
        console.file = sys.stdout

        try:
            print(f"[batch {batch_id}] test_login for {source_code}")
            scraper = scraper_cls(self.conn)
            scraper.batch_id = batch_id

            test_login = getattr(scraper, "test_login", None)
            if not callable(test_login):
                msg = (
                    f"scraper {source_code} does not support test_login "
                    "(not an AuthenticatedScraper subclass)"
                )
                print(msg)
                return ScrapeResult(error=msg, batch_id=batch_id)

            try:
                ok, message = test_login()
            except Exception as e:
                ok, message = False, f"unexpected: {e}"

            print(f"test_login result: ok={ok} message={message}")
            if ok:
                return ScrapeResult(batch_id=batch_id, error=None)
            return ScrapeResult(batch_id=batch_id, error=message)
        finally:
            sys.stdout = orig_stdout
            sys.stderr = orig_stderr
            console.file = orig_stdout
            try:
                log_file.flush()
                log_file.close()
            except Exception:
                pass

    def run_loop(self):
        console.print(
            f"[bold green]Job runner started.[/bold green] "
            f"Polling every 5 s… workers={self.max_workers}"
        )
        self.start_scheduler()

        # in_flight: Future → job_id mapping so we can reap results.
        in_flight: dict[Future, str] = {}
        _poll_iter = 0

        with ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="scraper") as executor:
            try:
                while True:
                    _poll_iter += 1
                    # ── 0. Refresh schedules from DB every 60 s ─────────────
                    if _poll_iter % 12 == 0:
                        self._refresh_schedules()

                    # ── 1. Reap completed futures ────────────────────────────
                    done_futures = [f for f in list(in_flight) if f.done()]
                    for future in done_futures:
                        job_id = in_flight.pop(future)
                        try:
                            _returned_job_id, result = future.result()
                        except Exception as exc:
                            # Safety-net: exception escaped the worker wrapper.
                            console.print(
                                f"[red]Worker raised unhandled exception for job {job_id[:8]}…: {exc}[/red]"
                            )
                            result = ScrapeResult(error=str(exc))
                        self._finish_job(job_id, result)
                        icon = "[red]✗[/red]" if result.error else "[green]✓[/green]"
                        console.print(
                            f"{icon} job={job_id[:8]}… "
                            f"fetched={result.rows_fetched} inserted={result.rows_inserted} dlq={result.rows_dlq}"
                        )

                    # ── 2. Claim new jobs to fill free worker slots ──────────
                    free_slots = self.max_workers - len(in_flight)
                    if free_slots > 0:
                        jobs = self._claim_jobs(free_slots)
                        for job in jobs:
                            source_code = (
                                self._get_source_code(job["source_key"])
                                if job.get("source_key")
                                else None
                            )
                            if source_code and source_code in self.scrapers:
                                params = job.get("params") or {}
                                if not isinstance(params, dict):
                                    params = {}
                                limit = int(params["limit"]) if params.get("limit") else None
                                test_auth = bool(params.get("test_auth"))

                                batch_id = _make_batch_id(source_code)
                                self._set_batch_id(job["job_id"], batch_id)

                                future = executor.submit(
                                    _worker_run_job,
                                    self.db_path,
                                    self.scrapers,
                                    job,
                                    source_code,
                                    batch_id,
                                    limit,
                                    test_auth,
                                )
                                in_flight[future] = job["job_id"]
                            else:
                                self.conn.execute(
                                    "UPDATE ops_job_queue SET status='failed', error_message='Unknown source' WHERE job_id=?",
                                    (job["job_id"],),
                                )
                                self.conn.commit()

                    time.sleep(5)

            except (KeyboardInterrupt, SystemExit):
                console.print("[bold yellow]Job runner stopping…[/bold yellow]")
            finally:
                if self._scheduler is not None:
                    try:
                        self._scheduler.shutdown(wait=False)
                        console.print("[dim]Scheduler shut down.[/dim]")
                    except Exception:
                        pass
                # executor.__exit__ will wait for in-flight futures to finish.
