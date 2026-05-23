# REGISTER_IN_CLI = True
"""
vinsbrunin.com scraper — WiziShop retail price ingestion.

Vins Brunin-Guillier runs on the WiziShop platform (not WooCommerce).
Products are organised by wine-region category (no single catalog URL).
Each category uses directory-style pagination: /category/, /category/2, ...
Product titles follow the format: "Appellation - Cuvée - Producer - Vintage"
"""
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

_BASE = "https://www.vinsbrunin.com"

# French wine category slugs + their canonical region name for dim_appellation inserts.
# Skipping international categories (italie-5, espagnol, …) as dim_appellation is France-only.
_WINE_CATEGORIES: list[tuple[str, str]] = [
    ("bordeaux",   "Bordeaux"),
    ("bourgogne",  "Bourgogne"),
    ("loire",      "Loire"),
    ("rhone",      "Rhône"),
    ("alsace",     "Alsace"),
    ("languedoc",  "Languedoc"),
    ("roussillon", "Roussillon"),
    ("provence",   "Provence"),
    ("corse",      "Corse"),
    ("sud-ouest",  "Sud-Ouest"),
    ("beaujolais", "Beaujolais"),
    ("savoie",     "Savoie"),
    ("jura",       "Jura"),
    ("champagnes", "Champagne"),
    ("nos-bulles", "Effervescent"),
]

_PRICE_RE    = re.compile(r"(?<!\d)(\d{1,4}[,\.]\d{2})\s*€")
_YEAR_RE     = re.compile(r"\b(199\d|20[0-3]\d)\b")
_BOTTLE_RE   = re.compile(r"^(\d[\d,\.]*\s*(?:cl|ml|L|litre|magnum|jeroboam))", re.IGNORECASE)
# Known leading non-producer tags to strip from the title before parsing
_STRIP_PREFIXES = re.compile(
    r"^(Bio|Biologique|Biodynamique|Nature|Natural|Vegan|Demeter|"
    r"Agriculture Biologique|AB|HVE|Sans Soufre)\s*[-–]\s*",
    re.IGNORECASE,
)

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_vintage(text: str) -> Optional[int]:
    m = _YEAR_RE.search(text or "")
    return int(m.group(1)) if m else None


def _parse_price(raw: str) -> Optional[float]:
    m = _PRICE_RE.search(raw or "")
    if not m:
        return None
    cleaned = m.group(1).replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _color_from_title(title: str, category_slug: str) -> str:
    t = (title + " " + category_slug).lower()
    if any(k in t for k in ("champagne", "crémant", "cremant", "effervescent",
                             "mousseux", "pétillant", "petillant", "nos-bulles")):
        return "sparkling"
    # "rosé" is unambiguous; avoid matching "rose" inside proper names like "Gruaud-Larose"
    if "rosé" in t or " rose " in t:
        return "rosé"
    if any(k in t for k in ("blanc", "chardonnay", "riesling", "pinot blanc",
                             "gewurztraminer", "sauvignon", "viognier", "roussanne",
                             "marsanne", "chenin", "muscat", "aligoté", "aligote",
                             "sylvaner", "bourgogne blanc", "chablis", "macon blanc",
                             "pouilly")):
        return "white"
    return "red"


def _parse_wine_title(title: str) -> dict:
    """
    Parse WiziShop title format: "Appellation [- Cuvée] - Producer - Vintage"
    Vintage is the rightmost part matching a year.  Producer is the part
    immediately to its left.  Anything before producer is appellation + cuvée.
    """
    parts = [p.strip() for p in title.split(" - ") if p.strip()]
    vintage: Optional[int] = None

    # Strip trailing vintage
    if parts and _YEAR_RE.fullmatch(parts[-1].strip()):
        vintage = int(parts.pop())
    elif parts and _YEAR_RE.search(parts[-1]):
        vintage = _extract_vintage(parts[-1])
        parts[-1] = _YEAR_RE.sub("", parts[-1]).strip(" ,")
        if not parts[-1]:
            parts.pop()

    if not parts:
        return {}

    producer = parts[-1]
    cuvee = " ".join(parts[1:-1]) if len(parts) >= 3 else ""
    appellation_hint = parts[0] if parts else ""

    return {
        "producer":         producer,
        "cuvee":            cuvee,
        "vintage":          vintage,
        "appellation_hint": appellation_hint,
    }


def _appellation_from_title(conn: sqlite3.Connection, title: str) -> tuple[str, str]:
    """Longest-match lookup against dim_appellation.  Falls back to Vin de France."""
    title_up = title.upper()
    rows = conn.execute(
        "SELECT appellation_name, appellation_norm FROM dim_appellation"
        " WHERE country_code = 'FR' ORDER BY length(appellation_name) DESC"
    ).fetchall()
    for name, anorm in rows:
        if name.upper() in title_up:
            return name, anorm
    return "Vin de France", "vin de france"


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
        return cur.lastrowid or _find_appellation_key(conn, appellation_norm)
    except Exception:
        return None


def _ensure_producer(conn: sqlite3.Connection, producer_norm: str, producer_name: str) -> bool:
    if conn.execute(
        "SELECT 1 FROM dim_producer WHERE producer_norm = ? AND country_code = 'FR'",
        (producer_norm,),
    ).fetchone():
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
    try:
        conn.execute(
            """INSERT OR IGNORE INTO dim_wine
               (wine_key, producer_key, appellation_key, cuvee_name, cuvee_norm,
                color, vintage, is_non_vintage, bottle_ml, canonical_name)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 750, ?)""",
            (wine_key, producer_row[0], appellation_key, cuvee_name, cuvee_norm,
             color, vintage, 1 if vintage is None else 0, cuvee_name),
        )
        conn.commit()
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Product-card extraction from WiziShop HTML
# ---------------------------------------------------------------------------

def _parse_cards(tree: "HTMLParser") -> list[dict]:
    """
    Extract product cards from a WiziShop category listing page.

    WiziShop themes vary, but the common invariant is:
      - Product images have the full wine title in their alt attribute.
      - The price is in a nearby <strong> element.
      - Product links point to paths ending in .html.

    We find every <strong> containing a price, then walk up the DOM (up to
    4 levels) to find a sibling/ancestor that also contains an img[alt]
    and an a[href$='.html'].
    """
    cards: list[dict] = []
    seen_urls: set[str] = set()

    for strong in tree.css("strong"):
        raw_price = strong.text(strip=True)
        if not _PRICE_RE.search(raw_price):
            continue

        # Walk up to find a container that has both a product link and an img
        container = strong.parent
        for _ in range(4):
            if container is None:
                break
            img = container.css_first("img[alt]")
            link = container.css_first("a[href]")
            if img and link:
                title = img.attrs.get("alt", "").strip()
                href  = link.attrs.get("href", "").strip()
                if " - " in title and href.endswith(".html") and not _BOTTLE_RE.match(title):
                    url = href if href.startswith("http") else f"{_BASE}{href}"
                    if url not in seen_urls:
                        seen_urls.add(url)
                        cards.append({"title": title, "raw_price": raw_price, "url": url})
                    break
            container = container.parent

    return cards


# ---------------------------------------------------------------------------
# Scraper class
# ---------------------------------------------------------------------------

class VinsBruninScraper(BaseScraper):
    source_code = "vinsbrunin"

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.batch_id: Optional[str] = None

    def run(self, limit: Optional[int] = None) -> ScrapeResult:
        if not HAS_DEPS:
            return ScrapeResult(error="Missing dependencies: httpx or selectolax not installed")

        batch_id = (
            self.batch_id
            or f"vinsbrunin-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        )
        result = ScrapeResult(batch_id=batch_id)

        source_row = self.conn.execute(
            "SELECT source_key FROM dim_source WHERE source_code = ?", (self.source_code,)
        ).fetchone()
        if not source_row:
            return ScrapeResult(error=f"source_code '{self.source_code}' not found in dim_source")
        SOURCE_KEY = source_row[0]

        headers = {
            "User-Agent": _USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,*/*",
            "Accept-Language": "fr-FR,fr;q=0.9",
        }

        total_fetched = 0

        with httpx.Client(headers=headers, timeout=30, follow_redirects=True) as client:
            for category_slug, region_name in _WINE_CATEGORIES:
                if limit is not None and total_fetched >= limit:
                    break

                page = 1
                while True:
                    if limit is not None and total_fetched >= limit:
                        break

                    # WiziShop directory-style pagination
                    url = (
                        f"{_BASE}/{category_slug}/"
                        if page == 1
                        else f"{_BASE}/{category_slug}/{page}"
                    )

                    try:
                        resp = self._fetch(lambda u=url: client.get(u))
                    except Exception as e:
                        write_dlq(self.conn, SOURCE_KEY, batch_id, "auth_error", str(e), {"url": url})
                        result.rows_dlq += 1
                        break

                    if resp.status_code == 404:
                        break  # past last page for this category
                    if resp.status_code in (403, 429):
                        msg = f"Blocked at {url}: HTTP {resp.status_code}"
                        write_dlq(self.conn, SOURCE_KEY, batch_id, "auth_error", msg, {"url": url})
                        result.rows_dlq += 1
                        result.error = msg
                        break

                    page_hash = hashlib.sha256(resp.content).hexdigest()
                    cached = self.conn.execute(
                        "SELECT last_hash FROM ops_content_hashes WHERE url = ?", (url,)
                    ).fetchone()
                    if cached and cached[0] == page_hash:
                        # Estimate ~20 products/page for limit accounting
                        result.rows_skipped_unchanged += 20
                        page += 1
                        time.sleep(0.5)
                        continue

                    self.conn.execute(
                        """INSERT OR REPLACE INTO ops_content_hashes
                           (url, source_key, last_hash, last_fetched_at, last_changed_at, fetch_count)
                           VALUES (?, ?, ?, ?, ?,
                             COALESCE((SELECT fetch_count + 1 FROM ops_content_hashes WHERE url = ?), 1))""",
                        (url, SOURCE_KEY, page_hash,
                         int(time.time()), int(time.time()), url),
                    )
                    self.conn.commit()

                    tree = HTMLParser(resp.text)
                    cards = _parse_cards(tree)

                    if not cards:
                        break  # empty page → end of pagination for this category

                    for card in cards:
                        if limit is not None and total_fetched >= limit:
                            break

                        title     = card["title"]
                        raw_price = card["raw_price"]
                        source_url = card["url"]

                        price_eur = _parse_price(raw_price)
                        if price_eur is None:
                            write_dlq(
                                self.conn, SOURCE_KEY, batch_id,
                                "parse_error",
                                f"Unparseable price: {raw_price!r}",
                                {"title": title},
                            )
                            result.rows_dlq += 1
                            result.rows_fetched += 1
                            total_fetched += 1
                            continue

                        # Strip leading organic/natural/etc. labels before parsing
                        clean_title = _STRIP_PREFIXES.sub("", title).strip()
                        parsed   = _parse_wine_title(clean_title)
                        producer = parsed.get("producer", "")
                        vintage  = parsed.get("vintage")

                        cuvee_raw  = parsed.get("cuvee") or parsed.get("appellation_hint") or title
                        color      = _color_from_title(clean_title, category_slug)

                        appellation_name, appellation_norm = _appellation_from_title(self.conn, clean_title)

                        producer_norm = normalize_producer(producer or title)
                        cuvee_norm    = normalize_cuvee(
                            cuvee_raw,
                            strip_words=[producer_norm, appellation_norm],
                        )

                        if not producer_norm:
                            write_dlq(
                                self.conn, SOURCE_KEY, batch_id,
                                "parse_error", f"Empty producer_norm for: {title!r}",
                                {"title": title},
                            )
                            result.rows_dlq += 1
                            result.rows_fetched += 1
                            total_fetched += 1
                            continue

                        wine_key = compute_wine_key(producer_norm, cuvee_norm, vintage, appellation_norm)

                        _ensure_producer(self.conn, producer_norm, producer or title)
                        if not _ensure_wine(
                            self.conn, wine_key, producer_norm,
                            cuvee_raw, cuvee_norm,
                            appellation_name, appellation_norm, region_name,
                            vintage, color,
                        ):
                            write_dlq(
                                self.conn, SOURCE_KEY, batch_id,
                                "unresolved_dim",
                                "Could not resolve producer or appellation",
                                {"title": title, "wine_key": wine_key},
                            )
                            result.rows_dlq += 1
                            result.rows_fetched += 1
                            total_fetched += 1
                            continue

                        card_hash = hashlib.sha256(
                            json.dumps(
                                {"title": title, "price": price_eur, "url": source_url},
                                sort_keys=True,
                            ).encode()
                        ).hexdigest()

                        inserted = insert_staging_candidate(
                            self.conn,
                            wine_key=wine_key,
                            source_key=SOURCE_KEY,
                            retailer="vinsbrunin",
                            recorded_at=int(time.time()),
                            currency_code="EUR",
                            amount_local=price_eur,
                            amount_eur=price_eur,
                            source_url=source_url,
                            content_hash=card_hash,
                            batch_id=batch_id,
                        )
                        if inserted:
                            result.rows_inserted += 1
                        else:
                            result.rows_skipped_unchanged += 1

                        result.rows_fetched += 1
                        total_fetched += 1

                    page += 1
                    time.sleep(1.0)

        return result
