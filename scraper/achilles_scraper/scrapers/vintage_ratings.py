# REGISTER_IN_CLI = True
"""
Vintage chart ratings scraper.

Fetches vintage-level ratings by region from:
  - Wine Spectator: per-region sub-pages at
    https://www.winespectator.com/vintage-charts/region/<slug>  (public)
  - Decanter: https://www.decanter.com/wine-buying-guide/vintage-charts/ (404 — disabled)

Data is in a <table> on each region sub-page.  Each <tr> contains:
  td[0]: vintage year  (a.font-bold link text, preceded by h5 "Vintage")
  td[1]: score         (bare number, preceded by h5 "Score")
  td[2]: drink window  (text, preceded by h5 "Drink Window")
  td[3]: description   (text, td.d-none.d-md-table-cell)

Writes to `fact_vintage_rating` (NOT fact_rating).

fact_vintage_rating columns:
  vintage_rating_key  — autoincrement PK
  country_code        — TEXT NOT NULL
  region              — TEXT NOT NULL
  subregion           — TEXT (nullable)
  color               — TEXT ('red','white','rosé','sparkling','sweet','fortified','all')
  vintage             — INT NOT NULL
  source_key          — INT FK
  score               — REAL NOT NULL
  scale               — TEXT ('/100', '/20', '/5')
  score_normalized_100 — REAL NOT NULL
  character_notes     — TEXT (nullable)
  source_url          — TEXT
  recorded_at         — INT (unixepoch default)

Unique constraint: (country_code, region, subregion, color, vintage, source_key)
→ use INSERT OR IGNORE for dedup.

source_codes used: 'wine_spectator' (both must be in dim_source)
NOTE: Decanter vintage charts returns 404 — that fetch is disabled.
"""
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
from ..dlq import write_dlq

_logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_WS_BASE = "https://www.winespectator.com"

# Decanter vintage chart URL returns 404 — disabled until fixed upstream.
# _DECANTER_URL = "https://www.decanter.com/wine-buying-guide/vintage-charts/"

# Valid color values per schema
_VALID_COLORS = {"red", "white", "rosé", "sparkling", "sweet", "fortified", "all"}

# Map of WS region slugs → (country_code, region, subregion, color)
_WS_REGION_SLUG_MAP: dict[str, tuple[str, str, Optional[str], str]] = {
    "burgundy-cotes-de-nuits-reds":              ("FR", "Burgundy", "Côte de Nuits", "red"),
    "burgundy-cotes-de-beaune-reds":             ("FR", "Burgundy", "Côte de Beaune", "red"),
    "burgundy-white":                            ("FR", "Burgundy", None, "white"),
    "burgundy-older-vintage-reds":               ("FR", "Burgundy", None, "red"),
    "bordeaux-left-bank-reds-medoc-pessac-leognan": ("FR", "Bordeaux", "Left Bank", "red"),
    "bordeaux-right-bank-reds-pomerol-st-emilion":  ("FR", "Bordeaux", "Right Bank", "red"),
    "bordeaux-sauternes":                        ("FR", "Bordeaux", "Sauternes", "sweet"),
    "bordeaux-vintage-reds-pre-1995":            ("FR", "Bordeaux", None, "red"),
    "champagne":                                 ("FR", "Champagne", None, "sparkling"),
    "alsace":                                    ("FR", "Alsace", None, "white"),
    "loire":                                     ("FR", "Loire", None, "white"),
    "rhone-northern":                            ("FR", "Rhône", "Northern", "red"),
    "rhone-southern":                            ("FR", "Rhône", "Southern", "red"),
}


def _normalize_score_to_100(score: float, scale: str) -> Optional[float]:
    if scale == "/100":
        return score if 0 <= score <= 100 else None
    if scale == "/20":
        return (score / 20.0) * 100.0 if 0 <= score <= 20 else None
    if scale == "/5":
        return (score / 5.0) * 100.0 if 0 <= score <= 5 else None
    return None


def _insert_vintage_rating(
    conn: sqlite3.Connection,
    source_key: int,
    batch_id: str,
    country_code: str,
    region: str,
    subregion: Optional[str],
    color: str,
    vintage: int,
    score: float,
    scale: str,
    score_norm: float,
    character_notes: Optional[str],
    source_url: str,
    result: ScrapeResult,
) -> None:
    """Insert a single vintage rating row, handling dedup via INSERT OR IGNORE."""
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO fact_vintage_rating
            (country_code, region, subregion, color, vintage, source_key,
             score, scale, score_normalized_100, character_notes, source_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (country_code, region, subregion, color, vintage, source_key,
             score, scale, score_norm, character_notes, source_url),
        )
        conn.commit()
        result.rows_inserted += 1
    except Exception as exc:
        _logger.error(
            "DB error inserting vintage rating %s %s %d: %s", region, color, vintage, exc
        )
        result.rows_dlq += 1


def _scrape_ws_region(
    client: "httpx.Client",
    scraper: "VintageRatingsScraper",
    slug: str,
    region_info: tuple,
    source_key: int,
    batch_id: str,
    result: ScrapeResult,
    limit: Optional[int],
) -> None:
    """Scrape one Wine Spectator region sub-page and insert vintage ratings."""
    url = f"{_WS_BASE}/vintage-charts/region/{slug}"
    country_code, region, subregion, color = region_info

    try:
        resp = scraper._fetch(lambda: client.get(url))
        resp.raise_for_status()
    except Exception as exc:
        write_dlq(scraper.conn, source_key, batch_id, "network_error", str(exc), {"url": url})
        result.rows_dlq += 1
        return

    if resp.status_code in (401, 403, 429):
        write_dlq(
            scraper.conn, source_key, batch_id, "auth_error",
            f"Blocked: HTTP {resp.status_code}", {"url": url},
        )
        result.rows_dlq += 1
        return

    tree = HTMLParser(resp.text)

    # Table rows: td[0]=year, td[1]=score, td[2]=drink, td[3]=description
    # Each row has an a.font-bold link whose text is the vintage year.
    rows = tree.css("tr")
    fetched_here = 0
    for row in rows:
        if limit is not None and result.rows_inserted >= limit:
            break

        tds = row.css("td")
        if len(tds) < 2:
            continue

        year_link = tds[0].css_first("a.font-bold")
        if not year_link:
            continue

        year_text = year_link.text(strip=True)
        try:
            vintage_year = int(year_text)
        except ValueError:
            continue

        if not (1900 <= vintage_year <= 2030):
            continue

        # Score cell: text like "Score98" (the h5 mobile label is included in text())
        # Strip the "Score" prefix
        score_raw_text = tds[1].text(strip=True)
        score_raw_text = re.sub(r"^Score\s*", "", score_raw_text, flags=re.I).strip()
        # Take the first integer (handles "95-97" → 95, or range midpoint)
        score_match = re.search(r"\b(\d{2,3})\b", score_raw_text)
        if not score_match:
            continue

        try:
            score = float(score_match.group(1))
        except ValueError:
            continue

        if not (50 <= score <= 100):
            continue

        scale = "/100"
        score_norm = _normalize_score_to_100(score, scale)
        if score_norm is None:
            continue

        # Description (4th td, mobile h5 prefix stripped)
        character_notes: Optional[str] = None
        if len(tds) >= 4:
            desc_text = tds[3].text(strip=True)
            desc_text = re.sub(r"^Description\s*", "", desc_text, flags=re.I).strip()
            if desc_text:
                character_notes = desc_text[:500]

        result.rows_fetched += 1
        fetched_here += 1
        _insert_vintage_rating(
            scraper.conn, source_key, batch_id,
            country_code, region, subregion, color,
            vintage_year, score, scale, score_norm,
            character_notes, url, result,
        )

    _logger.info("WS slug=%s → %d rows fetched", slug, fetched_here)


class VintageRatingsScraper(BaseScraper):
    # Primary source_code — the class attribute; actual DB lookups use wine_spectator
    source_code = "wine_spectator"

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.batch_id: Optional[str] = None

    def run(self, limit: Optional[int] = None) -> ScrapeResult:
        if not HAS_DEPS:
            return ScrapeResult(error="Missing dependencies: httpx or selectolax not installed")

        batch_id = self.batch_id or (
            f"vintage-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
            f"-{uuid.uuid4().hex[:8]}"
        )
        result = ScrapeResult(batch_id=batch_id)

        # Resolve Wine Spectator source key
        ws_row = self.conn.execute(
            "SELECT source_key FROM dim_source WHERE source_code = 'wine_spectator'"
        ).fetchone()

        if not ws_row:
            return ScrapeResult(
                error="'wine_spectator' not found in dim_source"
            )

        ws_source_key = ws_row[0]

        headers = {
            "User-Agent": _USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,*/*",
            "Accept-Language": "en-US,en;q=0.9,fr;q=0.8",
        }

        with httpx.Client(headers=headers, timeout=30, follow_redirects=True) as client:
            for slug, region_info in _WS_REGION_SLUG_MAP.items():
                if limit is not None and result.rows_inserted >= limit:
                    break

                _logger.info("Scraping Wine Spectator: %s", slug)
                _scrape_ws_region(
                    client, self, slug, region_info,
                    ws_source_key, batch_id, result, limit,
                )
                # Polite delay between region pages
                time.sleep(1.5)

        return result
