# REGISTER_IN_CLI = True
"""
Terre de Vins wine ratings scraper.

Target: https://www.terredevins.com/vins (public wine listings)
Terre de Vins is a French wine magazine publishing ratings from French critics.
Scores may be /20 or /100 depending on the reviewer.
critic_code = 'RVF'  — French wine press mapping (closest enum value)
source_code = 'terredevins'
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

_BASE = "https://www.terredevins.com"
_WINES_URL = "https://www.terredevins.com/vins"

VALID_CRITIC_CODES = {"WA", "Vinous", "BH", "JMIB", "RVF", "Decanter", "JS", "JG", "WS", "Hachette", "CT"}
CRITIC_CODE = "RVF"  # French wine press mapping


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


def _detect_scale_and_score(text: str) -> Optional[tuple[float, str]]:
    """Detect score and scale from text. Returns (score, scale) or None."""
    # /20 explicit — common for French press
    m = re.search(r"(\d{1,2}(?:\.\d+)?)\s*/\s*20", text)
    if m:
        return float(m.group(1)), "/20"
    # /100 explicit
    m = re.search(r"(\d{2,3})\s*/\s*100", text)
    if m:
        return float(m.group(1)), "/100"
    # Bare number 70-100 (assume /100)
    m = re.search(r"\b(\d{2,3})\b", text)
    if m:
        val = float(m.group(1))
        if 70 <= val <= 100:
            return val, "/100"
    # Bare number 10-20 (assume /20 for French press)
    m = re.search(r"\b(\d{1,2}(?:\.\d+)?)\b", text)
    if m:
        val = float(m.group(1))
        if 10 <= val <= 20:
            return val, "/20"
    return None


class TerreDeVinsScraper(BaseScraper):
    source_code = "terredevins"

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.batch_id: Optional[str] = None

    def run(self, limit: Optional[int] = None) -> ScrapeResult:
        if not HAS_DEPS:
            return ScrapeResult(error="Missing dependencies: httpx or selectolax not installed")

        batch_id = self.batch_id or f"tdv-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
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

        # Search terms covering French wine regions
        search_terms = ["bourgogne", "bordeaux", "rhone", "provence", "alsace"]
        if limit:
            search_terms = search_terms[:2]

        with httpx.Client(headers=headers, timeout=30, follow_redirects=True) as client:
            for term in search_terms:
                if limit is not None and result.rows_inserted >= limit:
                    break

                # Try both the vins listing page and a search path
                urls_to_try = [
                    f"{_WINES_URL}?region={term}",
                    f"{_BASE}/search?q={term}&post_type=vin",
                ]

                for url in urls_to_try:
                    if limit is not None and result.rows_inserted >= limit:
                        break

                    try:
                        resp = self._fetch(lambda: client.get(url))
                        resp.raise_for_status()
                    except Exception as exc:
                        write_dlq(self.conn, SOURCE_KEY, batch_id, "network_error", str(exc), {"url": url})
                        result.rows_dlq += 1
                        continue

                    if resp.status_code in (401, 403, 404, 429):
                        if resp.status_code == 404:
                            # URL path doesn't exist — try next variant
                            continue
                        write_dlq(self.conn, SOURCE_KEY, batch_id, "auth_error",
                                   f"Blocked/error: HTTP {resp.status_code}", {"url": url})
                        result.rows_dlq += 1
                        continue

                    tree = HTMLParser(resp.text)

                    # Terre de Vins wine card selectors
                    cards = tree.css(
                        ".wine-card, .vin-card, .post-type-vin, article.vin, "
                        "[class*='wine-result'], [class*='vin-item'], .entry-vin"
                    )

                    if not cards:
                        # Try generic post/article cards
                        cards = tree.css("article.post, .entry-summary, .wine-listing article")

                    if not cards:
                        _logger.debug("No TerreDeVins cards found for url=%s", url)
                        continue

                    for card in cards:
                        if limit is not None and result.rows_inserted >= limit:
                            break

                        result.rows_fetched += 1

                        name_node = card.css_first(
                            "h2, h3, h4, .wine-name, .entry-title, .vin-nom, [class*='title'], [class*='name']"
                        )
                        raw_name = name_node.text(strip=True) if name_node else ""
                        if not raw_name:
                            write_dlq(self.conn, SOURCE_KEY, batch_id, "parse_error",
                                       "Missing wine name", {"html": (card.html or "")[:200]})
                            result.rows_dlq += 1
                            continue

                        # Score detection
                        score_node = card.css_first(
                            ".score, .note, .rating, .notation, [class*='score'], [class*='note']"
                        )
                        score_text = score_node.text(strip=True) if score_node else ""

                        # Fall back to card text if no dedicated score node
                        if not score_text:
                            score_text = card.text(strip=True)

                        parsed = _detect_scale_and_score(score_text)
                        if parsed is None:
                            write_dlq(self.conn, SOURCE_KEY, batch_id, "parse_error",
                                       "No score found", {"wine": raw_name, "url": url})
                            result.rows_dlq += 1
                            continue

                        score_raw, scale = parsed
                        score_norm = _normalize_score_to_100(score_raw, scale)
                        if score_norm is None:
                            write_dlq(self.conn, SOURCE_KEY, batch_id, "validation_error",
                                       f"Score {score_raw} failed normalization for scale {scale}",
                                       {"wine": raw_name})
                            result.rows_dlq += 1
                            continue

                        vintage = _extract_vintage(raw_name)
                        producer_norm = normalize_producer(raw_name)
                        cuvee_norm = normalize_cuvee(raw_name)

                        if not producer_norm or not cuvee_norm:
                            write_dlq(self.conn, SOURCE_KEY, batch_id, "parse_error",
                                       f"Empty producer_norm or cuvee_norm for: {raw_name!r}",
                                       {"wine": raw_name})
                            result.rows_dlq += 1
                            continue

                        wine_key = compute_wine_key(producer_norm, cuvee_norm, vintage, "")

                        link_node = card.css_first("a[href]")
                        href = link_node.attributes.get("href", "") if link_node else ""
                        source_url = (_BASE + href) if href.startswith("/") else (href or url)

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
                    # If we got cards from first URL, skip the second
                    if result.rows_fetched > 0:
                        break

                time.sleep(0.5)

        return result
