"""
Wine-Searcher scraper — Firecrawl CLI page scrape, cuvée-level batching.

Target:  https://www.wine-searcher.com/find/{query}?sl-cur=EUR
Method:  subprocess: firecrawl scrape --profile wine-searcher --only-main-content
         The --profile flag reuses a persistent Firecrawl browser session that
         bypasses PerimeterX.  Direct httpx / REST-API scraping returns 403.
Cadence: Monthly (~5 Firecrawl credits per cuvée, one URL covers all vintages)
Output:  staging_price_candidates → fact_price via tri-source promoter

Batching strategy
-----------------
Scrapes at the cuvée level: one Wine-Searcher URL per (producer, cuvée) pair.
A single page shows all vintages, so we cover all wine_keys for that cuvée in
one CLI call.  vintage >= 2000 filter is applied at insert time.

Progress tracking (auto-resume)
---------------------------------
After each attempted cuvée — whether or not listings were found — the scraper
upserts a row to ops_content_hashes using a synthetic URL key:
    ws_cuvee:{producer_norm}|{cuvee_norm}
On subsequent runs the _load_cuvees query excludes URLs already fetched within
the last 30 days, so the next batch picks up exactly where the last one stopped.

Run example
-----------
    achilles-scraper run --source wine_searcher --limit 50
    # 50 cuvées per run ≈ 100 seconds.  Re-run to advance the cursor.

FX conversion
-------------
Prices requested in EUR (?sl-cur=EUR).  Non-EUR symbols fall back to the
Frankfurter API (api.frankfurter.app, no key, ECB-sourced).
Override base URL with FRANKFURTER_API_BASE.

Prerequisites
-------------
  - firecrawl CLI in PATH  (npm install -g firecrawl)
  - FIRECRAWL_API_KEY set (same key as CLI)
"""
import hashlib
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

from .base import BaseScraper, ScrapeResult
from ..dlq import insert_staging_candidate, write_dlq

_logger = logging.getLogger(__name__)

_WS_BASE          = "https://www.wine-searcher.com/find"
_FC_PROFILE       = "wine-searcher"
_SCRAPE_TIMEOUT   = 90        # seconds per CLI call
_REQUEST_DELAY    = 1.0       # seconds between cuvée requests
_PRICE_MIN_EUR    = 3.0
_PRICE_MAX_EUR    = 50_000.0
_VINTAGE_MIN      = 2000      # skip pre-2000 listings
_RESUME_DAYS      = 30        # re-attempt a cuvée after this many days
_FRANKFURTER_BASE = "https://api.frankfurter.app"

# ── Markdown parsing ──────────────────────────────────────────────────────────

# [Merchant Name](https://www.wine-searcher.com/merchant/…)
_MERCHANT_RE = re.compile(
    r'\[([^\]]+)\]\(https://www\.wine-searcher\.com/merchant/[^)]+\)'
)
# "$128.78 / 750ml"  |  "€ 152.95 / 750ml"
_PRICE_750_RE = re.compile(
    r'([$€£])\s*([\d,]+(?:\.\d+)?)\s*/\s*750\s*ml'
)
# Vintage 4-digit year, NOT immediately surrounded by other digits
_VINTAGE_RE = re.compile(r'(?<!\d)((?:19|20)\d{2})(?!\d)')
# Offer type
_OFFER_RE = re.compile(
    r'\b(Retail|Pre Arrival|By Request|Auction|In Bond|En Primeur(?:/Futures)?)\b',
    re.IGNORECASE,
)
_CURRENCY_MAP = {"$": "USD", "€": "EUR", "£": "GBP"}


# ── URL builder ───────────────────────────────────────────────────────────────

def _build_ws_url(cuvee: dict) -> str:
    """
    Build a Wine-Searcher search URL from DB-normalised cuvée fields.
    No vintage → WS returns all vintages on one page.
    """
    parts = (cuvee["producer_norm"] or "").split()
    cuvee_norm = cuvee.get("cuvee_norm") or ""
    if cuvee_norm and cuvee_norm != cuvee["producer_norm"]:
        prod_set = set(parts)
        parts += [t for t in cuvee_norm.split() if t not in prod_set]
    slug = "+".join(p for p in parts if p)
    return f"{_WS_BASE}/{slug}?sl-cur=EUR"


def _progress_key(cuvee: dict) -> str:
    """Synthetic ops_content_hashes key for tracking cuvée-level attempts."""
    return f"ws_cuvee:{cuvee['producer_norm']}|{cuvee.get('cuvee_norm') or ''}"


# ── Firecrawl CLI wrapper ─────────────────────────────────────────────────────

def _scrape_page(url: str) -> Optional[str]:
    """
    Run `firecrawl scrape --profile wine-searcher --only-main-content`.
    Returns the markdown body, or None on failure.
    Strips the CLI "Scrape ID: …" header line from stdout.
    """
    fc = shutil.which("firecrawl")
    if not fc:
        return None
    try:
        proc = subprocess.run(
            [fc, "scrape", url, "--profile", _FC_PROFILE, "--only-main-content"],
            capture_output=True, text=True,
            timeout=_SCRAPE_TIMEOUT,
            encoding="utf-8", errors="replace",
        )
    except subprocess.TimeoutExpired:
        _logger.warning("firecrawl timeout: %s", url)
        return None
    except Exception as exc:
        _logger.warning("firecrawl error: %s", exc)
        return None

    if proc.returncode != 0:
        _logger.warning("firecrawl rc=%d: %.200s", proc.returncode, proc.stderr)
        return None

    lines = proc.stdout.splitlines(keepends=True)
    return "".join(l for l in lines if not l.startswith("Scrape ID:"))


# ── Markdown parser ───────────────────────────────────────────────────────────

def _parse_listings(markdown: str) -> list[dict]:
    """
    Parse a Wine-Searcher page markdown into a list of offer dicts.
    Each dict: retailer, price_local, currency, vintage, offer_type, source_url.

    The "Go to shop" link in WS markdown spans ~15 lines (each field on its own
    line with backslash continuation).  We use a 35-line window per listing.
    """
    listings: list[dict] = []
    lines = markdown.splitlines()
    n = len(lines)
    i = 0
    while i < n:
        m = _MERCHANT_RE.search(lines[i])
        if not m:
            i += 1
            continue

        retailer = m.group(1).strip()
        block = "\n".join(lines[i : i + 35])

        pm = _PRICE_750_RE.search(block)
        if not pm:
            i += 1
            continue

        try:
            price_local = float(pm.group(2).replace(",", ""))
        except ValueError:
            i += 1
            continue

        currency = _CURRENCY_MAP.get(pm.group(1), "EUR")

        vm = _VINTAGE_RE.search(block)
        vintage = int(vm.group(1)) if vm else None

        om = _OFFER_RE.search(block)
        offer_type = om.group(1).strip() if om else "Retail"

        su = re.search(r'\[Go to shop[^\]]*\]\((https?://[^)]+)\)', block)
        source_url = su.group(1) if su else ""

        listings.append({
            "retailer":    retailer,
            "price_local": price_local,
            "currency":    currency,
            "vintage":     vintage,
            "offer_type":  offer_type,
            "source_url":  source_url,
        })
        i += 1

    return listings


# ── FX helper ─────────────────────────────────────────────────────────────────

def _eur_rate(client: "httpx.Client", currency: str, base: str) -> Optional[float]:
    if currency == "EUR":
        return 1.0
    try:
        r = client.get(f"{base}/latest", params={"from": currency, "to": "EUR"}, timeout=10)
        if r.is_success:
            return r.json().get("rates", {}).get("EUR")
    except Exception:
        pass
    return None


# ── Scraper class ─────────────────────────────────────────────────────────────

class WineSearcherScraper(BaseScraper):
    """
    Wine-Searcher full-coverage scraper via Firecrawl CLI.

    Operates at the cuvée level: one URL per (producer, cuvée) covers all
    vintages.  Progress is tracked in ops_content_hashes so each batch picks
    up where the last one stopped.
    """

    source_code = "wine_searcher"

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.batch_id: Optional[str] = None

    # ── Public entry point ────────────────────────────────────────────────────

    def run(self, limit: Optional[int] = None) -> ScrapeResult:
        batch_id = self.batch_id or (
            f"wine_searcher-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
            f"-{uuid.uuid4().hex[:8]}"
        )
        result = ScrapeResult(batch_id=batch_id)

        source_row = self.conn.execute(
            "SELECT source_key FROM dim_source WHERE source_code = ?",
            (self.source_code,),
        ).fetchone()
        if not source_row:
            return ScrapeResult(error="dim_source row missing for 'wine_searcher'.")
        source_key = source_row[0]

        if not shutil.which("firecrawl"):
            write_dlq(
                self.conn, source_key, batch_id,
                "scraper_not_applicable",
                "firecrawl CLI not found — install with: npm install -g firecrawl",
                {},
            )
            result.rows_dlq += 1
            return result

        cuvees = self._load_cuvees(source_key, limit)
        if not cuvees:
            _logger.info("No cuvées to scrape (all already attempted within %d days).", _RESUME_DAYS)
            return result

        _logger.info("Scraping %d cuvées (limit=%s)", len(cuvees), limit)

        frankfurter_base = os.environ.get("FRANKFURTER_API_BASE", _FRANKFURTER_BASE).rstrip("/")
        # SSRF guard: only trust the ECB-sourced Frankfurter host over HTTPS. An
        # attacker who can set this env var could otherwise redirect FX lookups at
        # an internal service. Anything else falls back to the safe default.
        from urllib.parse import urlparse as _urlparse
        _fb = _urlparse(frankfurter_base)
        if _fb.scheme != "https" or not (_fb.hostname or "").endswith("frankfurter.app"):
            _logger.warning("Ignoring untrusted FRANKFURTER_API_BASE=%r; using default", frankfurter_base)
            frankfurter_base = _FRANKFURTER_BASE
        fx_cache: dict[str, Optional[float]] = {}
        fx_client = httpx.Client(timeout=15, follow_redirects=True) if HAS_HTTPX else None

        try:
            for cuvee in cuvees:
                self._scrape_cuvee(
                    fx_client, frankfurter_base,
                    source_key, batch_id, cuvee, fx_cache, result,
                )
                time.sleep(_REQUEST_DELAY)
        finally:
            if fx_client:
                fx_client.close()

        return result

    # ── Data loading ──────────────────────────────────────────────────────────

    def _load_cuvees(self, source_key: int, limit: Optional[int]) -> list[dict]:
        """
        Return cuvées not yet attempted in the last _RESUME_DAYS days.

        Each row is a unique (producer_norm, cuvee_norm) pair with:
          - producer_name, cuvee_name  for display / URL building
          - vintage_map: {vintage: wine_key}  for matching listings back
          - appellation_norm for URL enrichment
        """
        cutoff = int(datetime.now(timezone.utc).timestamp()) - _RESUME_DAYS * 86400
        cap = limit if limit is not None else 999_999

        rows = self.conn.execute(
            """
            SELECT
                p.producer_norm,
                p.producer_name,
                w.cuvee_norm,
                w.cuvee_name,
                a.appellation_norm,
                GROUP_CONCAT(
                    CAST(COALESCE(w.vintage, 0) AS TEXT) || ':' || w.wine_key
                ) AS vintage_keys,
                p.coverage_tier
            FROM dim_wine w
            JOIN dim_producer p USING (producer_key)
            JOIN dim_appellation a USING (appellation_key)
            WHERE p.country_code = 'FR'
              AND a.country_code = 'FR'
              AND (w.vintage IS NULL OR w.vintage >= ?)
              AND NOT EXISTS (
                  SELECT 1 FROM ops_content_hashes och
                  WHERE och.url  = 'ws_cuvee:' || p.producer_norm || '|' || COALESCE(w.cuvee_norm, '')
                    AND och.source_key = ?
                    AND och.last_fetched_at >= ?
              )
            GROUP BY p.producer_norm, w.cuvee_norm
            ORDER BY
                CASE p.coverage_tier
                    WHEN 'notable' THEN 1
                    WHEN 'mid'     THEN 2
                    ELSE 3
                END,
                p.producer_name
            LIMIT ?
            """,
            (_VINTAGE_MIN, source_key, cutoff, cap),
        ).fetchall()

        result = []
        for r in rows:
            vintage_map: dict[Optional[int], str] = {}
            if r[5]:
                for pair in r[5].split(","):
                    v_str, wkey = pair.split(":", 1)
                    v = int(v_str) if v_str != "0" else None
                    vintage_map[v] = wkey
            result.append({
                "producer_norm":   r[0],
                "producer_name":   r[1],
                "cuvee_norm":      r[2],
                "cuvee_name":      r[3],
                "appellation_norm": r[4],
                "vintage_map":     vintage_map,  # {vintage_int_or_None → wine_key}
                "coverage_tier":   r[6],
            })
        return result

    # ── Per-cuvée scrape ──────────────────────────────────────────────────────

    def _scrape_cuvee(
        self,
        fx_client,
        frankfurter_base: str,
        source_key: int,
        batch_id: str,
        cuvee: dict,
        fx_cache: dict,
        result: ScrapeResult,
    ) -> None:
        url = _build_ws_url(cuvee)
        result.rows_fetched += 1

        markdown = _scrape_page(url)

        # Always mark as attempted (whether we got results or not) so the
        # next batch skips this cuvée for _RESUME_DAYS days.
        self._mark_attempted(cuvee, source_key)

        if not markdown:
            write_dlq(
                self.conn, source_key, batch_id, "network_error",
                "firecrawl scrape returned no content",
                {"producer": cuvee["producer_norm"], "cuvee": cuvee["cuvee_norm"], "url": url},
            )
            result.rows_dlq += 1
            return

        listings = _parse_listings(markdown)
        if not listings:
            result.rows_skipped_unchanged += 1
            return

        recorded_at = int(datetime.now(timezone.utc).timestamp())

        for listing in listings:
            vintage = listing["vintage"]

            # Skip pre-2000 vintages
            if vintage is not None and vintage < _VINTAGE_MIN:
                continue

            # Match listing vintage back to a wine_key in this cuvée
            wine_key = cuvee["vintage_map"].get(vintage)
            if wine_key is None:
                # Vintage not in DB for this cuvée → skip rather than fabricate
                result.rows_skipped_unchanged += 1
                continue

            # FX to EUR
            currency = listing["currency"]
            if currency not in fx_cache:
                fx_cache[currency] = (
                    _eur_rate(fx_client, currency, frankfurter_base)
                    if fx_client else (1.0 if currency == "EUR" else None)
                )
            rate = fx_cache.get(currency)
            if rate is None:
                result.rows_skipped_unchanged += 1
                continue

            price_eur = round(listing["price_local"] * rate, 2)
            if not (_PRICE_MIN_EUR <= price_eur <= _PRICE_MAX_EUR):
                result.rows_skipped_unchanged += 1
                continue

            content_hash = hashlib.sha256(
                f"{wine_key}:{listing['retailer']}:{vintage}:{price_eur:.2f}".encode()
            ).hexdigest()

            inserted = insert_staging_candidate(
                self.conn,
                wine_key=wine_key,
                source_key=source_key,
                retailer=listing["retailer"],
                recorded_at=recorded_at,
                currency_code="EUR",
                amount_local=price_eur,
                amount_eur=price_eur,
                source_url=listing["source_url"],
                content_hash=content_hash,
                batch_id=batch_id,
            )
            if inserted:
                result.rows_inserted += 1
            else:
                result.rows_skipped_unchanged += 1

    # ── Progress tracking ─────────────────────────────────────────────────────

    def _mark_attempted(self, cuvee: dict, source_key: int) -> None:
        """
        Upsert a sentinel into ops_content_hashes to record that this cuvée
        was attempted.  Subsequent _load_cuvees calls exclude it for _RESUME_DAYS.
        """
        now = int(datetime.now(timezone.utc).timestamp())
        key = _progress_key(cuvee)
        self.conn.execute(
            """
            INSERT INTO ops_content_hashes
                (url, source_key, last_hash, last_fetched_at, fetch_count)
            VALUES (?, ?, 'attempted', ?, 1)
            ON CONFLICT(url) DO UPDATE SET
                last_hash       = 'attempted',
                last_fetched_at = excluded.last_fetched_at,
                fetch_count     = fetch_count + 1
            """,
            (key, source_key, now),
        )
        self.conn.commit()
