# REGISTER_IN_CLI = True
"""
Decanter.com wine ratings scraper.

Target: https://www.decanter.com/wine-reviews/search/ (public search)
Scores are on /100 scale.
critic_code = 'Decanter'
source_code = 'decanter'
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

_BASE = "https://www.decanter.com"
_SEARCH_URL = "https://www.decanter.com/wine-reviews/search/"

VALID_CRITIC_CODES = {"WA", "Vinous", "BH", "JMIB", "RVF", "Decanter", "JS", "JG", "WS", "Hachette", "CT"}
CRITIC_CODE = "Decanter"


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


class DecanterRatingsScraper(BaseScraper):
    source_code = "decanter"

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.batch_id: Optional[str] = None

    def run(self, limit: Optional[int] = None) -> ScrapeResult:
        if not HAS_DEPS:
            return ScrapeResult(error="Missing dependencies: httpx or selectolax not installed")

        batch_id = self.batch_id or f"decanter-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
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
            "Accept-Language": "en-GB,en;q=0.9,fr;q=0.8",
        }

        # Search queries for different wine regions
        search_queries = [
            "burgundy red",
            "bordeaux",
            "champagne",
            "rhone red",
            "alsace",
        ]
        if limit:
            search_queries = search_queries[:2]

        with httpx.Client(headers=headers, timeout=30, follow_redirects=True) as client:
            # Use the first query URL to detect the Piano paywall
            url = f"{_SEARCH_URL}?search=burgundy&page=1"
            try:
                resp = self._fetch(lambda: client.get(url))
            except Exception as exc:
                write_dlq(self.conn, SOURCE_KEY, batch_id, "network_error", str(exc), {"url": url})
                result.rows_dlq += 1
                return result

            html = resp.text
            tree = HTMLParser(html)

            # Piano paywall detection: Decanter search results are gated behind
            # a Piano subscription. The empty container div is always present.
            piano_el = tree.css_first(".piano-container-search-results, [class*='piano-container-search']")
            if piano_el is not None or "piano-container-search-results" in html:
                msg = (
                    "Decanter search requires a paid Piano subscription. "
                    "The response contains an empty 'piano-container-search-results' div. "
                    "Set requires_auth=1 in dim_source and provide valid Piano credentials "
                    "to enable this scraper."
                )
                _logger.warning(msg)
                write_dlq(
                    self.conn, SOURCE_KEY, batch_id, "auth_error", msg,
                    {"url": url, "status": resp.status_code},
                )
                result.rows_dlq += 1
                result.error = msg
                # Mark requires_auth=1 so the scheduler skips this source
                try:
                    self.conn.execute(
                        "UPDATE dim_source SET requires_auth = 1 WHERE source_code = ?",
                        (self.source_code,),
                    )
                    self.conn.commit()
                    _logger.info(
                        "Set requires_auth=1 for source_code='decanter' in dim_source"
                    )
                except Exception as db_exc:
                    _logger.warning("Could not update requires_auth: %s", db_exc)
                return result

            # If no paywall detected, attempt to parse results (future-proofing)
            for query in search_queries:
                if limit is not None and result.rows_inserted >= limit:
                    break

                url = f"{_SEARCH_URL}?search={query.replace(' ', '+')}&page=1"
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
                cards = tree.css(
                    ".search-result, .wine-review-card, .review-item, "
                    "[class*='search-result'], [class*='wine-card']"
                )
                if not cards:
                    _logger.debug("No Decanter rating cards found for query=%s", query)
                    continue

                for card in cards:
                    if limit is not None and result.rows_inserted >= limit:
                        break

                    result.rows_fetched += 1
                    name_node = card.css_first(
                        "h2, h3, h4, .wine-name, .review-title, [class*='title']"
                    )
                    raw_name = name_node.text(strip=True) if name_node else ""
                    if not raw_name:
                        write_dlq(self.conn, SOURCE_KEY, batch_id, "parse_error",
                                   "Missing wine name", {"html": (card.html or "")[:200]})
                        result.rows_dlq += 1
                        continue

                    score_node = card.css_first(
                        ".score, .rating, .points, [class*='score'], [class*='point']"
                    )
                    score_text = score_node.text(strip=True) if score_node else ""
                    score_match = re.search(
                        r"\b(\d{2,3})\b(?:\s*points?|/100)?",
                        score_text or card.text(strip=True),
                    )
                    if not score_match:
                        write_dlq(self.conn, SOURCE_KEY, batch_id, "parse_error",
                                   "No score found", {"wine": raw_name, "url": url})
                        result.rows_dlq += 1
                        continue

                    try:
                        score_raw = float(score_match.group(1))
                    except ValueError:
                        result.rows_dlq += 1
                        continue

                    if not (50 <= score_raw <= 100):
                        result.rows_dlq += 1
                        continue

                    scale = "/100"
                    score_norm = _normalize_score_to_100(score_raw, scale)
                    if score_norm is None:
                        result.rows_dlq += 1
                        continue

                    vintage = _extract_vintage(raw_name)
                    producer_norm = normalize_producer(raw_name)
                    cuvee_norm = normalize_cuvee(raw_name)
                    if not producer_norm or not cuvee_norm:
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
