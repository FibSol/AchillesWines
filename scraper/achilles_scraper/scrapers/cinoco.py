# REGISTER_IN_CLI = True
"""
Cinoco.com scraper — retail price ingestion via HTML catalog.

Cinoco is a major Belgian wine importer with a public online shop.
Products are listed under /fr/vins with pagination.
"""
import hashlib
import json
import logging
import re
import time
import uuid
import sqlite3
from datetime import datetime, timezone
from typing import Optional

try:
    import httpx
    from selectolax.parser import HTMLParser
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False

from .base import BaseScraper, ScrapeResult
from ..identity import normalize_producer, normalize_cuvee, compute_wine_key, norm_text
from ..dlq import write_dlq, insert_staging_candidate

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_BASE = "https://www.cinoco.com"
_PRODUCTS_API = f"{_BASE}/collections/les-vins/products.json"

_logger = logging.getLogger(__name__)


def _extract_vintage(text: str) -> Optional[int]:
    m = re.search(r"\b(199\d|20[0-3]\d)\b", text or "")
    return int(m.group(1)) if m else None


def _extract_price(text: str) -> Optional[float]:
    m = re.search(r"(\d+[.,]\d{1,2})", text or "")
    if m:
        return float(m.group(1).replace(",", "."))
    return None


_COLOR_MAP = {
    "rouge": "red",
    "blanc": "white",
    "rosé": "rosé",
    "rose": "rosé",
    "champagne": "sparkling",
    "mousseux": "sparkling",
    "effervescent": "sparkling",
    "liquoreux": "sweet",
    "moelleux": "sweet",
    "fortifié": "fortified",
    "orange": "orange",
}


def _map_color(text: str) -> str:
    t = text.lower().strip()
    for k, v in _COLOR_MAP.items():
        if k in t:
            return v
    return "red"


def _find_appellation_key(conn: sqlite3.Connection, appellation_norm: str) -> Optional[int]:
    if not appellation_norm:
        return None
    row = conn.execute(
        "SELECT appellation_key FROM dim_appellation WHERE appellation_norm = ?",
        (appellation_norm,),
    ).fetchone()
    return row[0] if row else None


def _ensure_appellation(
    conn: sqlite3.Connection,
    appellation_name: str,
    appellation_norm: str,
    region: str,
) -> Optional[int]:
    existing = _find_appellation_key(conn, appellation_norm)
    if existing:
        return existing
    if not appellation_name or not region:
        return None
    try:
        cur = conn.execute(
            """INSERT OR IGNORE INTO dim_appellation
               (country_code, region, appellation_name, appellation_norm, level)
               VALUES ('FR', ?, ?, ?, 'regional')""",
            (region, appellation_name, appellation_norm),
        )
        conn.commit()
        if cur.lastrowid:
            return cur.lastrowid
        return _find_appellation_key(conn, appellation_norm)
    except Exception:
        return None


def _ensure_wine(
    conn: sqlite3.Connection,
    wine_key: str,
    producer_norm: str,
    cuvee_name: str,
    cuvee_norm: str,
    appellation_name: str,
    appellation_norm: str,
    region: str,
    vintage: Optional[int],
    color: str,
) -> bool:
    if conn.execute("SELECT 1 FROM dim_wine WHERE wine_key = ?", (wine_key,)).fetchone():
        return True
    producer_row = conn.execute(
        "SELECT producer_key FROM dim_producer WHERE producer_norm = ? AND country_code = 'FR'",
        (producer_norm,),
    ).fetchone()
    if not producer_row:
        return False
    appellation_key = _ensure_appellation(conn, appellation_name, appellation_norm, region)
    if appellation_key is None:
        return False
    is_nv = 1 if vintage is None else 0
    try:
        conn.execute(
            """INSERT OR IGNORE INTO dim_wine
               (wine_key, producer_key, appellation_key, cuvee_name, cuvee_norm,
                color, vintage, is_non_vintage, bottle_ml, canonical_name)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 750, ?)""",
            (wine_key, producer_row[0], appellation_key, cuvee_name, cuvee_norm,
             color, vintage, is_nv, cuvee_name),
        )
        conn.commit()
        return True
    except Exception:
        return False


def _ensure_producer(conn: sqlite3.Connection, producer_norm: str, producer_name: str) -> bool:
    row = conn.execute(
        "SELECT producer_key FROM dim_producer WHERE producer_norm = ? AND country_code = 'FR'",
        (producer_norm,)
    ).fetchone()
    if row:
        return True
    try:
        conn.execute(
            """INSERT OR IGNORE INTO dim_producer
               (producer_name, producer_norm, country_code, allowed_appellations, aliases, status)
               VALUES (?, ?, 'FR', '[]', '[]', 'pending_review')""",
            (producer_name, producer_norm)
        )
        conn.commit()
        return True
    except Exception:
        return False


def _appellation_from_title(conn: sqlite3.Connection, title: str) -> tuple[str, str]:
    """Match the longest known French appellation in the wine title; falls back to Vin de France."""
    title_up = title.upper()
    rows = conn.execute(
        "SELECT appellation_name, appellation_norm FROM dim_appellation"
        " WHERE country_code = 'FR' ORDER BY length(appellation_name) DESC"
    ).fetchall()
    for name, norm in rows:
        if name.upper() in title_up:
            return name, norm
    return "Vin de France", "vin de france"


class CinocoScraper(BaseScraper):
    source_code = "cinoco"

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.batch_id: Optional[str] = None

    def run(self, limit: Optional[int] = None) -> ScrapeResult:
        if not HAS_DEPS:
            return ScrapeResult(error="Missing dependencies: httpx or selectolax not installed")

        source_row = self.conn.execute(
            "SELECT source_key FROM dim_source WHERE source_code = ?", (self.source_code,)
        ).fetchone()
        if not source_row:
            return ScrapeResult(error=f"source_code '{self.source_code}' not found in dim_source")
        SOURCE_KEY = source_row[0]

        batch_id = self.batch_id or f"cinoco-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        result = ScrapeResult(batch_id=batch_id)

        headers = {
            "User-Agent": _USER_AGENT,
            "Accept": "application/json",
            "Accept-Language": "fr-BE,fr;q=0.9,en;q=0.8",
        }

        page = 1
        total_fetched = 0

        # Cinoco is a Shopify store — use the products.json API for reliable structured data
        with httpx.Client(headers=headers, timeout=30, follow_redirects=True) as client:
            while True:
                url = f"{_PRODUCTS_API}?limit=250&page={page}"
                try:
                    resp = self._fetch(lambda u=url: client.get(u))
                    resp.raise_for_status()
                except Exception as e:
                    result.error = f"HTTP error on page {page}: {e}"
                    write_dlq(self.conn, SOURCE_KEY, batch_id, "auth_error", str(e), {"url": url})
                    result.rows_dlq += 1
                    break

                try:
                    data = resp.json()
                    products_data = data.get("products") or []
                except Exception:
                    break

                if not products_data:
                    break

                _logger.info("page=%d products=%d", page, len(products_data))
                page_hash = hashlib.sha256(resp.content).hexdigest()
                cached = self.conn.execute(
                    "SELECT last_hash FROM ops_content_hashes WHERE url = ?", (url,)
                ).fetchone()
                if cached and cached[0] == page_hash:
                    result.rows_skipped_unchanged += len(products_data)
                    if limit is not None and total_fetched + len(products_data) >= limit:
                        break
                    page += 1
                    time.sleep(0.5)
                    continue

                self.conn.execute(
                    """INSERT OR REPLACE INTO ops_content_hashes
                       (url, source_key, last_hash, last_fetched_at, last_changed_at, fetch_count)
                       VALUES (?, ?, ?, ?, ?,
                         COALESCE((SELECT fetch_count + 1 FROM ops_content_hashes WHERE url = ?), 1))""",
                    (url, SOURCE_KEY, page_hash, int(time.time()), int(time.time()), url),
                )
                self.conn.commit()

                for p in products_data:
                    if limit is not None and total_fetched >= limit:
                        break

                    raw_name = (p.get("title") or "").strip()
                    variants = p.get("variants") or []
                    price_eur = None
                    if variants:
                        try:
                            price_eur = float(variants[0].get("price") or 0) or None
                        except (TypeError, ValueError):
                            pass

                    if not raw_name or price_eur is None:
                        write_dlq(self.conn, SOURCE_KEY, batch_id, "parse_error",
                                  f"Missing name or price: name={raw_name!r}", {"url": url})
                        result.rows_dlq += 1
                        continue

                    vintage = _extract_vintage(raw_name)
                    product_type = (p.get("product_type") or "").lower()
                    color = _map_color(product_type + " " + raw_name.lower())
                    handle = p.get("handle") or ""
                    source_url = f"{_BASE}/products/{handle}" if handle else _BASE
                    vendor_raw = (p.get("vendor") or "").strip()
                    if not vendor_raw or norm_text(vendor_raw) in ("cinoco", ""):
                        parts = raw_name.split(" - ", 1)
                        producer_name = parts[0].strip() if len(parts) == 2 else raw_name
                    else:
                        producer_name = vendor_raw

                    appellation, appellation_norm = _appellation_from_title(self.conn, raw_name)
                    region = appellation
                    producer_norm = normalize_producer(producer_name)
                    cuvee_norm = normalize_cuvee(raw_name, strip_words=[producer_norm, appellation_norm])
                    wine_key = compute_wine_key(producer_norm, cuvee_norm, vintage, appellation_norm)

                    if not producer_norm:
                        write_dlq(self.conn, SOURCE_KEY, batch_id, "parse_error",
                                  f"Empty producer_norm for: {raw_name!r}", {"raw_name": raw_name})
                        result.rows_dlq += 1
                        continue
                    # cuvee_norm can be empty for single-estate wines (château IS the wine)

                    _ensure_producer(self.conn, producer_norm, producer_name or raw_name)

                    if not _ensure_wine(self.conn, wine_key, producer_norm, raw_name, cuvee_norm,
                                        appellation, appellation_norm, region, vintage, color):
                        write_dlq(self.conn, SOURCE_KEY, batch_id, "unresolved_dim",
                                  "Could not resolve producer or appellation",
                                  {"raw_name": raw_name, "wine_key": wine_key})
                        result.rows_dlq += 1
                        continue

                    card_hash = hashlib.sha256(
                        json.dumps({"name": raw_name, "price": price_eur}, sort_keys=True).encode()
                    ).hexdigest()

                    try:
                        inserted = insert_staging_candidate(
                            self.conn,
                            wine_key=wine_key, source_key=SOURCE_KEY, retailer="cinoco",
                            recorded_at=int(time.time()), amount_local=price_eur,
                            amount_eur=price_eur, source_url=source_url,
                            content_hash=card_hash, batch_id=batch_id,
                        )
                        if inserted:
                            result.rows_inserted += 1
                            _logger.info("inserted wine_key=%s price=%.2f name=%s", wine_key, price_eur, raw_name)
                        else:
                            result.rows_skipped_unchanged += 1
                    except Exception as e:
                        write_dlq(self.conn, SOURCE_KEY, batch_id, "validation_error", str(e),
                                  {"wine_key": wine_key, "price_eur": price_eur})
                        result.rows_dlq += 1
                        _logger.warning("dlq validation_error wine_key=%s err=%s", wine_key, e)

                    total_fetched += 1
                    result.rows_fetched += 1

                if limit is not None and total_fetched >= limit:
                    break

                page += 1
                time.sleep(1.0)

        return result
