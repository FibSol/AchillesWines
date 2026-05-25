# REGISTER_IN_CLI = True
"""
CellarTracker parallel scraper — N concurrent Firecrawl requests.

10–20x faster than the sequential cellartracker scraper by running multiple
iWine fetches simultaneously.  Each request still costs 1 Firecrawl credit.

Env vars
--------
ACHILLES_CT_WORKERS    concurrent Firecrawl requests   (default 10)
ACHILLES_CT_MIN_SCORE  only save wines scoring >= this (default 0 = save all)
ACHILLES_CT_WAIT_MS    Firecrawl JS waitFor in ms      (default 2500)
ACHILLES_CT_START_ID   override resume cursor          (cold re-crawl)
FIRECRAWL_API_KEY      required

Usage
-----
achilles-scraper run --source cellartracker_fast [--limit 1000]
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

try:
    import httpx
    from selectolax.parser import HTMLParser
    from rich.console import Console
    from rich.progress import (
        Progress, SpinnerColumn, BarColumn, MofNCompleteColumn,
        TextColumn, TimeElapsedColumn, TaskID,
    )
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False

from .base import BaseScraper, ScrapeResult
from .cellartracker import (
    _load_cursor, _save_cursor,
    _ensure_source, _ensure_producer, _ensure_appellation, _ensure_wine,
    _parse_table_pairs, _parse_score, _is_not_found,
    _map_color, _map_country,
    _WINE_URL, _FIRECRAWL_SCRAPE_URL, _FC_ENV_KEY,
    CRITIC_CODE, SCALE,
)
from ..identity import normalize_producer, normalize_cuvee, compute_wine_key, norm_text
from ..dlq import write_dlq

_logger = logging.getLogger(__name__)

_RE_VINTAGE = re.compile(r"\b(1[89]\d{2}|20[0-3]\d)\b")

_DEFAULT_WORKERS = 10
_DEFAULT_WAIT_MS = 2500
_DEFAULT_MIN_SCORE = 0.0


# ---------------------------------------------------------------------------
# Async fetch helpers
# ---------------------------------------------------------------------------

async def _fetch_one(
    client: "httpx.AsyncClient",
    sem: asyncio.Semaphore,
    api_key: str,
    iwine: int,
    wait_ms: int,
) -> dict[str, Any]:
    """Fetch one iWine page via Firecrawl.  Returns a result dict."""
    wine_url = f"{_WINE_URL}{iwine}"
    async with sem:
        try:
            resp = await client.post(
                _FIRECRAWL_SCRAPE_URL,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"url": wine_url, "formats": ["rawHtml"], "waitFor": wait_ms, "mobile": False},
            )
        except Exception as e:
            return {"iwine": iwine, "url": wine_url, "status": "network_error", "error": str(e)}

        if resp.status_code == 401:
            return {"iwine": iwine, "url": wine_url, "status": "auth_error", "error": "Firecrawl 401"}
        if resp.status_code == 429:
            # Back off and retry once
            await asyncio.sleep(30)
            try:
                resp = await client.post(
                    _FIRECRAWL_SCRAPE_URL,
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={"url": wine_url, "formats": ["rawHtml"], "waitFor": wait_ms, "mobile": False},
                )
            except Exception as e:
                return {"iwine": iwine, "url": wine_url, "status": "network_error", "error": str(e)}
        if not resp.is_success:
            return {
                "iwine": iwine, "url": wine_url,
                "status": "http_error", "error": f"HTTP {resp.status_code}",
            }
        try:
            fc_data = resp.json()
        except Exception:
            return {"iwine": iwine, "url": wine_url, "status": "parse_error", "error": "JSON decode failed"}

        raw_html = (fc_data.get("data") or {}).get("rawHtml") or ""
        ct_status = (fc_data.get("data") or {}).get("metadata", {}).get("statusCode", 200)
        return {"iwine": iwine, "url": wine_url, "status": "ok", "html": raw_html, "ct_status": ct_status}


# ---------------------------------------------------------------------------
# DB write helper (called under db_lock — runs in event-loop thread)
# ---------------------------------------------------------------------------

def _process_and_write(
    conn: sqlite3.Connection,
    source_key: int,
    batch_id: str,
    result: ScrapeResult,
    fetch: dict[str, Any],
    min_score: float,
) -> None:
    """Parse HTML and write to DB.  Must be called serially (no concurrent access)."""
    iwine = fetch["iwine"]
    wine_url = fetch["url"]

    if fetch["status"] == "auth_error":
        result.error = fetch["error"]
        return

    if fetch["status"] in ("network_error", "http_error", "parse_error"):
        write_dlq(conn, source_key, batch_id, "network_error", fetch.get("error", ""), {"iWine": iwine})
        result.rows_dlq += 1
        _save_cursor(iwine)
        return

    raw_html: str = fetch.get("html", "")
    ct_status: int = fetch.get("ct_status", 200)
    tree = HTMLParser(raw_html)

    if _is_not_found(tree, ct_status):
        _save_cursor(iwine)
        return

    result.rows_fetched += 1
    pairs = _parse_table_pairs(tree)
    producer_raw = pairs.get("producer", "")
    designation = pairs.get("designation", "") or pairs.get("wine", "")
    vintage_raw = pairs.get("vintage", "")
    country_raw = pairs.get("country", "")
    region_raw = pairs.get("region", "")
    appellation_raw = (
        pairs.get("appellation", "")
        or pairs.get("subregion", "")
        or pairs.get("sub-region", "")
    )
    type_raw = pairs.get("type", "")

    if not producer_raw or not designation:
        write_dlq(conn, source_key, batch_id, "parse_error",
                  "missing producer or designation", {"iWine": iwine, "pairs": pairs})
        result.rows_dlq += 1
        _save_cursor(iwine)
        return

    vintage: Optional[int] = None
    vraw = (vintage_raw or "").strip().upper()
    if vraw and vraw not in {"NV", "N.V.", "NON-VINTAGE", "N/A", "-"}:
        m = _RE_VINTAGE.search(vraw)
        if m:
            v = int(m.group(1))
            if 1900 <= v <= 2040:
                vintage = v

    country = _map_country(country_raw)
    color = _map_color(type_raw) or "red"

    if not country:
        write_dlq(conn, source_key, batch_id, "unresolved_dim",
                  f"unmapped country: {country_raw!r}",
                  {"iWine": iwine, "producer": producer_raw, "country": country_raw})
        result.rows_dlq += 1
        _save_cursor(iwine)
        return

    producer_norm = normalize_producer(producer_raw)
    cuvee_norm = normalize_cuvee(designation)
    appellation_name = appellation_raw or region_raw or ""
    appellation_norm = norm_text(appellation_name) if appellation_name else norm_text(region_raw)
    region = region_raw or appellation_name

    if not producer_norm or not cuvee_norm:
        write_dlq(conn, source_key, batch_id, "parse_error",
                  "empty producer_norm or cuvee_norm after normalisation",
                  {"iWine": iwine, "producer": producer_raw, "designation": designation})
        result.rows_dlq += 1
        _save_cursor(iwine)
        return

    score, notes = _parse_score(tree)
    if score is None:
        result.rows_skipped_unchanged += 1
        _save_cursor(iwine)
        return

    # Score filter — skip low-scoring wines (still cost a credit, but avoid DB noise)
    if min_score > 0 and score < min_score:
        result.rows_skipped_unchanged += 1
        _save_cursor(iwine)
        return

    producer_key = _ensure_producer(conn, country, producer_norm, producer_raw)
    appellation_key = _ensure_appellation(
        conn, country, region or "Unknown",
        appellation_name or region or "Unknown",
        appellation_norm or norm_text(region or "Unknown"),
    )
    if producer_key is None or appellation_key is None:
        write_dlq(conn, source_key, batch_id, "unresolved_dim",
                  "could not resolve producer or appellation",
                  {"iWine": iwine, "producer": producer_raw,
                   "appellation": appellation_name, "country": country})
        result.rows_dlq += 1
        _save_cursor(iwine)
        return

    wine_key = compute_wine_key(producer_norm, cuvee_norm, vintage, appellation_norm)
    _ensure_wine(conn, wine_key, producer_key, appellation_key,
                 designation, cuvee_norm, color, vintage)

    content_hash = hashlib.sha256(
        json.dumps(
            {"wine_key": wine_key, "score": score, "notes": notes, "iWine": iwine},
            sort_keys=True,
        ).encode()
    ).hexdigest()

    try:
        conn.execute(
            """INSERT OR IGNORE INTO fact_rating
               (wine_key, source_key, critic_code, reviewer_type,
                score, scale, score_normalized_100,
                source_url, content_hash, batch_id)
               VALUES (?, ?, ?, 'crowd', ?, ?, ?, ?, ?, ?)""",
            (wine_key, source_key, CRITIC_CODE,
             score, SCALE, score, wine_url, content_hash, batch_id),
        )
        conn.commit()
        result.rows_inserted += 1
    except Exception as e:
        write_dlq(conn, source_key, batch_id, "validation_error",
                  str(e), {"iWine": iwine, "wine_key": wine_key, "score": score})
        result.rows_dlq += 1

    _save_cursor(iwine)


# ---------------------------------------------------------------------------
# Scraper class
# ---------------------------------------------------------------------------

class CellarTrackerFastScraper(BaseScraper):
    """Parallel CellarTracker iWine scraper — N concurrent Firecrawl requests."""

    source_code = "cellartracker_fast"

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.batch_id: Optional[str] = None

    def run(self, limit: Optional[int] = None) -> ScrapeResult:
        if not HAS_DEPS:
            return ScrapeResult(error="Missing deps: httpx, selectolax, or rich not installed")
        api_key = os.environ.get(_FC_ENV_KEY, "").strip()
        if not api_key:
            return ScrapeResult(
                error=f"{_FC_ENV_KEY} not set — required for CellarTracker (Firecrawl bypasses Kasada)"
            )
        return asyncio.run(self._run_async(limit, api_key))

    async def _run_async(self, limit: Optional[int], api_key: str) -> ScrapeResult:
        workers = int(os.getenv("ACHILLES_CT_WORKERS", str(_DEFAULT_WORKERS)))
        min_score = float(os.getenv("ACHILLES_CT_MIN_SCORE", str(_DEFAULT_MIN_SCORE)))
        wait_ms = int(os.getenv("ACHILLES_CT_WAIT_MS", str(_DEFAULT_WAIT_MS)))
        budget = limit if limit is not None else 500

        batch_id = self.batch_id or f"ctf-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        result = ScrapeResult(batch_id=batch_id)

        source_key = _ensure_source(self.conn)
        if source_key is None:
            return ScrapeResult(error="could not resolve or create dim_source row for 'cellartracker'")

        start_id = _load_cursor()
        sem = asyncio.Semaphore(workers)
        db_lock = asyncio.Lock()

        console = Console()
        score_label = f" ≥{min_score:.0f}pts" if min_score > 0 else ""
        console.print(
            f"[bold]CellarTracker parallel[/bold]  "
            f"workers=[cyan]{workers}[/cyan]  "
            f"waitFor=[cyan]{wait_ms}ms[/cyan]  "
            f"budget=[cyan]{budget}[/cyan]{score_label}  "
            f"start_iWine=[cyan]{start_id}[/cyan]"
        )

        auth_error_event = asyncio.Event()
        iwine_ids = list(range(start_id, start_id + budget))

        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                TextColumn("ins=[green]{task.fields[ins]}[/green]"),
                TextColumn("dlq=[yellow]{task.fields[dlq]}[/yellow]"),
                TimeElapsedColumn(),
                console=console,
                transient=False,
            ) as progress:
                task_id = progress.add_task(
                    "Scraping…", total=budget, ins=0, dlq=0
                )

                async def worker(iwine: int) -> None:
                    if auth_error_event.is_set():
                        return
                    fetch = await _fetch_one(client, sem, api_key, iwine, wait_ms)
                    async with db_lock:
                        _process_and_write(
                            self.conn, source_key, batch_id,
                            result, fetch, min_score,
                        )
                        if result.error and "401" in (result.error or ""):
                            auth_error_event.set()
                        progress.update(
                            task_id, advance=1,
                            ins=result.rows_inserted,
                            dlq=result.rows_dlq,
                        )

                await asyncio.gather(*(worker(iw) for iw in iwine_ids))

        # Save cursor past the attempted range
        _save_cursor(start_id + budget - 1)

        console.print(
            f"[bold green]Done.[/bold green]  "
            f"fetched=[bold]{result.rows_fetched}[/bold]  "
            f"inserted=[bold]{result.rows_inserted}[/bold]  "
            f"skipped={result.rows_skipped_unchanged}  "
            f"dlq={result.rows_dlq}"
            + (f"  [red]error: {result.error}[/red]" if result.error else "")
        )
        return result
