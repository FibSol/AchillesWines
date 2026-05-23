"""
Christie's Wine & Spirits auction scraper.

Source: https://www.christies.com/en/departments/wine-and-spirits
Auth:   None required (auction results are public)
Cadence: Monthly
Data:   Hammer prices for individual wine lots → staging_price_candidates

Christie's exposes an internal JSON search API that powers their React frontend.
We target that API directly (avoids JS rendering overhead). If the endpoint drifts,
the scraper fails fast and logs to DLQ — run with --limit 5 to probe.

Lot title format: "Château Pétrus 1990, Pomerol (12 bottles per lot)"
Producer, vintage, and appellation are extracted via regex + identity normaliser.

Currency: Christie's prices are in GBP for London sales, USD for New York.
FX conversion to EUR uses the Frankfurter API (same pattern as other scrapers).
"""
import hashlib
import json
import re
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx
from rich.console import Console

from .base import BaseScraper, ScrapeResult
from ..identity import normalize_producer, normalize_cuvee, compute_wine_key, norm_text
from ..dlq import write_dlq

console = Console()

# Christie's internal discovery API (reverse-engineered from XHR traffic).
# NOTE (May 2026): /api/discovery/lots/searchlots now returns 404.
# Christie's blocks all alternative GET endpoints with empty-body 200 responses.
# The scraper is kept in place for when a working endpoint is re-discovered;
# run `achilles-scraper run --source christies --limit 5` to probe after any site update.
_SEARCH_URL = "https://www.christies.com/api/discovery/lots/searchlots"
_FX_URL = "https://api.frankfurter.app/latest"

_WINE_DEPT_CODE = "wine-spirits"
_PAGE_SIZE = 50
_DEFAULT_MONTHS_BACK = 6

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


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


def _fetch_fx(client: httpx.Client, currency: str) -> Optional[float]:
    """Return currency→EUR rate, or None on failure."""
    if currency.upper() == "EUR":
        return 1.0
    try:
        resp = client.get(_FX_URL, params={"from": currency.upper(), "to": "EUR"}, timeout=10)
        resp.raise_for_status()
        rates = resp.json().get("rates", {})
        return rates.get("EUR")
    except Exception:
        return None


def _extract_vintage(text: str) -> Optional[int]:
    m = re.search(r"\b(19[5-9]\d|20[0-3]\d)\b", text or "")
    return int(m.group(1)) if m else None


def _extract_bottle_count(text: str) -> int:
    """Return number of bottles in a lot, default 1."""
    m = re.search(r"\((\d+)\s+bottle", text or "", re.IGNORECASE)
    return int(m.group(1)) if m else 1


def _parse_lot_title(title: str) -> tuple[str, str, Optional[str], Optional[int]]:
    """
    Extract (raw_name, producer_part, appellation, vintage) from a Christie's lot title.

    Examples:
      "Pétrus 1990, Pomerol (12 bottles per lot)"
        → ("Pétrus 1990, Pomerol", "Pétrus", "Pomerol", 1990)
      "Domaine de la Romanée-Conti, La Tâche 2015 (6 bottles)"
        → ("Domaine de la Romanée-Conti, La Tâche 2015", "Domaine de la Romanée-Conti", None, 2015)
    """
    # Strip lot count suffix
    raw = re.sub(r"\s*\(\d+\s+(?:bottle|magnum|case)[^)]*\)", "", title, flags=re.IGNORECASE).strip()
    vintage = _extract_vintage(raw)

    # Remove vintage from name for normalisation
    name_no_vintage = re.sub(r"\b(19[5-9]\d|20[0-3]\d)\b", "", raw).strip().strip(",").strip()

    # Appellation: last comma-separated segment, if it looks like a place name
    # (title case, no numbers, not too long)
    parts = [p.strip() for p in name_no_vintage.split(",")]
    appellation: Optional[str] = None
    if len(parts) >= 2:
        candidate = parts[-1]
        if re.match(r"^[A-ZÀ-Ö][a-zA-ZÀ-öÙ-ý\- ]{1,40}$", candidate):
            appellation = candidate
            name_no_vintage = ",".join(parts[:-1]).strip()

    return raw, name_no_vintage, appellation, vintage


def _ensure_producer(conn: sqlite3.Connection, producer_norm: str, producer_name: str) -> bool:
    row = conn.execute(
        "SELECT producer_key FROM dim_producer WHERE producer_norm = ?",
        (producer_norm,),
    ).fetchone()
    if row:
        return True
    try:
        conn.execute(
            """INSERT OR IGNORE INTO dim_producer
               (producer_name, producer_norm, country_code, allowed_appellations, aliases, status)
               VALUES (?, ?, 'FR', '[]', '[]', 'pending_review')""",
            (producer_name, producer_norm),
        )
        conn.commit()
        return True
    except Exception:
        return False


def _find_appellation_key(conn: sqlite3.Connection, appellation_norm: str) -> Optional[int]:
    if not appellation_norm:
        return None
    row = conn.execute(
        "SELECT appellation_key FROM dim_appellation WHERE appellation_norm = ?",
        (appellation_norm,),
    ).fetchone()
    return row[0] if row else None


def _ensure_appellation(
    conn: sqlite3.Connection, appellation_name: str, appellation_norm: str
) -> Optional[int]:
    existing = _find_appellation_key(conn, appellation_norm)
    if existing:
        return existing
    if not appellation_name:
        return None
    try:
        cur = conn.execute(
            """INSERT OR IGNORE INTO dim_appellation
               (country_code, region, appellation_name, appellation_norm, level)
               VALUES ('FR', ?, ?, ?, 'regional')""",
            (appellation_name, appellation_name, appellation_norm),
        )
        conn.commit()
        return cur.lastrowid or _find_appellation_key(conn, appellation_norm)
    except Exception:
        return None


def _ensure_wine(
    conn: sqlite3.Connection,
    wine_key: str,
    producer_norm: str,
    cuvee_name: str,
    cuvee_norm: str,
    appellation_name: Optional[str],
    appellation_norm: str,
    vintage: Optional[int],
) -> bool:
    if conn.execute("SELECT 1 FROM dim_wine WHERE wine_key = ?", (wine_key,)).fetchone():
        return True

    # Try country-agnostic producer lookup (Christie's has global wines)
    producer_row = conn.execute(
        "SELECT producer_key FROM dim_producer WHERE producer_norm = ?",
        (producer_norm,),
    ).fetchone()
    if not producer_row:
        return False

    appellation_key = _ensure_appellation(
        conn, appellation_name or "", appellation_norm
    )
    if appellation_key is None:
        return False

    is_nv = 1 if vintage is None else 0
    try:
        conn.execute(
            """INSERT OR IGNORE INTO dim_wine
               (wine_key, producer_key, appellation_key, cuvee_name, cuvee_norm,
                color, vintage, is_non_vintage, bottle_ml, canonical_name)
               VALUES (?, ?, ?, ?, ?, 'red', ?, ?, 750, ?)""",
            (wine_key, producer_row[0], appellation_key, cuvee_name, cuvee_norm,
             vintage, is_nv, cuvee_name),
        )
        conn.commit()
        return True
    except Exception:
        return False


class ChristiesScraper(BaseScraper):
    """
    Fetches Christie's Wine & Spirits auction results and feeds hammer prices
    into staging_price_candidates.

    The scraper targets Christie's internal JSON search API. If the endpoint
    changes, run `achilles-scraper run --source christies --limit 5` to probe
    and check the DLQ for parse errors.
    """

    source_code = "christies"

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.batch_id: Optional[str] = None

    def run(self, limit: Optional[int] = None) -> ScrapeResult:
        source_key = _get_source_key(self.conn, self.source_code)
        batch_id = self.batch_id or f"christies-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        result = ScrapeResult(batch_id=batch_id)

        headers = {
            "User-Agent": _USER_AGENT,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Referer": "https://www.christies.com/en/departments/wine-and-spirits",
        }

        # FX cache: currency → EUR rate
        fx_cache: dict[str, Optional[float]] = {}

        with httpx.Client(headers=headers, timeout=30, follow_redirects=True) as client:

            def _get_fx(currency: str) -> Optional[float]:
                if currency not in fx_cache:
                    fx_cache[currency] = _fetch_fx(client, currency)
                return fx_cache[currency]

            page = 0
            total_lots = None

            while True:
                payload = {
                    "contexts": [{"type": "department", "code": _WINE_DEPT_CODE}],
                    "filters": [{"type": "HAS_RESULTS"}],
                    "sorts": [{"type": "DATE_DESC"}],
                    "page": page,
                    "pageSize": _PAGE_SIZE,
                }
                try:
                    resp = self._fetch(
                        lambda: client.post(_SEARCH_URL, json=payload)
                    )
                    resp.raise_for_status()
                    data = resp.json()
                except Exception as exc:
                    msg = f"API error on page {page}: {exc}"
                    console.print(f"[red]christies[/] {msg}")
                    write_dlq(self.conn, source_key, batch_id, "parse_error", msg, {
                        "page": page, "url": _SEARCH_URL
                    })
                    result.rows_dlq += 1
                    result.error = msg
                    break

                lots = data.get("lots", [])
                if total_lots is None:
                    total_lots = data.get("totalResults", 0)
                    console.print(f"[cyan]christies[/] {total_lots} lots found")

                if not lots:
                    break

                result.rows_fetched += len(lots)

                for lot in lots:
                    if limit is not None and (result.rows_inserted + result.rows_dlq) >= limit:
                        break

                    title = (lot.get("title") or lot.get("lotTitle") or "").strip()
                    if not title:
                        continue

                    # Price: hammer price (priceRealised) or estimate midpoint
                    price_info = (
                        lot.get("priceRealised")
                        or lot.get("estimatedPrice")
                        or {}
                    )
                    amount_raw = price_info.get("amount") or price_info.get("value")
                    currency = (price_info.get("currencyCode") or "GBP").upper()
                    if amount_raw is None:
                        result.rows_skipped_unchanged += 1
                        continue

                    try:
                        amount_local = float(str(amount_raw).replace(",", ""))
                    except (ValueError, TypeError):
                        result.rows_skipped_unchanged += 1
                        continue

                    # FX to EUR
                    fx = _get_fx(currency)
                    amount_eur = round(amount_local * fx, 2) if fx else None

                    # Per-bottle price (lots may contain multiple bottles)
                    bottle_count = _extract_bottle_count(title)
                    if bottle_count > 1:
                        amount_local = round(amount_local / bottle_count, 2)
                        if amount_eur:
                            amount_eur = round(amount_eur / bottle_count, 2)

                    # Parse lot title → wine identity
                    raw_name, name_part, appellation, vintage = _parse_lot_title(title)
                    producer_norm = normalize_producer(name_part)
                    cuvee_norm = normalize_cuvee(name_part)
                    appellation_norm = norm_text(appellation) if appellation else ""

                    if not producer_norm or not cuvee_norm:
                        write_dlq(self.conn, source_key, batch_id, "parse_error",
                                  f"Empty producer/cuvee from: {title!r}",
                                  {"title": title})
                        result.rows_dlq += 1
                        continue

                    wine_key = compute_wine_key(producer_norm, cuvee_norm, vintage, appellation_norm)
                    _ensure_producer(self.conn, producer_norm, name_part)

                    if not _ensure_wine(
                        self.conn, wine_key, producer_norm,
                        name_part, cuvee_norm,
                        appellation, appellation_norm, vintage,
                    ):
                        write_dlq(self.conn, source_key, batch_id, "unresolved_dim",
                                  "Could not resolve producer or appellation",
                                  {"title": title, "producer_norm": producer_norm,
                                   "appellation": appellation, "wine_key": wine_key})
                        result.rows_dlq += 1
                        continue

                    lot_url = lot.get("url") or lot.get("lotUrl") or ""
                    if lot_url and not lot_url.startswith("http"):
                        lot_url = f"https://www.christies.com{lot_url}"

                    content_hash = hashlib.sha256(
                        json.dumps(lot, sort_keys=True).encode()
                    ).hexdigest()

                    try:
                        self.conn.execute(
                            """INSERT OR IGNORE INTO staging_price_candidates
                               (wine_key, source_key, retailer, recorded_at, currency_code,
                                amount_local, amount_eur, source_url, content_hash, batch_id, needs_review)
                               VALUES (?, ?, 'christies', ?, ?, ?, ?, ?, ?, ?, 1)""",
                            (
                                wine_key, source_key, int(time.time()),
                                currency, amount_local, amount_eur,
                                lot_url, content_hash, batch_id,
                            ),
                        )
                        changed = self.conn.execute("SELECT changes()").fetchone()[0]
                        if changed:
                            result.rows_inserted += 1
                        else:
                            result.rows_skipped_unchanged += 1
                    except Exception as exc:
                        write_dlq(self.conn, source_key, batch_id, "validation_error",
                                  str(exc), {"wine_key": wine_key, "title": title})
                        result.rows_dlq += 1

                self.conn.commit()

                if limit is not None and (result.rows_inserted + result.rows_dlq) >= limit:
                    break
                if total_lots and result.rows_fetched >= total_lots:
                    break

                page += 1
                time.sleep(1.0)

        console.print(
            f"[green]christies[/] done — "
            f"{result.rows_inserted} inserted, {result.rows_dlq} DLQ, "
            f"{result.rows_skipped_unchanged} skipped"
        )
        return result
