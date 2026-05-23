# REGISTER_IN_CLI = True
"""
Hachette Vins guide ratings scraper.

Target: https://www.hachette-vins.com/vins/list/ (public catalogue, 60 wines/page)
Pagination: /vins/page-{N}/list/
Hachette uses a text-based rating system in .p-rating-ctn:
  "Vin exceptionnel" (coup de coeur) = 100/100
  "Vin très réussi"                   = 85/100
  "Vin réussi" / "Vin cité"           = 75/100
  (0-star / unrated wines are silently skipped)
critic_code = 'Hachette'
source_code = 'hachette_vins'
"""
import hashlib
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

_logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_BASE = "https://www.hachette-vins.com"
_LIST_URL = "https://www.hachette-vins.com/vins/list/"

VALID_CRITIC_CODES = {"WA", "Vinous", "BH", "JMIB", "RVF", "Decanter", "JS", "JG", "WS", "Hachette", "CT"}
CRITIC_CODE = "Hachette"

# Hachette rating text → /100 mapping
_RATING_TEXT_TO_SCORE: dict[str, float] = {
    "exceptionnel": 100.0,
    "très réussi": 85.0,
    "tres reussi": 85.0,
    "réussi": 75.0,
    "reussi": 75.0,
    "cité": 75.0,
    "cite": 75.0,
}


def _score_from_rating_text(text: str) -> Optional[float]:
    """Extract score from Hachette rating text in .p-rating-ctn."""
    if not text:
        return None
    low = text.lower()
    for key, score in _RATING_TEXT_TO_SCORE.items():
        if key in low:
            return score
    return None


def _extract_vintage(text: str) -> Optional[int]:
    m = re.search(r"\b(199\d|20[0-3]\d)\b", text or "")
    return int(m.group(1)) if m else None


class HachetteVinsGuideScraper(BaseScraper):
    source_code = "hachette_vins"

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.batch_id: Optional[str] = None

    def run(self, limit: Optional[int] = None) -> ScrapeResult:
        if not HAS_DEPS:
            return ScrapeResult(error="Missing dependencies: httpx or selectolax not installed")

        batch_id = self.batch_id or f"hachette-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        result = ScrapeResult(batch_id=batch_id)

        # Dynamic source_key lookup
        source_row = self.conn.execute(
            "SELECT source_key FROM dim_source WHERE source_code = ?", (self.source_code,)
        ).fetchone()
        if not source_row:
            return ScrapeResult(error=f"source_code '{self.source_code}' not found in dim_source")
        SOURCE_KEY = source_row[0]

        headers = {
            "User-Agent": _USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,*/*",
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
        }

        # Sanity cap: Hachette returns 200 OK with non-empty .wine-card markup
        # for pages well past the real catalog end (verified 2026-05-23: page 1000
        # still returns ~1.3 MB of HTML with cards). Without this cap the scraper
        # spins for >60s on limit=5 when rows_inserted stays at 0 (eg FK failures).
        MAX_PAGES = 50  # ~3000 wines per run, plenty for the v1 catalogue
        with httpx.Client(headers=headers, timeout=30, follow_redirects=True) as client:
            page = 1
            while page <= MAX_PAGES:
                # Bound by *fetched* rows (work done), not inserted (rows that
                # passed every downstream gate). Unrated wines + FK failures
                # both used to leave rows_inserted at 0 and burned hundreds of
                # pages before timing out.
                if limit is not None and result.rows_fetched >= limit:
                    break

                url = _LIST_URL if page == 1 else f"{_BASE}/vins/page-{page}/list/"
                try:
                    resp = client.get(url)
                except Exception as exc:
                    write_dlq(self.conn, SOURCE_KEY, batch_id, "network_error", str(exc), {"url": url})
                    result.rows_dlq += 1
                    break

                if resp.status_code == 404:
                    _logger.debug("Hachette page %d -> 404, stopping", page)
                    break

                if resp.status_code in (401, 403, 429):
                    write_dlq(self.conn, SOURCE_KEY, batch_id, "auth_error",
                               f"Blocked: HTTP {resp.status_code}", {"url": url})
                    result.rows_dlq += 1
                    break

                tree = HTMLParser(resp.text)
                cards = tree.css(".wine-card")

                if not cards:
                    _logger.debug("No .wine-card found on page %d -- stopping", page)
                    break

                for card in cards:
                    if limit is not None and result.rows_fetched >= limit:
                        break

                    result.rows_fetched += 1

                    # Name -- itemprop="name" is most reliable
                    name_node = card.css_first('[itemprop="name"]') or card.css_first("h2, h3, .p-title")
                    raw_name = name_node.text(strip=True) if name_node else ""
                    if not raw_name:
                        write_dlq(self.conn, SOURCE_KEY, batch_id, "parse_error",
                                   "Missing wine name", {"html": (card.html or "")[:200]})
                        result.rows_dlq += 1
                        continue

                    # Rating -- .p-rating-ctn contains text like "Vin exceptionnel", "Vin tres reussi"
                    rating_node = card.css_first(".p-rating-ctn")
                    rating_text = rating_node.text(strip=True) if rating_node else ""
                    score_raw = _score_from_rating_text(rating_text)

                    if score_raw is None:
                        # 0-star / unrated wines -- skip silently
                        _logger.debug("No rating detected for %r (text=%r) -- skipping", raw_name, rating_text)
                        continue

                    scale = "/100"
                    score_norm = score_raw  # already /100

                    vintage = _extract_vintage(raw_name)
                    producer_norm = normalize_producer(raw_name)
                    cuvee_norm = normalize_cuvee(raw_name)

                    if not producer_norm or not cuvee_norm:
                        write_dlq(self.conn, SOURCE_KEY, batch_id, "parse_error",
                                   f"Empty producer_norm or cuvee_norm for: {raw_name!r}", {"wine": raw_name})
                        result.rows_dlq += 1
                        continue

                    wine_key = compute_wine_key(producer_norm, cuvee_norm, vintage, "")

                    link_node = card.css_first("a[href]")
                    href = link_node.attributes.get("href", "") if link_node else ""
                    source_url = (href if href.startswith("http") else _BASE + href) if href else url

                    content_hash = hashlib.sha256(
                        f"{wine_key}:{CRITIC_CODE}:{score_raw}".encode()
                    ).hexdigest()

                    try:
                        self.conn.execute(
                            """
                            INSERT OR IGNORE INTO fact_rating
                            (wine_key, source_key, critic_code, reviewer_type, score, scale,
                             score_normalized_100, source_url, content_hash, batch_id)
                            VALUES (?, ?, ?, 'critic', ?, ?, ?, ?, ?, ?)
                            """,
                            (wine_key, SOURCE_KEY, CRITIC_CODE, score_raw, scale,
                             score_norm, source_url, content_hash, batch_id),
                        )
                        self.conn.commit()
                        result.rows_inserted += 1
                    except Exception as exc:
                        write_dlq(self.conn, SOURCE_KEY, batch_id, "validation_error", str(exc),
                                   {"wine_key": wine_key, "score": score_raw})
                        result.rows_dlq += 1

                page += 1
                time.sleep(1.5)

        return result
