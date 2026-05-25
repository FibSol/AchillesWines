# REGISTER_IN_CLI = True
"""
CellarTracker parallel scraper — curl_cffi + Playwright cookie bootstrap.

Strategy
--------
1. Playwright (headless Chromium) logs in once and solves the AWS WAF challenge,
   extracting session + WAF cookies.  Cookies are cached in
   data/ct_cookies.json and reused for up to 22 h (WAF token TTL is 24 h).
2. curl_cffi AsyncSession (Chrome TLS impersonation) fetches wine.asp pages in
   parallel using those cookies — no Firecrawl credits needed.
3. On 429 / stale-cookie response the cookie cache is invalidated and Playwright
   re-runs transparently.

Env vars
--------
ACHILLES_AUTH_CELLARTRACKER_USERNAME   required
ACHILLES_AUTH_CELLARTRACKER_PASSWORD   required
ACHILLES_CT_WORKERS    concurrent curl_cffi requests   (default 20)
ACHILLES_CT_MIN_SCORE  only save wines scoring >= this (default 0 = save all)
ACHILLES_CT_START_ID   override resume cursor for cold re-crawl

Usage
-----
achilles-scraper run --source cellartracker_fast [--limit 500]
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:
    from curl_cffi import requests as curl_requests
    from selectolax.parser import HTMLParser
    from rich.console import Console
    from rich.progress import (
        Progress, SpinnerColumn, BarColumn, MofNCompleteColumn,
        TextColumn, TimeElapsedColumn,
    )
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False

from .base import BaseScraper, ScrapeResult
from .cellartracker import (
    _load_cursor, _save_cursor,
    _ensure_source, _ensure_producer, _ensure_appellation, _ensure_wine,
    _parse_wine_list, _parse_score_v2, _parse_table_pairs, _parse_score, _is_not_found,
    _map_color, _map_country,
    _NOT_FOUND_DESIGNATIONS,
    CRITIC_CODE, SCALE,
)
from ..identity import normalize_producer, normalize_cuvee, compute_wine_key, norm_text
from ..dlq import write_dlq

_logger = logging.getLogger(__name__)

_BASE = "https://www.cellartracker.com"
_WINE_URL = f"{_BASE}/wine.asp?iWine="
_LOGIN_URL = f"{_BASE}/password.asp"

_COOKIE_CACHE = Path("data/ct_cookies.json")
_COOKIE_TTL = 22 * 3600   # refresh 2 h before the 24 h WAF token expiry

_RE_VINTAGE = re.compile(r"\b(1[89]\d{2}|20[0-3]\d)\b")

_DEFAULT_WORKERS = 20
_DEFAULT_MIN_SCORE = 0.0

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": f"{_BASE}/default.asp",
}


# ---------------------------------------------------------------------------
# Cookie management
# ---------------------------------------------------------------------------

def _playwright_login(username: str, password: str) -> list[dict]:
    """Open headless Chromium, solve AWS WAF, log in, return cookie list."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError("playwright not installed — run: pip install playwright && playwright install chromium")

    console = Console()
    console.print("[dim]Running Playwright to solve AWS WAF challenge and log in…[/dim]")
    t0 = time.time()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=_HEADERS["User-Agent"],
            viewport={"width": 1280, "height": 800},
        )
        page = ctx.new_page()

        # Homepage — AWS WAF challenge auto-resolves here
        page.goto(_BASE + "/", wait_until="networkidle", timeout=30000)

        # Login page
        page.goto(_LOGIN_URL, wait_until="networkidle", timeout=15000)
        _wait_past_challenge(page)

        page.fill('input[name="szUser"]', username)
        page.fill('input[name="szPassword"]', password)
        page.click("#sign_in")
        page.wait_for_load_state("networkidle", timeout=20000)
        _wait_past_challenge(page)

        body = page.content().lower()
        if not ("sign out" in body or "logout" in body or username.lower() in body):
            raise RuntimeError("CellarTracker login rejected — check credentials")

        cookies = ctx.cookies()
        browser.close()

    console.print(f"[dim]Playwright done in {time.time()-t0:.1f}s — {len(cookies)} cookies[/dim]")
    return cookies


def _wait_past_challenge(page, retries: int = 6, delay: float = 3.0) -> None:
    """Wait until AWS WAF 'Human Verification' challenge clears."""
    for _ in range(retries):
        content = page.content().lower()
        if "human verification" not in content:
            return
        time.sleep(delay)
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass


def _load_cookies(username: str, password: str) -> list[dict]:
    """Return cached cookies if fresh, otherwise run Playwright."""
    if _COOKIE_CACHE.exists():
        try:
            data = json.loads(_COOKIE_CACHE.read_text(encoding="utf-8"))
            if time.time() - data.get("created_at", 0) < _COOKIE_TTL:
                return data["cookies"]
        except Exception:
            pass
    cookies = _playwright_login(username, password)
    _COOKIE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    _COOKIE_CACHE.write_text(
        json.dumps({"created_at": time.time(), "cookies": cookies}),
        encoding="utf-8",
    )
    return cookies


def _invalidate_cookie_cache() -> None:
    try:
        _COOKIE_CACHE.unlink(missing_ok=True)
    except Exception:
        pass


def _cookies_to_dict(cookies: list[dict]) -> dict[str, str]:
    return {c["name"]: c["value"] for c in cookies}


# ---------------------------------------------------------------------------
# Async fetch
# ---------------------------------------------------------------------------

async def _fetch_one(
    session: "curl_requests.AsyncSession",
    sem: asyncio.Semaphore,
    iwine: int,
    cookies_dict: dict[str, str],
) -> dict[str, Any]:
    wine_url = f"{_WINE_URL}{iwine}"
    async with sem:
        try:
            resp = await session.get(wine_url, headers=_HEADERS, cookies=cookies_dict)
        except Exception as e:
            return {"iwine": iwine, "url": wine_url, "status": "network_error", "error": str(e)}

        if resp.status_code == 429:
            return {"iwine": iwine, "url": wine_url, "status": "rate_limited", "error": "429"}
        if resp.status_code == 403:
            return {"iwine": iwine, "url": wine_url, "status": "blocked", "error": "403"}
        if not (200 <= resp.status_code < 300):
            return {"iwine": iwine, "url": wine_url, "status": "http_error",
                    "error": f"HTTP {resp.status_code}"}

        html = resp.text or ""
        lo = html.lower()
        # Detect AWS WAF challenge (means cookies expired)
        if "human verification" in lo and len(html) < 15000:
            return {"iwine": iwine, "url": wine_url, "status": "waf_challenge", "error": "WAF challenge"}
        # Detect CT login redirect — session expired server-side even though TTL looks valid.
        # Signature: title "Sign In - CellarTracker", contains szUser input, short page.
        if ("sign in - cellartracker" in lo or ("szuser" in lo and "szpassword" in lo)) and len(html) < 20000:
            return {"iwine": iwine, "url": wine_url, "status": "waf_challenge", "error": "CT session expired (login redirect)"}

        return {"iwine": iwine, "url": wine_url, "status": "ok", "html": html, "ct_status": resp.status_code}


# ---------------------------------------------------------------------------
# DB write (called under db_lock — always in event-loop thread)
# ---------------------------------------------------------------------------

def _process_and_write(
    conn: sqlite3.Connection,
    source_key: int,
    batch_id: str,
    result: ScrapeResult,
    fetch: dict[str, Any],
    min_score: float,
) -> str:
    """Parse and write one fetch result.  Returns 'ok', 'skip', 'dlq', 'reauth'."""
    iwine = fetch["iwine"]
    wine_url = fetch["url"]
    status = fetch["status"]

    if status in ("waf_challenge", "rate_limited", "blocked"):
        return "reauth"

    if status in ("network_error", "http_error"):
        write_dlq(conn, source_key, batch_id, "network_error", fetch.get("error", ""), {"iWine": iwine})
        result.rows_dlq += 1
        _save_cursor(iwine)
        return "dlq"

    raw_html: str = fetch.get("html", "")
    ct_status: int = fetch.get("ct_status", 200)
    tree = HTMLParser(raw_html)

    if _is_not_found(tree, ct_status):
        _save_cursor(iwine)
        return "skip"

    result.rows_fetched += 1
    # Try the current twin_set_list layout first; fall back to legacy table parser.
    pairs = _parse_wine_list(tree) or _parse_table_pairs(tree)
    producer_raw = pairs.get("producer", "")
    vintage_raw = pairs.get("vintage", "")
    country_raw = pairs.get("country", "")
    region_raw = pairs.get("region", "")
    appellation_raw = (
        pairs.get("appellation", "")
        or pairs.get("subregion", "")
        or pairs.get("sub-region", "")
    )
    type_raw = pairs.get("type", "")
    # Resolve designation: prefer explicit designation, fall back to vineyard or variety
    desig_raw = pairs.get("designation", "")
    if desig_raw.lower() in _NOT_FOUND_DESIGNATIONS:
        desig_raw = ""
    designation = desig_raw or pairs.get("vineyard", "") or pairs.get("variety", "") or pairs.get("varietal", "")

    if not producer_raw or not designation:
        write_dlq(conn, source_key, batch_id, "parse_error",
                  "missing producer or designation", {"iWine": iwine, "pairs": pairs})
        result.rows_dlq += 1
        _save_cursor(iwine)
        return "dlq"

    vintage: Optional[int] = None
    vraw = (vintage_raw or "").strip().upper()
    if vraw and vraw not in {"NV", "N.V.", "NON-VINTAGE", "N/A", "-"}:
        m = _RE_VINTAGE.search(vraw)
        if m:
            v = int(m.group(1))
            if 1900 <= v <= 2040:
                vintage = v

    # Vintage filter: only keep NV wines and vintages >= 2000.
    if vintage is not None and vintage < 2000:
        result.rows_skipped_unchanged += 1
        _save_cursor(iwine)
        return "skip"

    country = _map_country(country_raw)
    color = _map_color(type_raw) or "red"

    if not country:
        write_dlq(conn, source_key, batch_id, "unresolved_dim",
                  f"unmapped country: {country_raw!r}",
                  {"iWine": iwine, "producer": producer_raw, "country": country_raw})
        result.rows_dlq += 1
        _save_cursor(iwine)
        return "dlq"

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
        return "dlq"

    score, notes = _parse_score_v2(tree)
    if score is None:
        score, notes = _parse_score(tree)
    if score is None:
        result.rows_skipped_unchanged += 1
        _save_cursor(iwine)
        return "skip"

    if min_score > 0 and score < min_score:
        result.rows_skipped_unchanged += 1
        _save_cursor(iwine)
        return "skip"

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
        return "dlq"

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
    return "ok"


# ---------------------------------------------------------------------------
# Scraper class
# ---------------------------------------------------------------------------

class CellarTrackerFastScraper(BaseScraper):
    """
    Parallel CellarTracker iWine scraper.

    Uses Playwright once to solve AWS WAF + login, then curl_cffi async
    for N concurrent wine page fetches.  No Firecrawl credits required.
    """

    source_code = "cellartracker_fast"

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.batch_id: Optional[str] = None

    def run(self, limit: Optional[int] = None) -> ScrapeResult:
        if not HAS_DEPS:
            return ScrapeResult(error="Missing deps: curl_cffi, selectolax, or rich not installed")
        username = os.environ.get("ACHILLES_AUTH_CELLARTRACKER_USERNAME", "").strip()
        password = os.environ.get("ACHILLES_AUTH_CELLARTRACKER_PASSWORD", "").strip()
        if not username or not password:
            return ScrapeResult(error="ACHILLES_AUTH_CELLARTRACKER_USERNAME / _PASSWORD not set")
        # Load cookies with sync Playwright BEFORE entering the asyncio event loop.
        try:
            cookies_list = _load_cookies(username, password)
        except Exception as e:
            return ScrapeResult(error=f"Cookie bootstrap failed: {e}")
        return asyncio.run(self._run_async(limit, cookies_list))

    async def _run_async(self, limit: Optional[int], cookies_list: list[dict]) -> ScrapeResult:
        workers = int(os.getenv("ACHILLES_CT_WORKERS", str(_DEFAULT_WORKERS)))
        min_score = float(os.getenv("ACHILLES_CT_MIN_SCORE", str(_DEFAULT_MIN_SCORE)))
        budget = limit if limit is not None else 500

        batch_id = self.batch_id or f"ctf-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        result = ScrapeResult(batch_id=batch_id)

        source_key = _ensure_source(self.conn)
        if source_key is None:
            return ScrapeResult(error="could not resolve or create dim_source row for 'cellartracker'")

        start_id = _load_cursor()
        cookies_dict = _cookies_to_dict(cookies_list)

        sem = asyncio.Semaphore(workers)
        db_lock = asyncio.Lock()
        reauth_event = asyncio.Event()

        console = Console()
        score_label = f" ≥{min_score:.0f}pts" if min_score > 0 else ""
        console.print(
            f"[bold]CellarTracker fast[/bold]  "
            f"workers=[cyan]{workers}[/cyan]  "
            f"budget=[cyan]{budget}[/cyan]{score_label}  "
            f"start_iWine=[cyan]{start_id}[/cyan]"
        )

        iwine_ids = list(range(start_id, start_id + budget))

        async with curl_requests.AsyncSession(impersonate="chrome124") as session:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                TextColumn("ins=[green]{task.fields[ins]}[/green]"),
                TextColumn("dlq=[yellow]{task.fields[dlq]}[/yellow]"),
                TextColumn("skip={task.fields[skip]}"),
                TimeElapsedColumn(),
                console=console,
                transient=False,
            ) as progress:
                task_id = progress.add_task("Scraping…", total=budget, ins=0, dlq=0, skip=0)

                async def worker(iwine: int) -> None:
                    if reauth_event.is_set():
                        return
                    fetch = await _fetch_one(session, sem, iwine, cookies_dict)
                    async with db_lock:
                        outcome = _process_and_write(
                            self.conn, source_key, batch_id,
                            result, fetch, min_score,
                        )
                        if outcome == "reauth":
                            reauth_event.set()
                            result.error = "WAF cookie expired — re-run to refresh"
                        progress.update(
                            task_id, advance=1,
                            ins=result.rows_inserted,
                            dlq=result.rows_dlq,
                            skip=result.rows_skipped_unchanged,
                        )

                await asyncio.gather(*(worker(iw) for iw in iwine_ids))

        # If WAF expired mid-run, invalidate cache so next run re-logins
        if reauth_event.is_set():
            _invalidate_cookie_cache()

        # Advance cursor past the attempted range
        _save_cursor(start_id + budget - 1)

        console.print(
            f"[bold green]Done.[/bold green]  "
            f"fetched=[bold]{result.rows_fetched}[/bold]  "
            f"inserted=[bold]{result.rows_inserted}[/bold]  "
            f"skipped={result.rows_skipped_unchanged}  "
            f"dlq={result.rows_dlq}"
            + (f"  [yellow]{result.error}[/yellow]" if result.error else "")
        )
        return result
