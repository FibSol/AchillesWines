# REGISTER_IN_CLI = True
"""
JamesSuckling.com wine ratings scraper.

Target: https://www.jamessuckling.com/top-wines/ (public top 100 list)
Scores are on /100 scale.
critic_code = 'JS'
source_code = 'james_suckling'

NOTE: 'james_suckling' may not yet be registered in dim_source. The scraper
handles this gracefully — it logs a clear warning and returns an empty result.
Run the source registration migration first to enable this scraper.
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

_BASE = "https://www.jamessuckling.com"
_TOP_WINES_URL = "https://www.jamessuckling.com/top-wines/"

VALID_CRITIC_CODES = {"WA", "Vinous", "BH", "JMIB", "RVF", "Decanter", "JS", "JG", "WS", "Hachette", "CT"}
CRITIC_CODE = "JS"


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


class JamesSucklingScraper(BaseScraper):
    source_code = "james_suckling"

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.batch_id: Optional[str] = None

    def run(self, limit: Optional[int] = None) -> ScrapeResult:
        if not HAS_DEPS:
            return ScrapeResult(error="Missing dependencies: httpx or selectolax not installed")

        batch_id = self.batch_id or f"js-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        result = ScrapeResult(batch_id=batch_id)

        # Dynamic source_key lookup — james_suckling may not be in dim_source yet
        source_row = self.conn.execute(
            "SELECT source_key FROM dim_source WHERE source_code = ?", (self.source_code,)
        ).fetchone()
        if not source_row:
            _logger.warning(
                "source_code 'james_suckling' not found in dim_source. "
                "Run the source registration migration to enable this scraper. "
                "Returning empty result."
            )
            return ScrapeResult(
                error=(
                    "source_code 'james_suckling' not registered in dim_source. "
                    "Insert a row with source_code='james_suckling' into dim_source first."
                )
            )
        SOURCE_KEY = source_row[0]

        headers = {
            "User-Agent": _USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,*/*",
            "Accept-Language": "en-US,en;q=0.9",
        }

        with httpx.Client(headers=headers, timeout=30, follow_redirects=True) as client:
            url = _TOP_WINES_URL
            try:
                resp = self._fetch(lambda: client.get(url))
                resp.raise_for_status()
            except Exception as exc:
                write_dlq(self.conn, SOURCE_KEY, batch_id, "network_error", str(exc), {"url": url})
                result.rows_dlq += 1
                result.error = f"Failed to fetch {url}: {exc}"
                return result

            if resp.status_code in (401, 403, 429):
                msg = f"Blocked by jamessuckling.com: HTTP {resp.status_code}"
                write_dlq(self.conn, SOURCE_KEY, batch_id, "auth_error", msg, {"url": url})
                result.rows_dlq += 1
                result.error = msg
                return result

            html = resp.text

            # Probe for __NEXT_DATA__ (Next.js SSR inline JSON)
            next_data_match = re.search(
                r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL
            )
            if not next_data_match:
                # jamessuckling.com/top-wines/ is a purely client-side rendered Next.js SPA.
                # The HTML is an app shell — no wine content in the static HTML.
                # Scraping requires a headless browser (Playwright/Puppeteer) which is
                # not available in this sidecar. Mark as not applicable.
                msg = (
                    "jamessuckling.com/top-wines/ is a client-side-only Next.js SPA "
                    "(no __NEXT_DATA__ in HTML). Wine content requires JS execution. "
                    "Set requires_auth=1 in dim_source as a proxy for 'needs browser' "
                    "and provide a Playwright-based scraper to resolve."
                )
                _logger.warning(msg)
                write_dlq(
                    self.conn, SOURCE_KEY, batch_id, "scraper_not_applicable", msg,
                    {"url": url, "html_length": len(html)},
                )
                result.rows_dlq += 1
                result.error = msg
                # Mark requires_auth=1 in dim_source so the scheduler skips it
                try:
                    self.conn.execute(
                        "UPDATE dim_source SET requires_auth = 1 WHERE source_code = ?",
                        (self.source_code,),
                    )
                    self.conn.commit()
                    _logger.info(
                        "Set requires_auth=1 for source_code='james_suckling' in dim_source"
                    )
                except Exception as db_exc:
                    _logger.warning("Could not update requires_auth: %s", db_exc)
                return result

            # __NEXT_DATA__ found — parse JSON and walk the tree for wine items
            import json as _json
            try:
                next_data = _json.loads(next_data_match.group(1))
            except _json.JSONDecodeError as exc:
                msg = f"Failed to parse __NEXT_DATA__ JSON: {exc}"
                write_dlq(self.conn, SOURCE_KEY, batch_id, "parse_error", msg, {"url": url})
                result.rows_dlq += 1
                result.error = msg
                return result

            # Walk the JSON tree looking for objects with score/name fields
            def _find_wines(obj, depth=0):
                if depth > 20:
                    return
                if isinstance(obj, dict):
                    name = obj.get("name") or obj.get("wineName") or obj.get("title") or ""
                    score = obj.get("score") or obj.get("points") or obj.get("rating")
                    if name and score:
                        try:
                            yield {"name": str(name), "score": float(str(score).split("-")[0])}
                        except (ValueError, TypeError):
                            pass
                    for v in obj.values():
                        yield from _find_wines(v, depth + 1)
                elif isinstance(obj, list):
                    for item in obj:
                        yield from _find_wines(item, depth + 1)

            for item in _find_wines(next_data):
                if limit is not None and result.rows_inserted >= limit:
                    break

                raw_name = item["name"]
                score_raw = item["score"]
                result.rows_fetched += 1

                if not (80 <= score_raw <= 100):
                    write_dlq(self.conn, SOURCE_KEY, batch_id, "validation_error",
                               f"Score {score_raw} not in plausible JS /100 range (80-100)",
                               {"wine": raw_name})
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
                    write_dlq(self.conn, SOURCE_KEY, batch_id, "parse_error",
                               f"Empty producer_norm or cuvee_norm for: {raw_name!r}",
                               {"wine": raw_name})
                    result.rows_dlq += 1
                    continue

                wine_key = compute_wine_key(producer_norm, cuvee_norm, vintage, "")
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
                         score_norm, url, content_hash, batch_id),
                    )
                    self.conn.commit()
                    result.rows_inserted += 1
                except Exception as exc:
                    write_dlq(self.conn, SOURCE_KEY, batch_id, "validation_error", str(exc),
                               {"wine_key": wine_key, "score": score_raw})
                    result.rows_dlq += 1

        return result
