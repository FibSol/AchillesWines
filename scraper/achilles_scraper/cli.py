import os
import sys
from pathlib import Path
import click
from rich.console import Console
from rich.table import Table

# Force UTF-8 output on Windows so Rich can render box-drawing and emoji chars.
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
if sys.stderr.encoding and sys.stderr.encoding.lower() not in ("utf-8", "utf8"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]


def _load_dotenv() -> None:
    """Load .env from the project root (3 levels above this file) if present.
    Env vars already set in the process take precedence (no override).
    """
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        if k and k not in os.environ:
            os.environ[k] = v.strip()


_load_dotenv()

console = Console()

SCRAPERS: dict[str, type] = {}

# All source codes available in the CLI
_ALL_SOURCES = [
    # --- Web retail scrapers (→ staging_price_candidates) ---
    "millesima",
    "millesima_be",
    "idealwine",
    "idealwine_auctions",
    "idealwine_history",
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
    "wine_searcher",         # Wine-Searcher per-merchant prices via Firecrawl CLI page scrape
    # --- Email newsletter scrapers (→ staging_price_candidates via IMAP) ---
    "millesima_email",
    "idealwine_email",
    "lavinia_email",
    "ventealapropriete_email",
    # --- Press / critic scrapers (→ fact_rating) ---
    "rvf",
    "decanter",
    "james_suckling",
    "hachette_vins",
    "figaro_vin",
    "terredevins",
    # --- Vintage chart scrapers (→ fact_vintage_rating) ---
    "vintage_ratings",
    # --- Official producer / syndicate sources (→ dim_producer) ---
    "civb",               # CIVB — Bordeaux interprofession → dim_producer
    "bivb",               # BIVB — Burgundy interprofession → dim_producer
    "inter_rhone",        # Inter-Rhône → dim_producer
    "interloire",         # InterLoire → dim_producer
    "civc",               # CIVC — Champagne interprofession → dim_producer
    "civa",               # CIVA — Alsace interprofession → dim_producer
    "civl",               # CIVL — Languedoc interprofession → dim_producer
    # --- Official appellation / dimension sources ---
    "inao",               # INAO French AOC/IGP registry → dim_appellation
    # --- Official market / statistical sources ---
    "ec_agrifood",        # EC Agri-food wine API → fact_market_index
    "eurostat_harvest",   # Eurostat tag00121 → fact_harvest_volume
    "werc",               # WERC megafile 1835-2024 → fact_werc_stats
    # --- Crowd / user-aggregate ratings (→ staging_rating_candidates / fact_rating) ---
    "vivino",             # Vivino community ratings (tiebreaker-only → staging, ADR-013)
    "xwines",             # X-Wines/Vivino crowd ratings (CC0)
    "kaggle_reviews",     # WineEnthusiast reviews via Kaggle API (v2, 130k, has title)
    "kaggle_reviews_v1",  # WineEnthusiast reviews via Kaggle API (v1, 150k, NV only)
    "cellartracker_xlquery",  # CellarTracker official xlquery.asp export — own cellar + 30 critic columns
    "somlier",               # soMLier Mendeley Data wine dataset (manual-download stub)
]


def _load_scrapers():
    # Web retail
    from .scrapers.millesima import MillesimaScraper
    from .scrapers.millesima_be import MillesimaBeScraper
    from .scrapers.idealwine import IDealwineScraper, IDealwineAuctionsScraper, IDealwineHistoricalScraper
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
        VenteALaProprieteEmailScraper,
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
    # Official producer / syndicate sources
    from .scrapers.syndicates import (
        CIVBScraper,
        BIVBScraper,
        InterRhoneScraper,
        InterLoireScraper,
        CIVCScraper,
        CIVAScraper,
        CIVLScraper,
    )
    # Official appellation / dimension sources
    from .scrapers.inao import INAOScraper
    # Official statistical sources
    from .scrapers.ec_agrifood import EcAgrifoodScraper
    from .scrapers.eurostat_harvest import EurostatHarvestScraper
    from .scrapers.werc import WercScraper
    # Crowd ratings
    from .scrapers.vivino import VivinoScraper
    from .scrapers.xwines import XWinesScraper
    from .scrapers.kaggle_reviews import KaggleReviewsScraper, KaggleReviewsV1Scraper
    from .scrapers.cellartracker_xlquery import CellarTrackerXlqueryScraper
    from .scrapers.somlier import SoMLierScraper

    SCRAPERS["millesima"] = MillesimaScraper
    SCRAPERS["millesima_be"] = MillesimaBeScraper
    SCRAPERS["idealwine"] = IDealwineScraper
    SCRAPERS["idealwine_auctions"] = IDealwineAuctionsScraper
    SCRAPERS["idealwine_history"] = IDealwineHistoricalScraper
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
    SCRAPERS["ventealapropriete_email"] = VenteALaProprieteEmailScraper
    SCRAPERS["rvf"] = RvfScraper
    SCRAPERS["decanter"] = DecanterRatingsScraper
    SCRAPERS["james_suckling"] = JamesSucklingScraper
    SCRAPERS["hachette_vins"] = HachetteVinsGuideScraper
    SCRAPERS["figaro_vin"] = FigaroVinScraper
    SCRAPERS["terredevins"] = TerreDeVinsScraper
    SCRAPERS["vintage_ratings"] = VintageRatingsScraper
    SCRAPERS["wine_searcher"] = WineSearcherScraper
    SCRAPERS["civb"] = CIVBScraper
    SCRAPERS["bivb"] = BIVBScraper
    SCRAPERS["inter_rhone"] = InterRhoneScraper
    SCRAPERS["interloire"] = InterLoireScraper
    SCRAPERS["civc"] = CIVCScraper
    SCRAPERS["civa"] = CIVAScraper
    SCRAPERS["civl"] = CIVLScraper
    SCRAPERS["inao"] = INAOScraper
    SCRAPERS["ec_agrifood"] = EcAgrifoodScraper
    SCRAPERS["eurostat_harvest"] = EurostatHarvestScraper
    SCRAPERS["werc"] = WercScraper
    SCRAPERS["vivino"] = VivinoScraper
    SCRAPERS["xwines"] = XWinesScraper
    SCRAPERS["kaggle_reviews"] = KaggleReviewsScraper
    SCRAPERS["kaggle_reviews_v1"] = KaggleReviewsV1Scraper
    SCRAPERS["cellartracker_xlquery"] = CellarTrackerXlqueryScraper
    SCRAPERS["somlier"] = SoMLierScraper


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
    # Case-insensitive match: CLI uses lowercase, some dim_source rows are uppercase.
    row = conn.execute(
        "SELECT source_key FROM dim_source WHERE LOWER(source_code) = LOWER(?)", (source,)
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


@cli.command("benchmark")
@click.option(
    "--source", required=True,
    type=click.Choice(_ALL_SOURCES),
    help="Source to benchmark",
)
@click.option(
    "--levels",
    default="20,50,100,500,750,1000",
    help="Comma-separated limit ladder (default: 20,50,100,500,750,1000)",
)
def benchmark(source: str, levels: str):
    """Run incremental scrape ladder to find optimal batch size for a source.

    Runs the scraper at each level sequentially. Because content-hash dedup is
    applied, each run only INSERTS the marginal rows not yet seen. The success
    rate at each step is inserted/(inserted+dlq), which measures quality of
    catalog items at that position range — independent of already-seen skips.

    Writes recommended_batch_size, benchmark_success_rate, and benchmark_notes
    back to dim_source so the admin UI can prefill the limit field.
    """
    import json
    import time
    from .config import config
    from .db import get_db
    from .job_runner import _make_batch_id, LOG_DIR

    config.ensure_dirs()
    conn = get_db(config.db_path)

    try:
        level_list = [int(l.strip()) for l in levels.split(",") if l.strip()]
    except ValueError:
        console.print("[red]--levels must be comma-separated integers[/red]")
        return

    console.rule(f"[bold]Benchmark: {source}[/bold]")
    console.print(f"Levels: {level_list}")
    console.print()

    rows = []          # list of dicts per level
    cumulative_staged = 0
    cumulative_dlq = 0

    for limit in level_list:
        console.rule(f"Level {limit}")
        batch_id = _make_batch_id(f"bench_{source}")
        LOG_DIR.mkdir(parents=True, exist_ok=True)

        import logging as _logging
        for _noisy in ("httpcore", "httpx", "hpack", "h2"):
            _logging.getLogger(_noisy).setLevel(_logging.WARNING)
        log_path = LOG_DIR / f"{batch_id}.log"
        fh = _logging.FileHandler(str(log_path), mode="w", encoding="utf-8")
        fh.setFormatter(_logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        fh.setLevel(_logging.DEBUG)
        root = _logging.getLogger()
        root.addHandler(fh)
        if root.level == _logging.NOTSET or root.level > _logging.DEBUG:
            root.setLevel(_logging.DEBUG)

        t0 = time.time()
        try:
            scraper = SCRAPERS[source](conn)
            scraper.batch_id = batch_id
            result = scraper.run(limit=limit)
        except Exception as exc:
            from .scrapers.base import ScrapeResult
            result = ScrapeResult(error=str(exc), batch_id=batch_id)
        elapsed = time.time() - t0

        root.removeHandler(fh)
        fh.close()

        marginal_inserted = result.rows_inserted
        marginal_dlq = result.rows_dlq
        denominator = marginal_inserted + marginal_dlq
        success_rate = (marginal_inserted / denominator) if denominator > 0 else None

        cumulative_staged += marginal_inserted
        cumulative_dlq += marginal_dlq

        rows.append({
            "limit": limit,
            "fetched": result.rows_fetched,
            "new_inserted": marginal_inserted,
            "new_dlq": marginal_dlq,
            "skipped": result.rows_skipped_unchanged,
            "success_rate": success_rate,
            "elapsed_s": round(elapsed, 1),
            "error": result.error,
        })

        sr_str = f"{success_rate:.0%}" if success_rate is not None else "n/a"
        color = "green" if (success_rate or 0) >= 0.6 else "yellow" if (success_rate or 0) >= 0.3 else "red"
        console.print(
            f"  fetched={result.rows_fetched}  new={marginal_inserted}  dlq={marginal_dlq}"
            f"  skip={result.rows_skipped_unchanged}  [{color}]rate={sr_str}[/{color}]"
            f"  {elapsed:.1f}s"
            + (f"  [red]ERROR: {result.error[:60]}[/red]" if result.error else "")
        )

        # Stop early if the scraper errored hard (not just DLQ)
        if result.error and marginal_inserted == 0:
            console.print(f"[red]Stopping ladder — scraper failed at level {limit}[/red]")
            break

    # --- Recommendation logic ---
    MIN_SUCCESS_RATE = 0.50   # below this the scraper is too unreliable at that depth
    MIN_MARGINAL = 3           # at least 3 new rows to count the level as meaningful

    recommended = None
    for r in reversed(rows):
        sr = r["success_rate"]
        if sr is None:
            continue
        if sr >= MIN_SUCCESS_RATE and r["new_inserted"] >= MIN_MARGINAL and not r["error"]:
            recommended = r["limit"]
            break

    # Fallback: first level that got any inserts
    if recommended is None:
        for r in rows:
            if r["new_inserted"] > 0:
                recommended = r["limit"]
                break

    rec_row = next((r for r in rows if r["limit"] == recommended), None)
    rec_sr = rec_row["success_rate"] if rec_row else None

    # --- Summary table ---
    console.print()
    t = Table(title=f"Benchmark results — {source}")
    t.add_column("Limit", justify="right")
    t.add_column("Fetched", justify="right")
    t.add_column("New ins.", justify="right", style="green")
    t.add_column("New DLQ", justify="right", style="yellow")
    t.add_column("Skipped", justify="right")
    t.add_column("Success%", justify="right")
    t.add_column("Time", justify="right")
    t.add_column("Rec?", justify="center")
    for r in rows:
        sr = f"{r['success_rate']:.0%}" if r["success_rate"] is not None else "—"
        t.add_row(
            str(r["limit"]),
            str(r["fetched"]),
            str(r["new_inserted"]),
            str(r["new_dlq"]),
            str(r["skipped"]),
            sr,
            f"{r['elapsed_s']}s",
            "[green]REC[/green]" if r["limit"] == recommended else "",
        )
    console.print(t)

    if recommended:
        console.print(
            f"\n[bold green]Recommended batch size: {recommended}[/bold green]"
            + (f"  (success rate {rec_sr:.0%})" if rec_sr is not None else "")
        )
    else:
        console.print("\n[red]Could not determine a recommended batch size — all levels had poor results[/red]")

    # --- Persist to dim_source ---
    notes_json = json.dumps({
        "levels": rows,
        "cumulative_staged": cumulative_staged,
        "cumulative_dlq": cumulative_dlq,
        "run_at": int(time.time()),
    }, separators=(",", ":"))

    conn.execute(
        """UPDATE dim_source
           SET recommended_batch_size = ?,
               last_benchmark_at      = ?,
               benchmark_success_rate = ?,
               benchmark_notes        = ?
           WHERE source_code = ?""",
        (
            recommended,
            int(time.time()),
            rec_sr,
            notes_json,
            source,
        ),
    )
    conn.commit()
    console.print(f"[dim]Saved to dim_source.recommended_batch_size = {recommended}[/dim]")


@cli.command("promote")
@click.option("--dry-run", is_flag=True, default=False, help="Show what would be promoted without writing to fact_price")
def promote(dry_run: bool):
    """Promote concordant staging candidates to fact_price.

    Applies the tri-source promotion rule: wine_keys with ≥2 staging rows whose
    prices agree within ±15% of the median are promoted to fact_price.  Already-
    promoted candidates (promoted_at IS NOT NULL) are skipped automatically.

    Use --dry-run to see the counts without committing any rows.
    """
    from .config import config
    from .db import get_db
    from .promoter import run_promotion

    config.ensure_dirs()
    conn = get_db(config.db_path)

    # Stats before
    before_fact = conn.execute("SELECT COUNT(*) FROM fact_price").fetchone()[0]
    pending = conn.execute(
        "SELECT COUNT(*) FROM staging_price_candidates WHERE needs_review=1 AND promoted_at IS NULL"
    ).fetchone()[0]
    overlap = conn.execute(
        """SELECT COUNT(*) FROM (
               SELECT wine_key FROM staging_price_candidates
               WHERE needs_review=1 AND promoted_at IS NULL
               GROUP BY wine_key HAVING COUNT(DISTINCT source_key) >= 2
           )"""
    ).fetchone()[0]

    console.print(f"[bold]Staging candidates pending:[/bold] {pending}")
    console.print(f"[bold]Wine keys with 2+ sources:[/bold] {overlap}")
    console.print(f"[bold]Current fact_price rows:[/bold] {before_fact}")
    console.print()

    if dry_run:
        console.print("[yellow]Dry-run mode — no rows will be written.[/yellow]")
        return

    result = run_promotion(conn)

    after_fact = conn.execute("SELECT COUNT(*) FROM fact_price").fetchone()[0]

    t = Table(title="Promotion result")
    t.add_column("Metric")
    t.add_column("Value", justify="right")
    t.add_row("Promoted to fact_price", str(result.promoted))
    t.add_row("Still pending (single-source)", str(result.pending))
    t.add_row("fact_price rows before", str(before_fact))
    t.add_row("fact_price rows after", str(after_fact))
    console.print(t)


@cli.command("promote-ratings")
@click.option("--dry-run", is_flag=True, default=False, help="Show what would be promoted without writing to fact_rating")
def promote_ratings(dry_run: bool):
    """Promote staging rating candidates to fact_rating.

    Applies the multi-source gate: wine_keys with ≥2 distinct source_key values
    in staging_rating_candidates are promoted to fact_rating.  Mono-source rows
    stay in staging with needs_review=1.

    Use --dry-run to see the counts without committing any rows.
    """
    from .config import config
    from .db import get_db
    from .promoter import promote_ratings as _promote_ratings, promote_vivino_tiebreakers as _promote_vivino

    config.ensure_dirs()
    conn = get_db(config.db_path)

    # Stats before
    before_fact = conn.execute("SELECT COUNT(*) FROM fact_rating").fetchone()[0]
    pending = conn.execute(
        "SELECT COUNT(*) FROM staging_rating_candidates WHERE needs_review=1 AND promoted_at IS NULL"
    ).fetchone()[0]
    multi_source = conn.execute(
        """SELECT COUNT(*) FROM (
               SELECT wine_key FROM staging_rating_candidates
               WHERE needs_review=1 AND promoted_at IS NULL
               AND source_key NOT IN (SELECT source_key FROM dim_source WHERE source_code='vivino')
               GROUP BY wine_key HAVING COUNT(DISTINCT source_key) >= 2
           )"""
    ).fetchone()[0]
    vivino_pending = conn.execute(
        "SELECT COUNT(*) FROM staging_rating_candidates src "
        "JOIN dim_source ds ON ds.source_key = src.source_key "
        "WHERE ds.source_code = 'vivino' AND src.promoted_at IS NULL"
    ).fetchone()[0]

    console.print(f"[bold]Staging rating candidates pending:[/bold] {pending}")
    console.print(f"[bold]Wine keys with 2+ critic sources:[/bold] {multi_source}")
    console.print(f"[bold]Vivino tiebreaker rows pending:[/bold] {vivino_pending}")
    console.print(f"[bold]Current fact_rating rows:[/bold] {before_fact}")
    console.print()

    if dry_run:
        console.print("[yellow]Dry-run mode — no rows will be written.[/yellow]")
        return

    result = _promote_ratings(conn)
    vivino_result = _promote_vivino(conn)

    after_fact = conn.execute("SELECT COUNT(*) FROM fact_rating").fetchone()[0]

    t = Table(title="Rating promotion result")
    t.add_column("Metric")
    t.add_column("Value", justify="right")
    t.add_row("Promoted to fact_rating (critics)", str(result.promoted))
    t.add_row("Still pending critics (single-source)", str(result.pending))
    t.add_row("Vivino tiebreakers promoted", str(vivino_result.promoted))
    t.add_row("Vivino tiebreakers still pending", str(vivino_result.pending))
    t.add_row("fact_rating rows before", str(before_fact))
    t.add_row("fact_rating rows after", str(after_fact))
    console.print(t)


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


@cli.command("compute-similarity")
@click.option("--limit", default=None, type=int, help="Max wines to process (default: all eligible)")
@click.option("--top-k", default=20, type=int, show_default=True, help="Top-K similar wines to keep per wine")
@click.option("--batch-size", default=500, type=int, show_default=True, help="Matrix block size for cosine computation")
def compute_similarity(limit: int | None, top_k: int, batch_size: int):
    """Compute wine feature-vector similarity scores and persist to wine_similarity.

    Builds fixed-length feature vectors (color, region, variety, score, price,
    vintage) for all wines with at least one price or rating row, then computes
    pairwise cosine similarity in NumPy batches and writes the top-K most similar
    wines per wine into wine_similarity.
    """
    import time as _time
    from .config import config
    from .db import get_db

    config.ensure_dirs()
    conn = get_db(config.db_path)

    # Count eligible wines
    eligible_count = conn.execute(
        """
        SELECT COUNT(DISTINCT dw.wine_key)
        FROM dim_wine dw
        WHERE EXISTS (SELECT 1 FROM fact_price fp WHERE fp.wine_key = dw.wine_key)
           OR EXISTS (SELECT 1 FROM fact_rating fr WHERE fr.wine_key = dw.wine_key)
        """
    ).fetchone()[0]

    if limit:
        eligible_count = min(eligible_count, limit)

    console.print(f"[bold]Computing similarity[/bold] — eligible wines: {eligible_count}, top-K={top_k}")
    console.print()

    t0 = _time.time()
    last_print = [0]

    def progress(processed: int, total: int, rows_written: int) -> None:
        elapsed = _time.time() - t0
        if processed - last_print[0] >= 500 or processed == total:
            console.print(
                f"  [{processed}/{total}]  rows written: {rows_written}"
                f"  elapsed: {elapsed:.1f}s"
            )
            last_print[0] = processed

    try:
        from .similarity import compute_all_similarities
    except ImportError as exc:
        console.print(f"[red]numpy is required: {exc}[/red]")
        console.print("[yellow]Run: scraper\\.venv\\Scripts\\pip.exe install numpy[/yellow]")
        return

    rows_written = compute_all_similarities(
        conn,
        top_k=top_k,
        batch_size=batch_size,
        progress_callback=progress,
    )

    elapsed = _time.time() - t0
    console.print()

    t = Table(title="Similarity result")
    t.add_column("Metric")
    t.add_column("Value", justify="right")
    t.add_row("Wines processed", str(eligible_count))
    t.add_row("Rows written (wine_similarity)", str(rows_written))
    t.add_row("Top-K per wine", str(top_k))
    t.add_row("Elapsed", f"{elapsed:.1f}s")
    console.print(t)


if __name__ == "__main__":
    cli()
