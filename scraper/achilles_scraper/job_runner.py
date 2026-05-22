import sqlite3
import time
from rich.console import Console
from .scrapers.base import ScrapeResult

console = Console()

class JobRunner:
    def __init__(self, conn: sqlite3.Connection, scrapers: dict):
        self.conn = conn
        self.scrapers = scrapers

    def _get_source_code(self, source_key: int) -> str | None:
        row = self.conn.execute("SELECT source_code FROM dim_source WHERE source_key = ?", (source_key,)).fetchone()
        return row["source_code"] if row else None

    def _claim_job(self) -> dict | None:
        row = self.conn.execute("SELECT * FROM ops_job_queue WHERE status='queued' ORDER BY requested_at ASC LIMIT 1").fetchone()
        if not row:
            return None
        affected = self.conn.execute(
            "UPDATE ops_job_queue SET status='running', started_at=? WHERE job_id=? AND status='queued'",
            (int(time.time()), row["job_id"])
        ).rowcount
        self.conn.commit()
        return dict(row) if affected > 0 else None

    def _finish_job(self, job_id: str, result: ScrapeResult):
        status = "failed" if result.error else "done"
        self.conn.execute(
            "UPDATE ops_job_queue SET status=?, finished_at=?, rows_fetched=?, rows_inserted=?, rows_dlq=?, error_message=?, batch_id=? WHERE job_id=?",
            (status, int(time.time()), result.rows_fetched, result.rows_inserted, result.rows_dlq, result.error, result.batch_id, job_id)
        )
        self.conn.commit()

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
                    try:
                        result = self.scrapers[source_code](self.conn).run(limit=limit)
                    except Exception as e:
                        result = ScrapeResult(error=str(e))
                    self._finish_job(job["job_id"], result)
                    icon = "[red]✗[/red]" if result.error else "[green]✓[/green]"
                    console.print(f"{icon} fetched={result.rows_fetched} inserted={result.rows_inserted} dlq={result.rows_dlq}")
                else:
                    self.conn.execute("UPDATE ops_job_queue SET status='failed', error_message='Unknown source' WHERE job_id=?", (job["job_id"],))
                    self.conn.commit()
            time.sleep(5)
