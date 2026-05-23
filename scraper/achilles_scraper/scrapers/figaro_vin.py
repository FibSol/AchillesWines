# REGISTER_IN_CLI = True
"""
Le Figaro wine ratings scraper.

Target: https://avis-vin.lefigaro.fr (subscription-gated)
avis-vin.lefigaro.fr/vins?page=N returns HTTP 400. Individual wine pages
require a Figaro Premium subscription. No public wine score endpoint exists.
Re-implement with authenticated session when Figaro credentials are available.
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
    m = re.search(r"(\d{2,3})\s*/\s*100", text)
    if m:
        return float(m.group(1)), "/100"
    m = re.search(r"(\d{1,2}(?:\.\d+)?)\s*/\s*20", text)
    if m:
        return float(m.group(1)), "/20"
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

        # avis-vin.lefigaro.fr/vins?page=N returns HTTP 400.
        # Individual wine detail pages require a Figaro Premium subscription —
        # no public numeric scores are accessible without authentication.
        write_dlq(
            self.conn, SOURCE_KEY, batch_id, "auth_error",
            "avis-vin.lefigaro.fr wine scores are paywalled. "
            "/vins?page=N returns HTTP 400. Individual wine pages require a Figaro Premium subscription. "
            "Re-implement with authenticated session when credentials are available.",
            {"url": _WINES_URL},
        )
        result.rows_dlq += 1
        return result
