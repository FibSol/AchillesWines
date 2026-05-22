import sqlite3
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from rich.console import Console
from .scrapers.base import ScrapeResult

console = Console()

# Per-batch logs live at <project_root>/logs/<batch_id>.log so the
# JobLogsDrawer at /admin/jobs can tail them via GET /api/jobs/[jobId]/logs.
LOG_DIR = Path.cwd() / "logs"


class _TeeWriter:
    """Write to both the original stream and an open file. Best-effort flush."""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for s in self.streams:
            try:
                s.write(data)
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


class JobRunner:
    def __init__(self, conn: sqlite3.Connection, scrapers: dict):
        self.conn = conn
        self.scrapers = scrapers

    def _get_source_code(self, source_key: int) -> str | None:
        row = self.conn.execute(
            "SELECT source_code FROM dim_source WHERE source_key = ?", (source_key,)
        ).fetchone()
        return row["source_code"] if row else None

    def _claim_job(self) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM ops_job_queue WHERE status='queued' ORDER BY requested_at ASC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        affected = self.conn.execute(
            "UPDATE ops_job_queue SET status='running', started_at=? WHERE job_id=? AND status='queued'",
            (int(time.time()), row["job_id"]),
        ).rowcount
        self.conn.commit()
        return dict(row) if affected > 0 else None

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

    def run_loop(self):
        console.print("[bold green]Job runner started.[/bold green] Polling every 5 s…")
        while True:
            job = self._claim_job()
            if job:
                source_code = self._get_source_code(job["source_key"]) if job.get("source_key") else None
                if source_code and source_code in self.scrapers:
                    console.print(f"[cyan]Job {job['job_id'][:8]}… source={source_code}[/cyan]")
                    params = job.get("params") or {}
                    limit = int(params["limit"]) if isinstance(params, dict) and params.get("limit") else None

                    batch_id = _make_batch_id(source_code)
                    self._set_batch_id(job["job_id"], batch_id)

                    result = self._run_scraper_with_logs(self.scrapers[source_code], batch_id, limit)
                    self._finish_job(job["job_id"], result)
                    icon = "[red]✗[/red]" if result.error else "[green]✓[/green]"
                    console.print(
                        f"{icon} fetched={result.rows_fetched} inserted={result.rows_inserted} dlq={result.rows_dlq}"
                    )
                else:
                    self.conn.execute(
                        "UPDATE ops_job_queue SET status='failed', error_message='Unknown source' WHERE job_id=?",
                        (job["job_id"],),
                    )
                    self.conn.commit()
            time.sleep(5)
