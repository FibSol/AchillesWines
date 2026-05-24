"""
Wine-Searcher Pro API scraper.

Target:  https://www.wine-searcher.com/find/{name}/{vintage}/1/France/
         ?format=json&apikey={key}&num=25
Auth:    ACHILLES_WINESEARCHER_API_KEY env var (Pro subscription required)
Cadence: Monthly
Output:  staging_price_candidates → fact_price via tri-source promoter

Strategy
--------
Iterate dim_wine (coverage_tier='notable' first, then 'mid') joined with
dim_producer.  For each wine build a Wine-Searcher search URL, call the
JSON API, and insert each merchant offer as a separate staging candidate.
Because Wine-Searcher aggregates dozens of retailers per wine, a single
run can produce many multi-source overlaps that promote quickly.

Without a key the scraper logs a single ``scraper_not_applicable`` DLQ row
and exits cleanly — the dim_source row remains enabled so the UI shows it
as "key needed" rather than "dead".

API response schema (Wine-Searcher XML Data Service, JSON format)
-----------------------------------------------------------------
{
  "product_name": "Chateau Margaux",
  "year": 2015,
  "list_count": 12,
  "price_list": [
    {
      "store_name": "...",
      "store_id": 123,
      "price": 550.00,
      "currency": "EUR",
      "link": "https://...",
      "country": "FR"
    }
  ]
}

Note: the exact schema may vary slightly across API plan tiers.
On first use with a real key, inspect the raw JSON by running:
  achilles-scraper run --source wine_searcher --limit 1
and checking the DLQ if parse errors appear.
"""
import hashlib
import logging
import os
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote_plus

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

from .base import BaseScraper, ScrapeResult
from ..dlq import insert_staging_candidate, write_dlq
from ..identity import normalize_producer, normalize_cuvee, compute_wine_key

_logger = logging.getLogger(__name__)

_API_BASE = "https://www.wine-searcher.com/find"
_RESULTS_PER_WINE = 25          # WS returns up to 25 merchant offers per query
_REQUEST_DELAY = 1.2            # seconds between API calls (be polite)
_PRICE_MIN_EUR = 3.0            # skip obvious data-entry errors
_PRICE_MAX_EUR = 50_000.0       # skip implausible values
_ENV_KEY = "ACHILLES_WINESEARCHER_API_KEY"

# Wine-Searcher returns ISO-4217 currency codes; we handle EUR natively,
# others require conversion (FX module optional, else skipped with DLQ).
_HANDLED_CURRENCIES = {"EUR"}


def _build_url(producer_name: str, cuvee_name: str, vintage: Optional[int], api_key: str) -> str:
    """Build a Wine-Searcher find URL for a given wine."""
    wine_label = " ".join(filter(None, [producer_name, cuvee_name])).strip()
    encoded = quote_plus(wine_label)
    year = str(vintage) if vintage else "NV"
    return (
        f"{_API_BASE}/{encoded}/{year}/1/France/"
        f"?format=json&apikey={api_key}&num={_RESULTS_PER_WINE}&Xcurrencycode=EUR"
    )


def _parse_price_list(raw: dict) -> list[dict]:
    """Extract offer list from WS JSON response.

    Handles both the documented ``price_list`` key and the alternate
    ``product`` → ``price_list`` nesting some API tiers return.
    """
    if isinstance(raw.get("price_list"), list):
        return raw["price_list"]
    product = raw.get("product") or {}
    if isinstance(product.get("price_list"), list):
        return product["price_list"]
    return []


class WineSearcherScraper(BaseScraper):
    """
    Wine-Searcher Pro API price scraper.

    Requires ACHILLES_WINESEARCHER_API_KEY in the environment.
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
                f"{_ENV_KEY} not set — set this env var to enable Wine-Searcher price ingestion. "
                "A Pro subscription is required; see https://www.wine-searcher.com/api.lml",
                {},
            )
            result.rows_dlq += 1
            return result

        wines = self._load_wines(limit)
        if not wines:
            return result

        headers = {
            "User-Agent": (
                "AchillesWines/1.0 (home cellar; contact nicolas.vandenbroeck@vcfcigars.com)"
            ),
            "Accept": "application/json",
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
        }

        with httpx.Client(headers=headers, timeout=30, follow_redirects=True) as client:
            for wine in wines:
                if limit is not None and result.rows_fetched >= limit:
                    break
                self._scrape_wine(client, source_key, batch_id, api_key, wine, result)
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

    def _scrape_wine(
        self,
        client,
        source_key: int,
        batch_id: str,
        api_key: str,
        wine: dict,
        result: ScrapeResult,
    ) -> None:
        url = _build_url(
            wine["producer_name"],
            wine["cuvee_name"] or "",
            wine["vintage"],
            api_key,
        )

        try:
            resp = self._fetch(lambda: client.get(url))
        except Exception as exc:
            write_dlq(
                self.conn, source_key, batch_id, "network_error", str(exc),
                {"wine_key": wine["wine_key"], "url": url},
            )
            result.rows_dlq += 1
            return

        result.rows_fetched += 1

        if resp.status_code == 401:
            write_dlq(
                self.conn, source_key, batch_id, "auth_error",
                f"Wine-Searcher returned 401 — check {_ENV_KEY} (key invalid or expired)",
                {"wine_key": wine["wine_key"]},
            )
            result.rows_dlq += 1
            return

        if resp.status_code == 403:
            write_dlq(
                self.conn, source_key, batch_id, "auth_error",
                "Wine-Searcher returned 403 — subscription may have lapsed or key is wrong",
                {"wine_key": wine["wine_key"]},
            )
            result.rows_dlq += 1
            return

        if resp.status_code == 429:
            write_dlq(
                self.conn, source_key, batch_id, "auth_error",
                "Wine-Searcher rate limit hit (429) — increase _REQUEST_DELAY",
                {"wine_key": wine["wine_key"]},
            )
            result.rows_dlq += 1
            return

        if not resp.is_success:
            write_dlq(
                self.conn, source_key, batch_id, "network_error",
                f"HTTP {resp.status_code}",
                {"wine_key": wine["wine_key"], "url": url},
            )
            result.rows_dlq += 1
            return

        try:
            data = resp.json()
        except Exception as exc:
            write_dlq(
                self.conn, source_key, batch_id, "parse_error",
                f"JSON decode failed: {exc}",
                {"wine_key": wine["wine_key"], "raw": resp.text[:500]},
            )
            result.rows_dlq += 1
            return

        offers = _parse_price_list(data)
        if not offers:
            # No results for this wine — not an error
            result.rows_skipped_unchanged += 1
            return

        recorded_at = int(datetime.now(timezone.utc).timestamp())

        for offer in offers:
            store_name = offer.get("store_name") or offer.get("merchant") or ""
            price_raw = offer.get("price")
            currency = (offer.get("currency") or "EUR").upper()
            offer_url = offer.get("link") or offer.get("url") or url

            if not store_name or price_raw is None:
                continue

            try:
                price = float(price_raw)
            except (TypeError, ValueError):
                continue

            if currency not in _HANDLED_CURRENCIES:
                # Skip non-EUR offers for now (FX conversion not wired)
                result.rows_skipped_unchanged += 1
                continue

            if not (_PRICE_MIN_EUR <= price <= _PRICE_MAX_EUR):
                result.rows_skipped_unchanged += 1
                continue

            content_hash = hashlib.sha256(
                f"{wine['wine_key']}:{store_name}:{price:.2f}:{currency}".encode()
            ).hexdigest()

            inserted = insert_staging_candidate(
                self.conn,
                wine_key=wine["wine_key"],
                source_key=source_key,
                retailer=store_name,
                recorded_at=recorded_at,
                currency_code=currency,
                amount_local=price,
                amount_eur=price,
                source_url=offer_url,
                content_hash=content_hash,
                batch_id=batch_id,
            )
            if inserted:
                result.rows_inserted += 1
            else:
                result.rows_skipped_unchanged += 1
