# REGISTER_IN_CLI = True
"""
CellarTracker.com scraper — community wine database with crowd ratings.

CellarTracker is the world's largest user-driven wine database (~6M+ wines,
~10M+ tasting notes). Every wine has a stable integer id and lives at
    https://www.cellartracker.com/wine.asp?iWine=<N>
Range: 1 .. ~6_500_000 (sparse — many gaps for deleted/private/merged wines).

What we capture (→ fact_rating with critic_code='CT', reviewer_type='crowd'):
- Producer, designation (cuvée), vintage, varietal, country, region, appellation
- Community average score (CT 100-point scale) + number of notes
- Wine type → color mapping

What we deliberately skip:
- Tasting note text (huge volume, copyrighted by individual users)
- Market prices (per project rule — prices come from retailer scrapers only)
- Private / hidden wines (login still resolves but score absent)

Credentials: ACHILLES_AUTH_CELLARTRACKER_USERNAME / _PASSWORD
The site enforces a session cookie via POST to /password.asp.

Crawl strategy:
- Resumable cursor stored in data/cellartracker_cursor.txt (last successful iWine).
- `--limit` controls how many iWine ids to attempt this run (NOT how many rows
  to insert — many ids 404 or have no community score yet).
- `ACHILLES_CT_START_ID` env var overrides the cursor (useful for re-crawls
  or starting cold). Defaults to 1 on first run.
- Polite default delay of 0.6s between requests, jittered.

The site has no public terms-of-service block on personal/research scraping
at low rates, but we keep concurrency at 1 and obey 429s with exponential
backoff via the shared retry wrapper.

⚠ KNOWN LIMITATION (2026-05-23 smoke test): CellarTracker is fronted by
CloudFront with an aggressive edge ruleset that returns HTTP 403
("Request blocked") for plain httpx clients — even the homepage. Real
browser headers (Sec-CH-UA, HTTP/2, full Accept-Language) do not bypass it;
the block is almost certainly TLS-fingerprint based (httpx ≠ Chrome JA3).

To make this scraper actually fetch pages we need one of:
  (a) Playwright (real Chromium) — slow but reliable. See
      scripts/playwright_ct_session.py for a starter once implemented.
  (b) curl_cffi / tls-client to spoof Chrome's JA3 over plain HTTP.
  (c) Routing through CellarTracker's own bulk-export endpoints
      (xlquery.asp / Cellar.xml) — these bypass CloudFront-edge rules but
      only expose the *logged-in user's own cellar*, not the global DB.

Until one of the above is wired in, `.run()` will return ScrapeResult with
network_error rows in the DLQ and rows_fetched=0. The module is still
useful as scaffolding: dim_source registration, parse helpers, cursor file.
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

from .base import ScrapeResult
from ..auth import AuthenticatedScraper, has_credentials, AuthMissingError, AuthError, Credentials
from ..identity import normalize_producer, normalize_cuvee, compute_wine_key, norm_text
from ..dlq import write_dlq

_logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_BASE = "https://www.cellartracker.com"
_LOGIN_URL = f"{_BASE}/password.asp"
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
    return (
        "wine not found" in body
        or "no such wine" in body
        or "this wine has been deleted" in body
    )


class CellarTrackerScraper(AuthenticatedScraper):
    source_code = "cellartracker"

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.batch_id: Optional[str] = None

    def _login(self, client: "httpx.Client", creds: Credentials) -> bool:
        # CT's classic ASP login: POST /password.asp with szLogin/szPassword.
        # Successful login sets a session cookie ("CTSession" or similar) and
        # redirects to the homepage. We just confirm we land on a non-login page.
        resp = client.post(
            _LOGIN_URL,
            data={
                "szLogin": creds.username,
                "szPassword": creds.password,
                "Remember": "True",
                "Login": "Sign+In",
            },
            headers={
                "User-Agent": _USER_AGENT,
                "Referer": _LOGIN_URL,
                "Origin": _BASE,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        if resp.status_code >= 500:
            raise AuthError(f"CT login HTTP {resp.status_code}")
        # Heuristic: a logged-in cookie is set, OR follow-up GET of /default.asp
        # shows the username / "Sign out" link.
        probe = client.get(f"{_BASE}/default.asp", headers={"User-Agent": _USER_AGENT})
        if probe.status_code != 200:
            return False
        body = (probe.text or "").lower()
        return ("sign out" in body) or ("logout" in body) or (creds.username.lower() in body)

    def run(self, limit: Optional[int] = None) -> ScrapeResult:
        if not HAS_DEPS:
            return ScrapeResult(error="Missing dependencies: httpx or selectolax not installed")
        if not has_credentials(self.source_code):
            return ScrapeResult(
                error="Credentials missing: set ACHILLES_AUTH_CELLARTRACKER_USERNAME / _PASSWORD"
            )

        batch_id = self.batch_id or f"ct-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        result = ScrapeResult(batch_id=batch_id)

        SOURCE_KEY = _ensure_source(self.conn)
        if SOURCE_KEY is None:
            return ScrapeResult(error="could not resolve or create dim_source row for 'cellartracker'")

        attempts_budget = limit if limit is not None else 500  # iWine ids to try this run
        start_id = _load_cursor(default_start=1)

        headers = {
            "User-Agent": _USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
            "Accept-Language": "en-US,en;q=0.7,fr;q=0.5",
        }

        try:
            client = self.authenticated_client(headers=headers)
        except AuthMissingError as e:
            return ScrapeResult(error=str(e))
        except AuthError as e:
            return ScrapeResult(error=str(e))

        delay_min = float(os.getenv("ACHILLES_CT_DELAY_MIN", "0.5"))
        delay_max = float(os.getenv("ACHILLES_CT_DELAY_MAX", "0.9"))

        consecutive_404 = 0
        try:
            for i in range(attempts_budget):
                iwine = start_id + i
                url = f"{_WINE_URL}{iwine}"
                try:
                    resp = self._fetch(lambda u=url: client.get(u))
                except Exception as e:
                    write_dlq(self.conn, SOURCE_KEY, batch_id, "network_error", str(e), {"iWine": iwine})
                    result.rows_dlq += 1
                    _save_cursor(iwine)
                    continue

                tree = HTMLParser(resp.text or "")
                if _is_not_found(tree, resp.status_code):
                    consecutive_404 += 1
                    _save_cursor(iwine)
                    # If we hit 200 consecutive 404s past iWine=2_000_000, assume tail of range
                    if consecutive_404 >= 200 and iwine > 2_000_000:
                        result.error = f"stopping early at iWine={iwine} after {consecutive_404} consecutive misses"
                        break
                    continue
                consecutive_404 = 0
                result.rows_fetched += 1

                if resp.status_code != 200:
                    write_dlq(self.conn, SOURCE_KEY, batch_id, "network_error",
                              f"HTTP {resp.status_code}", {"iWine": iwine})
                    result.rows_dlq += 1
                    _save_cursor(iwine)
                    continue

                pairs = _parse_table_pairs(tree)
                producer_raw = pairs.get("producer", "")
                designation = pairs.get("designation", "") or pairs.get("wine", "")
                vintage_raw = pairs.get("vintage", "")
                country_raw = pairs.get("country", "")
                region_raw = pairs.get("region", "")
                appellation_raw = pairs.get("appellation", "") or pairs.get("subregion", "") or pairs.get("sub-region", "")
                type_raw = pairs.get("type", "")

                if not producer_raw or not designation:
                    write_dlq(self.conn, SOURCE_KEY, batch_id, "parse_error",
                              "missing producer or designation",
                              {"iWine": iwine, "pairs": pairs})
                    result.rows_dlq += 1
                    _save_cursor(iwine)
                    if delay_max > 0:
                        time.sleep(random.uniform(delay_min, delay_max))
                    continue

                # Vintage: "N.V." / "NV" / "1998"
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
                    # Without a country we can't satisfy the dim_producer/appellation
                    # unique constraints. Park in DLQ for manual review.
                    write_dlq(self.conn, SOURCE_KEY, batch_id, "unresolved_dim",
                              f"unmapped country: {country_raw!r}",
                              {"iWine": iwine, "producer": producer_raw, "country": country_raw})
                    result.rows_dlq += 1
                    _save_cursor(iwine)
                    if delay_max > 0:
                        time.sleep(random.uniform(delay_min, delay_max))
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
                    if delay_max > 0:
                        time.sleep(random.uniform(delay_min, delay_max))
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
                    if delay_max > 0:
                        time.sleep(random.uniform(delay_min, delay_max))
                    continue

                wine_key = compute_wine_key(producer_norm, cuvee_norm, vintage, appellation_norm)
                _ensure_wine(self.conn, wine_key, producer_key, appellation_key,
                             designation, cuvee_norm, color, vintage)

                # Community score → fact_rating
                score, notes = _parse_score(tree)
                if score is None:
                    # Wine exists but no community score yet — we already
                    # captured dim_wine, just count as skipped for the rating leg.
                    result.rows_skipped_unchanged += 1
                    _save_cursor(iwine)
                    if delay_max > 0:
                        time.sleep(random.uniform(delay_min, delay_max))
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
                         score, SCALE, score, url, content_hash, batch_id),
                    )
                    self.conn.commit()
                    result.rows_inserted += 1
                except Exception as e:
                    write_dlq(self.conn, SOURCE_KEY, batch_id, "validation_error",
                              str(e), {"iWine": iwine, "wine_key": wine_key, "score": score})
                    result.rows_dlq += 1

                _save_cursor(iwine)
                if delay_max > 0:
                    time.sleep(random.uniform(delay_min, delay_max))

        finally:
            try:
                client.close()
            except Exception:
                pass

        return result
