"""
ops_auth_sessions — SQLite-backed cache for scraper auth sessions (ADR-010 extension, #22).

Stores JWT bearer tokens and cookie jars so AuthenticatedScraper can reuse an
existing session instead of re-logging in on every batch run.

Session lifecycle:
  - First batch: fresh login → save session to ops_auth_sessions.
  - Subsequent batches: load session → if not expired, skip login entirely.
  - 401 during scrape: caller calls invalidate_session() then retries with fresh login.
  - Expiry: JWT tokens include an `exp` claim (parsed from base64url payload).
    Cookie sessions fall back to DEFAULT_SESSION_TTL_SECONDS.
"""
from __future__ import annotations

import base64
import json
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Optional

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False
    httpx = None  # type: ignore[assignment]

# Conservative TTL for sessions where we cannot parse an explicit expiry.
DEFAULT_SESSION_TTL_SECONDS = 3600  # 1 hour

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS ops_auth_sessions (
    session_key   INTEGER PRIMARY KEY AUTOINCREMENT,
    source_code   TEXT    NOT NULL UNIQUE,
    token_type    TEXT    NOT NULL CHECK (token_type IN ('cookie_jar', 'jwt_bearer')),
    cookie_jar    TEXT,
    auth_token    TEXT,
    extra_headers TEXT,
    created_at    INTEGER NOT NULL DEFAULT (unixepoch()),
    expires_at    INTEGER,
    last_used_at  INTEGER NOT NULL DEFAULT (unixepoch())
)
"""


@dataclass
class AuthSession:
    source_code: str
    token_type: str  # 'cookie_jar' | 'jwt_bearer'
    cookie_jar: dict = field(default_factory=dict)
    auth_token: str = ""
    extra_headers: dict = field(default_factory=dict)
    created_at: int = field(default_factory=lambda: int(time.time()))
    expires_at: Optional[int] = None
    last_used_at: int = field(default_factory=lambda: int(time.time()))


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(_CREATE_TABLE_SQL)
    conn.commit()


def is_expired(session: AuthSession, now: Optional[int] = None) -> bool:
    """Return True if the session has passed its expiry timestamp."""
    t = now if now is not None else int(time.time())
    if session.expires_at is not None:
        return t >= session.expires_at
    return t >= (session.created_at + DEFAULT_SESSION_TTL_SECONDS)


def parse_jwt_exp(token: str) -> Optional[int]:
    """Extract the `exp` claim from a JWT bearer token, or None on failure."""
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return None
        payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64).decode("utf-8"))
        exp = payload.get("exp")
        return int(exp) if isinstance(exp, (int, float)) else None
    except Exception:
        return None


def extract_session_from_client(
    source_code: str,
    client: "httpx.Client",
    token_type: str = "cookie_jar",
) -> "AuthSession":
    """Build an AuthSession from a freshly logged-in httpx.Client.

    For JWT sessions (token_type='jwt_bearer'), reads Authorization header from client.
    For cookie sessions, serialises all cookies to a dict.
    """
    now = int(time.time())
    if token_type == "jwt_bearer":
        auth_header = client.headers.get("Authorization", "") if HAS_HTTPX else ""
        token = (
            auth_header[len("Bearer "):].strip()
            if auth_header.startswith("Bearer ")
            else auth_header
        )
        exp = parse_jwt_exp(token)
        # Expire 60 s before the JWT's own exp to avoid using a token right as it dies.
        expires_at = (exp - 60) if exp is not None else None
        return AuthSession(
            source_code=source_code,
            token_type="jwt_bearer",
            auth_token=token,
            extra_headers={"Authorization": f"Bearer {token}"} if token else {},
            created_at=now,
            expires_at=expires_at,
            last_used_at=now,
        )
    else:
        cookies: dict = {}
        if HAS_HTTPX:
            cookies = {name: value for name, value in client.cookies.items()}
        return AuthSession(
            source_code=source_code,
            token_type="cookie_jar",
            cookie_jar=cookies,
            created_at=now,
            expires_at=None,
            last_used_at=now,
        )


def restore_session_to_client(client: "httpx.Client", session: "AuthSession") -> None:
    """Apply a cached session's credentials to an httpx.Client."""
    if not HAS_HTTPX:
        return
    if session.token_type == "jwt_bearer":
        if session.auth_token:
            client.headers.update({"Authorization": f"Bearer {session.auth_token}"})
        if session.extra_headers:
            client.headers.update(session.extra_headers)
    else:
        for name, value in session.cookie_jar.items():
            client.cookies.set(name, value)
        if session.extra_headers:
            client.headers.update(session.extra_headers)


def load_session(conn: sqlite3.Connection, source_code: str) -> Optional[AuthSession]:
    """Load the cached session for source_code, or None if not present."""
    _ensure_table(conn)
    row = conn.execute(
        "SELECT token_type, cookie_jar, auth_token, extra_headers, "
        "       created_at, expires_at, last_used_at "
        "FROM ops_auth_sessions WHERE source_code = ?",
        (source_code,),
    ).fetchone()
    if not row:
        return None
    return AuthSession(
        source_code=source_code,
        token_type=row[0],
        cookie_jar=json.loads(row[1]) if row[1] else {},
        auth_token=row[2] or "",
        extra_headers=json.loads(row[3]) if row[3] else {},
        created_at=row[4] or 0,
        expires_at=row[5],
        last_used_at=row[6] or 0,
    )


def save_session(conn: sqlite3.Connection, session: AuthSession) -> None:
    """Upsert a session into ops_auth_sessions."""
    _ensure_table(conn)
    now = int(time.time())
    conn.execute(
        """INSERT INTO ops_auth_sessions
               (source_code, token_type, cookie_jar, auth_token, extra_headers,
                created_at, expires_at, last_used_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(source_code) DO UPDATE SET
               token_type    = excluded.token_type,
               cookie_jar    = excluded.cookie_jar,
               auth_token    = excluded.auth_token,
               extra_headers = excluded.extra_headers,
               created_at    = excluded.created_at,
               expires_at    = excluded.expires_at,
               last_used_at  = ?""",
        (
            session.source_code,
            session.token_type,
            json.dumps(session.cookie_jar) if session.cookie_jar else None,
            session.auth_token or None,
            json.dumps(session.extra_headers) if session.extra_headers else None,
            session.created_at,
            session.expires_at,
            session.last_used_at,
            now,
        ),
    )
    conn.commit()


def invalidate_session(conn: sqlite3.Connection, source_code: str) -> None:
    """Delete the cached session for source_code. Call this on a 401 during scraping."""
    _ensure_table(conn)
    conn.execute("DELETE FROM ops_auth_sessions WHERE source_code = ?", (source_code,))
    conn.commit()
