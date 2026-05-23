"""
Millesima.fr scraper — retail price ingestion via Next.js internal JSON API.

Millesima migrated to Next.js; product data lives in /_next/data/{buildId}/
tous-nos-vins.html.json. The buildId is fetched once per run from the homepage
__NEXT_DATA__ block. Each page returns ~44 products; total catalogue ~10 900.
"""
import hashlib
import json
import logging
import os
import re
import time
import uuid
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
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

SOURCE_KEY = 2  # millesima in dim_source

_BASE = "https://www.millesima.fr"
_CATALOGUE_SLUG = "tous-nos-vins.html"

_logger = logging.getLogger(__name__)


def _build_id_cache_path() -> Path:
    """Return the path to the buildId cache file, honouring ACHILLES_DATA_DIR."""
    data_dir = os.environ.get("ACHILLES_DATA_DIR", "data")
    return Path(data_dir) / "millesima_build_id.json"


def _load_cached_build_id() -> Optional[tuple[str, str]]:
    """Return (build_id, cached_at) from the cache file, or None if absent/invalid."""
    cache_path = _build_id_cache_path()
    try:
        with cache_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        build_id = data.get("build_id")
        cached_at = data.get("cached_at", "")
        if build_id:
            return build_id, cached_at
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return None


def _save_cached_build_id(build_id: str) -> None:
    """Persist *build_id* to the JSON sidecar file."""
    cache_path = _build_id_cache_path()
    cached_at = datetime.now(timezone.utc).isoformat()
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with cache_path.open("w", encoding="utf-8") as fh:
            json.dump({"build_id": build_id, "cached_at": cached_at}, fh)
    except OSError as exc:
        _logger.warning("Could not write buildId cache to %s: %s", cache_path, exc)


def _fetch_build_id(client: "httpx.Client", fetch_fn=None) -> Optional[str]:
    """Fetch the Next.js buildId from the homepage __NEXT_DATA__ block.

    ``fetch_fn`` is an optional callable(url) → Response injected by the
    scraper so that HTTP goes through the retry wrapper.  Falls back to a
    plain ``client.get`` when not provided (used by unit tests / standalone
    callers).

    On success the buildId is persisted to ``data/millesima_build_id.json``
    (path controlled by ``ACHILLES_DATA_DIR`` env var).

    On failure (after retries are exhausted by the caller), if a cached value
    exists it is returned with a warning.  If no cache exists the original
    exception is re-raised.
    """
    try:
        url = f"{_BASE}/"
        r = fetch_fn(url) if fetch_fn is not None else client.get(url, timeout=15)
        tree = HTMLParser(r.text)
        nd = tree.css_first("#__NEXT_DATA__")
        build_id: Optional[str] = None
        if nd:
            build_id = json.loads(nd.text()).get("buildId")
        if build_id:
            _save_cached_build_id(build_id)
        return build_id
    except Exception as exc:
        cached = _load_cached_build_id()
        if cached is not None:
            build_id_cached, cached_at = cached
            _logger.warning(
                "homepage unreachable, using cached buildId from %s", cached_at
            )
            return build_id_cached
        raise


def _extract_vintage(text: str) -> Optional[int]:
    m = re.search(r"\b(199\d|20[0-3]\d)\b", text or "")
    return int(m.group(1)) if m else None


def _attr_value(attrs: dict, key: str) -> str:
    """Extract the string value from an attribute dict or return ''."""
    v = attrs.get(key)
    if v is None:
        return ""
    if isinstance(v, dict):
        return str(v.get("value") or "")
    if isinstance(v, list) and v:
        return str(v[0].get("value") or "")
    return str(v)


_COLOR_MAP = {
    "rouge": "red",
    "blanc": "white",
    "rosé": "rosé",
    "rose": "rosé",
    "champagne": "sparkling",
    "effervescent": "sparkling",
    "pétillant": "sparkling",
    "petillant": "sparkling",
    "liquoreux": "sweet",
    "moelleux": "sweet",
    "fortifié": "fortified",
    "fortifie": "fortified",
    "orange": "orange",
}


def _map_color(raw: str) -> str:
    return _COLOR_MAP.get(raw.lower().strip(), "red")


def _parse_product(p: dict) -> Optional[dict]:
    """
    Convert a Millesima JSON product dict to a normalised card dict.
    Returns None if essential fields are missing.
    """
    raw_name = (p.get("productName") or "").strip()
    if not raw_name:
        return None

    attrs = p.get("attributes") or {}

    # Price: prefer first item's offerPrice, then listPrice, then product minPrice
    price_eur: Optional[float] = None
    items = p.get("items") or []
    if items:
        item = items[0]
        price_eur = item.get("offerPrice") or item.get("listPrice")
    if price_eur is None:
        price_eur = p.get("minPrice")
    if price_eur is None:
        return None

    # Vintage: prefer attribute value dict, fall back to product name
    vintage_raw = _attr_value(attrs, "millesime")
    vintage = _extract_vintage(vintage_raw) or _extract_vintage(raw_name)

    appellation = _attr_value(attrs, "appellation").strip()
    region = _attr_value(attrs, "vignoble").strip() or _attr_value(attrs, "region").strip()
    color = _map_color(_attr_value(attrs, "couleur"))

    # seoKeyword already includes .html suffix on some products — strip to avoid double
    seo = (p.get("seoKeyword") or "").removesuffix(".html")
    source_url = f"{_BASE}/{seo}.html" if seo else _BASE

    return {
        "name": raw_name,
        "vintage": vintage,
        "price_eur": float(price_eur),
        "source_url": source_url,
        "appellation": appellation,
        "region": region,
        "color": color,
        "card_hash": hashlib.sha256(json.dumps(p, sort_keys=True).encode()).hexdigest(),
    }


def _find_appellation_key(conn: sqlite3.Connection, appellation_norm: str) -> Optional[int]:
    """Return appellation_key for a normalised appellation name, or None if not found."""
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
    """
    Return appellation_key, creating the row if it doesn't exist.
    Uses level='regional' and country_code='FR' for scraper-created rows.
    """
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
        # Race: someone else inserted — fetch it
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
    """
    Ensure dim_wine row exists. Returns True on success, False if required FK
    (producer or appellation) cannot be resolved.
    """
    # Fast path: already exists
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
            (
                wine_key,
                producer_row[0],
                appellation_key,
                cuvee_name,
                cuvee_norm,
                color,
                vintage,
                is_nv,
                cuvee_name,
            ),
        )
        conn.commit()
        return True
    except Exception:
        return False


def _appellation_from_title(conn: sqlite3.Connection, title: str) -> tuple[str, str]:
    """Match the longest known French appellation in the wine title.
    Falls back to ('Vin de France', 'vin de france') when nothing matches."""
    title_up = title.upper()
    rows = conn.execute(
        "SELECT appellation_name, appellation_norm FROM dim_appellation"
        " WHERE country_code = 'FR' ORDER BY length(appellation_name) DESC"
    ).fetchall()
    for name, norm in rows:
        if name.upper() in title_up:
            return name, norm
    return "Vin de France", "vin de france"


def _ensure_producer(conn: sqlite3.Connection, producer_norm: str, producer_name: str) -> bool:
    """
    Look up producer by producer_norm. If missing, insert as pending_review.
    Returns True if producer exists (active or pending), False on DB error.
    """
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


class MillesimaScraper(BaseScraper):
    source_code = "millesima"

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        # Optional: injected by JobRunner so logs/<batch_id>.log lines up with this run.
        self.batch_id: Optional[str] = None

    def run(self, limit: Optional[int] = None) -> ScrapeResult:
        if not HAS_DEPS:
            return ScrapeResult(error="Missing dependencies: httpx or selectolax not installed")

        batch_id = self.batch_id or f"millesima-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        result = ScrapeResult(batch_id=batch_id)

        headers = {
            "User-Agent": _USER_AGENT,
            "Accept": "application/json, text/html, */*",
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
        }

        page = 1
        total_fetched = 0

        with httpx.Client(headers=headers, timeout=30, follow_redirects=True) as client:
            # Wrap client.get so all HTTP calls go through the retry wrapper.
            def _get(url: str):
                resp = self._fetch(lambda: client.get(url))
                resp.raise_for_status()
                return resp

            build_id = _fetch_build_id(client, fetch_fn=_get)
            if not build_id:
                result.error = "Could not fetch Next.js buildId from millesima.fr homepage"
                return result

            while True:
                url = (
                    f"{_BASE}/_next/data/{build_id}/{_CATALOGUE_SLUG}.json"
                    f"?page={page}&slug[]={_CATALOGUE_SLUG}"
                )
                try:
                    resp = _get(url)
                except Exception as e:
                    result.error = f"HTTP error on page {page}: {e}"
                    write_dlq(self.conn, SOURCE_KEY, batch_id, "auth_error", str(e), {"url": url})
                    result.rows_dlq += 1
                    break

                if resp.status_code in (403, 429):
                    msg = f"Blocked by millesima.fr: HTTP {resp.status_code} on {url}"
                    write_dlq(self.conn, SOURCE_KEY, batch_id, "auth_error", msg, {"url": url, "status": resp.status_code})
                    result.rows_dlq += 1
                    result.error = msg
                    break

                if resp.status_code != 200:
                    result.error = f"Unexpected HTTP {resp.status_code} on {url}"
                    break

                try:
                    page_data = resp.json()
                except Exception:
                    result.error = f"Invalid JSON on page {page}"
                    break

                props = page_data.get("pageProps", {})
                products_raw = props.get("products", [])

                if not products_raw:
                    break  # end of catalogue

                page_hash = hashlib.sha256(resp.content).hexdigest()

                # Content-hash check: skip page if unchanged
                cached = self.conn.execute(
                    "SELECT last_hash FROM ops_content_hashes WHERE url = ?", (url,)
                ).fetchone()
                if cached and cached["last_hash"] == page_hash:
                    result.rows_skipped_unchanged += len(products_raw)
                    if limit is not None and total_fetched + len(products_raw) >= limit:
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

                for raw_product in products_raw:
                    if limit is not None and total_fetched >= limit:
                        break

                    card = _parse_product(raw_product)
                    if card is None:
                        write_dlq(
                            self.conn, SOURCE_KEY, batch_id,
                            "parse_error", "Missing name or price",
                            {"partnumber": raw_product.get("partnumber")},
                        )
                        result.rows_dlq += 1
                        continue

                    total_fetched += 1
                    result.rows_fetched += 1

                    raw_name = card["name"]
                    price_eur = card["price_eur"]
                    vintage = card["vintage"]
                    source_url = card["source_url"]
                    appellation = card["appellation"]
                    region = card["region"]
                    color = card["color"]
                    card_hash = card["card_hash"]

                    # Fall back to title-search when the API returns no appellation
                    if not appellation:
                        appellation, _ = _appellation_from_title(self.conn, raw_name)
                        if not region:
                            region = appellation
                    producer_norm = normalize_producer(raw_name)
                    appellation_norm = norm_text(appellation) if appellation else ""
                    cuvee_norm = normalize_cuvee(raw_name, strip_words=[producer_norm, appellation_norm])

                    if not producer_norm:
                        write_dlq(
                            self.conn, SOURCE_KEY, batch_id,
                            "parse_error", f"Empty producer_norm for: {raw_name!r}",
                            {"raw_name": raw_name, "url": source_url},
                        )
                        result.rows_dlq += 1
                        continue
                    # cuvee_norm can be empty for single-estate wines (e.g. "Château Pétrus 2010"
                    # where the château itself IS the wine — no separate cuvée name).

                    wine_key = compute_wine_key(producer_norm, cuvee_norm, vintage, appellation_norm)
                    _ensure_producer(self.conn, producer_norm, raw_name)

                    if not _ensure_wine(
                        self.conn, wine_key, producer_norm, raw_name,
                        cuvee_norm, appellation, appellation_norm, region, vintage, color,
                    ):
                        write_dlq(
                            self.conn, SOURCE_KEY, batch_id,
                            "unresolved_dim", "Could not resolve producer or appellation for dim_wine",
                            {"raw_name": raw_name, "appellation": appellation, "wine_key": wine_key},
                        )
                        result.rows_dlq += 1
                        continue

                    try:
                        self.conn.execute(
                            """INSERT OR IGNORE INTO staging_price_candidates
                               (wine_key, source_key, retailer, recorded_at, currency_code,
                                amount_local, amount_eur, source_url, content_hash, batch_id, needs_review)
                               VALUES (?, ?, 'millesima', ?, 'EUR', ?, ?, ?, ?, ?, 1)""",
                            (wine_key, SOURCE_KEY, int(time.time()), price_eur, price_eur, source_url, card_hash, batch_id),
                        )
                        self.conn.commit()
                        result.rows_inserted += 1
                    except Exception as e:
                        write_dlq(
                            self.conn, SOURCE_KEY, batch_id,
                            "validation_error", str(e),
                            {"wine_key": wine_key, "price_eur": price_eur, "url": source_url},
                        )
                        result.rows_dlq += 1

                if limit is not None and total_fetched >= limit:
                    break

                page += 1
                time.sleep(1.0)

        return result
