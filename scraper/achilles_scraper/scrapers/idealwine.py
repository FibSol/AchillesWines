# REGISTER_IN_CLI = True
"""
iDealwine.com scraper — auth-gated retail price ingestion via JSON API.

iDealwine migrated from a server-rendered JSP site to a Next.js SPA backed
by a Sylius /api/v2 REST API. Authentication uses a JWT bearer token obtained
from /api/v2/shop/authentication-token. Products are fetched from
/api/v2/shop/products (paginated, 30/page) and their prices from
/api/v2/shop/product-variants-by-product/{id}.

Credentials: ACHILLES_AUTH_IDEALWINE_USERNAME / _PASSWORD

Auction extension (IDealwineAuctionsScraper / source_code='idealwine_auctions'):
  iDealwine hosts live auction sales (ventes aux enchères) alongside its fixed-price
  e-caviste shop. Active auction catalogs are listed at
  /api/v2/shop/auction-catalogs (60 catalogs per cycle). Each product variant
  exposes a `saleType` field: AUCTION or DIRECT_PURCHASE. The auction scraper
  iterates all products, collects variants with saleType=AUCTION, and records the
  current bid/estimate price (priceByCountry, in cents) as a staging candidate
  under the 'idealwine_auctions' source. This produces a separate dim_source row
  so auction prices and fixed-price retail prices are never conflated in fact_price.
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
from ..identity import normalize_producer, normalize_cuvee, compute_wine_key, norm_text, clean_producer_display, clean_cuvee_display
from ..dlq import write_dlq, insert_staging_candidate

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_BASE = "https://www.idealwine.com"
_AUTH_URL = f"{_BASE}/api/v2/shop/authentication-token"
_PRODUCTS_URL = f"{_BASE}/api/v2/shop/products"
_VARIANTS_URL = f"{_BASE}/api/v2/shop/product-variants-by-product"
_AUCTION_CATALOGS_URL = f"{_BASE}/api/v2/shop/auction-catalogs"
# Historical sold lots — past auction results archive
_AUCTION_RESULTS_URL = f"{_BASE}/api/v2/shop/auction-results"

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


def _get_jwt_client(source_code: str, headers: Optional[dict] = None) -> "httpx.Client":
    """Authenticate with the Sylius JWT endpoint and return an authorized httpx.Client.

    The caller is responsible for closing the client.

    Raises:
        AuthMissingError: env vars not set.
        AuthError:        credentials rejected or HTTP error.
    """
    from ..auth import get_credentials, AuthMissingError as _AMe, AuthError as _AE

    creds = get_credentials(source_code)
    h = {"User-Agent": _USER_AGENT, "Accept": "application/ld+json"}
    if headers:
        h.update(headers)
    client = httpx.Client(headers=h, timeout=30.0, follow_redirects=True)
    try:
        resp = client.post(
            _AUTH_URL,
            json={"email": creds.username, "password": creds.password},
            headers={
                "User-Agent": _USER_AGENT,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
    except Exception as e:
        client.close()
        raise _AE(f"JWT request failed: {e}") from e

    if resp.status_code == 401:
        client.close()
        raise _AE(f"JWT login rejected for {source_code} (bad credentials?)")
    if resp.status_code != 200:
        client.close()
        raise _AE(f"JWT endpoint returned HTTP {resp.status_code}")

    try:
        token = resp.json().get("token", "")
    except Exception as e:
        client.close()
        raise _AE(f"JWT response parse error: {e}") from e

    if not token:
        client.close()
        raise _AE(f"JWT response contained no token for {source_code}")

    client.headers.update({
        "Authorization": f"Bearer {token}",
        "Accept": "application/ld+json",
    })
    return client


def _process_variant(
    conn: sqlite3.Connection,
    source_key: int,
    batch_id: str,
    result: "ScrapeResult",
    product: dict,
    variant: dict,
    retailer: str,
    *,
    sale_type_filter: Optional[str] = None,
) -> bool:
    """Process one product variant: normalize, ensure dim rows, insert staging candidate.

    Returns True if a staging row was inserted, False otherwise.
    The result counters (rows_fetched, rows_inserted, rows_dlq) are mutated in place.
    """
    # Optional saleType filter (e.g. only AUCTION or only DIRECT_PURCHASE)
    if sale_type_filter and variant.get("saleType") != sale_type_filter:
        return False

    product_id = product.get("id")
    name = product.get("name", "")
    appellation_raw = product.get("appellation", "") or ""
    region_raw = product.get("region", "") or ""
    owner_raw = product.get("owner", "") or ""
    color_raw = product.get("color", "") or ""
    color = _map_color(color_raw)

    # Price: priceByCountry dict, values in cents
    price_by_country = variant.get("priceByCountry") or {}
    price_cents = price_by_country.get("FR") or price_by_country.get("BE") or (
        list(price_by_country.values())[0] if price_by_country else None
    )
    if not price_cents:
        return False
    price_eur = price_cents / 100.0

    # Vintage — accept a wide range for auction (older bottles are the point)
    vintage_raw = variant.get("vintage")
    if isinstance(vintage_raw, int) and 1850 <= vintage_raw <= 2035:
        vintage: Optional[int] = vintage_raw
    else:
        vintage = None

    # Wine name from variant (prefer French translation)
    variant_name_raw = variant.get("additionalObservations", {}).get("fr", "") or name
    if not variant_name_raw:
        variant_name_raw = name

    # Apply display-name cleanup before normalization
    producer_raw = owner_raw or variant_name_raw
    variant_name = clean_cuvee_display(variant_name_raw, producer_name=owner_raw or None)
    if not variant_name:
        variant_name = variant_name_raw
    producer_display = clean_producer_display(producer_raw)
    if not producer_display:
        producer_display = producer_raw

    appellation = variant.get("appellation") or appellation_raw or ""
    region = variant.get("region") or region_raw or ""

    producer_norm = normalize_producer(producer_display)
    cuvee_norm = normalize_cuvee(variant_name)
    appellation_norm = norm_text(appellation) if appellation else ""

    if not producer_norm or not cuvee_norm:
        write_dlq(
            conn, source_key, batch_id,
            "parse_error",
            f"Empty producer_norm or cuvee_norm for: {variant_name_raw!r}",
            {"raw_name": variant_name_raw},
        )
        result.rows_dlq += 1
        return False

    wine_key = compute_wine_key(producer_norm, cuvee_norm, vintage, appellation_norm)
    _ensure_producer(conn, producer_norm, producer_display)

    if not _ensure_wine(
        conn, wine_key, producer_norm, variant_name,
        cuvee_norm, appellation, appellation_norm, region, vintage, color,
    ):
        write_dlq(
            conn, source_key, batch_id,
            "unresolved_dim", "Could not resolve producer or appellation",
            {"raw_name": variant_name_raw, "wine_key": wine_key},
        )
        result.rows_dlq += 1
        return False

    source_url = f"{_BASE}/fr/acheter-du-vin/{product.get('slug', product_id)}"
    # For auction lots, include variant ID in hash so per-lot dedup works correctly
    variant_id = variant.get("id") or variant.get("code") or ""
    card_hash = hashlib.sha256(
        json.dumps(
            {
                "wine_key": wine_key,
                "price": price_eur,
                "product_id": product_id,
                "variant_id": variant_id,
                "retailer": retailer,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()

    try:
        inserted = insert_staging_candidate(
            conn,
            wine_key=wine_key,
            source_key=source_key,
            retailer=retailer,
            recorded_at=int(time.time()),
            currency_code="EUR",
            amount_local=price_eur,
            amount_eur=price_eur,
            source_url=source_url,
            content_hash=card_hash,
            batch_id=batch_id,
        )
        result.rows_fetched += 1
        if inserted:
            result.rows_inserted += 1
        else:
            result.rows_skipped_unchanged += 1
        return inserted
    except Exception as e:
        write_dlq(
            conn, source_key, batch_id,
            "validation_error", str(e),
            {"wine_key": wine_key, "price_eur": price_eur},
        )
        result.rows_dlq += 1
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

    def _run_products(
        self,
        client: "httpx.Client",
        source_key: int,
        batch_id: str,
        result: "ScrapeResult",
        limit: Optional[int],
    ) -> None:
        """Iterate fixed-price shop products and insert staging candidates."""
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
                write_dlq(self.conn, source_key, batch_id, "network_error", str(e),
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
                    write_dlq(self.conn, source_key, batch_id, "network_error", str(e),
                              {"url": variants_url})
                    result.rows_dlq += 1
                    continue

                if not isinstance(variants, list):
                    continue

                for variant in variants:
                    if limit is not None and total_fetched >= limit:
                        break

                    # Fixed-price scraper: skip auction-only variants
                    if variant.get("saleType") == "AUCTION":
                        continue

                    _process_variant(
                        self.conn, source_key, batch_id, result,
                        product, variant, "idealwine",
                    )
                    total_fetched += 1

                time.sleep(0.2)

            # Check if there are more pages
            total_items = data.get("hydra:totalItems", 0)
            if page * items_per_page >= total_items:
                break

            page += 1
            time.sleep(1.0)

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
            client = self.authenticated_client(headers=headers, conn=self.conn)
        except AuthMissingError as e:
            return ScrapeResult(error=str(e))
        except AuthError as e:
            return ScrapeResult(error=str(e))

        try:
            self._run_products(client, SOURCE_KEY, batch_id, result, limit)
        finally:
            if client is not None:
                client.close()

        return result


def _ensure_auction_source(conn: sqlite3.Connection) -> Optional[int]:
    """Ensure the idealwine_auctions dim_source row exists; return its source_key."""
    row = conn.execute(
        "SELECT source_key FROM dim_source WHERE source_code = ?",
        ("idealwine_auctions",),
    ).fetchone()
    if row:
        return row[0]
    try:
        auctions_notes = (
            "Auction lot estimates/bids - separate from fixed-price retail. "
            "Shares JWT credentials with idealwine source_code."
        )
        cur = conn.execute(
            """INSERT OR IGNORE INTO dim_source
               (source_code, source_name, source_tier, country_code, base_url,
                license_class, cadence, enabled, requires_auth, notes)
               VALUES (
                 'idealwine_auctions',
                 'iDealwine Auctions',
                 'B_retailer',
                 'FR',
                 'https://www.idealwine.com',
                 'public_check_terms',
                 'weekly',
                 1,
                 1,
                 ?
               )""",
            (auctions_notes,),
        )
        conn.commit()
        if cur.lastrowid:
            return cur.lastrowid
        row2 = conn.execute(
            "SELECT source_key FROM dim_source WHERE source_code = ?",
            ("idealwine_auctions",),
        ).fetchone()
        return row2[0] if row2 else None
    except Exception as exc:
        _logger.error("Could not insert idealwine_auctions dim_source row: %s", exc)
        return None


class IDealwineAuctionsScraper(AuthenticatedScraper):
    """Scrape live auction lots from iDealwine's auction catalogs.

    Authenticates with the same JWT credentials as IDealwineScraper but writes
    to source_code='idealwine_auctions' so auction prices are not conflated with
    fixed-price retail data in fact_price.

    Each auction lot is a product variant with saleType=AUCTION. The price stored
    is the current bid / starting estimate (priceByCountry, in cents → EUR).
    Historical vintage coverage goes back to the early 1900s in Bordeaux catalogs.

    Env vars: ACHILLES_AUTH_IDEALWINE_USERNAME / ACHILLES_AUTH_IDEALWINE_PASSWORD
    (same as the main idealwine scraper).
    """

    source_code = "idealwine_auctions"
    # The JWT credentials env vars match the main source (IDEALWINE, not IDEALWINE_AUCTIONS)
    _auth_source_code = "idealwine"

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.batch_id: Optional[str] = None

    def _login(self, client: "httpx.Client", creds: "Credentials") -> bool:
        """Obtain a JWT bearer token using IDEALWINE credentials."""
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
        client.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/ld+json",
        })
        return True

    def authenticated_client(
        self,
        headers: Optional[dict] = None,
        timeout: float = 30.0,
        *,
        conn=None,
        cache_key: Optional[str] = None,
    ) -> "httpx.Client":
        """Override to use the main IDEALWINE credentials and cache under 'idealwine'.

        Both IDealwineScraper and IDealwineAuctionsScraper share the same JWT, so
        they cache under the same key to avoid redundant logins.
        """
        from ..auth import get_credentials, AuthError as _AE
        from ..session_store import (
            load_session, is_expired, restore_session_to_client,
            extract_session_from_client, save_session,
        )
        if not HAS_DEPS:
            raise AuthError("httpx not installed — install scraper deps")

        key = cache_key or self._auth_source_code  # always "idealwine"

        # Try cached session first
        if conn is not None:
            session = load_session(conn, key)
            if session is not None and not is_expired(session):
                client = httpx.Client(headers=headers or {}, timeout=timeout, follow_redirects=True)
                restore_session_to_client(client, session)
                return client

        # Fresh login with IDEALWINE credentials
        creds = get_credentials(self._auth_source_code)
        client = httpx.Client(headers=headers or {}, timeout=timeout, follow_redirects=True)
        try:
            ok = self._login(client, creds)
        except Exception as e:
            client.close()
            raise AuthError(f"login dance failed for {self.source_code}: {e}") from e
        if not ok:
            client.close()
            raise AuthError(f"login rejected for {self.source_code} (bad credentials?)")

        if conn is not None:
            auth_hdr = client.headers.get("Authorization", "")
            token_type = "jwt_bearer" if auth_hdr.startswith("Bearer ") else "cookie_jar"
            session = extract_session_from_client(key, client, token_type)
            save_session(conn, session)

        return client

    def _fetch_auction_catalogs(self, client: "httpx.Client") -> list:
        """Fetch all active auction catalogs from the /api/v2/shop/auction-catalogs endpoint."""
        try:
            resp = self._fetch(
                lambda: client.get(f"{_AUCTION_CATALOGS_URL}?itemsPerPage=200")
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("hydra:member", [])
        except Exception as e:
            _logger.warning("Could not fetch auction catalogs: %s", e)
            return []

    def _run_auctions(
        self,
        client: "httpx.Client",
        source_key: int,
        batch_id: str,
        result: "ScrapeResult",
        limit: Optional[int],
        active_catalog_ids: "set[int]",
    ) -> None:
        """Iterate all products and collect variants with saleType=AUCTION.

        Only variants whose auctionCatalogId is in active_catalog_ids are processed.
        If active_catalog_ids is empty, all AUCTION variants are accepted.
        """
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
                result.error = f"HTTP error fetching auction products page {page}: {e}"
                write_dlq(self.conn, source_key, batch_id, "network_error", str(e),
                          {"url": products_url})
                result.rows_dlq += 1
                break

            try:
                data = resp.json()
            except Exception as e:
                result.error = f"JSON parse error on auction products: {e}"
                break

            products = data.get("hydra:member", [])
            if not products:
                break

            for product in products:
                if limit is not None and total_fetched >= limit:
                    break

                product_id = product.get("id")
                if not product_id:
                    continue

                name = product.get("name", "")
                if not name:
                    continue

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
                    write_dlq(self.conn, source_key, batch_id, "network_error", str(e),
                              {"url": variants_url})
                    result.rows_dlq += 1
                    continue

                if not isinstance(variants, list):
                    continue

                for variant in variants:
                    if limit is not None and total_fetched >= limit:
                        break

                    # Only process auction variants
                    if variant.get("saleType") != "AUCTION":
                        continue

                    # If we have active catalog IDs, only accept lots from those catalogs
                    catalog_id = variant.get("auctionCatalogId")
                    if active_catalog_ids and catalog_id not in active_catalog_ids:
                        continue

                    inserted = _process_variant(
                        self.conn, source_key, batch_id, result,
                        product, variant, "idealwine_auctions",
                        sale_type_filter=None,  # already filtered above
                    )
                    total_fetched += 1
                    if not inserted and result.rows_fetched > 0:
                        # _process_variant already counted this row
                        pass

                time.sleep(0.2)

            total_items = data.get("hydra:totalItems", 0)
            if page * items_per_page >= total_items:
                break

            page += 1
            time.sleep(1.0)

    def run(self, limit: Optional[int] = None) -> ScrapeResult:
        if not HAS_DEPS:
            return ScrapeResult(error="Missing dependencies: httpx not installed")

        # Credentials use the main IDEALWINE source code
        if not has_credentials(self._auth_source_code):
            return ScrapeResult(
                error="Credentials missing: set ACHILLES_AUTH_IDEALWINE_USERNAME / _PASSWORD"
            )

        # Ensure the dim_source row exists (idempotent)
        source_key = _ensure_auction_source(self.conn)
        if source_key is None:
            return ScrapeResult(error="Could not ensure idealwine_auctions dim_source row")

        batch_id = (
            self.batch_id
            or f"idealwine_auctions-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        )
        result = ScrapeResult(batch_id=batch_id)

        headers = {
            "User-Agent": _USER_AGENT,
            "Accept": "application/ld+json",
        }

        client = None
        try:
            client = self.authenticated_client(headers=headers, conn=self.conn)
        except AuthMissingError as e:
            return ScrapeResult(error=str(e))
        except AuthError as e:
            return ScrapeResult(error=str(e))

        try:
            # Discover active auction catalogs so we can filter variants accordingly
            catalogs = self._fetch_auction_catalogs(client)
            active_catalog_ids: set[int] = {c["id"] for c in catalogs if isinstance(c.get("id"), int)}
            _logger.info(
                "[%s] Found %d active auction catalogs: %s",
                batch_id, len(active_catalog_ids),
                sorted(active_catalog_ids)[:10],
            )

            self._run_auctions(client, source_key, batch_id, result, limit, active_catalog_ids)
        finally:
            if client is not None:
                client.close()

        return result


def _ensure_history_source(conn: sqlite3.Connection) -> Optional[int]:
    """Ensure the idealwine_history dim_source row exists; return its source_key."""
    row = conn.execute(
        "SELECT source_key FROM dim_source WHERE source_code = ?",
        ("idealwine_history",),
    ).fetchone()
    if row:
        return row[0]
    try:
        notes = (
            "Past auction sold-lot results archive - hammer prices for old vintages "
            "(pre-2010). Separate from idealwine_auctions (live lots). "
            "Shares JWT credentials with idealwine source_code."
        )
        cur = conn.execute(
            """INSERT OR IGNORE INTO dim_source
               (source_code, source_name, source_tier, country_code, base_url,
                license_class, cadence, enabled, requires_auth, notes)
               VALUES (
                 'idealwine_history',
                 'iDealwine Historical Auction Results',
                 'B_retailer',
                 'FR',
                 'https://www.idealwine.com',
                 'public_check_terms',
                 'monthly',
                 1,
                 1,
                 ?
               )""",
            (notes,),
        )
        conn.commit()
        if cur.lastrowid:
            return cur.lastrowid
        row2 = conn.execute(
            "SELECT source_key FROM dim_source WHERE source_code = ?",
            ("idealwine_history",),
        ).fetchone()
        return row2[0] if row2 else None
    except Exception as exc:
        _logger.error("Could not insert idealwine_history dim_source row: %s", exc)
        return None


class IDealwineHistoricalScraper(IDealwineAuctionsScraper):
    """Scrape past auction sold-lot results from iDealwine's historical archive.

    iDealwine keeps an extensive archive of hammer prices for past auction
    sales. This scraper pulls that archive so old vintages (pre-2010, pre-2000)
    that never appear in active auction catalogs are covered.

    Strategy
    --------
    1. Try the dedicated ``/api/v2/shop/auction-results`` endpoint first.
       This endpoint, if it exists on the Sylius backend, returns sold lots
       with a ``soldAt`` timestamp suitable for cursor-based incremental runs.
    2. Fall back to the standard ``/api/v2/shop/products`` endpoint with no
       active-catalog filter (all AUCTION variants accepted regardless of
       their ``auctionCatalogId``).  This is the same data as
       ``IDealwineAuctionsScraper`` but without the live-catalog filter, so
       it captures lots from all historical catalogs.

    ``from_date`` parameter
    -----------------------
    Pass an ISO-8601 string (``YYYY-MM-DD``) to skip lots whose ``soldAt``
    is before that date. On the results endpoint this maps to the API filter
    ``?soldAtAfter=YYYY-MM-DD``. On the products fallback it is applied
    client-side via the variant's ``createdAt`` / ``updatedAt`` field.

    The source is registered as ``idealwine_history`` in ``dim_source``, so
    historical hammer prices are kept separate from both retail prices
    (``idealwine``) and live auction estimates (``idealwine_auctions``).

    Env vars: ACHILLES_AUTH_IDEALWINE_USERNAME / ACHILLES_AUTH_IDEALWINE_PASSWORD
    (shared with the main idealwine scraper).
    """

    source_code = "idealwine_history"
    _auth_source_code = "idealwine"

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.batch_id: Optional[str] = None
        self.from_date: Optional[str] = None  # ISO-8601 date string, e.g. "2020-01-01"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse_from_ts(self) -> Optional[int]:
        """Convert self.from_date to a Unix timestamp, or None."""
        if not self.from_date:
            return None
        try:
            from datetime import date
            d = date.fromisoformat(self.from_date)
            return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())
        except Exception:
            return None

    def _run_results_endpoint(
        self,
        client: "httpx.Client",
        source_key: int,
        batch_id: str,
        result: "ScrapeResult",
        limit: Optional[int],
    ) -> bool:
        """Try the /api/v2/shop/auction-results endpoint.

        Returns True if the endpoint existed and was successfully iterated,
        False if it returned 404/405 (meaning we should fall back).
        """
        page = 1
        items_per_page = 30
        total_fetched = 0

        date_filter = f"&soldAtAfter={self.from_date}" if self.from_date else ""

        while True:
            if limit is not None and total_fetched >= limit:
                break

            url = (
                f"{_AUCTION_RESULTS_URL}"
                f"?page={page}&itemsPerPage={items_per_page}{date_filter}"
            )
            try:
                resp = self._fetch(lambda u=url: client.get(u))
            except Exception as e:
                result.error = f"HTTP error on auction-results page {page}: {e}"
                write_dlq(self.conn, source_key, batch_id, "network_error", str(e),
                          {"url": url})
                result.rows_dlq += 1
                return True  # endpoint existed, just errored

            # 404 / 405 → endpoint does not exist on this Sylius instance
            if resp.status_code in (404, 405):
                _logger.info(
                    "[%s] /api/v2/shop/auction-results returned HTTP %d — falling back",
                    batch_id, resp.status_code,
                )
                return False

            try:
                resp.raise_for_status()
            except Exception as e:
                result.error = f"HTTP error on auction-results page {page}: {e}"
                write_dlq(self.conn, source_key, batch_id, "network_error", str(e),
                          {"url": url})
                result.rows_dlq += 1
                return True

            try:
                data = resp.json()
            except Exception as e:
                result.error = f"JSON parse error on auction-results: {e}"
                return True

            lots = data.get("hydra:member", [])
            if not lots:
                break

            from_ts = self._parse_from_ts()

            for lot in lots:
                if limit is not None and total_fetched >= limit:
                    break

                # Date filtering on the lot level (belt-and-suspenders)
                if from_ts:
                    sold_at_raw = lot.get("soldAt") or lot.get("createdAt") or ""
                    if sold_at_raw:
                        try:
                            sold_ts = int(datetime.fromisoformat(
                                sold_at_raw.replace("Z", "+00:00")
                            ).timestamp())
                            if sold_ts < from_ts:
                                continue
                        except Exception:
                            pass

                # Each lot contains embedded product + variant data
                product = lot.get("product") or lot
                variant = lot.get("variant") or lot

                # Ensure saleType is present for _process_variant
                if "saleType" not in variant:
                    variant = dict(variant, saleType="AUCTION")

                # Use hammer price if available, else estimate
                hammer_cents = lot.get("hammerPrice") or lot.get("finalPrice")
                if hammer_cents and "priceByCountry" not in variant:
                    variant = dict(variant, priceByCountry={"FR": hammer_cents})

                inserted = _process_variant(
                    self.conn, source_key, batch_id, result,
                    product, variant, "idealwine_history",
                    sale_type_filter=None,
                )
                total_fetched += 1

            total_items = data.get("hydra:totalItems", 0)
            if page * items_per_page >= total_items:
                break

            page += 1
            time.sleep(1.0)

        return True

    def _run_products_fallback(
        self,
        client: "httpx.Client",
        source_key: int,
        batch_id: str,
        result: "ScrapeResult",
        limit: Optional[int],
    ) -> None:
        """Fallback: iterate /api/v2/shop/products accepting all AUCTION variants.

        Unlike IDealwineAuctionsScraper._run_auctions(), this does NOT filter
        by active catalog IDs, so past catalog lots are included.  A from_date
        guard is applied on the variant's createdAt/updatedAt field.
        """
        page = 1
        items_per_page = 30
        total_fetched = 0
        from_ts = self._parse_from_ts()

        while True:
            if limit is not None and total_fetched >= limit:
                break

            products_url = f"{_PRODUCTS_URL}?page={page}&itemsPerPage={items_per_page}"
            try:
                resp = self._fetch(lambda u=products_url: client.get(u))
                resp.raise_for_status()
            except Exception as e:
                result.error = f"HTTP error fetching products page {page}: {e}"
                write_dlq(self.conn, source_key, batch_id, "network_error", str(e),
                          {"url": products_url})
                result.rows_dlq += 1
                break

            try:
                data = resp.json()
            except Exception as e:
                result.error = f"JSON parse error on products: {e}"
                break

            products = data.get("hydra:member", [])
            if not products:
                break

            for product in products:
                if limit is not None and total_fetched >= limit:
                    break

                product_id = product.get("id")
                if not product_id:
                    continue

                name = product.get("name", "")
                if not name:
                    continue

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
                    write_dlq(self.conn, source_key, batch_id, "network_error", str(e),
                              {"url": variants_url})
                    result.rows_dlq += 1
                    continue

                if not isinstance(variants, list):
                    continue

                for variant in variants:
                    if limit is not None and total_fetched >= limit:
                        break

                    # Only auction variants
                    if variant.get("saleType") != "AUCTION":
                        continue

                    # Date-cursor filtering (from_date support)
                    if from_ts:
                        updated_raw = (
                            variant.get("updatedAt")
                            or variant.get("createdAt")
                            or ""
                        )
                        if updated_raw:
                            try:
                                var_ts = int(datetime.fromisoformat(
                                    updated_raw.replace("Z", "+00:00")
                                ).timestamp())
                                if var_ts < from_ts:
                                    continue
                            except Exception:
                                pass

                    _process_variant(
                        self.conn, source_key, batch_id, result,
                        product, variant, "idealwine_history",
                        sale_type_filter=None,
                    )
                    total_fetched += 1

                time.sleep(0.2)

            total_items = data.get("hydra:totalItems", 0)
            if page * items_per_page >= total_items:
                break

            page += 1
            time.sleep(1.0)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run(self, limit: Optional[int] = None) -> ScrapeResult:  # type: ignore[override]
        if not HAS_DEPS:
            return ScrapeResult(error="Missing dependencies: httpx not installed")

        if not has_credentials(self._auth_source_code):
            return ScrapeResult(
                error="Credentials missing: set ACHILLES_AUTH_IDEALWINE_USERNAME / _PASSWORD"
            )

        # Ensure the dim_source row exists (idempotent)
        source_key = _ensure_history_source(self.conn)
        if source_key is None:
            return ScrapeResult(error="Could not ensure idealwine_history dim_source row")

        batch_id = (
            self.batch_id
            or f"idealwine_history-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        )
        result = ScrapeResult(batch_id=batch_id)

        headers = {
            "User-Agent": _USER_AGENT,
            "Accept": "application/ld+json",
        }

        client = None
        try:
            client = self.authenticated_client(headers=headers, conn=self.conn)
        except AuthMissingError as e:
            return ScrapeResult(error=str(e))
        except AuthError as e:
            return ScrapeResult(error=str(e))

        try:
            _logger.info(
                "[%s] Starting idealwine_history run (from_date=%s, limit=%s)",
                batch_id, self.from_date, limit,
            )

            # Try dedicated results endpoint first; fall back to products scan
            used_results_endpoint = self._run_results_endpoint(
                client, source_key, batch_id, result, limit,
            )

            if not used_results_endpoint:
                _logger.info(
                    "[%s] auction-results endpoint not available; using products fallback",
                    batch_id,
                )
                self._run_products_fallback(client, source_key, batch_id, result, limit)
            else:
                _logger.info(
                    "[%s] Used auction-results endpoint; fetched=%d inserted=%d",
                    batch_id, result.rows_fetched, result.rows_inserted,
                )

        finally:
            if client is not None:
                client.close()

        return result
