"""
EC Agri-food wine API scraper — EU bulk wine market prices.

Source: https://agridata.ec.europa.eu/extensions/API_Documentation/wine.html
Auth: None (public REST API)
Cadence: Weekly
Data: Weekly bulk wine prices (€/HL) by wine category for FR, IT, ES, DE, PT

API endpoint history:
  - https://api.tech.ec.europa.eu/agrifood  — confirmed working May 2026
    Returns 404 only when queried date range has no published data yet
    (data lags ~6-8 months); use a 540-day lookback window to avoid this.
  - https://agridata.ec.europa.eu/agridata  — Qlik Sense dashboard (400)

Writes to fact_market_index (NOT staging_price_candidates — these are wholesale
bulk prices per hectoliter, not individual bottle prices).
"""
import re
import sqlite3
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from rich.console import Console

from .base import BaseScraper, ScrapeResult
from ..dlq import write_dlq

console = Console()

# Try in order — first working base wins at runtime
# Note: api.tech.ec.europa.eu returns 404 when the date range has no data
#       (data lags ~8 months) but works fine with a wide enough lookback window.
_API_BASES = [
    "https://api.tech.ec.europa.eu/agrifood",    # primary — confirmed working May 2026
    "https://agridata.ec.europa.eu/agridata",   # fallback (Qlik Sense, currently 400)
]
_MEMBER_STATES = ["FR", "IT", "ES", "DE", "PT"]
# EC Agrifood data lags ~6-8 months behind real time; use 540-day window
# so we always catch the most recent published prices.
_WINDOW_DAYS = 540

_ENSURE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS fact_market_index (
    market_index_id integer PRIMARY KEY AUTOINCREMENT NOT NULL,
    source_key      integer NOT NULL REFERENCES dim_source(source_key),
    country_code    text    NOT NULL,
    wine_category   text    NOT NULL,
    price_eur_hl    real    NOT NULL,
    week_begin_date text    NOT NULL,
    week_end_date   text    NOT NULL,
    batch_id        text    NOT NULL,
    created_at      integer NOT NULL DEFAULT (unixepoch())
);
"""
_ENSURE_IDX_UNIQUE = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_market_unique
ON fact_market_index(source_key, country_code, wine_category, week_begin_date);
"""
_ENSURE_IDX_COUNTRY = """
CREATE INDEX IF NOT EXISTS idx_market_country_date
ON fact_market_index(country_code, week_begin_date);
"""


def _parse_price(raw: str) -> Optional[float]:
    """Extract numeric value from strings like '€ 90.00' or '90,50'."""
    cleaned = re.sub(r"[^\d.,]", "", str(raw)).replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _get_source_key(conn: sqlite3.Connection, source_code: str) -> int:
    row = conn.execute(
        "SELECT source_key FROM dim_source WHERE source_code = ?", (source_code,)
    ).fetchone()
    if row is None:
        raise RuntimeError(
            f"dim_source row missing for '{source_code}'. "
            "Run migration 0008 or seed manually."
        )
    return row[0]


class EcAgrifoodScraper(BaseScraper):
    """Fetches weekly EU bulk wine market prices from the EC Agri-food REST API."""

    source_code = "ec_agrifood"

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.batch_id: Optional[str] = None

    def _ensure_tables(self) -> None:
        self.conn.execute(_ENSURE_TABLE_SQL)
        self.conn.execute(_ENSURE_IDX_UNIQUE)
        self.conn.execute(_ENSURE_IDX_COUNTRY)
        self.conn.commit()

    def run(self, limit: Optional[int] = None) -> ScrapeResult:
        self._ensure_tables()
        source_key = _get_source_key(self.conn, self.source_code)
        batch_id = self.batch_id or f"ec_agrifood-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        result = ScrapeResult(batch_id=batch_id)

        end_dt = datetime.now(timezone.utc)
        begin_dt = end_dt - timedelta(days=_WINDOW_DAYS)
        begin_str = begin_dt.strftime("%d/%m/%Y")
        end_str = end_dt.strftime("%d/%m/%Y")
        codes = ",".join(_MEMBER_STATES)

        console.print(f"[cyan]ec_agrifood[/] fetching {begin_str} → {end_str} for {codes}")

        headers = {"Accept": "application/json"}
        data = None
        last_error = None
        with httpx.Client(headers=headers, timeout=30, follow_redirects=True) as client:
            for base in _API_BASES:
                url = f"{base}/api/wine/prices"
                try:
                    resp = self._fetch(
                        lambda u=url: client.get(
                            u,
                            params={
                                "memberStateCodes": codes,
                                "beginDate": begin_str,
                                "endDate": end_str,
                            },
                        )
                    )
                    if resp.status_code == 400:
                        # Log full response so we can debug parameter issues
                        console.print(
                            f"[yellow]ec_agrifood[/] {base} → 400: {resp.text[:300]}"
                        )
                        last_error = f"HTTP 400 from {base}: {resp.text[:200]}"
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                    console.print(f"[cyan]ec_agrifood[/] working endpoint: {base}")
                    break
                except Exception as exc:
                    console.print(f"[yellow]ec_agrifood[/] {base} failed: {exc}")
                    last_error = str(exc)
                    continue

        if data is None:
            write_dlq(self.conn, source_key, batch_id, "parse_error",
                      f"All endpoints failed. Last: {last_error}",
                      {"begin": begin_str, "end": end_str, "tried": _API_BASES})
            result.rows_dlq += 1
            result.error = last_error
            return result

        records: list[dict] = data if isinstance(data, list) else data.get("data", [])
        console.print(f"[cyan]ec_agrifood[/] {len(records)} records received")
        result.rows_fetched = len(records)

        for rec in records:
            if limit is not None and result.rows_inserted >= limit:
                break
            try:
                price = _parse_price(rec.get("price", ""))
                if price is None or price <= 0:
                    continue
                self.conn.execute(
                    """
                    INSERT OR IGNORE INTO fact_market_index
                        (source_key, country_code, wine_category,
                         price_eur_hl, week_begin_date, week_end_date, batch_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_key,
                        rec["memberStateCode"],
                        rec["description"],
                        price,
                        rec["beginDate"],
                        rec["endDate"],
                        batch_id,
                    ),
                )
                changed = self.conn.execute("SELECT changes()").fetchone()[0]
                if changed:
                    result.rows_inserted += 1
                else:
                    result.rows_skipped_unchanged += 1
            except (KeyError, Exception) as exc:
                write_dlq(self.conn, source_key, batch_id, "parse_error", str(exc), rec)
                result.rows_dlq += 1

        self.conn.commit()
        console.print(
            f"[green]ec_agrifood[/] done — "
            f"{result.rows_inserted} inserted, {result.rows_skipped_unchanged} already present"
        )
        return result
