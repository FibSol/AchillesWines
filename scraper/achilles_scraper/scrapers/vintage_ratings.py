# REGISTER_IN_CLI = True
"""
Vintage chart ratings scraper.

Fetches vintage-level ratings by region from:
  - Wine Spectator: https://www.winespectator.com/vintagecharts/ (public)
  - Decanter: https://www.decanter.com/wine-buying-guide/vintage-charts/ (public)

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

source_codes used: 'wine_spectator' and 'decanter' (both must be in dim_source)
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
from ..dlq import write_dlq

_logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_WS_URL = "https://www.winespectator.com/vintagecharts/"
_DECANTER_URL = "https://www.decanter.com/wine-buying-guide/vintage-charts/"

# Valid color values per schema
_VALID_COLORS = {"red", "white", "rosé", "sparkling", "sweet", "fortified", "all"}

# Region name normalisation: raw string → (country_code, region, subregion, color)
# Wine Spectator and Decanter use similar region labels
_WS_REGION_MAP: dict[str, tuple[str, str, Optional[str], str]] = {
    "Burgundy Red": ("FR", "Burgundy", None, "red"),
    "Burgundy White": ("FR", "Burgundy", None, "white"),
    "Bordeaux": ("FR", "Bordeaux", None, "red"),
    "Bordeaux White": ("FR", "Bordeaux", None, "white"),
    "Champagne": ("FR", "Champagne", None, "sparkling"),
    "Alsace": ("FR", "Alsace", None, "white"),
    "Loire": ("FR", "Loire", None, "white"),
    "Rhône Red": ("FR", "Rhône", None, "red"),
    "Rhône White": ("FR", "Rhône", None, "white"),
    "Sauternes": ("FR", "Bordeaux", "Sauternes", "sweet"),
    "Barolo/Barbaresco": ("IT", "Piedmont", None, "red"),
    "Tuscany": ("IT", "Tuscany", None, "red"),
    "Rioja": ("ES", "Rioja", None, "red"),
    "Ribera del Duero": ("ES", "Ribera del Duero", None, "red"),
    "Napa Cabernet": ("US", "Napa Valley", None, "red"),
    "Napa Chardonnay": ("US", "Napa Valley", None, "white"),
    "Vintage Port": ("PT", "Douro", "Port", "fortified"),
    "Mosel Riesling": ("DE", "Mosel", None, "white"),
    "Rheingau": ("DE", "Rheingau", None, "white"),
}

_DECANTER_REGION_MAP: dict[str, tuple[str, str, Optional[str], str]] = {
    "Burgundy Red": ("FR", "Burgundy", None, "red"),
    "Burgundy White": ("FR", "Burgundy", None, "white"),
    "Bordeaux Red": ("FR", "Bordeaux", None, "red"),
    "Bordeaux White": ("FR", "Bordeaux", None, "white"),
    "Champagne": ("FR", "Champagne", None, "sparkling"),
    "Alsace": ("FR", "Alsace", None, "white"),
    "Loire Red": ("FR", "Loire", None, "red"),
    "Loire White": ("FR", "Loire", None, "white"),
    "Rhône Red": ("FR", "Rhône", None, "red"),
    "Rhône White": ("FR", "Rhône", None, "white"),
    "Sauternes/Barsac": ("FR", "Bordeaux", "Sauternes", "sweet"),
    "Barolo": ("IT", "Piedmont", "Barolo", "red"),
    "Barbaresco": ("IT", "Piedmont", "Barbaresco", "red"),
    "Brunello di Montalcino": ("IT", "Tuscany", "Montalcino", "red"),
    "Rioja": ("ES", "Rioja", None, "red"),
    "Port": ("PT", "Douro", "Port", "fortified"),
    "Mosel": ("DE", "Mosel", None, "white"),
    "Rheingau": ("DE", "Rheingau", None, "white"),
    "Napa Valley Cabernet Sauvignon": ("US", "Napa Valley", None, "red"),
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
        _logger.error("DB error inserting vintage rating %s %s %d: %s", region, color, vintage, exc)
        result.rows_dlq += 1


def _scrape_wine_spectator(
    client: "httpx.Client",
    scraper: "VintageRatingsScraper",
    source_key: int,
    batch_id: str,
    result: ScrapeResult,
    limit: Optional[int],
) -> None:
    """Scrape Wine Spectator vintage charts."""
    url = _WS_URL
    try:
        resp = scraper._fetch(lambda: client.get(url))
        resp.raise_for_status()
    except Exception as exc:
        write_dlq(scraper.conn, source_key, batch_id, "network_error", str(exc), {"url": url})
        result.rows_dlq += 1
        return

    if resp.status_code in (401, 403, 429):
        write_dlq(scraper.conn, source_key, batch_id, "auth_error",
                   f"Blocked: HTTP {resp.status_code}", {"url": url})
        result.rows_dlq += 1
        return

    tree = HTMLParser(resp.text)

    # WS vintage chart: typically a table or grid with region rows and vintage columns
    # Look for vintage year headers and score cells
    # Structure varies; try multiple selectors
    tables = tree.css("table.vintage-chart, .vintage-chart table, table[class*='chart']")
    if not tables:
        tables = tree.css("table")

    for table in tables:
        if limit is not None and result.rows_inserted >= limit:
            break

        headers = table.css("th")
        header_texts = [h.text(strip=True) for h in headers]

        # Find vintage year columns (4-digit years in headers)
        year_cols: list[tuple[int, int]] = []  # (col_index, vintage_year)
        for i, ht in enumerate(header_texts):
            m = re.search(r"\b(19\d{2}|20[0-3]\d)\b", ht)
            if m:
                year_cols.append((i, int(m.group(1))))

        if not year_cols:
            continue

        rows = table.css("tr")
        for row in rows:
            if limit is not None and result.rows_inserted >= limit:
                break

            cells = row.css("td")
            if not cells:
                continue

            # First cell is typically the region name
            region_raw = cells[0].text(strip=True)
            region_info = _WS_REGION_MAP.get(region_raw)
            if region_info is None:
                # Try partial match
                for key, info in _WS_REGION_MAP.items():
                    if key.lower() in region_raw.lower() or region_raw.lower() in key.lower():
                        region_info = info
                        break

            if region_info is None:
                _logger.debug("WS: unknown region %r — skipping", region_raw)
                continue

            country_code, region, subregion, color = region_info

            for col_idx, vintage_year in year_cols:
                if col_idx < len(cells):
                    cell = cells[col_idx]
                    cell_text = cell.text(strip=True)

                    # WS scores are /100, sometimes with letters like "93-95" or "NV"
                    # Take the first number
                    score_match = re.search(r"\b(\d{2,3})\b", cell_text)
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

                    # Character notes: any non-numeric text in cell
                    notes_text = re.sub(r"\d+", "", cell_text).strip(" /-")
                    character_notes = notes_text if notes_text else None

                    result.rows_fetched += 1
                    _insert_vintage_rating(
                        scraper.conn, source_key, batch_id,
                        country_code, region, subregion, color,
                        vintage_year, score, scale, score_norm,
                        character_notes, url, result,
                    )


def _scrape_decanter_vintages(
    client: "httpx.Client",
    scraper: "VintageRatingsScraper",
    source_key: int,
    batch_id: str,
    result: ScrapeResult,
    limit: Optional[int],
) -> None:
    """Scrape Decanter vintage charts."""
    url = _DECANTER_URL
    try:
        resp = scraper._fetch(lambda: client.get(url))
        resp.raise_for_status()
    except Exception as exc:
        write_dlq(scraper.conn, source_key, batch_id, "network_error", str(exc), {"url": url})
        result.rows_dlq += 1
        return

    if resp.status_code in (401, 403, 429):
        write_dlq(scraper.conn, source_key, batch_id, "auth_error",
                   f"Blocked: HTTP {resp.status_code}", {"url": url})
        result.rows_dlq += 1
        return

    tree = HTMLParser(resp.text)

    # Decanter vintage chart: similar table structure
    tables = tree.css("table.vintage-chart, .vintage-chart-table, table[class*='vintage']")
    if not tables:
        tables = tree.css("table")

    for table in tables:
        if limit is not None and result.rows_inserted >= limit:
            break

        headers = table.css("th")
        header_texts = [h.text(strip=True) for h in headers]

        year_cols: list[tuple[int, int]] = []
        for i, ht in enumerate(header_texts):
            m = re.search(r"\b(19\d{2}|20[0-3]\d)\b", ht)
            if m:
                year_cols.append((i, int(m.group(1))))

        if not year_cols:
            continue

        rows = table.css("tr")
        for row in rows:
            if limit is not None and result.rows_inserted >= limit:
                break

            cells = row.css("td")
            if not cells:
                continue

            region_raw = cells[0].text(strip=True)
            region_info = _DECANTER_REGION_MAP.get(region_raw)
            if region_info is None:
                for key, info in _DECANTER_REGION_MAP.items():
                    if key.lower() in region_raw.lower() or region_raw.lower() in key.lower():
                        region_info = info
                        break

            if region_info is None:
                _logger.debug("Decanter: unknown region %r — skipping", region_raw)
                continue

            country_code, region, subregion, color = region_info

            for col_idx, vintage_year in year_cols:
                if col_idx < len(cells):
                    cell = cells[col_idx]
                    cell_text = cell.text(strip=True)

                    # Decanter uses /100 scale for vintage charts
                    score_match = re.search(r"\b(\d{2,3})\b", cell_text)
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

                    notes_text = re.sub(r"\d+", "", cell_text).strip(" /-")
                    character_notes = notes_text if notes_text else None

                    result.rows_fetched += 1
                    _insert_vintage_rating(
                        scraper.conn, source_key, batch_id,
                        country_code, region, subregion, color,
                        vintage_year, score, scale, score_norm,
                        character_notes, url, result,
                    )


class VintageRatingsScraper(BaseScraper):
    # Primary source_code — the class attribute; actual DB lookups use both WS + Decanter
    source_code = "wine_spectator"

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.batch_id: Optional[str] = None

    def run(self, limit: Optional[int] = None) -> ScrapeResult:
        if not HAS_DEPS:
            return ScrapeResult(error="Missing dependencies: httpx or selectolax not installed")

        batch_id = self.batch_id or f"vintage-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        result = ScrapeResult(batch_id=batch_id)

        # Resolve both source keys
        ws_row = self.conn.execute(
            "SELECT source_key FROM dim_source WHERE source_code = 'wine_spectator'"
        ).fetchone()
        dec_row = self.conn.execute(
            "SELECT source_key FROM dim_source WHERE source_code = 'decanter'"
        ).fetchone()

        if not ws_row and not dec_row:
            return ScrapeResult(
                error="Neither 'wine_spectator' nor 'decanter' found in dim_source"
            )

        headers = {
            "User-Agent": _USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,*/*",
            "Accept-Language": "en-US,en;q=0.9,fr;q=0.8",
        }

        with httpx.Client(headers=headers, timeout=30, follow_redirects=True) as client:
            if ws_row:
                ws_source_key = ws_row[0]
                _logger.info("Scraping Wine Spectator vintage charts (source_key=%d)", ws_source_key)
                _scrape_wine_spectator(client, self, ws_source_key, batch_id, result, limit)
                time.sleep(2.0)
            else:
                _logger.warning("'wine_spectator' not in dim_source — skipping WS vintage charts")

            if dec_row:
                dec_source_key = dec_row[0]
                if limit is None or result.rows_inserted < limit:
                    _logger.info("Scraping Decanter vintage charts (source_key=%d)", dec_source_key)
                    _scrape_decanter_vintages(client, self, dec_source_key, batch_id, result, limit)
            else:
                _logger.warning("'decanter' not in dim_source — skipping Decanter vintage charts")

        return result
