# REGISTER_IN_CLI = True
"""
BelgiumWineWatchers.com scraper — retail price ingestion via HTML catalog.

Belgium Wine Watchers is a niche Belgian wine marketplace/community with
a shop section. Public HTML, no auth required.
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
from ..dlq import write_dlq

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_BASE = "https://www.belgiumwinewatchers.com"
# Try multiple possible shop paths
_CATALOGUE_PATHS = ["/shop", "/wines", "/vins", "/wijnen", "/wine", "/products", "/"]

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
    "rood": "red",
    "blanc": "white",
    "wit": "white",
    "rosé": "rosé",
    "rose": "rosé",
    "champagne": "sparkling",
    "mousseux": "sparkling",
    "schuimwijn": "sparkling",
    "liquoreux": "sweet",
    "zoet": "sweet",
    "fortifié": "fortified",
    "versterkt": "fortified",
    "orange": "orange",
    "oranje": "orange",
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


def _find_catalogue_url(client: "httpx.Client", base: str, paths: list) -> Optional[str]:
    """Try each path and return the first that returns HTTP 200 with substantial content."""
    for path in paths:
        url = f"{base}{path}"
        try:
            resp = client.get(url, timeout=15)
            if resp.status_code == 200 and len(resp.text) > 1000:
                return url
        except Exception:
            continue
    return None


class BelgiumWineWatchersScraper(BaseScraper):
    source_code = "belgiumwinewatchers"

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

        batch_id = self.batch_id or f"belgiumwinewatchers-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        result = ScrapeResult(batch_id=batch_id)

        headers = {
            "User-Agent": _USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,*/*",
            "Accept-Language": "fr-BE,fr;q=0.9,nl;q=0.8,en;q=0.7",
        }

        page = 1
        total_fetched = 0

        with httpx.Client(headers=headers, timeout=30, follow_redirects=True) as client:
            def _get(url: str):
                resp = self._fetch(lambda: client.get(url))
                resp.raise_for_status()
                return resp

            catalogue_base = _find_catalogue_url(client, _BASE, _CATALOGUE_PATHS)
            if not catalogue_base:
                result.error = f"Could not find a working catalogue URL at {_BASE}"
                return result

            while True:
                url = f"{catalogue_base}?page={page}" if page > 1 else catalogue_base
                try:
                    resp = _get(url)
                except Exception as e:
                    result.error = f"HTTP error on page {page}: {e}"
                    write_dlq(self.conn, SOURCE_KEY, batch_id, "auth_error", str(e), {"url": url})
                    result.rows_dlq += 1
                    break

                if resp.status_code == 404:
                    break

                if resp.status_code in (403, 429):
                    msg = f"Blocked by belgiumwinewatchers.com: HTTP {resp.status_code} on {url}"
                    write_dlq(self.conn, SOURCE_KEY, batch_id, "auth_error", msg, {"url": url, "status": resp.status_code})
                    result.rows_dlq += 1
                    result.error = msg
                    break

                if resp.status_code != 200:
                    result.error = f"Unexpected HTTP {resp.status_code} on {url}"
                    break

                page_hash = hashlib.sha256(resp.content).hexdigest()
                cached = self.conn.execute(
                    "SELECT last_hash FROM ops_content_hashes WHERE url = ?", (url,)
                ).fetchone()

                tree = HTMLParser(resp.text)

                product_cards = (
                    tree.css(".product-item")
                    or tree.css(".product-card")
                    or tree.css("ul.products li.product")
                    or tree.css(".wine-item")
                    or tree.css(".wine-listing")
                    or tree.css(".product")
                    or tree.css("article")
                )

                if not product_cards:
                    break

                if cached and cached[0] == page_hash:
                    result.rows_skipped_unchanged += len(product_cards)
                    if limit is not None and total_fetched + len(product_cards) >= limit:
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

                for card in product_cards:
                    if limit is not None and total_fetched >= limit:
                        break

                    name_node = (
                        card.css_first(".product-title")
                        or card.css_first(".product-name")
                        or card.css_first("h2")
                        or card.css_first("h3")
                        or card.css_first(".name")
                        or card.css_first(".title")
                    )
                    raw_name = name_node.text(strip=True) if name_node else ""
                    if not raw_name:
                        result.rows_dlq += 1
                        continue

                    price_node = (
                        card.css_first(".price")
                        or card.css_first(".product-price")
                        or card.css_first("[class*='price']")
                    )
                    price_text = price_node.text(strip=True) if price_node else ""
                    price_eur = _extract_price(price_text)
                    if price_eur is None:
                        write_dlq(
                            self.conn, SOURCE_KEY, batch_id,
                            "parse_error", f"No price found for: {raw_name!r}",
                            {"raw_name": raw_name, "url": url},
                        )
                        result.rows_dlq += 1
                        continue

                    vintage = _extract_vintage(raw_name)

                    link_node = card.css_first("a[href]")
                    product_url = url
                    if link_node:
                        href = link_node.attributes.get("href", "")
                        product_url = href if href.startswith("http") else f"{_BASE}{href}"

                    color_text = card.text(strip=True)
                    color = _map_color(color_text)

                    card_hash = hashlib.sha256(
                        json.dumps({"name": raw_name, "price": price_eur, "url": product_url}, sort_keys=True).encode()
                    ).hexdigest()

                    producer_norm = normalize_producer(raw_name)
                    cuvee_norm = normalize_cuvee(raw_name)

                    if not producer_norm or not cuvee_norm:
                        write_dlq(
                            self.conn, SOURCE_KEY, batch_id,
                            "parse_error", f"Empty producer_norm or cuvee_norm for: {raw_name!r}",
                            {"raw_name": raw_name, "url": product_url},
                        )
                        result.rows_dlq += 1
                        continue

                    appellation_norm = ""
                    wine_key = compute_wine_key(producer_norm, cuvee_norm, vintage, appellation_norm)
                    _ensure_producer(self.conn, producer_norm, raw_name)

                    if not _ensure_wine(
                        self.conn, wine_key, producer_norm, raw_name,
                        cuvee_norm, "", appellation_norm, "", vintage, color,
                    ):
                        write_dlq(
                            self.conn, SOURCE_KEY, batch_id,
                            "unresolved_dim", "Could not resolve producer or appellation for dim_wine",
                            {"raw_name": raw_name, "wine_key": wine_key},
                        )
                        result.rows_dlq += 1
                        continue

                    try:
                        self.conn.execute(
                            """INSERT OR IGNORE INTO staging_price_candidates
                               (wine_key, source_key, retailer, recorded_at, currency_code,
                                amount_local, amount_eur, source_url, content_hash, batch_id, needs_review)
                               VALUES (?, ?, 'belgiumwinewatchers', ?, 'EUR', ?, ?, ?, ?, ?, 1)""",
                            (wine_key, SOURCE_KEY, int(time.time()), price_eur, price_eur, product_url, card_hash, batch_id),
                        )
                        self.conn.commit()
                        result.rows_inserted += 1
                    except Exception as e:
                        write_dlq(
                            self.conn, SOURCE_KEY, batch_id,
                            "validation_error", str(e),
                            {"wine_key": wine_key, "price_eur": price_eur, "url": product_url},
                        )
                        result.rows_dlq += 1

                    total_fetched += 1
                    result.rows_fetched += 1

                if limit is not None and total_fetched >= limit:
                    break

                page += 1
                time.sleep(1.0)

        return result
