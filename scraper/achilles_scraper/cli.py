import click
from rich.console import Console
from rich.table import Table

console = Console()

SCRAPERS: dict[str, type] = {}

def _load_scrapers():
    from .scrapers.millesima import MillesimaScraper
    SCRAPERS["millesima"] = MillesimaScraper

@click.group()
def cli():
    """Achilles scraper — wine data ingestion CLI."""
    _load_scrapers()

@cli.command()
@click.option("--source", required=True, type=click.Choice(["millesima"]), help="Source to scrape")
@click.option("--limit", default=None, type=int, help="Max rows to fetch")
def run(source: str, limit):
    """Run a scraper immediately."""
    from .config import config
    from .db import get_db
    config.ensure_dirs()
    conn = get_db(config.db_path)
    scraper = SCRAPERS[source](conn)
    console.print(f"[bold]Scraping:[/bold] {source}" + (f" (limit={limit})" if limit else ""))
    result = scraper.run(limit=limit)
    t = Table(title="Result")
    t.add_column("Metric")
    t.add_column("Value", justify="right")
    for label, val in [("Fetched", result.rows_fetched), ("Inserted (staging)", result.rows_inserted), ("DLQ", result.rows_dlq), ("Skipped unchanged", result.rows_skipped_unchanged)]:
        t.add_row(label, str(val))
    if result.error:
        t.add_row("[red]Error[/red]", result.error)
    console.print(t)

@cli.command("run-jobs")
def run_jobs():
    """Poll ops_job_queue and execute queued jobs."""
    from .config import config
    from .db import get_db
    from .job_runner import JobRunner
    conn = get_db(config.db_path)
    runner = JobRunner(conn, SCRAPERS)
    runner.run_loop()

if __name__ == "__main__":
    cli()
