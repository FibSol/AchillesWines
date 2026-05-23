# REGISTER_IN_CLI = True
"""
iDealwine.com scraper — auth-gated retail price ingestion via JSON API.

iDealwine migrated from a server-rendered JSP site to a Next.js SPA backed
by a Sylius /api/v2 REST API. Authentication uses a JWT bearer token obtained
from /api/v2/shop/authentication-token. Products are fetched from
/api/v2/shop/products (paginated, 30/page) and their prices from
/api/v2/shop/product-variants-by-product/{id}.

Credentials: ACHILLES_AUTH_IDEALWINE_USERNAME / _PASSWORD
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
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False

from .base import BaseScraper, ScrapeResult
from ..auth import AuthenticatedScraper, has_credentials, AuthMissingError, AuthError, Credentials
from ..identity import normalize_producer, normalize_cuvee, compute_wine_key, norm_text
from ..dlq import write_dlq

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_BASE = "https://www.idealwine.com"
_AUTH_URL = f"{_BASE}/api/v2/shop/authentication-token"
_PRODUCTS_URL = f"{_BASE}/api/v2/shop/products"
_VARIANTS_URL = f"{_BASE}/api/v2/shop/product-variants-by-product"

_logger = logging.getLogger(__name__)

_COLOR_MAP = {
    "RED": "red",
    "WHITE": "white",
    "ROSE": "rosé",
    "ROSÉ": "rosé",
    "SPARKLING": "sparkling",
    "SWEET": "sweet",
    "FORTIFIED": "fortified",
    "ORANGE": "orange",
}


def _map_color(raw: str) -> str:
    return _COLOR_MAP.get((raw or "").upper().strip(), "red")


def _find_appellation_key(conn: sqlite3.Connection, appellation_norm: str) -> Optional[int]:
    if not appellation_norm:
        return None
    row = conn.execute(
        "SELECT appellation_key FROM dim_appellation WHERE appellation_norm = ?",
        (appellation_norm,),
    ).fetchone()
    return row[0] if row else None


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
    if conn.execute("SELECT 1 FROM dim_wine WHERE wine_key = ?", (wine_key,)).fetchone():
        return True
    producer_row = conn.execute(
        "SELECT producer_key FROM dim_producer WHERE producer_norm = ? AND country_code = 'FR'",
        (producer_norm,),
    ).fetchone()
    if not producer_row:
        return False
    appellation_key = _ensure_appellation(conn, appellation_name, appellation_norm, region)
    if appellation_key is None:
        return False
    is_nv = 1 if vintage is None else 0
    try:
        conn.execute(
            """INSERT OR IGNORE INTO dim_wine
               (wine_key, producer_key, appellation_key, cuvee_name, cuvee_norm,
                color, vintage, is_non_vintage, bottle_ml, canonical_name)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 750, ?)""",
            (wine_key, producer_row[0], appellation_key, cuvee_name, cuvee_norm,
             color, vintage, is_nv, cuvee_name),
        )
        conn.commit()
        return True
    except Exception:
        return False


def _ensure_producer(conn: sqlite3.Connection, producer_norm: str, producer_name: str) -> bool:
    row = conn.execute(
        "SELECT producer_key FROM dim_producer WHERE producer_norm = ? AND country_code = 'FR'",
        (producer_norm,),
    ).fetchone()
    if row:
        return True
    try:
        conn.execute(
            """INSERT OR IGNORE INTO dim_producer
               (producer_name, producer_norm, country_code, allowed_appellations, aliases, status)
               VALUES (?, ?, 'FR', '[]', '[]', 'pending_review')""",
            (producer_name, producer_norm),
        )
        conn.commit()
        return True
    except Exception:
        return False


class IDealwineScraper(AuthenticatedScraper):
    source_code = "idealwine"

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.batch_id: Optional[str] = None

    def _login(self, client: "httpx.Client", creds: "Credentials") -> bool:
        """Obtain a JWT bearer token from the Sylius /api/v2 endpoint."""
        resp = client.post(
            _AUTH_URL,
            json={"email": creds.username, "password": creds.password},
            headers={
                "User-Agent": _USER_AGENT,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        if resp.status_code == 401:
            return False
        if resp.status_code != 200:
            return False
        try:
            token = resp.json().get("token", "")
        except Exception:
            return False
        if not token:
            return False
        # Attach JWT to the shared client for all subsequent requests
        client.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/ld+json",
        })
        return True

    def run(self, limit: Optional[int] = None) -> ScrapeResult:
        if not HAS_DEPS:
            return ScrapeResult(error="Missing dependencies: httpx not installed")

        if not has_credentials(self.source_code):
            return ScrapeResult(
                error="Credentials missing: set ACHILLES_AUTH_IDEALWINE_USERNAME / _PASSWORD"
            )

        batch_id = self.batch_id or f"idealwine-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        result = ScrapeResult(batch_id=batch_id)

        source_row = self.conn.execute(
            "SELECT source_key FROM dim_source WHERE source_code = ?", (self.source_code,)
        ).fetchone()
        if not source_row:
            return ScrapeResult(error=f"source_code '{self.source_code}' not found in dim_source")
        SOURCE_KEY = source_row[0]

        headers = {
            "User-Agent": _USER_AGENT,
            "Accept": "application/ld+json",
        }

        client = None
        try:
            client = self.authenticated_client(headers=headers)
        except AuthMissingError as e:
            return ScrapeResult(error=str(e))
        except AuthError as e:
            return ScrapeResult(error=str(e))

        try:
            page = 1
            items_per_page = 30
            total_fetched = 0

            while True:
                if limit is not None and total_fetched >= limit:
                    break

                products_url = f"{_PRODUCTS_URL}?page={page}&itemsPerPage={items_per_page}"
                try:
                    resp = self._fetch(lambda u=products_url: client.get(u))
                    resp.raise_for_status()
                except Exception as e:
                    result.error = f"HTTP error on products page {page}: {e}"
                    write_dlq(self.conn, SOURCE_KEY, batch_id, "network_error", str(e),
                              {"url": products_url})
                    result.rows_dlq += 1
                    break

                try:
                    data = resp.json()
                except Exception as e:
                    result.error = f"JSON parse error: {e}"
                    break

                products = data.get("hydra:member", [])
                if not products:
                    break  # no more pages

                for product in products:
                    if limit is not None and total_fetched >= limit:
                        break

                    product_id = product.get("id")
                    if not product_id:
                        continue

                    name = product.get("name", "")
                    if not name:
                        continue

                    appellation_raw = product.get("appellation", "") or ""
                    region_raw = product.get("region", "") or ""
                    owner_raw = product.get("owner", "") or ""
                    color_raw = product.get("color", "") or ""
                    color = _map_color(color_raw)

                    # Fetch variants (contains price data)
                    variants_url = f"{_VARIANTS_URL}/{product_id}"
                    try:
                        vresp = self._fetch(
                            lambda u=variants_url: client.get(u, headers={"Accept": "application/json"})
                        )
                        if vresp.status_code == 404:
                            continue
                        vresp.raise_for_status()
                        variants = vresp.json()
                    except Exception as e:
                        write_dlq(self.conn, SOURCE_KEY, batch_id, "network_error", str(e),
                                  {"url": variants_url})
                        result.rows_dlq += 1
                        continue

                    if not isinstance(variants, list):
                        continue

                    for variant in variants:
                        if limit is not None and total_fetched >= limit:
                            break

                        # Price: priceByCountry dict, values in cents
                        price_by_country = variant.get("priceByCountry") or {}
                        price_cents = price_by_country.get("FR") or price_by_country.get("BE") or (
                            list(price_by_country.values())[0] if price_by_country else None
                        )
                        if not price_cents:
                            continue
                        price_eur = price_cents / 100.0

                        # Vintage
                        vintage_raw = variant.get("vintage")
                        if isinstance(vintage_raw, int) and 1990 <= vintage_raw <= 2035:
                            vintage: Optional[int] = vintage_raw
                        else:
                            vintage = None

                        # Wine name from variant
                        variant_name = variant.get("additionalObservations", {}).get("fr", "") or name
                        if not variant_name:
                            variant_name = name

                        appellation = variant.get("appellation") or appellation_raw or ""
                        region = variant.get("region") or region_raw or ""

                        producer_norm = normalize_producer(owner_raw or variant_name)
                        cuvee_norm = normalize_cuvee(variant_name)
                        appellation_norm = norm_text(appellation) if appellation else ""

                        if not producer_norm or not cuvee_norm:
                            write_dlq(
                                self.conn, SOURCE_KEY, batch_id,
                                "parse_error",
                                f"Empty producer_norm or cuvee_norm for: {variant_name!r}",
                                {"raw_name": variant_name},
                            )
                            result.rows_dlq += 1
                            continue

                        wine_key = compute_wine_key(producer_norm, cuvee_norm, vintage, appellation_norm)
                        _ensure_producer(self.conn, producer_norm, owner_raw or variant_name)

                        if not _ensure_wine(
                            self.conn, wine_key, producer_norm, variant_name,
                            cuvee_norm, appellation, appellation_norm, region, vintage, color,
                        ):
                            write_dlq(
                                self.conn, SOURCE_KEY, batch_id,
                                "unresolved_dim", "Could not resolve producer or appellation",
                                {"raw_name": variant_name, "wine_key": wine_key},
                            )
                            result.rows_dlq += 1
                            continue

                        source_url = f"{_BASE}/fr/acheter-du-vin/{product.get('slug', product_id)}"
                        card_hash = hashlib.sha256(
                            json.dumps(
                                {"wine_key": wine_key, "price": price_eur, "product_id": product_id},
                                sort_keys=True,
                            ).encode()
                        ).hexdigest()

                        try:
                            self.conn.execute(
                                """INSERT OR IGNORE INTO staging_price_candidates
                                   (wine_key, source_key, retailer, recorded_at, currency_code,
                                    amount_local, amount_eur, source_url, content_hash, batch_id, needs_review)
                                   VALUES (?, ?, 'idealwine', ?, 'EUR', ?, ?, ?, ?, ?, 1)""",
                                (wine_key, SOURCE_KEY, int(time.time()), price_eur, price_eur,
                                 source_url, card_hash, batch_id),
                            )
                            self.conn.commit()
                            result.rows_inserted += 1
                        except Exception as e:
                            write_dlq(
                                self.conn, SOURCE_KEY, batch_id,
                                "validation_error", str(e),
                                {"wine_key": wine_key, "price_eur": price_eur},
                            )
                            result.rows_dlq += 1

                        total_fetched += 1
                        result.rows_fetched += 1

                    time.sleep(0.2)

                # Check if there are more pages
                total_items = data.get("hydra:totalItems", 0)
                if page * items_per_page >= total_items:
                    break

                page += 1
                time.sleep(1.0)

        finally:
            if client is not None:
                client.close()

        return result
