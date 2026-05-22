# REGISTER_IN_CLI = True
"""
Hachette Vins guide ratings scraper.

Target: https://www.hachette-vins.com/guide/ (some content free)
Hachette uses a 0-3 star system:
  0 stars = not recommended (skip)
  1 star  = 75/100
  2 stars = 85/100
  3 stars = 100/100 (coup de coeur)
Scores are stored as /100 mapped directly from star count.
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
_GUIDE_URL = "https://www.hachette-vins.com/guide/"

VALID_CRITIC_CODES = {"WA", "Vinous", "BH", "JMIB", "RVF", "Decanter", "JS", "JG", "WS", "Hachette", "CT"}
CRITIC_CODE = "Hachette"

# Hachette star → /100 mapping (normalized directly)
_STAR_TO_SCORE: dict[int, float] = {
    1: 75.0,
    2: 85.0,
    3: 100.0,
}


def _normalize_score_to_100(score: float, scale: str) -> Optional[float]:
    if scale == "/100":
        return score if 0 <= score <= 100 else None
    if scale == "/20":
        return (score / 20.0) * 100.0 if 0 <= score <= 20 else None
    if scale == "/5":
        return (score / 5.0) * 100.0 if 0 <= score <= 5 else None
    if scale == "stars":
        return (score / 5.0) * 100.0 if 0 <= score <= 5 else None
    return None


def _extract_vintage(text: str) -> Optional[int]:
    m = re.search(r"\b(199\d|20[0-3]\d)\b", text or "")
    return int(m.group(1)) if m else None


def _count_stars_from_html(card_html: str) -> Optional[int]:
    """Count filled star icons from HTML. Returns 1-3 or None."""
    if not card_html:
        return None
    # Common patterns: filled star icons, aria-label="X étoiles", star count attributes
    # Try aria-label pattern first
    aria_match = re.search(r"(\d)\s+(?:é|e)toile", card_html, re.I)
    if aria_match:
        count = int(aria_match.group(1))
        return count if 1 <= count <= 3 else None

    # Count filled star SVG/icon elements (★ vs ☆, or class="star filled" vs "star empty")
    filled_stars = len(re.findall(r'class="[^"]*\bstar[^"]*\bfilled\b[^"]*"', card_html, re.I))
    if filled_stars:
        return filled_stars if 1 <= filled_stars <= 3 else None

    # Unicode stars
    filled_unicode = card_html.count("★")
    if filled_unicode:
        return filled_unicode if 1 <= filled_unicode <= 3 else None

    return None


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

        # Search various regions
        search_terms = ["bourgogne", "bordeaux", "alsace", "champagne", "Loire"]
        if limit:
            search_terms = search_terms[:2]

        with httpx.Client(headers=headers, timeout=30, follow_redirects=True) as client:
            for term in search_terms:
                if limit is not None and result.rows_inserted >= limit:
                    break

                url = f"{_GUIDE_URL}?q={term}"
                try:
                    resp = self._fetch(lambda: client.get(url))
                    resp.raise_for_status()
                except Exception as exc:
                    write_dlq(self.conn, SOURCE_KEY, batch_id, "network_error", str(exc), {"url": url})
                    result.rows_dlq += 1
                    continue

                if resp.status_code in (401, 403, 429):
                    write_dlq(self.conn, SOURCE_KEY, batch_id, "auth_error",
                               f"Blocked: HTTP {resp.status_code}", {"url": url})
                    result.rows_dlq += 1
                    continue

                tree = HTMLParser(resp.text)

                # Hachette wine cards
                cards = tree.css(
                    ".wine-card, .vin-card, .guide-item, .result-item, "
                    "[class*='wine-result'], [class*='vin-item']"
                )

                if not cards:
                    _logger.debug("No Hachette wine cards found for term=%s", term)
                    continue

                for card in cards:
                    if limit is not None and result.rows_inserted >= limit:
                        break

                    result.rows_fetched += 1

                    name_node = card.css_first("h2, h3, h4, .wine-name, .vin-nom, [class*='name'], [class*='titre']")
                    raw_name = name_node.text(strip=True) if name_node else ""
                    if not raw_name:
                        write_dlq(self.conn, SOURCE_KEY, batch_id, "parse_error",
                                   "Missing wine name", {"html": (card.html or "")[:200]})
                        result.rows_dlq += 1
                        continue

                    # Count stars from card HTML
                    stars = _count_stars_from_html(card.html or "")

                    # Fallback: try text-based star count node
                    if stars is None:
                        star_node = card.css_first(".stars, .etoiles, .notation, [class*='star'], [class*='étoile']")
                        if star_node:
                            stars = _count_stars_from_html(star_node.html or "")

                    # Second fallback: look for explicit text like "2 étoiles" or "★★"
                    if stars is None:
                        card_text = card.text(strip=True)
                        stars_match = re.search(r"(\d)\s+é?toile", card_text, re.I)
                        if stars_match:
                            s = int(stars_match.group(1))
                            stars = s if 1 <= s <= 3 else None
                        else:
                            unicode_count = card_text.count("★")
                            if 1 <= unicode_count <= 3:
                                stars = unicode_count

                    if stars is None:
                        # 0-star wines (not recommended) or undetectable — skip silently
                        _logger.debug("No stars detected for %r — skipping (0-star or undetected)", raw_name)
                        continue

                    score_raw = float(_STAR_TO_SCORE.get(stars, 0))
                    if score_raw == 0:
                        _logger.debug("Unrecognized star count %d for %r — skipping", stars, raw_name)
                        continue

                    scale = "/100"
                    # score_raw is already /100 mapped
                    score_norm = score_raw  # Already normalized

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
                    source_url = (_BASE + link_node.attributes.get("href", "")) if link_node else url

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

                time.sleep(1.5)

        return result
