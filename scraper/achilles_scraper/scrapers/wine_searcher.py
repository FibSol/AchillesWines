"""
Wine-Searcher scraper — Firecrawl search approach.

Target:  Firecrawl /v1/search → wine-searcher.com result snippets
Auth:    FIRECRAWL_API_KEY env var (same key used by the CLI)
Cadence: Monthly
Output:  staging_price_candidates → fact_price via tri-source promoter

Strategy
--------
For each wine in dim_wine (coverage_tier='notable' first) POST a Firecrawl
search query:
    "{producer} {cuvee} {vintage} site:wine-searcher.com"

Wine-Searcher's Google snippet reliably contains the avg price in the format:
    "Avg Price (ex-tax) $1,234 / 750ml"

That single price point is extracted, converted to EUR if needed, and inserted
as a staging_price_candidate with retailer="wine-searcher.com".

Why this works without a WS Pro API subscription
-------------------------------------------------
Firecrawl's /search endpoint routes through its own cached/indexed layer and
does not hit wine-searcher.com directly, bypassing PerimeterX entirely.
Direct HTTP scraping of wine-searcher.com is blocked by PerimeterX regardless
of headers or proxies.

Credit cost
-----------
1 Firecrawl credit per wine.  Run with --limit 500 for an initial sweep of
notable-tier wines; increase once the credit budget is confirmed.

Without FIRECRAWL_API_KEY the scraper logs a single scraper_not_applicable
DLQ row and exits cleanly — the dim_source row stays enabled.

FX conversion
-------------
Wine-Searcher snippets show the US market average price (USD).  EUR conversion
uses the Frankfurter API (FRANKFURTER_API_BASE env var, defaults to
https://api.frankfurter.app) — a free, ECB-sourced endpoint, no key needed.
"""
import hashlib
import logging
import os
import re
import sqlite3
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
from ..identity import normalize_producer, normalize_cuvee, compute_wine_key

_logger = logging.getLogger(__name__)

_FIRECRAWL_SEARCH_URL = "https://api.firecrawl.dev/v1/search"
_FRANKFURTER_BASE = "https://api.frankfurter.app"
_REQUEST_DELAY = 1.5            # seconds between Firecrawl calls
_PRICE_MIN_EUR = 3.0
_PRICE_MAX_EUR = 50_000.0
_ENV_KEY = "FIRECRAWL_API_KEY"

# Matches "Avg Price (ex-tax) $1,234 / 750ml" or "€ 567" or "£ 890"
_AVG_PRICE_RE = re.compile(
    r"Avg Price.*?([$€£])\s*([\d,]+(?:\.\d+)?)\s*/\s*750\s*ml",
    re.IGNORECASE,
)
_CURRENCY_SYMBOL = {"$": "USD", "€": "EUR", "£": "GBP"}


def _parse_avg_price(description: str) -> tuple[Optional[float], str]:
    """Extract (price, currency_code) from a WS snippet description.

    Returns (None, 'EUR') if no price pattern is found.
    """
    if not description:
        return None, "EUR"
    m = _AVG_PRICE_RE.search(description)
    if not m:
        return None, "EUR"
    symbol, raw = m.group(1), m.group(2)
    try:
        price = float(raw.replace(",", ""))
    except ValueError:
        return None, "EUR"
    currency = _CURRENCY_SYMBOL.get(symbol, "USD")
    return price, currency


def _fetch_eur_rate(client: "httpx.Client", from_currency: str, base: str) -> Optional[float]:
    """Return the EUR rate for 1 unit of from_currency via Frankfurter."""
    if from_currency == "EUR":
        return 1.0
    try:
        resp = client.get(
            f"{base}/latest",
            params={"from": from_currency, "to": "EUR"},
            timeout=10,
        )
        if resp.is_success:
            data = resp.json()
            return data.get("rates", {}).get("EUR")
    except Exception:
        pass
    return None


class WineSearcherScraper(BaseScraper):
    """
    Wine-Searcher avg-price scraper via Firecrawl /v1/search.

    Requires FIRECRAWL_API_KEY in the environment.
    Without a key, logs a single ``scraper_not_applicable`` DLQ row and exits.
    """

    source_code = "wine_searcher"

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.batch_id: Optional[str] = None

    def run(self, limit: Optional[int] = None) -> ScrapeResult:
        if not HAS_HTTPX:
            return ScrapeResult(error="Missing dependency: httpx not installed")

        api_key = os.environ.get(_ENV_KEY, "").strip()

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

        if not api_key:
            write_dlq(
                self.conn, source_key, batch_id,
                "scraper_not_applicable",
                f"{_ENV_KEY} not set — set this env var (same key as the Firecrawl CLI) "
                "to enable Wine-Searcher price ingestion.",
                {},
            )
            result.rows_dlq += 1
            return result

        wines = self._load_wines(limit)
        if not wines:
            return result

        frankfurter_base = os.environ.get("FRANKFURTER_API_BASE", _FRANKFURTER_BASE).rstrip("/")
        # Cache FX rates to avoid hammering Frankfurter for every wine
        fx_cache: dict[str, Optional[float]] = {}

        fc_headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        with httpx.Client(timeout=30, follow_redirects=True) as client:
            for wine in wines:
                if limit is not None and result.rows_fetched >= limit:
                    break
                self._scrape_wine(
                    client, fc_headers, frankfurter_base,
                    source_key, batch_id, wine, fx_cache, result,
                )
                time.sleep(_REQUEST_DELAY)

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_wines(self, limit: Optional[int]) -> list[dict]:
        """Return dim_wine rows joined with producer name, notable tier first."""
        cap = limit if limit is not None else 999_999
        rows = self.conn.execute(
            """
            SELECT
                w.wine_key,
                p.producer_name,
                p.producer_norm,
                w.cuvee_name,
                w.cuvee_norm,
                w.vintage,
                w.color,
                a.appellation_norm
            FROM dim_wine w
            JOIN dim_producer p USING (producer_key)
            LEFT JOIN dim_appellation a USING (appellation_key)
            WHERE p.country_code = 'FR'
            ORDER BY
                CASE p.coverage_tier
                    WHEN 'notable'   THEN 1
                    WHEN 'mid'       THEN 2
                    WHEN 'long_tail' THEN 3
                    ELSE 4
                END,
                p.producer_name
            LIMIT ?
            """,
            (cap,),
        ).fetchall()
        cols = [
            "wine_key", "producer_name", "producer_norm",
            "cuvee_name", "cuvee_norm", "vintage", "color", "appellation_norm",
        ]
        return [dict(zip(cols, r)) for r in rows]

    def _build_query(self, wine: dict) -> str:
        parts = [wine["producer_name"]]
        if wine["cuvee_name"] and wine["cuvee_name"] != wine["producer_name"]:
            parts.append(wine["cuvee_name"])
        if wine["vintage"]:
            parts.append(str(wine["vintage"]))
        parts.append("site:wine-searcher.com")
        return " ".join(parts)

    def _scrape_wine(
        self,
        client: "httpx.Client",
        fc_headers: dict,
        frankfurter_base: str,
        source_key: int,
        batch_id: str,
        wine: dict,
        fx_cache: dict,
        result: ScrapeResult,
    ) -> None:
        query = self._build_query(wine)

        try:
            resp = self._fetch(lambda: client.post(
                _FIRECRAWL_SEARCH_URL,
                headers=fc_headers,
                json={"query": query, "limit": 1, "location": "Belgium"},
            ))
        except Exception as exc:
            write_dlq(
                self.conn, source_key, batch_id, "network_error", str(exc),
                {"wine_key": wine["wine_key"], "query": query},
            )
            result.rows_dlq += 1
            return

        result.rows_fetched += 1

        if resp.status_code == 401:
            write_dlq(
                self.conn, source_key, batch_id, "auth_error",
                f"Firecrawl returned 401 — check {_ENV_KEY}",
                {"wine_key": wine["wine_key"]},
            )
            result.rows_dlq += 1
            return

        if resp.status_code == 429:
            write_dlq(
                self.conn, source_key, batch_id, "auth_error",
                "Firecrawl rate limit (429) — increase _REQUEST_DELAY",
                {"wine_key": wine["wine_key"]},
            )
            result.rows_dlq += 1
            return

        if not resp.is_success:
            write_dlq(
                self.conn, source_key, batch_id, "network_error",
                f"HTTP {resp.status_code}",
                {"wine_key": wine["wine_key"]},
            )
            result.rows_dlq += 1
            return

        try:
            data = resp.json()
        except Exception as exc:
            write_dlq(
                self.conn, source_key, batch_id, "parse_error",
                f"JSON decode failed: {exc}",
                {"wine_key": wine["wine_key"]},
            )
            result.rows_dlq += 1
            return

        results = data.get("data") or []
        if not results:
            result.rows_skipped_unchanged += 1
            return

        first = results[0]
        description = first.get("description") or ""
        source_url = first.get("url") or _FIRECRAWL_SEARCH_URL

        price_local, currency = _parse_avg_price(description)
        if price_local is None:
            result.rows_skipped_unchanged += 1
            return

        # FX conversion to EUR
        if currency not in fx_cache:
            fx_cache[currency] = _fetch_eur_rate(client, currency, frankfurter_base)
        rate = fx_cache.get(currency)

        if rate is None:
            write_dlq(
                self.conn, source_key, batch_id, "validation_error",
                f"FX rate unavailable for {currency}→EUR",
                {"wine_key": wine["wine_key"], "price": price_local, "currency": currency},
            )
            result.rows_dlq += 1
            return

        price_eur = round(price_local * rate, 2)

        if not (_PRICE_MIN_EUR <= price_eur <= _PRICE_MAX_EUR):
            result.rows_skipped_unchanged += 1
            return

        content_hash = hashlib.sha256(
            f"{wine['wine_key']}:wine-searcher.com:{price_eur:.2f}:EUR".encode()
        ).hexdigest()

        recorded_at = int(datetime.now(timezone.utc).timestamp())

        inserted = insert_staging_candidate(
            self.conn,
            wine_key=wine["wine_key"],
            source_key=source_key,
            retailer="wine-searcher.com",
            recorded_at=recorded_at,
            currency_code="EUR",
            amount_local=price_eur,
            amount_eur=price_eur,
            source_url=source_url,
            content_hash=content_hash,
            batch_id=batch_id,
        )
        if inserted:
            result.rows_inserted += 1
        else:
            result.rows_skipped_unchanged += 1
