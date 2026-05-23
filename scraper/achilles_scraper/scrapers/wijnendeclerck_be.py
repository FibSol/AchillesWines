# REGISTER_IN_CLI = True
"""
Wijnendeclerck.be scraper — French wine price ingestion via KMO Manager REST API.

Wijnen De Clerck is a Belgian wine retailer with a web shop at
webshop.wijnendeclerck.be, powered by the kmo-software / ICM Labarque
Angular platform.  The front-end is a pure Angular SPA with no server-rendered
product data; the back-end REST API is publicly accessible at
https://kmo-manager.azurewebsites.net/.

Discovery (2026-05-23):
  - GET /products/{id}  — single product JSON, no auth required
  - productGroupIds field identifies category: 11=wijn, 10=bubbels, etc.
  - productOptionItems list contains Kleur (colour), Jaartal (vintage),
    Streek (region), Land (country), Appellatie (appellation)
  - salePrice = excl. VAT; salePriceWithTaxesAndVat = consumer price (21% BTW)
  - ID space: valid products from ~800 to ~5200, sparse below 800

Strategy: enumerate IDs 1–5500 concurrently (asyncio + httpx, 20 workers).
Filter: productGroupId=11 (wine) AND Land=Frankrijk.  ~2–3 minutes total.
"""
import asyncio
import hashlib
import json
import logging
import re
import time
import uuid
import sqlite3
from datetime import datetime
from typing import Optional

try:
    import httpx
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

_KMO_BASE = "https://kmo-manager.azurewebsites.net"
_WEBSHOP_BASE = "https://webshop.wijnendeclerck.be"
_PRODUCT_URL = f"{_KMO_BASE}/products/{{product_id}}"

# ID range to scan.
# Products below 800 are non-wine items (delivery fees etc.) — all 404 tested.
# Upper bound ~5200 discovered empirically; use 5500 for safety.
_ID_MIN = 800
_ID_MAX = 5500
_CONCURRENCY = 20          # concurrent async requests
_RETRY_TIMEOUT = 10        # seconds per request

# Category ID for wine on this platform
_WINE_CATEGORY_ID = 11
_WINE_COUNTRY = "frankrijk"   # normalised Dutch name for France

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Colour mapping (Dutch KMO field values → canonical)
# ---------------------------------------------------------------------------
_COLOR_MAP: dict[str, str] = {
    "rood": "red",
    "rouge": "red",
    "wit": "white",
    "blanc": "white",
    "rosé": "rosé",
    "rose": "rosé",
    "schuimwijn": "sparkling",
    "mousseux": "sparkling",
    "champagne": "sparkling",
    "pétillant": "sparkling",
    "zoet": "sweet",
    "liquoreux": "sweet",
    "versterkt": "fortified",
    "fortifié": "fortified",
    "oranje": "orange",
    "orange": "orange",
}


def _map_color(text: str) -> str:
    t = (text or "").lower().strip()
    for k, v in _COLOR_MAP.items():
        if k in t:
            return v
    return "red"


# ---------------------------------------------------------------------------
# Appellation helpers (reused from other scrapers)
# ---------------------------------------------------------------------------
def _clean_appellation(raw: str) -> str:
    """Strip suffix designators like AOP / AOC / AC / IGP from appellation name."""
    return re.sub(r"\s+(?:AOP|AOC|AC|IGP|PDO|DO)\s*$", "", raw.strip(), flags=re.IGNORECASE).strip()


def _find_appellation_key(conn: sqlite3.Connection, appellation_norm: str) -> Optional[int]:
    if not appellation_norm:
        return None
    row = conn.execute(
        "SELECT appellation_key FROM dim_appellation WHERE appellation_norm = ?",
        (appellation_norm,),
    ).fetchone()
    return row[0] if row else None


def _appellation_from_name(conn: sqlite3.Connection, raw_appellation: str) -> tuple[str, str]:
    """
    Try to match the appellation provided by KMO (stripped of AOP/AOC).
    Falls back to longest-match on the full wine title, then 'Vin de France'.
    """
    cleaned = _clean_appellation(raw_appellation)
    if cleaned:
        cleaned_norm = norm_text(cleaned)
        key = _find_appellation_key(conn, cleaned_norm)
        if key:
            return cleaned, cleaned_norm
        # Fuzzy: try just the first word(s)
        parts = cleaned.split()
        for n in range(len(parts), 0, -1):
            candidate = " ".join(parts[:n])
            cand_norm = norm_text(candidate)
            key = _find_appellation_key(conn, cand_norm)
            if key:
                return candidate, cand_norm
    return "Vin de France", "vin de france"


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


# ---------------------------------------------------------------------------
# Async product fetcher
# ---------------------------------------------------------------------------
async def _fetch_products(
    id_min: int,
    id_max: int,
    concurrency: int,
    limit: Optional[int] = None,
) -> list[dict]:
    """
    Async-fetch all product IDs in [id_min, id_max].
    Returns list of product dicts for products that returned HTTP 200.
    """
    semaphore = asyncio.Semaphore(concurrency)
    results: list[dict] = []
    ids = list(range(id_min, id_max + 1))
    if limit is not None:
        # For limited runs (testing), cap the ID scan to avoid scanning 5000 IDs.
        # Density: ~83 % hit rate, ~35 % French wine → need ~limit / 0.29 ≈ limit × 4 IDs.
        # Add generous headroom; minimum 400 IDs so we always get a few results.
        scan_cap = max(limit * 10, 400)
        ids = ids[:scan_cap]

    headers = {
        "User-Agent": _USER_AGENT,
        "Accept": "application/json",
        "Origin": _WEBSHOP_BASE,
        "Referer": f"{_WEBSHOP_BASE}/",
    }

    async def fetch_one(client: "httpx.AsyncClient", product_id: int) -> Optional[dict]:
        async with semaphore:
            try:
                resp = await client.get(
                    _PRODUCT_URL.format(product_id=product_id),
                    timeout=_RETRY_TIMEOUT,
                )
                if resp.status_code == 200:
                    return resp.json()
                return None
            except Exception:
                return None

    async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
        tasks = [fetch_one(client, pid) for pid in ids]
        for coro in asyncio.as_completed(tasks):
            result = await coro
            if result is not None:
                results.append(result)

    return results


def _extract_option(product: dict, type_name: str) -> Optional[str]:
    """Return the first productOptionItem value for a given type name (Dutch)."""
    for item in product.get("productOptionItems", []):
        if item.get("productOptionTypeLocalizedDescription", "").lower() == type_name.lower():
            return item.get("localizedDescription", "")
    return None


def _extract_options(product: dict, type_name: str) -> list[str]:
    """Return ALL productOptionItem values for a given type name."""
    return [
        item.get("localizedDescription", "")
        for item in product.get("productOptionItems", [])
        if item.get("productOptionTypeLocalizedDescription", "").lower() == type_name.lower()
    ]


# ---------------------------------------------------------------------------
# Main scraper class
# ---------------------------------------------------------------------------
class WijnendeclerckBeScraper(BaseScraper):
    source_code = "wijnendeclerck_be"

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.batch_id: Optional[str] = None

    def run(self, limit: Optional[int] = None) -> ScrapeResult:
        if not HAS_DEPS:
            return ScrapeResult(error="Missing dependency: httpx not installed")

        source_row = self.conn.execute(
            "SELECT source_key FROM dim_source WHERE source_code = ?", (self.source_code,)
        ).fetchone()
        if not source_row:
            return ScrapeResult(error=f"source_code '{self.source_code}' not found in dim_source")
        SOURCE_KEY = source_row[0]

        batch_id = (
            self.batch_id
            or f"wijnendeclerck_be-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        )
        result = ScrapeResult(batch_id=batch_id)

        _logger.info(
            "wijnendeclerck_be: scanning product IDs %d–%d (concurrency=%d)",
            _ID_MIN, _ID_MAX, _CONCURRENCY,
        )

        # ------------------------------------------------------------------ #
        # 1. Async-fetch all product records                                  #
        # ------------------------------------------------------------------ #
        try:
            all_products = asyncio.run(
                _fetch_products(_ID_MIN, _ID_MAX, _CONCURRENCY, limit)
            )
        except Exception as exc:
            result.error = f"Async fetch failed: {exc}"
            return result

        _logger.info("wijnendeclerck_be: fetched %d valid product records", len(all_products))

        # ------------------------------------------------------------------ #
        # 2. Filter: wine category (productGroupId=11) + French (Land=França) #
        # ------------------------------------------------------------------ #
        wine_products = []
        for prod in all_products:
            group_ids = prod.get("productGroupIds") or []
            if _WINE_CATEGORY_ID not in group_ids:
                continue
            if not prod.get("isWebshop", False):
                continue
            land = (_extract_option(prod, "Land") or "").lower().strip()
            if land != _WINE_COUNTRY:
                continue
            wine_products.append(prod)

        _logger.info("wijnendeclerck_be: %d French wine products after filtering", len(wine_products))

        # ------------------------------------------------------------------ #
        # 3. Process each French wine product                                 #
        # ------------------------------------------------------------------ #
        now = int(time.time())
        processed = 0

        for prod in wine_products:
            if limit is not None and processed >= limit:
                break

            product_id: int = prod["id"]
            result.rows_fetched += 1

            # --- Extract fields ------------------------------------------- #
            price_eur: Optional[float] = prod.get("salePriceWithTaxesAndVat")
            if not price_eur or price_eur <= 0:
                write_dlq(
                    self.conn, SOURCE_KEY, batch_id,
                    "parse_error", f"No valid price for product id={product_id}",
                    {"product_id": product_id, "price": price_eur},
                )
                result.rows_dlq += 1
                continue

            # Producer
            producer_name: str = prod.get("localizedBrandName") or prod.get("localizedDescription") or ""
            producer_norm = normalize_producer(producer_name)
            if not producer_norm:
                write_dlq(
                    self.conn, SOURCE_KEY, batch_id,
                    "parse_error", f"Empty producer_norm for product id={product_id}",
                    {"product_id": product_id, "producer_name": producer_name},
                )
                result.rows_dlq += 1
                continue

            # Cuvée name (full wine name)
            cuvee_name: str = prod.get("localizedDescription") or producer_name

            # Vintage (Jaartal)
            jaar_raw = _extract_option(prod, "Jaartal") or ""
            vintage: Optional[int] = None
            if jaar_raw:
                m = re.search(r"\b(19[5-9]\d|20[0-3]\d)\b", jaar_raw)
                if m:
                    vintage = int(m.group(1))

            # Colour (Kleur)
            kleur_raw = _extract_option(prod, "Kleur") or ""
            color = _map_color(kleur_raw)

            # Appellation (Appellatie) and region (Streek)
            appellation_raw = _extract_option(prod, "Appellatie") or ""
            streek_raw = _extract_option(prod, "Streek") or ""
            appellation_name, appellation_norm = _appellation_from_name(
                self.conn, appellation_raw or streek_raw
            )
            region = streek_raw or appellation_name

            # Cuvée normalisation (strip producer and appellation noise)
            cuvee_norm = normalize_cuvee(
                cuvee_name,
                strip_words=[producer_norm, appellation_norm],
            )

            wine_key = compute_wine_key(producer_norm, cuvee_norm, vintage, appellation_norm)

            # Product URL
            hyperlink = prod.get("hyperlink") or f"/product/{product_id}"
            product_url = (
                hyperlink if hyperlink.startswith("http")
                else f"{_WEBSHOP_BASE}{hyperlink}"
            )

            # Content hash: (product_id, price_incl_vat)
            content_hash = hashlib.sha256(
                json.dumps({"id": product_id, "price": price_eur}, sort_keys=True).encode()
            ).hexdigest()

            # --- Ensure producer ------------------------------------------ #
            _ensure_producer(self.conn, producer_norm, producer_name)

            # --- Ensure wine dim ------------------------------------------ #
            if not _ensure_wine(
                self.conn, wine_key, producer_norm, cuvee_name, cuvee_norm,
                appellation_name, appellation_norm, region, vintage, color,
            ):
                write_dlq(
                    self.conn, SOURCE_KEY, batch_id,
                    "unresolved_dim",
                    "Could not resolve producer or appellation for dim_wine",
                    {
                        "product_id": product_id,
                        "producer_norm": producer_norm,
                        "appellation_norm": appellation_norm,
                        "wine_key": wine_key,
                    },
                )
                result.rows_dlq += 1
                continue

            # --- Insert staging candidate ---------------------------------- #
            try:
                inserted = insert_staging_candidate(
                    self.conn,
                    wine_key=wine_key,
                    source_key=SOURCE_KEY,
                    retailer="wijnendeclerck_be",
                    recorded_at=now,
                    amount_local=price_eur,
                    amount_eur=price_eur,
                    source_url=product_url,
                    content_hash=content_hash,
                    batch_id=batch_id,
                )
                if inserted:
                    result.rows_inserted += 1
                    _logger.debug(
                        "inserted wine_key=%s price=%.2f name=%s",
                        wine_key, price_eur, cuvee_name,
                    )
                else:
                    result.rows_skipped_unchanged += 1
            except Exception as exc:
                write_dlq(
                    self.conn, SOURCE_KEY, batch_id,
                    "validation_error", str(exc),
                    {"wine_key": wine_key, "price_eur": price_eur, "product_url": product_url},
                )
                result.rows_dlq += 1

            processed += 1

        return result
