# REGISTER_IN_CLI = True
"""
Cavissima.be scraper — retail price ingestion via authenticated HTML catalog.

Cavissima.be is auth-gated: prices are only visible after login.
Uses AuthenticatedScraper which reads credentials from env vars:
    ACHILLES_AUTH_CAVISSIMA_BE_USERNAME
    ACHILLES_AUTH_CAVISSIMA_BE_PASSWORD
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

from .base import ScrapeResult
from ..auth import AuthenticatedScraper, has_credentials, AuthMissingError, AuthError
from ..identity import normalize_producer, normalize_cuvee, compute_wine_key, norm_text
from ..dlq import write_dlq, insert_staging_candidate

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_BASE = "https://www.cavissima.be"
_CATALOGUE_URL = f"{_BASE}/vins/"
_LOGIN_URL = f"{_BASE}/connexion/"

_logger = logging.getLogger(__name__)


def _extract_vintage(text: str) -> Optional[int]:
    m = re.search(r"\b(199\d|20[0-3]\d)\b", text or "")
    return int(m.group(1)) if m else None


def _extract_price(text: str) -> Optional[float]:
    m = re.search(r"(\d+[.,]\d{1,2})", text or "")
    if m:
        return float(m.group(1).replace(",", "."))
    return None


_COLOR_MAP = {
    "rouge": "red",
    "blanc": "white",
    "rosé": "rosé",
    "rose": "rosé",
    "champagne": "sparkling",
    "effervescent": "sparkling",
    "pétillant": "sparkling",
    "liquoreux": "sweet",
    "moelleux": "sweet",
    "fortifié": "fortified",
    "orange": "orange",
}


def _map_color(text: str) -> str:
    t = text.lower().strip()
    for k, v in _COLOR_MAP.items():
        if k in t:
            return v
    return "red"


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


def _appellation_from_title(conn: sqlite3.Connection, title: str) -> tuple[str, str]:
    """Match the longest known French appellation in the wine title; falls back to Vin de France."""
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
    row = conn.execute(
        "SELECT producer_key FROM dim_producer WHERE producer_norm = ? AND country_code = 'FR'",
        (producer_norm,)
    ).fetchone()
    if row:
        return True
    try:
        conn.execute(
            """INSERT OR IGNORE INTO dim_producer
               (producer_name, producer_norm, country_code, allowed_appellations, aliases, status)
               VALUES (?, ?, 'FR', '[]', '[]', 'pending_review')""",
            (producer_name, producer_norm)
        )
        conn.commit()
        return True
    except Exception:
        return False


class CavissimaBeScraper(AuthenticatedScraper):
    source_code = "cavissima_be"

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.batch_id: Optional[str] = None

    def _login(self, client: "httpx.Client", creds) -> bool:
        """Perform the Cavissima.be form login.

        Cavissima uses a standard POST form login. We first GET the login page
        to capture any CSRF token, then POST with credentials.
        Returns True if login succeeds (redirected away from login page or
        session cookie set), False if credentials are rejected.
        """
        # Step 1: GET the login page to capture CSRF token if present
        try:
            r = client.get(_LOGIN_URL, timeout=15)
            tree = HTMLParser(r.text)

            # Look for CSRF / hidden fields
            csrf_token = None
            token_node = (
                tree.css_first("input[name='_token']")
                or tree.css_first("input[name='csrf_token']")
                or tree.css_first("input[name='authenticity_token']")
                or tree.css_first("input[name='form_key']")
            )
            if token_node:
                csrf_token = token_node.attributes.get("value", "")

            # Build login form data
            form_data: dict = {
                "email": creds.username,
                "password": creds.password,
            }
            # Common field name variants
            for email_field in ["email", "username", "login", "user_email"]:
                form_data[email_field] = creds.username
            for pass_field in ["password", "pass", "pwd", "user_pass"]:
                form_data[pass_field] = creds.password
            if csrf_token:
                form_data["_token"] = csrf_token

            # Detect the form action URL
            form_node = tree.css_first("form[method='post']") or tree.css_first("form")
            action_url = _LOGIN_URL
            if form_node:
                action = form_node.attributes.get("action", "")
                if action:
                    action_url = action if action.startswith("http") else f"{_BASE}{action}"

        except Exception as exc:
            raise AuthError(f"Could not fetch cavissima.be login page: {exc}") from exc

        # Step 2: POST credentials
        try:
            resp = client.post(action_url, data=form_data, timeout=15)
        except Exception as exc:
            raise AuthError(f"Login POST failed for cavissima.be: {exc}") from exc

        # Success heuristics: redirected away from login, or dashboard/account page found
        final_url = str(resp.url)
        text = resp.text.lower()

        # Failure indicators
        if "mot de passe" in text and "incorrect" in text:
            return False
        if "invalid" in text and "password" in text:
            return False
        if "erreur" in text and "connexion" in text:
            return False

        # Success indicators: redirected to account or catalogue
        if "/connexion" not in final_url:
            return True
        if "mon-compte" in final_url or "account" in final_url or "dashboard" in final_url:
            return True

        # If we have a session cookie it's likely OK
        if client.cookies:
            return True

        return False

    def run(self, limit: Optional[int] = None) -> ScrapeResult:
        if not HAS_DEPS:
            return ScrapeResult(error="Missing dependencies: httpx or selectolax not installed")

        source_row = self.conn.execute(
            "SELECT source_key FROM dim_source WHERE source_code = ?", (self.source_code,)
        ).fetchone()
        if not source_row:
            return ScrapeResult(error=f"source_code '{self.source_code}' not found in dim_source")
        SOURCE_KEY = source_row[0]

        if not has_credentials(self.source_code):
            return ScrapeResult(
                error=(
                    "cavissima_be credentials not set. "
                    "Export ACHILLES_AUTH_CAVISSIMA_BE_USERNAME and "
                    "ACHILLES_AUTH_CAVISSIMA_BE_PASSWORD."
                )
            )

        batch_id = self.batch_id or f"cavissima_be-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        result = ScrapeResult(batch_id=batch_id)

        headers = {
            "User-Agent": _USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,*/*",
            "Accept-Language": "fr-BE,fr;q=0.9,nl;q=0.8,en;q=0.7",
        }

        page = 1
        total_fetched = 0

        try:
            client_ctx = self.authenticated_client(headers=headers, timeout=30.0)
        except AuthMissingError as e:
            result.error = f"Credentials missing: {e}"
            return result
        except AuthError as e:
            result.error = f"Login failed: {e}"
            write_dlq(self.conn, SOURCE_KEY, batch_id, "auth_error", str(e), {"url": _LOGIN_URL})
            result.rows_dlq += 1
            return result

        with client_ctx as client:
            def _get(url: str):
                resp = self._fetch(lambda: client.get(url))
                resp.raise_for_status()
                return resp

            while True:
                url = f"{_CATALOGUE_URL}?page={page}" if page > 1 else _CATALOGUE_URL
                try:
                    resp = _get(url)
                except Exception as e:
                    result.error = f"HTTP error on page {page}: {e}"
                    write_dlq(self.conn, SOURCE_KEY, batch_id, "auth_error", str(e), {"url": url})
                    result.rows_dlq += 1
                    break

                if resp.status_code == 404:
                    break

                if resp.status_code in (403, 429):
                    msg = f"Blocked by cavissima.be: HTTP {resp.status_code} on {url}"
                    write_dlq(self.conn, SOURCE_KEY, batch_id, "auth_error", msg, {"url": url, "status": resp.status_code})
                    result.rows_dlq += 1
                    result.error = msg
                    break

                if resp.status_code != 200:
                    result.error = f"Unexpected HTTP {resp.status_code} on {url}"
                    break

                page_hash = hashlib.sha256(resp.content).hexdigest()
                cached = self.conn.execute(
                    "SELECT last_hash FROM ops_content_hashes WHERE url = ?", (url,)
                ).fetchone()

                tree = HTMLParser(resp.text)

                product_cards = (
                    tree.css(".product-item")
                    or tree.css(".product-card")
                    or tree.css(".wine-item")
                    or tree.css(".product")
                    or tree.css("article")
                )

                if not product_cards:
                    break

                if cached and cached[0] == page_hash:
                    result.rows_skipped_unchanged += len(product_cards)
                    if limit is not None and total_fetched + len(product_cards) >= limit:
                        break
                    page += 1
                    time.sleep(0.5)
                    continue

                self.conn.execute(
                    """INSERT OR REPLACE INTO ops_content_hashes
                       (url, source_key, last_hash, last_fetched_at, last_changed_at, fetch_count)
                       VALUES (?, ?, ?, ?, ?,
                         COALESCE((SELECT fetch_count + 1 FROM ops_content_hashes WHERE url = ?), 1))""",
                    (url, SOURCE_KEY, page_hash, int(time.time()), int(time.time()), url),
                )
                self.conn.commit()

                for card in product_cards:
                    if limit is not None and total_fetched >= limit:
                        break

                    name_node = (
                        card.css_first(".product-title")
                        or card.css_first(".product-name")
                        or card.css_first("h2")
                        or card.css_first("h3")
                        or card.css_first(".name")
                    )
                    raw_name = name_node.text(strip=True) if name_node else ""
                    if not raw_name:
                        result.rows_dlq += 1
                        continue

                    price_node = (
                        card.css_first(".price")
                        or card.css_first(".product-price")
                        or card.css_first("[class*='price']")
                    )
                    price_text = price_node.text(strip=True) if price_node else ""
                    price_eur = _extract_price(price_text)
                    if price_eur is None:
                        write_dlq(
                            self.conn, SOURCE_KEY, batch_id,
                            "parse_error", f"No price found for: {raw_name!r}",
                            {"raw_name": raw_name, "url": url},
                        )
                        result.rows_dlq += 1
                        continue

                    vintage = _extract_vintage(raw_name)

                    link_node = card.css_first("a[href]")
                    product_url = url
                    if link_node:
                        href = link_node.attrs.get("href", "")
                        product_url = href if href.startswith("http") else f"{_BASE}{href}"

                    color_text = card.text(strip=True)
                    color = _map_color(color_text)

                    card_hash = hashlib.sha256(
                        json.dumps({"name": raw_name, "price": price_eur, "url": product_url}, sort_keys=True).encode()
                    ).hexdigest()

                    producer_norm = normalize_producer(raw_name)
                    if not producer_norm:
                        write_dlq(
                            self.conn, SOURCE_KEY, batch_id,
                            "parse_error", f"Empty producer_norm for: {raw_name!r}",
                            {"raw_name": raw_name, "url": product_url},
                        )
                        result.rows_dlq += 1
                        continue

                    appellation, appellation_norm = _appellation_from_title(self.conn, raw_name)
                    region = appellation
                    cuvee_norm = normalize_cuvee(raw_name, strip_words=[producer_norm, appellation_norm])
                    wine_key = compute_wine_key(producer_norm, cuvee_norm, vintage, appellation_norm)
                    _ensure_producer(self.conn, producer_norm, raw_name)

                    if not _ensure_wine(
                        self.conn, wine_key, producer_norm, raw_name,
                        cuvee_norm, appellation, appellation_norm, region, vintage, color,
                    ):
                        write_dlq(
                            self.conn, SOURCE_KEY, batch_id,
                            "unresolved_dim", "Could not resolve producer or appellation for dim_wine",
                            {"raw_name": raw_name, "wine_key": wine_key},
                        )
                        result.rows_dlq += 1
                        continue

                    try:
                        inserted = insert_staging_candidate(
                            self.conn,
                            wine_key=wine_key, source_key=SOURCE_KEY, retailer="cavissima_be",
                            recorded_at=int(time.time()), amount_local=price_eur,
                            amount_eur=price_eur, source_url=product_url,
                            content_hash=card_hash, batch_id=batch_id,
                        )
                        if inserted:
                            result.rows_inserted += 1
                            _logger.info("inserted wine_key=%s price=%.2f name=%s", wine_key, price_eur, raw_name)
                        else:
                            result.rows_skipped_unchanged += 1
                    except Exception as e:
                        write_dlq(
                            self.conn, SOURCE_KEY, batch_id,
                            "validation_error", str(e),
                            {"wine_key": wine_key, "price_eur": price_eur, "url": product_url},
                        )
                        result.rows_dlq += 1

                    total_fetched += 1
                    result.rows_fetched += 1

                if limit is not None and total_fetched >= limit:
                    break

                page += 1
                time.sleep(1.0)

        return result
