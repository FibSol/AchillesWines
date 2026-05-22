"""
Millesima.fr scraper — retail price ingestion.

NOTE: millesima.fr may return 403/429 when running from cloud IPs or without
a valid browser-like session. In that case, the scraper logs the block to DLQ
with error_class="auth_error" and returns gracefully with rows_fetched=0.
"""
import hashlib
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
from ..dlq import write_dlq

# Representative sample HTML for parser testing (from millesima.fr wine listing cards)
SAMPLE_HTML = """
<div class="product-item-info">
  <a class="product-item-link" href="/vins/domaine-leflaive-puligny-montrachet-les-pucelles-2020.html">
    Domaine Leflaive Puligny-Montrachet Les Pucelles
  </a>
  <div class="price-box">
    <span class="price">189,00 €</span>
  </div>
  <div class="product-item-details">
    <span class="vintage">2020</span>
    <span class="appellation">Puligny-Montrachet</span>
  </div>
</div>
<div class="product-item-info">
  <a class="product-item-link" href="/vins/chateau-petrus-pomerol-2018.html">
    Château Pétrus Pomerol
  </a>
  <div class="price-box">
    <span class="price">3 250,00 €</span>
  </div>
  <div class="product-item-details">
    <span class="vintage">2018</span>
    <span class="appellation">Pomerol</span>
  </div>
</div>
"""

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

SOURCE_KEY = 2  # millesima in dim_source


def _parse_price_eur(price_text: str) -> Optional[float]:
    """Parse French-formatted price string like '189,00 €' or '3 250,00 €' → float."""
    if not price_text:
        return None
    cleaned = price_text.replace("\xa0", "").replace(" ", "").replace("€", "").replace(",", ".").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def _extract_vintage(text: str) -> Optional[int]:
    """Extract 4-digit year (1990–2030) from text."""
    import re
    m = re.search(r"\b(19[9]\d|20[0-3]\d)\b", text)
    return int(m.group(1)) if m else None


def _parse_cards(html: str) -> list[dict]:
    """
    Parse wine cards from a Millesima listing page.
    Returns list of dicts: {name, vintage, price_eur, source_url, appellation, card_html}
    """
    tree = HTMLParser(html)
    results = []

    # Millesima uses .product-item-info cards
    for card in tree.css(".product-item-info"):
        card_html = card.html or ""

        # Wine name + URL
        link_node = card.css_first("a.product-item-link")
        if not link_node:
            continue
        raw_name = (link_node.text(strip=True) or "").strip()
        href = link_node.attributes.get("href", "")

        # Price
        price_node = card.css_first(".price")
        price_text = price_node.text(strip=True) if price_node else ""
        price_eur = _parse_price_eur(price_text)

        # Vintage: prefer explicit span, fall back to extracting from name
        vintage_node = card.css_first(".vintage")
        vintage_text = vintage_node.text(strip=True) if vintage_node else ""
        vintage = _extract_vintage(vintage_text) or _extract_vintage(raw_name)

        # Appellation
        app_node = card.css_first(".appellation")
        appellation = app_node.text(strip=True) if app_node else ""

        if not raw_name or price_eur is None:
            continue

        results.append({
            "name": raw_name,
            "vintage": vintage,
            "price_eur": price_eur,
            "source_url": f"https://www.millesima.fr{href}" if href.startswith("/") else href,
            "appellation": appellation,
            "card_html": card_html,
        })

    return results


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
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
        }

        page = 1
        total_fetched = 0

        with httpx.Client(
            headers=headers,
            timeout=30,
            follow_redirects=True,
        ) as client:
            while True:
                url = f"https://www.millesima.fr/vins/?nb=100&p={page}"
                try:
                    resp = client.get(url)
                except Exception as e:
                    result.error = f"HTTP error on page {page}: {e}"
                    write_dlq(
                        self.conn, SOURCE_KEY, batch_id,
                        "auth_error", str(e), {"url": url}
                    )
                    result.rows_dlq += 1
                    break

                if resp.status_code in (403, 429):
                    msg = f"Blocked by millesima.fr: HTTP {resp.status_code} on {url}"
                    write_dlq(
                        self.conn, SOURCE_KEY, batch_id,
                        "auth_error", msg, {"url": url, "status": resp.status_code}
                    )
                    result.rows_dlq += 1
                    result.error = msg
                    break

                if resp.status_code != 200:
                    result.error = f"Unexpected HTTP {resp.status_code} on {url}"
                    break

                html = resp.text
                page_hash = hashlib.sha256(html.encode()).hexdigest()

                # Content-hash check: skip page if unchanged
                cached = self.conn.execute(
                    "SELECT last_hash FROM ops_content_hashes WHERE url = ?", (url,)
                ).fetchone()
                if cached and cached["last_hash"] == page_hash:
                    result.rows_skipped_unchanged += 1
                    # No new wines on this page — might still be more pages
                    page += 1
                    continue

                # Update content hash
                self.conn.execute(
                    """INSERT OR REPLACE INTO ops_content_hashes
                       (url, source_key, last_hash, last_fetched_at, last_changed_at, fetch_count)
                       VALUES (?, ?, ?, ?, ?,
                         COALESCE((SELECT fetch_count + 1 FROM ops_content_hashes WHERE url = ?), 1))""",
                    (url, SOURCE_KEY, page_hash, int(time.time()), int(time.time()), url)
                )
                self.conn.commit()

                cards = _parse_cards(html)

                if not cards:
                    # No more cards → end of catalogue
                    break

                for card in cards:
                    if limit is not None and total_fetched >= limit:
                        break

                    total_fetched += 1
                    result.rows_fetched += 1

                    raw_name = card["name"]
                    price_eur = card["price_eur"]
                    vintage = card["vintage"]
                    source_url = card["source_url"]
                    appellation = card.get("appellation", "")
                    card_hash = hashlib.sha256(card["card_html"].encode()).hexdigest()

                    # Normalize
                    producer_norm = normalize_producer(raw_name)
                    cuvee_norm = normalize_cuvee(raw_name)
                    appellation_norm = norm_text(appellation) if appellation else ""

                    if not producer_norm or not cuvee_norm:
                        write_dlq(
                            self.conn, SOURCE_KEY, batch_id,
                            "parse_error", f"Empty producer_norm or cuvee_norm for: {raw_name!r}",
                            {"raw_name": raw_name, "url": source_url}
                        )
                        result.rows_dlq += 1
                        continue

                    wine_key = compute_wine_key(producer_norm, cuvee_norm, vintage, appellation_norm)

                    # Ensure producer exists
                    _ensure_producer(self.conn, producer_norm, raw_name)

                    # Insert into staging
                    try:
                        self.conn.execute(
                            """INSERT OR IGNORE INTO staging_price_candidates
                               (wine_key, source_key, retailer, recorded_at, currency_code,
                                amount_local, amount_eur, source_url, content_hash, batch_id, needs_review)
                               VALUES (?, ?, 'millesima', ?, 'EUR', ?, ?, ?, ?, ?, 1)""",
                            (
                                wine_key, SOURCE_KEY, int(time.time()),
                                price_eur, price_eur,
                                source_url, card_hash, batch_id
                            )
                        )
                        self.conn.commit()
                        result.rows_inserted += 1
                    except Exception as e:
                        write_dlq(
                            self.conn, SOURCE_KEY, batch_id,
                            "validation_error", str(e),
                            {"wine_key": wine_key, "price_eur": price_eur, "url": source_url}
                        )
                        result.rows_dlq += 1

                if limit is not None and total_fetched >= limit:
                    break

                page += 1
                # Be polite
                time.sleep(1.0)

        return result
