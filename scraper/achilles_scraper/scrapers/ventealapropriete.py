# REGISTER_IN_CLI = True
"""
ventealapropriete.com scraper — flash-sale price ingestion via Algolia.

Vente à la Propriété is a French flash-sale wine platform.  Prices are
only visible to authenticated members.  This scraper:

  1. POSTs to /api/auth/login (Nuxt server-side auth).
  2. Fetches /compte to extract the authenticated Algolia API key from the
     embedded __NUXT_DATA__ JSON.
  3. Queries the private Algolia index "ventes_prod_valap_nuxt_prive_fr"
     filtered to `typeProduit:vin AND pays:France` — ~700 active wine
     products per scrape cycle, all priced.
  4. Inserts into staging_price_candidates via insert_staging_candidate.

No browser / Playwright required — pure httpx + selectolax.
"""
import hashlib
import json
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
from ..dlq import write_dlq, insert_staging_candidate

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_BASE = "https://www.ventealapropriete.com"
_LOGIN_URL = f"{_BASE}/api/auth/login"
_PROFILE_URL = f"{_BASE}/compte"
_ALGOLIA_APP_ID = "GQC1D7S33F"
_ALGOLIA_INDEX = "ventes_prod_valap_nuxt_prive_fr"
_ALGOLIA_SEARCH_URL = (
    f"https://{_ALGOLIA_APP_ID}-dsn.algolia.net"
    f"/1/indexes/{_ALGOLIA_INDEX}/query"
)

_logger = logging.getLogger(__name__)

_COLOR_MAP = {
    "rouge": "red",
    "blanc": "white",
    "rosé": "rosé",
    "rose": "rosé",
    "champagne": "sparkling",
    "mousseux": "sparkling",
    "pétillant": "sparkling",
    "petillant": "sparkling",
    "effervescent": "sparkling",
    "crémant": "sparkling",
    "cremant": "sparkling",
    "liquoreux": "sweet",
    "moelleux": "sweet",
    "fortifié": "fortified",
    "fortifie": "fortified",
    "orange": "orange",
}


def _map_color(raw: str) -> str:
    """Map French couleur field to our internal color enum."""
    t = (raw or "").lower().strip()
    for k, v in _COLOR_MAP.items():
        if k in t:
            return v
    return "red"


def _find_appellation_key(
    conn: sqlite3.Connection, appellation_norm: str
) -> Optional[int]:
    if not appellation_norm:
        return None
    row = conn.execute(
        "SELECT appellation_key FROM dim_appellation WHERE appellation_norm = ?",
        (appellation_norm,),
    ).fetchone()
    return row[0] if row else None


def _appellation_from_title(
    conn: sqlite3.Connection, title: str
) -> tuple[str, str]:
    """Longest-match lookup of French appellations; falls back to Vin de France."""
    title_up = title.upper()
    rows = conn.execute(
        "SELECT appellation_name, appellation_norm FROM dim_appellation"
        " WHERE country_code = 'FR' ORDER BY length(appellation_name) DESC"
    ).fetchall()
    for name, norm in rows:
        if name.upper() in title_up:
            return name, norm
    return "Vin de France", "vin de france"


def _ensure_appellation(
    conn: sqlite3.Connection,
    appellation_name: str,
    appellation_norm: str,
    region: str,
) -> Optional[int]:
    existing = _find_appellation_key(conn, appellation_norm)
    if existing:
        return existing
    if not appellation_name or not region:
        return None
    try:
        cur = conn.execute(
            """INSERT OR IGNORE INTO dim_appellation
               (country_code, region, appellation_name, appellation_norm, level)
               VALUES ('FR', ?, ?, ?, 'regional')""",
            (region, appellation_name, appellation_norm),
        )
        conn.commit()
        if cur.lastrowid:
            return cur.lastrowid
        return _find_appellation_key(conn, appellation_norm)
    except Exception:
        return None


def _ensure_producer(
    conn: sqlite3.Connection, producer_norm: str, producer_name: str
) -> bool:
    row = conn.execute(
        "SELECT producer_key FROM dim_producer"
        " WHERE producer_norm = ? AND country_code = 'FR'",
        (producer_norm,),
    ).fetchone()
    if row:
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
    appellation_name: str,
    appellation_norm: str,
    region: str,
    vintage: Optional[int],
    color: str,
) -> bool:
    if conn.execute(
        "SELECT 1 FROM dim_wine WHERE wine_key = ?", (wine_key,)
    ).fetchone():
        return True
    producer_row = conn.execute(
        "SELECT producer_key FROM dim_producer"
        " WHERE producer_norm = ? AND country_code = 'FR'",
        (producer_norm,),
    ).fetchone()
    if not producer_row:
        return False
    appellation_key = _ensure_appellation(
        conn, appellation_name, appellation_norm, region
    )
    if appellation_key is None:
        return False
    is_nv = 1 if vintage is None else 0
    try:
        conn.execute(
            """INSERT OR IGNORE INTO dim_wine
               (wine_key, producer_key, appellation_key, cuvee_name,
                cuvee_norm, color, vintage, is_non_vintage, bottle_ml,
                canonical_name)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 750, ?)""",
            (
                wine_key, producer_row[0], appellation_key,
                cuvee_name, cuvee_norm, color, vintage, is_nv, cuvee_name,
            ),
        )
        conn.commit()
        return True
    except Exception:
        return False


def _get_algolia_key(client: "httpx.Client") -> Optional[str]:
    """
    Fetch /compte and extract the authenticated Algolia API key from the
    embedded Nuxt 3 __NUXT_DATA__ SSR payload.

    Returns None if login was not recognised or key is absent.
    """
    try:
        resp = client.get(
            _PROFILE_URL,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "text/html,*/*",
                "Accept-Language": "fr-FR,fr;q=0.9",
            },
            timeout=20,
            follow_redirects=True,
        )
    except Exception as exc:
        _logger.warning("Failed to fetch /compte: %s", exc)
        return None

    tree = HTMLParser(resp.text)
    script_node = tree.css_first("script#__NUXT_DATA__")
    if not script_node:
        return None

    try:
        data = json.loads(script_node.text(strip=True))
    except Exception:
        return None

    def resolve(v: object, _seen: Optional[set] = None) -> object:
        if _seen is None:
            _seen = set()
        while isinstance(v, int) and v not in _seen:
            _seen.add(v)
            if v < len(data):
                v = data[v]
            else:
                break
        return v

    # data[12] = session dict with keys 'user', 'algoliaKey', 'accessToken', …
    if len(data) <= 12 or not isinstance(data[12], dict):
        return None

    algolia_key_idx = data[12].get("algoliaKey")
    if algolia_key_idx is None:
        return None

    key = resolve(algolia_key_idx)
    return key if isinstance(key, str) and len(key) > 20 else None


class VenteALaPropieteScraper(BaseScraper):
    """
    Scraper for ventealapropriete.com flash-sale prices via Algolia.

    Credentials are read from the environment:
      ACHILLES_AUTH_VENTEALAPROPRIETE_USERNAME
      ACHILLES_AUTH_VENTEALAPROPRIETE_PASSWORD
    """

    source_code = "ventealapropriete"

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.batch_id: Optional[str] = None

    @staticmethod
    def _read_credentials() -> tuple[Optional[str], Optional[str]]:
        import os
        username = os.environ.get("ACHILLES_AUTH_VENTEALAPROPRIETE_USERNAME")
        password = os.environ.get("ACHILLES_AUTH_VENTEALAPROPRIETE_PASSWORD")
        return username, password

    def run(self, limit: Optional[int] = None) -> ScrapeResult:
        if not HAS_DEPS:
            return ScrapeResult(
                error="Missing dependencies: httpx or selectolax not installed"
            )

        username, password = self._read_credentials()
        if not username or not password:
            return ScrapeResult(
                error=(
                    "Credentials missing: set "
                    "ACHILLES_AUTH_VENTEALAPROPRIETE_USERNAME / _PASSWORD"
                )
            )

        source_row = self.conn.execute(
            "SELECT source_key FROM dim_source WHERE source_code = ?",
            (self.source_code,),
        ).fetchone()
        if not source_row:
            return ScrapeResult(
                error=f"source_code '{self.source_code}' not found in dim_source"
            )
        SOURCE_KEY = source_row[0]

        batch_id = (
            self.batch_id
            or f"ventealapropriete-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
            f"-{uuid.uuid4().hex[:8]}"
        )
        result = ScrapeResult(batch_id=batch_id)

        headers = {
            "User-Agent": _USER_AGENT,
            "Accept": "text/html,*/*",
            "Accept-Language": "fr-FR,fr;q=0.9",
        }

        with httpx.Client(
            headers=headers, timeout=30, follow_redirects=True
        ) as client:
            # ── Step 1: authenticate ──────────────────────────────────────
            try:
                login_resp = client.post(
                    _LOGIN_URL,
                    json={"email": username, "password": password},
                    headers={
                        **headers,
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                        "Origin": _BASE,
                        "Referer": f"{_BASE}/fr/connexion",
                    },
                )
                if login_resp.status_code != 200:
                    result.error = (
                        f"Login failed: HTTP {login_resp.status_code}"
                    )
                    write_dlq(
                        self.conn, SOURCE_KEY, batch_id, "auth_error",
                        result.error, {"status": login_resp.status_code},
                    )
                    result.rows_dlq += 1
                    return result
            except Exception as exc:
                result.error = f"Login request failed: {exc}"
                return result

            _logger.info("Login OK for %s", username)

            # ── Step 2: get authenticated Algolia key ─────────────────────
            algolia_key = _get_algolia_key(client)
            if not algolia_key:
                result.error = (
                    "Could not extract Algolia key from /compte page — "
                    "login may not have been accepted."
                )
                write_dlq(
                    self.conn, SOURCE_KEY, batch_id, "auth_error",
                    result.error, {},
                )
                result.rows_dlq += 1
                return result

            _logger.info("Got Algolia key (len=%d)", len(algolia_key))

        # ── Step 3: query Algolia (outside httpx session — different host) ──
        algolia_headers = {
            "X-Algolia-Application-Id": _ALGOLIA_APP_ID,
            "X-Algolia-API-Key": algolia_key,
            "Content-Type": "application/json",
            "User-Agent": _USER_AGENT,
        }

        page = 0
        hits_per_page = 1000  # Algolia limit; all 701 French wines fit in one page
        total_fetched = 0

        with httpx.Client(timeout=30) as alg_client:
            while True:
                payload = {
                    "query": "",
                    "hitsPerPage": hits_per_page,
                    "page": page,
                    "filters": "typeProduit:vin AND pays:France",
                    "attributesToRetrieve": [
                        "objectID",
                        "ligne1",
                        "ligne2",
                        "ligne3",
                        "appellation",
                        "millesime",
                        "couleur",
                        "prixUnitaireTtc",
                        "region",
                        "slug",
                        "slugParent",
                        "pays",
                        "domaine",
                        "produitEpuise",
                        "typeVente",
                    ],
                }

                try:
                    resp = alg_client.post(
                        _ALGOLIA_SEARCH_URL,
                        json=payload,
                        headers=algolia_headers,
                    )
                    resp.raise_for_status()
                    alg_data = resp.json()
                except Exception as exc:
                    result.error = f"Algolia query failed (page {page}): {exc}"
                    write_dlq(
                        self.conn, SOURCE_KEY, batch_id, "auth_error",
                        str(exc), {"page": page},
                    )
                    result.rows_dlq += 1
                    break

                hits = alg_data.get("hits", [])
                nb_pages = alg_data.get("nbPages", 1)
                _logger.info(
                    "Algolia page=%d hits=%d / total=%d",
                    page, len(hits), alg_data.get("nbHits", 0),
                )

                if not hits:
                    break

                for hit in hits:
                    if limit is not None and total_fetched >= limit:
                        break

                    object_id = hit.get("objectID", "")
                    raw_name = (
                        (hit.get("ligne1") or "").strip()
                        or (hit.get("domaine") or "").strip()
                    )
                    if not raw_name:
                        result.rows_dlq += 1
                        continue

                    # Skip sold-out products
                    if hit.get("produitEpuise"):
                        result.rows_skipped_unchanged += 1
                        continue

                    # Price
                    prix_dict = hit.get("prixUnitaireTtc")
                    price_eur: Optional[float] = None
                    if isinstance(prix_dict, dict):
                        price_eur = prix_dict.get("FR")
                    elif isinstance(prix_dict, (int, float)):
                        price_eur = float(prix_dict)

                    if price_eur is None or price_eur <= 0:
                        write_dlq(
                            self.conn, SOURCE_KEY, batch_id,
                            "parse_error",
                            f"No FR price for: {raw_name!r}",
                            {"objectID": object_id, "prixUnitaireTtc": prix_dict},
                        )
                        result.rows_dlq += 1
                        continue

                    vintage: Optional[int] = None
                    raw_millesime = hit.get("millesime")
                    if isinstance(raw_millesime, int) and 1900 <= raw_millesime <= 2100:
                        vintage = raw_millesime

                    color = _map_color(hit.get("couleur") or "")

                    # Appellation — prefer the explicit field, fall back to title match
                    raw_appellation = (hit.get("appellation") or "").strip()
                    raw_region = (hit.get("region") or "").strip()

                    if raw_appellation:
                        appellation_norm = norm_text(raw_appellation)
                        # Check if it exists in dim_appellation
                        if _find_appellation_key(self.conn, appellation_norm):
                            appellation_name = raw_appellation
                        else:
                            # Fallback to longest-match lookup
                            title_for_match = " ".join(filter(None, [
                                raw_name, raw_appellation,
                                hit.get("ligne2") or "", hit.get("ligne3") or "",
                            ]))
                            appellation_name, appellation_norm = _appellation_from_title(
                                self.conn, title_for_match
                            )
                    else:
                        title_for_match = " ".join(filter(None, [
                            raw_name,
                            hit.get("ligne2") or "", hit.get("ligne3") or "",
                        ]))
                        appellation_name, appellation_norm = _appellation_from_title(
                            self.conn, title_for_match
                        )

                    region = raw_region or appellation_name

                    # Build cuvee_norm — strip producer and appellation noise
                    line2 = (hit.get("ligne2") or "").strip()
                    cuvee_label = line2 if line2 and line2 != raw_appellation else raw_name
                    producer_norm = normalize_producer(raw_name)
                    if not producer_norm:
                        write_dlq(
                            self.conn, SOURCE_KEY, batch_id,
                            "parse_error",
                            f"Empty producer_norm for: {raw_name!r}",
                            {"objectID": object_id},
                        )
                        result.rows_dlq += 1
                        continue

                    cuvee_norm = normalize_cuvee(
                        cuvee_label,
                        strip_words=[producer_norm, appellation_norm],
                    )
                    wine_key = compute_wine_key(
                        producer_norm, cuvee_norm, vintage, appellation_norm
                    )

                    # Source URL
                    slug_parent = (
                        hit.get("slugParent") or hit.get("slug") or ""
                    )
                    source_url = (
                        f"{_BASE}/fr/ventes-privees/{slug_parent}"
                        if slug_parent
                        else f"{_BASE}/fr/ventes-privees"
                    )

                    # Dedup hash
                    content_hash = hashlib.sha256(
                        json.dumps(
                            {
                                "objectID": object_id,
                                "prix_fr": price_eur,
                            },
                            sort_keys=True,
                        ).encode()
                    ).hexdigest()

                    _ensure_producer(self.conn, producer_norm, raw_name)

                    if not _ensure_wine(
                        self.conn, wine_key, producer_norm, cuvee_label,
                        cuvee_norm, appellation_name, appellation_norm,
                        region, vintage, color,
                    ):
                        write_dlq(
                            self.conn, SOURCE_KEY, batch_id,
                            "unresolved_dim",
                            "Could not resolve producer or appellation",
                            {"raw_name": raw_name, "wine_key": wine_key},
                        )
                        result.rows_dlq += 1
                        continue

                    try:
                        inserted = insert_staging_candidate(
                            self.conn,
                            wine_key=wine_key,
                            source_key=SOURCE_KEY,
                            retailer="ventealapropriete",
                            recorded_at=int(time.time()),
                            amount_local=price_eur,
                            amount_eur=price_eur,
                            source_url=source_url,
                            content_hash=content_hash,
                            batch_id=batch_id,
                        )
                        if inserted:
                            result.rows_inserted += 1
                            _logger.debug(
                                "inserted wine_key=%s price=%.2f name=%s",
                                wine_key, price_eur, raw_name,
                            )
                        else:
                            result.rows_skipped_unchanged += 1
                    except Exception as exc:
                        write_dlq(
                            self.conn, SOURCE_KEY, batch_id,
                            "validation_error", str(exc),
                            {"wine_key": wine_key, "price_eur": price_eur},
                        )
                        result.rows_dlq += 1

                    total_fetched += 1
                    result.rows_fetched += 1

                if limit is not None and total_fetched >= limit:
                    break

                if page + 1 >= nb_pages:
                    break

                page += 1
                time.sleep(0.5)

        return result
