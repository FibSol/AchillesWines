# REGISTER_IN_CLI = True
"""
Revue du Vin de France (RVF) critic ratings scraper.

Target: https://www.larvf.com/recherche (subscription-gated)
All /20 scores are behind a paywall — public HTML contains no numeric ratings.
Re-implement with an authenticated session when RVF credentials are available.
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

        # larvf.com (La Revue du Vin de France) publishes wine scores exclusively
        # behind a subscriber paywall. The public search (/recherche?q=…&type=degustation)
        # returns article cards but all score details (/20) are hidden — no numeric
        # ratings are visible in the HTML without a paid subscription.
        msg = (
            "larvf.com (RVF) wine scores are fully paywalled. Public search "
            "returns article cards but no /20 scores are visible in HTML. "
            "Re-implement with authenticated session when RVF credentials are available."
        )
        write_dlq(self.conn, SOURCE_KEY, batch_id, "auth_error", msg,
                  {"url": _SEARCH_URL})
        result.rows_dlq += 1
        result.error = msg
        return result
