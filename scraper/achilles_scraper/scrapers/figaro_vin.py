# REGISTER_IN_CLI = True
"""
Le Figaro wine ratings scraper.

Target: https://avis-vin.lefigaro.fr/vins (public wine search)
Figaro Vin publishes free wine ratings from French critics.
Scores are typically /100 (or /20 on some pages).
critic_code = 'RVF'  — closest mapped critic in the closed enum for French press
source_code = 'figaro_vin'
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

_BASE = "https://avis-vin.lefigaro.fr"
_WINES_URL = "https://avis-vin.lefigaro.fr/vins"

VALID_CRITIC_CODES = {"WA", "Vinous", "BH", "JMIB", "RVF", "Decanter", "JS", "JG", "WS", "Hachette", "CT"}
CRITIC_CODE = "RVF"  # French press mapping


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
    # /100 explicit
    m = re.search(r"(\d{2,3})\s*/\s*100", text)
    if m:
        return float(m.group(1)), "/100"
    # /20 explicit
    m = re.search(r"(\d{1,2}(?:\.\d+)?)\s*/\s*20", text)
    if m:
        return float(m.group(1)), "/20"
    # Bare number 70-100 (assume /100)
    m = re.search(r"\b(\d{2,3})\b(?:\s*pts?|/100)?", text)
    if m:
        val = float(m.group(1))
        if 70 <= val <= 100:
            return val, "/100"
    return None


class FigaroVinScraper(BaseScraper):
    source_code = "figaro_vin"

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.batch_id: Optional[str] = None

    def run(self, limit: Optional[int] = None) -> ScrapeResult:
        if not HAS_DEPS:
            return ScrapeResult(error="Missing dependencies: httpx or selectolax not installed")

        batch_id = self.batch_id or f"figaro-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
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

        # Paginate through wine listings
        page = 1
        max_pages = 5 if limit is None else 2

        with httpx.Client(headers=headers, timeout=30, follow_redirects=True) as client:
            while page <= max_pages:
                if limit is not None and result.rows_inserted >= limit:
                    break

                url = f"{_WINES_URL}?page={page}"
                try:
                    resp = self._fetch(lambda: client.get(url))
                    resp.raise_for_status()
                except Exception as exc:
                    write_dlq(self.conn, SOURCE_KEY, batch_id, "network_error", str(exc), {"url": url})
                    result.rows_dlq += 1
                    break

                if resp.status_code in (401, 403, 429):
                    write_dlq(self.conn, SOURCE_KEY, batch_id, "auth_error",
                               f"Blocked: HTTP {resp.status_code}", {"url": url})
                    result.rows_dlq += 1
                    break

                tree = HTMLParser(resp.text)

                # Figaro Vin wine card selectors
                cards = tree.css(
                    ".wine-card, .vin-item, .avis-item, .product-item, "
                    "[class*='wine-card'], [class*='vin-card'], article.vin"
                )

                if not cards:
                    _logger.debug("No Figaro Vin cards found on page %d — stopping", page)
                    break

                for card in cards:
                    if limit is not None and result.rows_inserted >= limit:
                        break

                    result.rows_fetched += 1

                    name_node = card.css_first(
                        "h2, h3, h4, .wine-name, .nom-vin, .titre, [class*='name'], [class*='titre']"
                    )
                    raw_name = name_node.text(strip=True) if name_node else ""
                    if not raw_name:
                        write_dlq(self.conn, SOURCE_KEY, batch_id, "parse_error",
                                   "Missing wine name", {"html": (card.html or "")[:200]})
                        result.rows_dlq += 1
                        continue

                    # Score detection
                    score_node = card.css_first(
                        ".score, .note, .rating, .points, [class*='score'], [class*='note']"
                    )
                    score_text = score_node.text(strip=True) if score_node else card.text(strip=True)

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
                                   f"Empty producer_norm or cuvee_norm for: {raw_name!r}", {"wine": raw_name})
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

                page += 1
                time.sleep(1.5)

        return result
