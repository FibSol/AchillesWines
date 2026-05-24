"""
Per-source authentication for scrapers (ADR-010).

Form-login flow only — re-login on every batch (no session cache). Credentials
are read from environment variables and never written to disk or the DB.

Env pattern (uppercase source_code, '-' → '_'):
    ACHILLES_AUTH_<SOURCE>_USERNAME
    ACHILLES_AUTH_<SOURCE>_PASSWORD

Subclass `AuthenticatedScraper` and implement `_login()` for sites that
gate prices behind a login form.

Session caching (#22): pass `conn=` to `authenticated_client()` to enable
ops_auth_sessions caching. The first call performs a fresh login and saves
the session; subsequent calls within the TTL reuse the cached token/cookies
without re-logging in.
"""
from __future__ import annotations

import os
import sqlite3
from abc import abstractmethod
from dataclasses import dataclass
from typing import Optional

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False
    httpx = None  # type: ignore[assignment]

from .scrapers.base import BaseScraper
from .errors import AuthError, AuthMissingError
from .session_store import (
    extract_session_from_client,
    invalidate_session as _invalidate_session,
    is_expired,
    load_session,
    restore_session_to_client,
    save_session,
)

# Re-export so existing imports from achilles_scraper.auth continue to work.
__all__ = [
    "AuthError", "AuthMissingError", "Credentials",
    "has_credentials", "get_credentials",
    "AuthenticatedScraper",
    "invalidate_auth_session",
]


@dataclass(frozen=True)
class Credentials:
    username: str
    password: str

    def __repr__(self) -> str:  # never leak the password
        return f"Credentials(username={self.username!r}, password=<redacted>)"


def _env_key(source_code: str) -> str:
    return source_code.strip().upper().replace("-", "_")


def has_credentials(source_code: str) -> bool:
    """Return True iff both username + password env vars are present and non-empty."""
    k = _env_key(source_code)
    u = os.getenv(f"ACHILLES_AUTH_{k}_USERNAME", "").strip()
    p = os.getenv(f"ACHILLES_AUTH_{k}_PASSWORD", "")
    return bool(u) and bool(p)


def get_credentials(source_code: str) -> Credentials:
    """Load credentials for `source_code` or raise AuthMissingError."""
    k = _env_key(source_code)
    username = os.getenv(f"ACHILLES_AUTH_{k}_USERNAME", "").strip()
    password = os.getenv(f"ACHILLES_AUTH_{k}_PASSWORD", "")
    if not username or not password:
        missing = []
        if not username:
            missing.append(f"ACHILLES_AUTH_{k}_USERNAME")
        if not password:
            missing.append(f"ACHILLES_AUTH_{k}_PASSWORD")
        raise AuthMissingError(
            f"missing env var(s) for source={source_code}: {', '.join(missing)}"
        )
    return Credentials(username=username, password=password)


class AuthenticatedScraper(BaseScraper):
    """Base class for scrapers that need a username + password form login.

    Subclasses implement `_login(client, creds)` — perform the POST(s) needed
    to attach a session cookie to `client`. Return True on success, False on
    rejected credentials (bad password). Raise AuthError on transport/protocol
    breakage (5xx, parse errors).
    """

    @abstractmethod
    def _login(self, client: "httpx.Client", creds: Credentials) -> bool:
        """Perform the login dance. Must mutate `client` in place (cookies)."""

    def authenticated_client(
        self,
        headers: Optional[dict] = None,
        timeout: float = 30.0,
        *,
        conn: Optional[sqlite3.Connection] = None,
        cache_key: Optional[str] = None,
    ) -> "httpx.Client":
        """Return an httpx.Client with a valid session attached.

        When `conn` is provided, the session is cached in ops_auth_sessions:
          - On cache hit (non-expired): credentials are restored without re-login.
          - On cache miss or expiry: fresh login is performed and saved to cache.

        Parameters
        ----------
        conn:
            SQLite connection for session caching. Pass None to always re-login
            (original ADR-010 behaviour).
        cache_key:
            Override the source_code used as the ops_auth_sessions lookup key.
            Useful when multiple scrapers share one credential set (e.g.
            idealwine + idealwine_auctions both cache under "idealwine").

        Raises
        ------
        AuthMissingError: env vars not set.
        AuthError:        credentials rejected by the site.
        """
        if not HAS_HTTPX:
            raise AuthError("httpx not installed — install scraper deps")

        key = cache_key or self.source_code

        # --- Try cached session first ---
        if conn is not None:
            session = load_session(conn, key)
            if session is not None and not is_expired(session):
                client = httpx.Client(headers=headers or {}, timeout=timeout, follow_redirects=True)
                restore_session_to_client(client, session)
                return client

        # --- Fresh login ---
        creds = get_credentials(self.source_code)
        client = httpx.Client(headers=headers or {}, timeout=timeout, follow_redirects=True)
        try:
            ok = self._login(client, creds)
        except Exception as e:
            client.close()
            raise AuthError(f"login dance failed for {self.source_code}: {e}") from e
        if not ok:
            client.close()
            raise AuthError(f"login rejected for {self.source_code} (bad credentials?)")

        # --- Persist session ---
        if conn is not None:
            auth_hdr = client.headers.get("Authorization", "")
            token_type = "jwt_bearer" if auth_hdr.startswith("Bearer ") else "cookie_jar"
            session = extract_session_from_client(key, client, token_type)
            save_session(conn, session)

        return client

    def test_login(self) -> tuple[bool, str]:
        """Try to log in without scraping anything. Returns (ok, message).

        Used by the /admin/auth "Test login" button. Never raises.
        """
        try:
            with self.authenticated_client() as _:
                return True, "login ok"
        except AuthMissingError as e:
            return False, f"missing credentials: {e}"
        except AuthError as e:
            return False, f"auth error: {e}"
        except Exception as e:  # network, etc.
            return False, f"unexpected error: {e}"


def invalidate_auth_session(conn: sqlite3.Connection, source_code: str) -> None:
    """Remove the cached auth session for source_code.

    Call this when a scraper receives an unexpected 401/403 mid-run so the
    next batch performs a fresh login instead of reusing a stale token.
    """
    _invalidate_session(conn, source_code)
