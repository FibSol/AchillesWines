"""
Vivino community ratings scraper.

Target:  https://www.vivino.com/api/explore/explore  (public JSON API)
Auth:    None
Cadence: Weekly
Output:  staging_rating_candidates (never direct to fact_rating)

Vivino is a tiebreaker source (ADR-013).  A Vivino staging row is only
promoted to fact_rating by promote_vivino_tiebreakers() when ≥2 professional
critic sources already exist in fact_rating for the same wine_key.

critic_code    = 'VI'
reviewer_type  = 'user_aggregate'
scale          = '/5'  → normalized to /100
ratings_count filter: skip wines with < 10 community ratings.
Country filter: France only (country_code=fr in API request).
"""
import hashlib
import logging
import re
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

from .base import BaseScraper, ScrapeResult
from ..identity import normalize_producer, normalize_cuvee, compute_wine_key, norm_text
from ..dlq import write_dlq

_logger = logging.getLogger(__name__)

_CRITIC_CODE = "VI"
_REVIEWER_TYPE = "user_aggregate"
_SCALE = "/5"
_MIN_RATINGS = 10

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Wine type IDs → color mapping
_TYPE_COLORS: dict[int, str] = {
    1: "red",
    2: "white",
    3: "sparkling",
    4: "rosé",
    7: "sweet",
    24: "fortified",
}
_WINE_TYPE_IDS = list(_TYPE_COLORS.keys())

_EXPLORE_URL = "https://www.vivino.com/api/explore/explore"

_VINTAGE_RE = re.compile(r"\b(19[5-9]\d|20[0-3]\d)\b")


def _appellation_from_region(conn: sqlite3.Connection, region_name: str, title: str) -> tuple[str, str]:
    """Best-effort appellation lookup: try region name first, then title longest-match.
    Falls back to ('Vin de France', 'vin de france')."""
    if region_name:
        region_up = region_name.upper()
        rows = conn.execute(
            "SELECT appellation_name, appellation_norm FROM dim_appellation"
            " WHERE country_code = 'FR' ORDER BY length(appellation_name) DESC"
        ).fetchall()
        for name, norm in rows:
            if name.upper() in region_up or region_up in name.upper():
                return name, norm

    # Fall back to longest-match in wine title
    title_up = title.upper()
    rows = conn.execute(
        "SELECT appellation_name, appellation_norm FROM dim_appellation"
        " WHERE country_code = 'FR' ORDER BY length(appellation_name) DESC"
    ).fetchall()
    for name, norm in rows:
        if name.upper() in title_up:
            return name, norm

    return "Vin de France", "vin de france"


def _ensure_producer(conn: sqlite3.Connection, producer_norm: str, producer_name: str) -> bool:
    if conn.execute(
        "SELECT 1 FROM dim_producer WHERE producer_norm = ?", (producer_norm,)
    ).fetchone():
        return True
    try:
        conn.execute(
            """INSERT OR IGNORE INTO dim_producer
               (producer_name, producer_norm, country_code,
                allowed_appellations, aliases, status)
               VALUES (?, ?, 'FR', '[]', '[]', 'pending_review')""",
            (producer_name, producer_norm),
        )
        conn.commit()
        return True
    except Exception:
        return False


def _ensure_wine(
    conn: sqlite3.Connection,
    wine_key: str,
    producer_norm: str,
    cuvee_name: str,
    cuvee_norm: str,
    color: str,
    vintage: Optional[int],
    appellation_norm: str,
) -> bool:
    if conn.execute("SELECT 1 FROM dim_wine WHERE wine_key = ?", (wine_key,)).fetchone():
        return True

    producer_row = conn.execute(
        "SELECT producer_key FROM dim_producer WHERE producer_norm = ?", (producer_norm,)
    ).fetchone()
    if not producer_row:
        return False

    app_row = conn.execute(
        "SELECT appellation_key FROM dim_appellation WHERE appellation_norm = ?",
        (appellation_norm,),
    ).fetchone()
    if not app_row:
        app_row = conn.execute(
            "SELECT appellation_key FROM dim_appellation WHERE appellation_norm = 'vin de france'"
        ).fetchone()
    if not app_row:
        return False

    is_nv = 1 if vintage is None else 0
    try:
        conn.execute(
            """INSERT OR IGNORE INTO dim_wine
               (wine_key, producer_key, appellation_key, cuvee_name, cuvee_norm,
                color, vintage, is_non_vintage, bottle_ml, canonical_name)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 750, ?)""",
            (wine_key, producer_row[0], app_row[0], cuvee_name, cuvee_norm,
             color, vintage, is_nv, cuvee_name),
        )
        conn.commit()
        return True
    except Exception:
        return False


class VivinoScraper(BaseScraper):
    """
    Fetches French wine community ratings from Vivino's public explore API.

    Writes to staging_rating_candidates (needs_review=1).  Rows are only
    promoted to fact_rating by promote_vivino_tiebreakers() when ≥2
    professional critic sources already exist for the same wine_key.
    """

    source_code = "vivino"

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.batch_id: Optional[str] = None

    def run(self, limit: Optional[int] = None) -> ScrapeResult:
        if not HAS_HTTPX:
            return ScrapeResult(error="Missing dependency: httpx not installed")

        batch_id = self.batch_id or (
            f"vivino-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
            f"-{uuid.uuid4().hex[:8]}"
        )
        result = ScrapeResult(batch_id=batch_id)

        source_row = self.conn.execute(
            "SELECT source_key FROM dim_source WHERE source_code = ?", (self.source_code,)
        ).fetchone()
        if not source_row:
            return ScrapeResult(error="dim_source row missing for 'vivino'. Run migration 0015.")
        source_key = source_row[0]

        headers = {
            "User-Agent": _USER_AGENT,
            "Accept": "application/json",
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
        }

        with httpx.Client(headers=headers, timeout=30, follow_redirects=True) as client:
            for type_id in _WINE_TYPE_IDS:
                if limit is not None and result.rows_fetched >= limit:
                    break
                color = _TYPE_COLORS[type_id]
                self._scrape_type(client, source_key, batch_id, type_id, color,
                                  limit, result)
                time.sleep(1.0)

        return result

    def _scrape_type(
        self,
        client,
        source_key: int,
        batch_id: str,
        type_id: int,
        color: str,
        limit: Optional[int],
        result: ScrapeResult,
    ) -> None:
        page = 1
        MAX_PAGES = 20  # 25 results/page → up to 500 per type

        while page <= MAX_PAGES:
            if limit is not None and result.rows_fetched >= limit:
                break

            params = {
                "country_code": "fr",
                "currency_code": "EUR",
                "grape_filter": "types",
                "min_rating": 1,
                "order_by": "ratings_count",
                "order": "desc",
                "page": page,
                "price_range_max": 500,
                "price_range_min": 5,
                "wine_type_ids[]": type_id,
            }

            try:
                resp = self._fetch(lambda: client.get(_EXPLORE_URL, params=params))
            except Exception as exc:
                write_dlq(self.conn, source_key, batch_id, "network_error", str(exc),
                          {"url": _EXPLORE_URL, "type_id": type_id, "page": page})
                result.rows_dlq += 1
                break

            if resp.status_code == 403:
                write_dlq(self.conn, source_key, batch_id, "auth_error",
                          "Vivino returned 403 — API may be rate-limited or blocked",
                          {"type_id": type_id, "page": page})
                result.rows_dlq += 1
                break

            if resp.status_code == 429:
                write_dlq(self.conn, source_key, batch_id, "auth_error",
                          "Vivino returned 429 — rate limit hit",
                          {"type_id": type_id, "page": page})
                result.rows_dlq += 1
                break

            if not resp.is_success:
                write_dlq(self.conn, source_key, batch_id, "network_error",
                          f"HTTP {resp.status_code}",
                          {"type_id": type_id, "page": page})
                result.rows_dlq += 1
                break

            try:
                data = resp.json()
            except Exception as exc:
                write_dlq(self.conn, source_key, batch_id, "parse_error",
                          f"JSON decode failed: {exc}", {"type_id": type_id, "page": page})
                result.rows_dlq += 1
                break

            matches = (data.get("explore_vintage") or {}).get("matches") or []
            if not matches:
                break  # no more results for this type

            for match in matches:
                if limit is not None and result.rows_fetched >= limit:
                    break

                vintage_obj = match.get("vintage") or {}
                wine_obj = vintage_obj.get("wine") or {}
                stats = vintage_obj.get("statistics") or {}

                winery_name = (wine_obj.get("winery") or {}).get("name") or ""
                wine_name = wine_obj.get("name") or ""
                region_name = (wine_obj.get("region") or {}).get("name") or ""
                country = ((wine_obj.get("region") or {}).get("country") or {}).get("name") or ""
                vintage_year_raw = vintage_obj.get("year")
                ratings_avg = stats.get("ratings_average") or 0.0
                ratings_count = stats.get("ratings_count") or 0

                result.rows_fetched += 1

                # Skip non-French wines (the API should already filter, but verify)
                if country and "france" not in country.lower() and region_name:
                    known_fr_regions = {"bordeaux", "bourgogne", "champagne", "alsace",
                                        "loire", "rhone", "provence", "languedoc",
                                        "roussillon", "jura", "savoie", "corse",
                                        "beaujolais", "sud-ouest"}
                    if not any(r in region_name.lower() for r in known_fr_regions):
                        result.rows_skipped_unchanged += 1
                        continue

                # Filter low-credibility ratings
                if ratings_count < _MIN_RATINGS:
                    result.rows_skipped_unchanged += 1
                    continue

                if not winery_name or not wine_name:
                    write_dlq(self.conn, source_key, batch_id, "parse_error",
                              "Missing winery or wine name", {"match": str(match)[:200]})
                    result.rows_dlq += 1
                    continue

                if ratings_avg <= 0 or ratings_avg > 5:
                    result.rows_skipped_unchanged += 1
                    continue

                try:
                    vintage_year: Optional[int] = int(vintage_year_raw) if vintage_year_raw else None
                except (TypeError, ValueError):
                    vintage_year = None

                producer_norm = normalize_producer(winery_name)
                full_title = f"{winery_name} {wine_name}"
                appellation_name, appellation_norm = _appellation_from_region(
                    self.conn, region_name, full_title
                )
                cuvee_norm = normalize_cuvee(
                    wine_name,
                    strip_words=[producer_norm, appellation_norm],
                )

                if not producer_norm:
                    write_dlq(self.conn, source_key, batch_id, "parse_error",
                              f"Empty producer_norm for: {winery_name!r}", {"wine": wine_name})
                    result.rows_dlq += 1
                    continue

                wine_key = compute_wine_key(producer_norm, cuvee_norm, vintage_year, appellation_norm)

                _ensure_producer(self.conn, producer_norm, winery_name)
                if not _ensure_wine(
                    self.conn, wine_key, producer_norm,
                    wine_name, cuvee_norm, color, vintage_year, appellation_norm,
                ):
                    write_dlq(self.conn, source_key, batch_id, "unresolved_dim",
                              f"Cannot resolve wine: {winery_name!r} / {wine_name!r}",
                              {"wine_key": wine_key, "region": region_name})
                    result.rows_dlq += 1
                    continue

                score_norm = round((ratings_avg / 5.0) * 100, 2)
                content_hash = hashlib.sha256(
                    f"{wine_key}:{_CRITIC_CODE}:{vintage_year}:{ratings_avg:.3f}".encode()
                ).hexdigest()

                source_url = (
                    f"https://www.vivino.com/wines/{wine_obj.get('id', '')}"
                    if wine_obj.get("id") else _EXPLORE_URL
                )

                try:
                    self.conn.execute(
                        """INSERT OR IGNORE INTO staging_rating_candidates
                           (wine_key, source_key, critic_code, reviewer_type,
                            score, scale, score_normalized_100, rating_count,
                            source_url, content_hash, batch_id, needs_review)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                        (
                            wine_key, source_key, _CRITIC_CODE, _REVIEWER_TYPE,
                            round(ratings_avg, 3), _SCALE, score_norm, ratings_count,
                            source_url, content_hash, batch_id,
                        ),
                    )
                    changed = self.conn.execute("SELECT changes()").fetchone()[0]
                    if changed:
                        result.rows_inserted += 1
                    else:
                        result.rows_skipped_unchanged += 1
                    self.conn.commit()
                except Exception as exc:
                    write_dlq(self.conn, source_key, batch_id, "validation_error",
                              str(exc), {"wine_key": wine_key})
                    result.rows_dlq += 1

            page += 1
            time.sleep(1.0)
