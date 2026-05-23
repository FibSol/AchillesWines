# REGISTER_IN_CLI = True
"""
Terre de Vins wine ratings scraper.

Target: https://www.terredevins.com (subscription-gated)
terredevins.com is an editorial wine magazine. Its wine degustation content
is behind a premium subscription — /vins and /search?q=…&post_type=vin
return 404. No public wine score endpoint exists.
Re-implement with an authenticated session when credentials are available.
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

        # terredevins.com is an editorial wine magazine. Its degustation pages
        # (/vins, /search?q=…&post_type=vin) return 404. Wine tasting notes and
        # scores are published in articles that require a premium subscription.
        # No free machine-readable wine score endpoint exists.
        msg = (
            "terredevins.com wine scores are subscription-gated. "
            "/vins and /search?q=...&post_type=vin both return 404. "
            "Degustation content requires a premium subscription. "
            "Re-implement with authenticated session when credentials are available."
        )
        write_dlq(self.conn, SOURCE_KEY, batch_id, "auth_error", msg,
                  {"url": _WINES_URL})
        result.rows_dlq += 1
        result.error = msg
        return result
