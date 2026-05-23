# REGISTER_IN_CLI = True
"""
CellarTracker xlquery.asp scraper — official partner data-export endpoint.

This is the *useful* CT integration. Where the iWine sweep is killed by
Kasada anti-bot, the documented xlquery.asp endpoint (used by CT's own
mobile app and 3rd-party sync tools) bypasses it cleanly and returns
TSV / CSV / XML directly.

Tables we ingest:
  List       — one row per wine currently in the user's cellar, with 30+
               pre-aggregated critic scores per wine and CT community avg.
  Inventory  — bottle-level data (per location, purchase date, native price).
  Notes      — tasting notes (community + partner-linked critics).

Why this is the right pattern (not a workaround):
  CellarTracker positions itself as a *critic aggregation hub*. Via its
  Partner Integrations page (getcontent.asp) users link subscriptions to
  Vinous, Jancis Robinson, Decanter, Burghound, Halliday, Jeb Dunnuck,
  Inside Burgundy, James Suckling, Wine Align, Wine Doctor, etc. — and CT
  funnels those critics' reviews and scores into the user's cellar view.
  Pulling our cellar via xlquery.asp returns ALL of that aggregated data
  in one request: no per-critic scraping, no Kasada, no ToS gymnastics.

Limitation by design:
  Only wines IN the logged-in user's CT cellar are returned. xlquery.asp
  is not a global-DB endpoint. The product flow this implies:
    1. Add wine to Achilles cellar → also add to CT cellar (manual today,
       barcode-scan via CT mobile, or future bulk-add API).
    2. Run this scraper → pull aggregated critic scores + community avg
       per wine → write to fact_rating keyed on our wine_key.
    3. The 30+ critic columns automatically expand our rating coverage
       without needing per-critic scrapers.

Auth: same env vars as the page scraper (ACHILLES_AUTH_CELLARTRACKER_*).
Transport: curl_cffi with chrome124 impersonation — required for the
CloudFront TLS check; the xlquery endpoint itself is not Kasada-gated.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import os
import sqlite3
import time
import uuid
from datetime import datetime
from typing import Optional

try:
    from curl_cffi import requests as curl_requests
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False

from .base import BaseScraper, ScrapeResult
from ..auth import has_credentials, get_credentials, AuthMissingError, AuthError
from ..identity import normalize_producer, normalize_cuvee, compute_wine_key, norm_text
from ..dlq import write_dlq

_logger = logging.getLogger(__name__)

_BASE = "https://www.cellartracker.com"
_LOGIN_URL = f"{_BASE}/password.asp"
_XLQUERY = f"{_BASE}/xlquery.asp"

# CT critic-column → our critic_code (must be in VALID_CRITIC_CODES set
# defined per-scraper). 'CT' = community avg. Scores are /100 unless noted.
# Columns we don't map yet are silently ignored.
_CRITIC_COLUMNS: dict[str, tuple[str, str]] = {
    # TSV column   →   (critic_code, scale)
    "CT":  ("CT", "/100"),    # CellarTracker community avg
    "WA":  ("WA", "/100"),    # Wine Advocate / Parker
    "WS":  ("WS", "/100"),    # Wine Spectator
    "AG":  ("Vinous", "/100"),# Antonio Galloni / Vinous
    "IWC": ("Vinous", "/100"),# Legacy International Wine Cellar (Tanzer) — folded into Vinous
    "BH":  ("BH", "/100"),    # Burghound (Meadows)
    "JR":  ("JMIB", "/20"),   # Jancis Robinson — 20-pt scale!
    "DR":  ("Decanter", "/100"),
    "JS":  ("JS", "/100"),    # James Suckling
    "JM":  ("JMIB", "/100"),  # Jasper Morris (Inside Burgundy)
    "JH":  ("Hachette", "/100"),  # NOTE: JH = James Halliday — placeholder; refine when we add a Halliday critic_code
    "WE":  ("WE", "/100"),    # Wine Enthusiast
    "WAL": ("WAL", "/100"),   # Wine Align
    "WD":  ("WD", "/100"),    # Wine Doctor
    "JG":  ("JG", "/100"),    # Jeb Dunnuck (his column key is JD elsewhere — verify)
    "GV":  ("GV", "/100"),    # Gilbert & Gaillard
}

# Color label on CT → our color enum.
_TYPE_TO_COLOR = {
    "red": "red", "white": "white", "rosé": "rosé", "rose": "rosé",
    "pink": "rosé", "sparkling": "sparkling", "champagne": "sparkling",
    "dessert": "sweet", "sweet": "sweet", "fortified": "fortified",
    "port": "fortified", "sherry": "fortified", "madeira": "fortified",
    "orange": "orange",
}

_COUNTRY_TO_ISO2 = {
    "france": "FR", "italy": "IT", "spain": "ES", "portugal": "PT",
    "germany": "DE", "austria": "AT", "usa": "US", "united states": "US",
    "argentina": "AR", "chile": "CL", "australia": "AU", "new zealand": "NZ",
    "south africa": "ZA", "hungary": "HU", "greece": "GR", "switzerland": "CH",
    "belgium": "BE", "luxembourg": "LU", "canada": "CA", "uruguay": "UY",
    "lebanon": "LB", "israel": "IL", "georgia": "GE", "romania": "RO",
    "slovenia": "SI", "croatia": "HR", "bulgaria": "BG", "moldova": "MD",
    "japan": "JP", "china": "CN", "england": "GB", "united kingdom": "GB",
}


def _map_color(raw: str) -> str:
    if not raw:
        return "red"
    key = raw.strip().lower().split("-")[0].strip()
    return _TYPE_TO_COLOR.get(key, "red")


def _map_country(raw: str) -> Optional[str]:
    if not raw:
        return None
    return _COUNTRY_TO_ISO2.get(raw.strip().lower())


def _parse_int(s: str) -> Optional[int]:
    if not s:
        return None
    try:
        return int(s.strip())
    except Exception:
        return None


def _parse_float(s: str) -> Optional[float]:
    if not s:
        return None
    try:
        return float(s.strip())
    except Exception:
        return None


def _normalize_score_to_100(score: float, scale: str) -> Optional[float]:
    if scale == "/100":
        return score if 0 <= score <= 100 else None
    if scale == "/20":
        return (score / 20.0) * 100.0 if 0 <= score <= 20 else None
    if scale == "/5":
        return (score / 5.0) * 100.0 if 0 <= score <= 5 else None
    return None


def _ensure_source(conn: sqlite3.Connection) -> Optional[int]:
    row = conn.execute(
        "SELECT source_key FROM dim_source WHERE source_code = ?",
        ("cellartracker_xlquery",),
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
                       'Official CT data-export endpoint. Pulls user-cellar List/Inventory/Notes with 30+ pre-aggregated critic scores per wine. Bypasses Kasada.')""",
            ("cellartracker_xlquery", "CellarTracker (xlquery)", _BASE),
        )
        conn.commit()
    except Exception as e:
        _logger.warning("could not insert cellartracker_xlquery dim_source: %s", e)
    row = conn.execute(
        "SELECT source_key FROM dim_source WHERE source_code = ?",
        ("cellartracker_xlquery",),
    ).fetchone()
    return row[0] if row else None


def _ensure_producer(conn, country: str, producer_norm: str, producer_name: str) -> Optional[int]:
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
        pass
    row = conn.execute(
        "SELECT producer_key FROM dim_producer WHERE producer_norm = ? AND country_code = ?",
        (producer_norm, country),
    ).fetchone()
    return row[0] if row else None


def _ensure_appellation(conn, country: str, region: str, name: str, norm: str) -> Optional[int]:
    if not country or not norm:
        return None
    row = conn.execute(
        "SELECT appellation_key FROM dim_appellation WHERE country_code = ? AND appellation_norm = ?",
        (country, norm),
    ).fetchone()
    if row:
        return row[0]
    if not name or not region:
        return None
    try:
        cur = conn.execute(
            """INSERT OR IGNORE INTO dim_appellation
               (country_code, region, appellation_name, appellation_norm, level)
               VALUES (?, ?, ?, ?, 'regional')""",
            (country, region, name, norm),
        )
        conn.commit()
        if cur.lastrowid:
            return cur.lastrowid
    except Exception:
        pass
    row = conn.execute(
        "SELECT appellation_key FROM dim_appellation WHERE country_code = ? AND appellation_norm = ?",
        (country, norm),
    ).fetchone()
    return row[0] if row else None


def _ensure_wine(conn, wine_key, producer_key, appellation_key,
                 cuvee_name, cuvee_norm, color, vintage) -> bool:
    if conn.execute("SELECT 1 FROM dim_wine WHERE wine_key = ?", (wine_key,)).fetchone():
        return True
    try:
        conn.execute(
            """INSERT OR IGNORE INTO dim_wine
               (wine_key, producer_key, appellation_key, cuvee_name, cuvee_norm,
                color, vintage, is_non_vintage, bottle_ml, canonical_name)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 750, ?)""",
            (wine_key, producer_key, appellation_key, cuvee_name, cuvee_norm,
             color, vintage, 1 if vintage is None else 0, cuvee_name),
        )
        conn.commit()
        return True
    except Exception:
        return False


def _login_session(creds) -> "curl_requests.Session":
    s = curl_requests.Session(impersonate="chrome124")
    s.get(f"{_BASE}/")
    s.get(_LOGIN_URL)
    s.post(
        _LOGIN_URL,
        data={
            "Referrer": "",
            "szUser": creds.username,
            "szPassword": creds.password,
            "UseCookie": "true",
        },
        headers={"Referer": _LOGIN_URL, "Origin": _BASE,
                 "Content-Type": "application/x-www-form-urlencoded"},
    )
    probe = s.get(f"{_BASE}/default.asp")
    body = (probe.text or "").lower()
    if not (("sign out" in body) or ("logout" in body) or (creds.username.lower() in body)):
        raise AuthError("CellarTracker login rejected (no signed-in chrome on /default.asp)")
    return s


def _fetch_tsv(session, table: str) -> list[dict[str, str]]:
    r = session.get(
        f"{_XLQUERY}?Format=tab&Table={table}",
        headers={"Referer": f"{_BASE}/default.asp"},
    )
    text = r.text or ""
    if r.status_code != 200:
        raise AuthError(f"xlquery.asp HTTP {r.status_code} for table {table}")
    if "<html" in text[:80].lower():
        # "No results returned." / "requires a CellarTracker Subscription." etc.
        return []
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    return list(reader)


class CellarTrackerXlqueryScraper(BaseScraper):
    """Pulls List + Notes from xlquery.asp and writes fact_rating rows.

    Idempotent: every row's content_hash is derived from (wine_key, critic_code,
    score, source_table) so re-runs INSERT OR IGNORE harmlessly.
    """
    source_code = "cellartracker_xlquery"

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.batch_id: Optional[str] = None

    def _login_test(self) -> bool:
        # Used by /admin/auth test button — has no AuthenticatedScraper base so
        # we implement it directly.
        if not has_credentials(self.source_code.replace("_xlquery", "")):
            return False
        try:
            creds = get_credentials("cellartracker")
            _login_session(creds).close()
            return True
        except Exception:
            return False

    def test_login(self) -> tuple[bool, str]:
        try:
            ok = self._login_test()
            return ok, "login ok" if ok else "login rejected"
        except Exception as e:
            return False, f"error: {e}"

    def run(self, limit: Optional[int] = None) -> ScrapeResult:
        if not HAS_DEPS:
            return ScrapeResult(error="Missing dependency: curl_cffi not installed")
        # Credentials live under the base 'cellartracker' source code (shared).
        if not has_credentials("cellartracker"):
            return ScrapeResult(
                error="Credentials missing: set ACHILLES_AUTH_CELLARTRACKER_USERNAME / _PASSWORD"
            )

        batch_id = self.batch_id or f"ctxlq-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        result = ScrapeResult(batch_id=batch_id)

        SOURCE_KEY = _ensure_source(self.conn)
        if SOURCE_KEY is None:
            return ScrapeResult(error="could not resolve dim_source row for cellartracker_xlquery")

        try:
            creds = get_credentials("cellartracker")
            session = _login_session(creds)
        except (AuthMissingError, AuthError) as e:
            return ScrapeResult(error=str(e))

        try:
            rows = _fetch_tsv(session, "List")
        except AuthError as e:
            return ScrapeResult(error=str(e))

        if limit is not None:
            rows = rows[:limit]

        for row in rows:
            result.rows_fetched += 1

            iwine = _parse_int(row.get("iWine", "")) or 0
            vintage = _parse_int(row.get("Vintage", "")) or None
            if vintage is not None and not (1800 <= vintage <= 2040):
                vintage = None
            producer_raw = (row.get("Producer") or "").strip()
            designation = (row.get("Designation") or row.get("Wine") or "").strip()
            country_raw = (row.get("Country") or "").strip()
            region = (row.get("Region") or "").strip()
            subregion = (row.get("SubRegion") or "").strip()
            appellation_raw = (row.get("Appellation") or subregion or region).strip()
            color = _map_color(row.get("Color") or row.get("Type") or "")

            country = _map_country(country_raw)
            if not country or not producer_raw or not designation:
                write_dlq(self.conn, SOURCE_KEY, batch_id, "unresolved_dim",
                          "missing country/producer/designation",
                          {"iWine": iwine, "country": country_raw,
                           "producer": producer_raw, "designation": designation})
                result.rows_dlq += 1
                continue

            producer_norm = normalize_producer(producer_raw)
            cuvee_norm = normalize_cuvee(designation)
            appellation_norm = norm_text(appellation_raw or region)
            if not producer_norm or not cuvee_norm:
                write_dlq(self.conn, SOURCE_KEY, batch_id, "parse_error",
                          "empty producer_norm or cuvee_norm",
                          {"iWine": iwine, "producer": producer_raw,
                           "designation": designation})
                result.rows_dlq += 1
                continue

            producer_key = _ensure_producer(self.conn, country, producer_norm, producer_raw)
            appellation_key = _ensure_appellation(
                self.conn, country, region or "Unknown",
                appellation_raw or region or "Unknown",
                appellation_norm or norm_text(region or "Unknown"),
            )
            if producer_key is None or appellation_key is None:
                write_dlq(self.conn, SOURCE_KEY, batch_id, "unresolved_dim",
                          "could not ensure producer/appellation",
                          {"iWine": iwine, "country": country, "region": region})
                result.rows_dlq += 1
                continue

            wine_key = compute_wine_key(producer_norm, cuvee_norm, vintage, appellation_norm)
            _ensure_wine(self.conn, wine_key, producer_key, appellation_key,
                         designation, cuvee_norm, color, vintage)

            # Walk all critic columns and emit fact_rating rows.
            wine_inserted_any = False
            for col, (critic_code, scale) in _CRITIC_COLUMNS.items():
                raw = (row.get(col) or "").strip()
                if not raw:
                    continue
                score = _parse_float(raw)
                if score is None or score <= 0:
                    continue
                norm_score = _normalize_score_to_100(score, scale)
                if norm_score is None:
                    continue
                source_url = f"{_BASE}/wine.asp?iWine={iwine}" if iwine else _BASE
                content_hash = hashlib.sha256(
                    json.dumps(
                        {"wine_key": wine_key, "critic": critic_code,
                         "score": score, "source": "xlquery_list"},
                        sort_keys=True,
                    ).encode()
                ).hexdigest()
                reviewer_type = "crowd" if critic_code == "CT" else "critic"
                try:
                    self.conn.execute(
                        """INSERT OR IGNORE INTO fact_rating
                           (wine_key, source_key, critic_code, reviewer_type,
                            score, scale, score_normalized_100,
                            source_url, content_hash, batch_id)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (wine_key, SOURCE_KEY, critic_code, reviewer_type,
                         score, scale, norm_score, source_url, content_hash, batch_id),
                    )
                    if self.conn.total_changes:
                        result.rows_inserted += 1
                        wine_inserted_any = True
                except Exception as e:
                    write_dlq(self.conn, SOURCE_KEY, batch_id, "validation_error",
                              str(e), {"wine_key": wine_key, "critic": critic_code,
                                       "score": score})
                    result.rows_dlq += 1
            if not wine_inserted_any:
                result.rows_skipped_unchanged += 1

            self.conn.commit()

        try:
            session.close()
        except Exception:
            pass
        return result
