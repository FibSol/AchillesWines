# REGISTER_IN_CLI = True
"""
CellarTracker.com scraper — community wine database with crowd ratings.

Fetches wine pages via the Firecrawl /v1/scrape API (proxy + headless browser)
which bypasses CellarTracker's Kasada anti-bot protection.

Requires: FIRECRAWL_API_KEY env var.

Crawl strategy:
- Resumable cursor in data/cellartracker_cursor.txt (last successful iWine).
- `--limit` = number of iWine ids to attempt (NOT rows inserted — many ids are
  gaps / deleted wines / no community score).
- ACHILLES_CT_START_ID overrides cursor for a cold re-crawl.
- Each Firecrawl scrape costs 1 credit. Default limit=100 per run.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import re
import sqlite3
import time
import uuid
from datetime import datetime
from pathlib import Path
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

_FIRECRAWL_SCRAPE_URL = "https://api.firecrawl.dev/v1/scrape"
_FC_ENV_KEY = "FIRECRAWL_API_KEY"

_logger = logging.getLogger(__name__)

_BASE = "https://www.cellartracker.com"
_WINE_URL = f"{_BASE}/wine.asp?iWine="

CRITIC_CODE = "CT"
SCALE = "/100"

# Wine "Type" strings on CT → our color enum.
_TYPE_TO_COLOR = {
    "red": "red",
    "white": "white",
    "rosé": "rosé",
    "rose": "rosé",
    "pink": "rosé",
    "sparkling": "sparkling",
    "champagne": "sparkling",
    "dessert": "sweet",
    "sweet": "sweet",
    "fortified": "fortified",
    "port": "fortified",
    "sherry": "fortified",
    "madeira": "fortified",
    "orange": "orange",
    "white - sweet/dessert": "sweet",
    "white - sparkling": "sparkling",
}

# Best-effort country → ISO-2 mapping for the most common CT countries.
_COUNTRY_TO_ISO2 = {
    "france": "FR",
    "italy": "IT",
    "spain": "ES",
    "portugal": "PT",
    "germany": "DE",
    "austria": "AT",
    "usa": "US",
    "united states": "US",
    "argentina": "AR",
    "chile": "CL",
    "australia": "AU",
    "new zealand": "NZ",
    "south africa": "ZA",
    "hungary": "HU",
    "greece": "GR",
    "switzerland": "CH",
    "belgium": "BE",
    "luxembourg": "LU",
    "canada": "CA",
    "uruguay": "UY",
    "lebanon": "LB",
    "israel": "IL",
    "georgia": "GE",
    "romania": "RO",
    "slovenia": "SI",
    "croatia": "HR",
    "bulgaria": "BG",
    "moldova": "MD",
    "japan": "JP",
    "china": "CN",
    "england": "GB",
    "united kingdom": "GB",
}

_CURSOR_PATH = Path("data/cellartracker_cursor.txt")


def _load_cursor(default_start: int = 1) -> int:
    try:
        env_start = os.getenv("ACHILLES_CT_START_ID", "").strip()
        if env_start:
            return max(1, int(env_start))
        if _CURSOR_PATH.exists():
            txt = _CURSOR_PATH.read_text(encoding="utf-8").strip()
            if txt:
                return max(1, int(txt) + 1)
    except Exception:
        pass
    return default_start


def _save_cursor(iwine: int) -> None:
    try:
        _CURSOR_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CURSOR_PATH.write_text(str(iwine), encoding="utf-8")
    except Exception:
        pass


def _map_color(raw: str) -> Optional[str]:
    if not raw:
        return None
    key = raw.strip().lower()
    if key in _TYPE_TO_COLOR:
        return _TYPE_TO_COLOR[key]
    # CT sometimes uses compound types like "Red - Bordeaux Blend"
    head = key.split("-")[0].strip()
    return _TYPE_TO_COLOR.get(head)


def _map_country(raw: str) -> Optional[str]:
    if not raw:
        return None
    return _COUNTRY_TO_ISO2.get(raw.strip().lower())


def _ensure_source(conn: sqlite3.Connection) -> Optional[int]:
    row = conn.execute(
        "SELECT source_key FROM dim_source WHERE source_code = ?", ("cellartracker",)
    ).fetchone()
    if row:
        return row[0]
    try:
        conn.execute(
            """INSERT OR IGNORE INTO dim_source
               (source_code, source_name, source_tier, cadence, base_url,
                license_class, enabled, requires_auth, notes)
               VALUES (?, ?, 'F_crowd_aggregator', 'on_demand', ?,
                       'public_check_terms', 1, 1,
                       'Community wine DB. Iterate wine.asp?iWine=N. critic_code=CT, reviewer_type=crowd.')""",
            ("cellartracker", "CellarTracker", _BASE),
        )
        conn.commit()
    except Exception as e:
        _logger.warning("could not insert cellartracker dim_source row: %s", e)
        return None
    row = conn.execute(
        "SELECT source_key FROM dim_source WHERE source_code = ?", ("cellartracker",)
    ).fetchone()
    return row[0] if row else None


def _find_appellation_key(conn: sqlite3.Connection, country: str, appellation_norm: str) -> Optional[int]:
    if not appellation_norm or not country:
        return None
    row = conn.execute(
        "SELECT appellation_key FROM dim_appellation WHERE country_code = ? AND appellation_norm = ?",
        (country, appellation_norm),
    ).fetchone()
    return row[0] if row else None


def _ensure_appellation(
    conn: sqlite3.Connection,
    country: str,
    region: str,
    appellation_name: str,
    appellation_norm: str,
) -> Optional[int]:
    if not country or not appellation_norm:
        return None
    existing = _find_appellation_key(conn, country, appellation_norm)
    if existing:
        return existing
    if not appellation_name or not region:
        return None
    try:
        cur = conn.execute(
            """INSERT OR IGNORE INTO dim_appellation
               (country_code, region, appellation_name, appellation_norm, level)
               VALUES (?, ?, ?, ?, 'regional')""",
            (country, region, appellation_name, appellation_norm),
        )
        conn.commit()
        if cur.lastrowid:
            return cur.lastrowid
        return _find_appellation_key(conn, country, appellation_norm)
    except Exception:
        return None


def _ensure_producer(conn: sqlite3.Connection, country: str, producer_norm: str, producer_name: str) -> Optional[int]:
    if not country or not producer_norm:
        return None
    row = conn.execute(
        "SELECT producer_key FROM dim_producer WHERE producer_norm = ? AND country_code = ?",
        (producer_norm, country),
    ).fetchone()
    if row:
        return row[0]
    try:
        cur = conn.execute(
            """INSERT OR IGNORE INTO dim_producer
               (producer_name, producer_norm, country_code, allowed_appellations, aliases, status)
               VALUES (?, ?, ?, '[]', '[]', 'pending_review')""",
            (producer_name, producer_norm, country),
        )
        conn.commit()
        if cur.lastrowid:
            return cur.lastrowid
    except Exception:
        return None
    row = conn.execute(
        "SELECT producer_key FROM dim_producer WHERE producer_norm = ? AND country_code = ?",
        (producer_norm, country),
    ).fetchone()
    return row[0] if row else None


def _ensure_wine(
    conn: sqlite3.Connection,
    wine_key: str,
    producer_key: int,
    appellation_key: int,
    cuvee_name: str,
    cuvee_norm: str,
    color: str,
    vintage: Optional[int],
) -> bool:
    if conn.execute("SELECT 1 FROM dim_wine WHERE wine_key = ?", (wine_key,)).fetchone():
        return True
    is_nv = 1 if vintage is None else 0
    try:
        conn.execute(
            """INSERT OR IGNORE INTO dim_wine
               (wine_key, producer_key, appellation_key, cuvee_name, cuvee_norm,
                color, vintage, is_non_vintage, bottle_ml, canonical_name)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 750, ?)""",
            (wine_key, producer_key, appellation_key, cuvee_name, cuvee_norm,
             color, vintage, is_nv, cuvee_name),
        )
        conn.commit()
        return True
    except Exception:
        return False


# --- HTML parsing -----------------------------------------------------------

_RE_VINTAGE = re.compile(r"\b(1[89]\d{2}|20[0-3]\d)\b")
_RE_SCORE = re.compile(r"(\d{2,3}(?:\.\d)?)")
_RE_NOTES = re.compile(r"(\d[\d,]*)\s+(?:community\s+)?(?:tasting\s+)?notes?", re.I)

_NOT_FOUND_DESIGNATIONS = {"n/a", "n.a.", "na", "unknown", ""}


def _parse_wine_list(tree: HTMLParser) -> dict[str, str]:
    """Extract wine metadata from the current CT layout.

    CT now renders wine details in::

        <ul class="twin_set_list">
          <li><span>Vintage</span><a href="...">1997</a></li>
          <li><span>Producer</span><a href="...">Abreu</a></li>
          ...
        </ul>

    Returns a flat dict with lower-cased label keys.
    """
    out: dict[str, str] = {}
    ul = tree.css_first("ul.twin_set_list")
    if ul is None:
        return out
    for li in ul.css("li"):
        label_node = li.css_first("span")
        if label_node is None:
            continue
        label = _text_of(label_node).rstrip(":").strip().lower()
        # Value is the first link or the remaining text after the span
        link = li.css_first("a")
        value = _text_of(link) if link else ""
        if not value:
            full = _text_of(li)
            label_raw = _text_of(label_node)
            value = full[len(label_raw):].strip()
        if label and value:
            out[label] = value
    return out


def _parse_score_v2(tree: HTMLParser) -> tuple[Optional[float], Optional[int]]:
    """Parse community avg score from the current CT wine page layout.

    Score: ``<span class="rating">95.7</span>`` inside a ``.score`` element.
    Notes count: from ``<meta property="og:description">`` content.
    """
    node = tree.css_first("span.rating")
    if node:
        m = _RE_SCORE.search(_text_of(node))
        if m:
            try:
                score = float(m.group(1))
                if 50.0 <= score <= 100.0:
                    notes: Optional[int] = None
                    og = tree.css_first('meta[property="og:description"]')
                    if og:
                        content = og.attrs.get("content", "") or ""
                        nm = re.search(r"(\d[\d,]*)\s+community\s+wine\s+reviews?", content, re.I)
                        if nm:
                            notes = int(nm.group(1).replace(",", ""))
                    return score, notes
            except ValueError:
                pass
    # Fallback to legacy parser
    return None, None


def _text_of(node) -> str:
    if node is None:
        return ""
    return re.sub(r"\s+", " ", node.text(strip=True) or "").strip()


def _parse_table_pairs(tree: HTMLParser) -> dict[str, str]:
    """Extract the small 'Producer / Designation / Vintage / Varietal / Country
    / Region / SubRegion / Appellation / Type' label-value table that appears
    near the top of every wine.asp page.
    """
    out: dict[str, str] = {}
    for table in tree.css("table"):
        rows = table.css("tr")
        for tr in rows:
            cells = tr.css("td, th")
            if len(cells) < 2:
                continue
            label = _text_of(cells[0]).rstrip(":").strip().lower()
            value = _text_of(cells[1])
            if label and value and label in {
                "producer", "designation", "vintage", "varietal", "varietal(s)",
                "country", "region", "subregion", "sub-region", "appellation",
                "type", "wine"
            }:
                out[label] = value
    return out


def _parse_score(tree: HTMLParser) -> tuple[Optional[float], Optional[int]]:
    """Return (community_avg_100, num_notes) from a wine summary page.

    CT renders the community score in a few different shapes depending on
    template version. We probe the common ones and fall back to a regex over
    the page text.
    """
    # Shape 1: <span class="bigScore">92.3</span>  ... <a>123 notes</a>
    for sel in (".bigScore", ".CT_score", ".score", "#community_avg"):
        node = tree.css_first(sel)
        if node:
            txt = _text_of(node)
            m = _RE_SCORE.search(txt)
            if m:
                try:
                    score = float(m.group(1))
                    if 50.0 <= score <= 100.0:
                        body_text = tree.body.text(separator=" ") if tree.body else ""
                        n = _RE_NOTES.search(body_text)
                        notes = int(n.group(1).replace(",", "")) if n else None
                        return score, notes
                except ValueError:
                    pass

    # Shape 2: full-page regex fallback — look for "CT 92.3" or "Score: 92.3"
    body_text = tree.body.text(separator=" ") if tree.body else ""
    m = re.search(r"(?:CT|Community\s+score|Avg(?:erage)?\s+score)[^\d]{0,8}(\d{2,3}(?:\.\d)?)", body_text, re.I)
    if m:
        try:
            score = float(m.group(1))
            if 50.0 <= score <= 100.0:
                n = _RE_NOTES.search(body_text)
                notes = int(n.group(1).replace(",", "")) if n else None
                return score, notes
        except ValueError:
            pass
    return None, None


def _is_not_found(tree: HTMLParser, status_code: int) -> bool:
    if status_code in (404, 410):
        return True
    if not tree.body:
        return True
    body = (tree.body.text(separator=" ") or "").lower()
    # CloudFront/CDN error pages returned when the proxy is blocked
    if "cloudfront" in body and ("403 error" in body or "request blocked" in body):
        return True
    return (
        "wine not found" in body
        or "no such wine" in body
        or "this wine has been deleted" in body
    )


class CellarTrackerScraper(BaseScraper):
    """Fetches CellarTracker wine pages via Firecrawl (bypasses Kasada anti-bot)."""

    source_code = "cellartracker"

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.batch_id: Optional[str] = None

    def run(self, limit: Optional[int] = None) -> ScrapeResult:
        if not HAS_DEPS:
            return ScrapeResult(error="Missing dependencies: httpx or selectolax not installed")

        api_key = os.environ.get(_FC_ENV_KEY, "").strip()
        if not api_key:
            return ScrapeResult(
                error=f"{_FC_ENV_KEY} not set — required for CellarTracker (Firecrawl bypasses Kasada)"
            )

        batch_id = self.batch_id or f"ct-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        result = ScrapeResult(batch_id=batch_id)

        SOURCE_KEY = _ensure_source(self.conn)
        if SOURCE_KEY is None:
            return ScrapeResult(error="could not resolve or create dim_source row for 'cellartracker'")

        attempts_budget = limit if limit is not None else 100  # each attempt costs 1 Firecrawl credit
        start_id = _load_cursor(default_start=1)

        fc_headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        consecutive_404 = 0
        with httpx.Client(timeout=60, follow_redirects=True) as client:
            for i in range(attempts_budget):
                iwine = start_id + i
                wine_url = f"{_WINE_URL}{iwine}"

                # Fetch via Firecrawl — handles Kasada JS challenge
                try:
                    fc_resp = client.post(
                        _FIRECRAWL_SCRAPE_URL,
                        headers=fc_headers,
                        json={
                            "url": wine_url,
                            "formats": ["rawHtml"],
                            "waitFor": 3000,
                            "mobile": False,
                        },
                    )
                except Exception as e:
                    write_dlq(self.conn, SOURCE_KEY, batch_id, "network_error", str(e), {"iWine": iwine})
                    result.rows_dlq += 1
                    _save_cursor(iwine)
                    continue

                if fc_resp.status_code == 401:
                    result.error = f"Firecrawl 401 — check {_FC_ENV_KEY}"
                    break
                if fc_resp.status_code == 429:
                    write_dlq(self.conn, SOURCE_KEY, batch_id, "network_error",
                              "Firecrawl rate limit (429)", {"iWine": iwine})
                    result.rows_dlq += 1
                    time.sleep(30)
                    continue
                if not fc_resp.is_success:
                    write_dlq(self.conn, SOURCE_KEY, batch_id, "network_error",
                              f"Firecrawl HTTP {fc_resp.status_code}", {"iWine": iwine})
                    result.rows_dlq += 1
                    _save_cursor(iwine)
                    continue

                try:
                    fc_data = fc_resp.json()
                except Exception:
                    write_dlq(self.conn, SOURCE_KEY, batch_id, "parse_error",
                              "Firecrawl JSON decode failed", {"iWine": iwine})
                    result.rows_dlq += 1
                    _save_cursor(iwine)
                    continue

                raw_html = (fc_data.get("data") or {}).get("rawHtml") or ""
                ct_status = (fc_data.get("data") or {}).get("metadata", {}).get("statusCode", 200)

                tree = HTMLParser(raw_html)
                if _is_not_found(tree, ct_status):
                    consecutive_404 += 1
                    _save_cursor(iwine)
                    if consecutive_404 >= 200 and iwine > 2_000_000:
                        result.error = f"stopping at iWine={iwine} after {consecutive_404} consecutive misses"
                        break
                    continue
                consecutive_404 = 0
                result.rows_fetched += 1

                pairs = _parse_table_pairs(tree)
                producer_raw = pairs.get("producer", "")
                designation = pairs.get("designation", "") or pairs.get("wine", "")
                vintage_raw = pairs.get("vintage", "")
                country_raw = pairs.get("country", "")
                region_raw = pairs.get("region", "")
                appellation_raw = (
                    pairs.get("appellation", "")
                    or pairs.get("subregion", "")
                    or pairs.get("sub-region", "")
                )
                type_raw = pairs.get("type", "")

                if not producer_raw or not designation:
                    write_dlq(self.conn, SOURCE_KEY, batch_id, "parse_error",
                              "missing producer or designation", {"iWine": iwine, "pairs": pairs})
                    result.rows_dlq += 1
                    _save_cursor(iwine)
                    continue

                vintage: Optional[int] = None
                vraw = (vintage_raw or "").strip().upper()
                if vraw and vraw not in {"NV", "N.V.", "NON-VINTAGE", "N/A", "-"}:
                    m = _RE_VINTAGE.search(vraw)
                    if m:
                        v = int(m.group(1))
                        if 1900 <= v <= 2040:
                            vintage = v

                country = _map_country(country_raw)
                color = _map_color(type_raw) or "red"

                if not country:
                    write_dlq(self.conn, SOURCE_KEY, batch_id, "unresolved_dim",
                              f"unmapped country: {country_raw!r}",
                              {"iWine": iwine, "producer": producer_raw, "country": country_raw})
                    result.rows_dlq += 1
                    _save_cursor(iwine)
                    continue

                producer_norm = normalize_producer(producer_raw)
                cuvee_norm = normalize_cuvee(designation)
                appellation_name = appellation_raw or region_raw or ""
                appellation_norm = norm_text(appellation_name) if appellation_name else norm_text(region_raw)
                region = region_raw or appellation_name

                if not producer_norm or not cuvee_norm:
                    write_dlq(self.conn, SOURCE_KEY, batch_id, "parse_error",
                              "empty producer_norm or cuvee_norm after normalisation",
                              {"iWine": iwine, "producer": producer_raw, "designation": designation})
                    result.rows_dlq += 1
                    _save_cursor(iwine)
                    continue

                producer_key = _ensure_producer(self.conn, country, producer_norm, producer_raw)
                appellation_key = _ensure_appellation(
                    self.conn, country, region or "Unknown",
                    appellation_name or region or "Unknown",
                    appellation_norm or norm_text(region or "Unknown"),
                )
                if producer_key is None or appellation_key is None:
                    write_dlq(self.conn, SOURCE_KEY, batch_id, "unresolved_dim",
                              "could not resolve producer or appellation",
                              {"iWine": iwine, "producer": producer_raw,
                               "appellation": appellation_name, "country": country})
                    result.rows_dlq += 1
                    _save_cursor(iwine)
                    continue

                wine_key = compute_wine_key(producer_norm, cuvee_norm, vintage, appellation_norm)
                _ensure_wine(self.conn, wine_key, producer_key, appellation_key,
                             designation, cuvee_norm, color, vintage)

                score, notes = _parse_score(tree)
                if score is None:
                    result.rows_skipped_unchanged += 1
                    _save_cursor(iwine)
                    continue

                content_hash = hashlib.sha256(
                    json.dumps(
                        {"wine_key": wine_key, "score": score, "notes": notes, "iWine": iwine},
                        sort_keys=True,
                    ).encode()
                ).hexdigest()

                try:
                    self.conn.execute(
                        """INSERT OR IGNORE INTO fact_rating
                           (wine_key, source_key, critic_code, reviewer_type,
                            score, scale, score_normalized_100,
                            source_url, content_hash, batch_id)
                           VALUES (?, ?, ?, 'crowd', ?, ?, ?, ?, ?, ?)""",
                        (wine_key, SOURCE_KEY, CRITIC_CODE,
                         score, SCALE, score, wine_url, content_hash, batch_id),
                    )
                    self.conn.commit()
                    result.rows_inserted += 1
                except Exception as e:
                    write_dlq(self.conn, SOURCE_KEY, batch_id, "validation_error",
                              str(e), {"iWine": iwine, "wine_key": wine_key, "score": score})
                    result.rows_dlq += 1

                _save_cursor(iwine)

        return result
