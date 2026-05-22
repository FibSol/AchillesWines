# REGISTER_IN_CLI = True
"""
Revue du Vin de France (RVF) critic ratings scraper.

Target: https://www.larvf.com/recherche (public search, some articles paywalled)
Scores are on /20 scale. Paywalled content is DLQ'd with auth_error.
critic_code = 'RVF'
source_code = 'rvf'
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

_BASE = "https://www.larvf.com"
_SEARCH_URL = "https://www.larvf.com/recherche"

VALID_CRITIC_CODES = {"WA", "Vinous", "BH", "JMIB", "RVF", "Decanter", "JS", "JG", "WS", "Hachette", "CT"}
CRITIC_CODE = "RVF"


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


class RvfScraper(BaseScraper):
    source_code = "rvf"

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.batch_id: Optional[str] = None

    def run(self, limit: Optional[int] = None) -> ScrapeResult:
        if not HAS_DEPS:
            return ScrapeResult(error="Missing dependencies: httpx or selectolax not installed")

        batch_id = self.batch_id or f"rvf-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
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

        # Search terms to try — common Burgundy appellations and regions
        search_terms = ["burgundy", "bordeaux", "champagne", "loire", "rhone"]
        if limit:
            search_terms = search_terms[:2]

        with httpx.Client(headers=headers, timeout=30, follow_redirects=True) as client:
            for term in search_terms:
                if limit is not None and result.rows_inserted >= limit:
                    break

                url = f"{_SEARCH_URL}?q={term}&type=degustation"
                try:
                    resp = self._fetch(lambda: client.get(url))
                    resp.raise_for_status()
                except Exception as exc:
                    write_dlq(self.conn, SOURCE_KEY, batch_id, "network_error", str(exc), {"url": url})
                    result.rows_dlq += 1
                    continue

                # Check for paywall / auth redirect
                if resp.status_code in (401, 403):
                    write_dlq(self.conn, SOURCE_KEY, batch_id, "auth_error",
                               f"Paywalled response HTTP {resp.status_code}", {"url": url})
                    result.rows_dlq += 1
                    continue

                tree = HTMLParser(resp.text)

                # Detect paywall messaging in the page
                paywall_signals = tree.css(".paywall, .subscription-wall, .abonnement")
                if paywall_signals and not tree.css(".degustation-score, .note-vin, .score"):
                    write_dlq(self.conn, SOURCE_KEY, batch_id, "auth_error",
                               "Content appears paywalled — no rating scores visible", {"url": url})
                    result.rows_dlq += 1
                    continue

                # Parse rating cards — RVF article cards with wine ratings
                # CSS selectors are best-effort; the site may change structure
                cards = tree.css("article.search-result, .article-card, .degustation-item, .vin-card")
                if not cards:
                    # Try a broader parse: look for score patterns in text
                    _logger.debug("No rating cards found on RVF search for term=%s", term)
                    continue

                for card in cards:
                    if limit is not None and result.rows_inserted >= limit:
                        break

                    result.rows_fetched += 1

                    # Extract wine name
                    name_node = card.css_first("h2, h3, .wine-name, .titre-vin, .article-title")
                    raw_name = name_node.text(strip=True) if name_node else ""
                    if not raw_name:
                        result.rows_dlq += 1
                        write_dlq(self.conn, SOURCE_KEY, batch_id, "parse_error",
                                   "Missing wine name", {"html": card.html[:200] if card.html else ""})
                        continue

                    # Extract score — look for /20 pattern
                    score_node = card.css_first(".note, .score, .rating, [class*='note'], [class*='score']")
                    score_text = score_node.text(strip=True) if score_node else ""

                    # Try to find a score in the format "17/20" or "17.5/20" in card text
                    score_match = re.search(r"(\d+(?:\.\d+)?)\s*/\s*20", score_text or card.text(strip=True))
                    if not score_match:
                        # No visible score — likely paywalled detail
                        write_dlq(self.conn, SOURCE_KEY, batch_id, "auth_error",
                                   "No score visible (paywalled?)", {"wine": raw_name, "url": url})
                        result.rows_dlq += 1
                        continue

                    try:
                        score_raw = float(score_match.group(1))
                    except ValueError:
                        write_dlq(self.conn, SOURCE_KEY, batch_id, "parse_error",
                                   f"Could not parse score: {score_text}", {"wine": raw_name})
                        result.rows_dlq += 1
                        continue

                    scale = "/20"
                    score_norm = _normalize_score_to_100(score_raw, scale)
                    if score_norm is None:
                        write_dlq(self.conn, SOURCE_KEY, batch_id, "validation_error",
                                   f"Score {score_raw} out of range for scale {scale}", {"wine": raw_name})
                        result.rows_dlq += 1
                        continue

                    vintage = _extract_vintage(raw_name)
                    producer_norm = normalize_producer(raw_name)
                    cuvee_norm = normalize_cuvee(raw_name)

                    if not producer_norm or not cuvee_norm:
                        write_dlq(self.conn, SOURCE_KEY, batch_id, "parse_error",
                                   f"Empty producer_norm or cuvee_norm for: {raw_name!r}", {"wine": raw_name})
                        result.rows_dlq += 1
                        continue

                    wine_key = compute_wine_key(producer_norm, cuvee_norm, vintage, "")

                    # Get card URL
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
