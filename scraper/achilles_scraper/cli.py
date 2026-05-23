import click
from rich.console import Console
from rich.table import Table

console = Console()

SCRAPERS: dict[str, type] = {}

# All source codes available in the CLI
_ALL_SOURCES = [
    # --- Web retail scrapers (→ staging_price_candidates) ---
    "millesima",
    "millesima_be",
    "idealwine",
    "lavinia",
    "vinatis",
    "cavissima",
    "cavissima_be",
    "ventealapropriete",
    "comptoir_des_millesimes",
    "vinsbrunin",
    "hachette_vins_shop",
    "wdc_be",
    "cinoco",
    "wijnhuis",
    "topwijnen_be",
    "wijnendeclerck_be",
    "belgiumwinewatchers",
    # --- Email newsletter scrapers (→ staging_price_candidates via IMAP) ---
    "millesima_email",
    "idealwine_email",
    "lavinia_email",
    # --- Press / critic scrapers (→ fact_rating) ---
    "rvf",
    "decanter",
    "james_suckling",
    "hachette_vins",
    "figaro_vin",
    "terredevins",
    # --- Vintage chart scrapers (→ fact_vintage_rating) ---
    "vintage_ratings",
]


def _load_scrapers():
    # Web retail
    from .scrapers.millesima import MillesimaScraper
    from .scrapers.millesima_be import MillesimaBeScraper
    from .scrapers.idealwine import IDealwineScraper
    from .scrapers.lavinia import LaviniaScraper
    from .scrapers.vinatis import VinatissScraper
    from .scrapers.cavissima import CavissimaScraper
    from .scrapers.cavissima_be import CavissimaBeScraper
    from .scrapers.ventealapropriete import VenteALaPropieteScraper
    from .scrapers.comptoir_des_millesimes import ComptoirDesMillesimesScraper
    from .scrapers.vinsbrunin import VinsBruninScraper
    from .scrapers.hachette_vins_shop import HachetteVinsShopScraper
    from .scrapers.wdc import WdcScraper
    from .scrapers.cinoco import CinocoScraper
    from .scrapers.wijnhuis import WijnhuisScraper
    from .scrapers.topwijnen_be import TopwijnenBeScraper
    from .scrapers.wijnendeclerck_be import WijnendeclerckBeScraper
    from .scrapers.belgiumwinewatchers import BelgiumWineWatchersScraper
    # Email newsletter
    from .scrapers.email_samples import (
        MillesimaEmailScraper,
        IDealwineEmailScraper,
        LaviniaEmailScraper,
    )
    # Press / critics
    from .scrapers.rvf import RvfScraper
    from .scrapers.decanter_ratings import DecanterRatingsScraper
    from .scrapers.james_suckling import JamesSucklingScraper
    from .scrapers.hachette_vins_guide import HachetteVinsGuideScraper
    from .scrapers.figaro_vin import FigaroVinScraper
    from .scrapers.terredevins import TerreDeVinsScraper
    # Vintage charts
    from .scrapers.vintage_ratings import VintageRatingsScraper
    from .scrapers.wine_searcher import WineSearcherScraper

    SCRAPERS["millesima"] = MillesimaScraper
    SCRAPERS["millesima_be"] = MillesimaBeScraper
    SCRAPERS["idealwine"] = IDealwineScraper
    SCRAPERS["lavinia"] = LaviniaScraper
    SCRAPERS["vinatis"] = VinatissScraper
    SCRAPERS["cavissima"] = CavissimaScraper
    SCRAPERS["cavissima_be"] = CavissimaBeScraper
    SCRAPERS["ventealapropriete"] = VenteALaPropieteScraper
    SCRAPERS["comptoir_des_millesimes"] = ComptoirDesMillesimesScraper
    SCRAPERS["vinsbrunin"] = VinsBruninScraper
    SCRAPERS["hachette_vins_shop"] = HachetteVinsShopScraper
    SCRAPERS["wdc_be"] = WdcScraper
    SCRAPERS["cinoco"] = CinocoScraper
    SCRAPERS["wijnhuis"] = WijnhuisScraper
    SCRAPERS["topwijnen_be"] = TopwijnenBeScraper
    SCRAPERS["wijnendeclerck_be"] = WijnendeclerckBeScraper
    SCRAPERS["belgiumwinewatchers"] = BelgiumWineWatchersScraper
    SCRAPERS["millesima_email"] = MillesimaEmailScraper
    SCRAPERS["idealwine_email"] = IDealwineEmailScraper
    SCRAPERS["lavinia_email"] = LaviniaEmailScraper
    SCRAPERS["rvf"] = RvfScraper
    SCRAPERS["decanter"] = DecanterRatingsScraper
    SCRAPERS["james_suckling"] = JamesSucklingScraper
    SCRAPERS["hachette_vins"] = HachetteVinsGuideScraper
    SCRAPERS["figaro_vin"] = FigaroVinScraper
    SCRAPERS["terredevins"] = TerreDeVinsScraper
    SCRAPERS["vintage_ratings"] = VintageRatingsScraper
    SCRAPERS["wine_searcher"] = WineSearcherScraper


@click.group()
def cli():
    """Achilles scraper — wine data ingestion CLI."""
    _load_scrapers()


@cli.command()
@click.option(
    "--source", required=True,
    type=click.Choice(_ALL_SOURCES),
    help="Source to scrape",
)
@click.option("--limit", default=None, type=int, help="Max rows to fetch")
def run(source: str, limit):
    """Run a scraper immediately (recorded in ops_job_queue for history)."""
    import time
    import uuid
    import json
    from .config import config
    from .db import get_db
    from .job_runner import _make_batch_id, LOG_DIR
    config.ensure_dirs()
    conn = get_db(config.db_path)

    # Resolve source_key from dim_source so the job row links correctly.
    row = conn.execute(
        "SELECT source_key FROM dim_source WHERE source_code = ?", (source,)
    ).fetchone()
    source_key = row["source_key"] if row else None

    job_id = str(uuid.uuid4())
    batch_id = _make_batch_id(source)
    params_json = json.dumps({"limit": limit}) if limit else None
    started_at = int(time.time())

    conn.execute(
        "INSERT INTO ops_job_queue "
        "(job_id, source_key, requested_by, status, started_at, batch_id, params) "
        "VALUES (?, ?, 'cli', 'running', ?, ?, ?)",
        (job_id, source_key, started_at, batch_id, params_json),
    )
    conn.commit()

    # Single log file — use Python logging for ALL writes so ordering is correct.
    # Two competing file descriptors (log_file + FileHandler) on the same path
    # cause ordering issues; instead we use one FileHandler for everything.
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"{batch_id}.log"

    import logging as _logging
    # Suppress noisy HTTP internals — keep only WARNING+ from httpcore/httpx.
    for _noisy in ("httpcore", "httpx", "hpack", "h2"):
        _logging.getLogger(_noisy).setLevel(_logging.WARNING)
    file_handler = _logging.FileHandler(str(log_path), mode="w", encoding="utf-8")
    file_handler.setFormatter(_logging.Formatter("%(asctime)s [%(name)s] %(levelname)s %(message)s"))
    file_handler.setLevel(_logging.DEBUG)
    root_logger = _logging.getLogger()
    root_logger.addHandler(file_handler)
    if root_logger.level == _logging.NOTSET or root_logger.level > _logging.DEBUG:
        root_logger.setLevel(_logging.DEBUG)
    _batch_log = _logging.getLogger("achilles_scraper.cli")

    console.print(f"[bold]Scraping:[/bold] {source}" + (f" (limit={limit})" if limit else ""))
    _batch_log.info("[batch %s] starting (cli)", batch_id)

    try:
        scraper = SCRAPERS[source](conn)
        scraper.batch_id = batch_id
        result = scraper.run(limit=limit)
        if not result.batch_id:
            result.batch_id = batch_id
    except Exception as exc:
        from .scrapers.base import ScrapeResult
        result = ScrapeResult(error=str(exc), batch_id=batch_id)

    _batch_log.info(
        "[batch %s] finished fetched=%d inserted=%d dlq=%d error=%s",
        batch_id, result.rows_fetched, result.rows_inserted, result.rows_dlq,
        result.error or "none",
    )
    root_logger.removeHandler(file_handler)
    file_handler.close()

    status = "failed" if result.error else "done"
    conn.execute(
        "UPDATE ops_job_queue SET status=?, finished_at=?, rows_fetched=?, "
        "rows_inserted=?, rows_dlq=?, error_message=? WHERE job_id=?",
        (
            status,
            int(time.time()),
            result.rows_fetched,
            result.rows_inserted,
            result.rows_dlq,
            result.error,
            job_id,
        ),
    )
    conn.commit()

    t = Table(title="Result")
    t.add_column("Metric")
    t.add_column("Value", justify="right")
    for label, val in [
        ("Fetched", result.rows_fetched),
        ("Inserted (staging)", result.rows_inserted),
        ("DLQ", result.rows_dlq),
        ("Skipped unchanged", result.rows_skipped_unchanged),
    ]:
        t.add_row(label, str(val))
    if result.error:
        t.add_row("[red]Error[/red]", result.error)
    console.print(t)
    console.print(f"[dim]Job recorded: {job_id[:8]}… batch={batch_id}[/dim]")


@cli.command("run-jobs")
def run_jobs():
    """Poll ops_job_queue and execute queued jobs."""
    from .config import config
    from .db import get_db
    from .job_runner import JobRunner
    conn = get_db(config.db_path)
    runner = JobRunner(conn, SCRAPERS)
    runner.run_loop()


@cli.command("list-sources")
def list_sources():
    """List all registered scrapers."""
    _load_scrapers()
    t = Table(title="Registered scrapers")
    t.add_column("source_code")
    t.add_column("class")
    for code, cls in sorted(SCRAPERS.items()):
        t.add_row(code, cls.__name__)
    console.print(t)


if __name__ == "__main__":
    cli()
