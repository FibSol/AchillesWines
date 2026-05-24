"""Unit tests for session_store.py (#22 — ops_auth_sessions cache)."""
import base64
import json
import sqlite3
import time
import unittest

from achilles_scraper.session_store import (
    DEFAULT_SESSION_TTL_SECONDS,
    AuthSession,
    extract_session_from_client,
    invalidate_session,
    is_expired,
    load_session,
    parse_jwt_exp,
    restore_session_to_client,
    save_session,
)


def _mem_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


def _make_jwt(exp: int | None = None) -> str:
    """Build a minimal JWT-shaped token (unsigned, for tests only)."""
    header = base64.urlsafe_b64encode(b'{"alg":"HS256"}').rstrip(b"=").decode()
    payload_data: dict = {"sub": "test"}
    if exp is not None:
        payload_data["exp"] = exp
    payload = (
        base64.urlsafe_b64encode(json.dumps(payload_data).encode())
        .rstrip(b"=")
        .decode()
    )
    return f"{header}.{payload}.fakesig"


class TestIsExpired(unittest.TestCase):
    def test_not_expired_with_future_expires_at(self):
        s = AuthSession(source_code="x", token_type="jwt_bearer", expires_at=int(time.time()) + 3600)
        self.assertFalse(is_expired(s))

    def test_expired_with_past_expires_at(self):
        s = AuthSession(source_code="x", token_type="jwt_bearer", expires_at=int(time.time()) - 1)
        self.assertTrue(is_expired(s))

    def test_expired_by_ttl_old_session(self):
        old = int(time.time()) - DEFAULT_SESSION_TTL_SECONDS - 1
        s = AuthSession(source_code="x", token_type="cookie_jar", created_at=old)
        self.assertTrue(is_expired(s))

    def test_not_expired_by_ttl_recent_session(self):
        s = AuthSession(source_code="x", token_type="cookie_jar")
        self.assertFalse(is_expired(s))

    def test_expired_at_exact_boundary(self):
        now = int(time.time())
        s = AuthSession(source_code="x", token_type="jwt_bearer", expires_at=now)
        self.assertTrue(is_expired(s, now=now))


class TestParseJwtExp(unittest.TestCase):
    def test_returns_exp_claim(self):
        future = int(time.time()) + 3600
        token = _make_jwt(exp=future)
        self.assertEqual(parse_jwt_exp(token), future)

    def test_returns_none_when_no_exp(self):
        token = _make_jwt(exp=None)
        self.assertIsNone(parse_jwt_exp(token))

    def test_returns_none_on_garbage(self):
        self.assertIsNone(parse_jwt_exp("not.a.jwt"))

    def test_returns_none_on_empty_string(self):
        self.assertIsNone(parse_jwt_exp(""))

    def test_returns_none_single_part(self):
        self.assertIsNone(parse_jwt_exp("onlyone"))


class TestSaveLoadRoundtrip(unittest.TestCase):
    def setUp(self):
        self.conn = _mem_db()

    def test_jwt_bearer_roundtrip(self):
        session = AuthSession(
            source_code="idealwine",
            token_type="jwt_bearer",
            auth_token="eyABC.eyDEF.sig",
            extra_headers={"Authorization": "Bearer eyABC.eyDEF.sig"},
            expires_at=int(time.time()) + 3600,
        )
        save_session(self.conn, session)
        loaded = load_session(self.conn, "idealwine")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.source_code, "idealwine")
        self.assertEqual(loaded.token_type, "jwt_bearer")
        self.assertEqual(loaded.auth_token, "eyABC.eyDEF.sig")
        self.assertEqual(loaded.extra_headers["Authorization"], "Bearer eyABC.eyDEF.sig")
        self.assertEqual(loaded.expires_at, session.expires_at)

    def test_cookie_jar_roundtrip(self):
        session = AuthSession(
            source_code="cellartracker",
            token_type="cookie_jar",
            cookie_jar={"session_id": "abc123", "remember_token": "xyz"},
        )
        save_session(self.conn, session)
        loaded = load_session(self.conn, "cellartracker")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.token_type, "cookie_jar")
        self.assertEqual(loaded.cookie_jar["session_id"], "abc123")
        self.assertEqual(loaded.cookie_jar["remember_token"], "xyz")

    def test_load_missing_returns_none(self):
        result = load_session(self.conn, "nonexistent_source")
        self.assertIsNone(result)

    def test_upsert_overwrites_existing(self):
        s1 = AuthSession(source_code="idealwine", token_type="jwt_bearer", auth_token="old_token")
        save_session(self.conn, s1)
        s2 = AuthSession(source_code="idealwine", token_type="jwt_bearer", auth_token="new_token")
        save_session(self.conn, s2)

        row_count = self.conn.execute(
            "SELECT COUNT(*) FROM ops_auth_sessions WHERE source_code = 'idealwine'"
        ).fetchone()[0]
        self.assertEqual(row_count, 1)

        loaded = load_session(self.conn, "idealwine")
        self.assertEqual(loaded.auth_token, "new_token")


class TestInvalidate(unittest.TestCase):
    def setUp(self):
        self.conn = _mem_db()

    def test_invalidate_removes_session(self):
        session = AuthSession(source_code="idealwine", token_type="jwt_bearer", auth_token="tok")
        save_session(self.conn, session)
        self.assertIsNotNone(load_session(self.conn, "idealwine"))

        invalidate_session(self.conn, "idealwine")
        self.assertIsNone(load_session(self.conn, "idealwine"))

    def test_invalidate_nonexistent_is_noop(self):
        invalidate_session(self.conn, "does_not_exist")  # must not raise


class TestRestoreSession(unittest.TestCase):
    def test_restore_jwt_injects_authorization_header(self):
        try:
            import httpx
        except ImportError:
            self.skipTest("httpx not installed")
        session = AuthSession(
            source_code="idealwine",
            token_type="jwt_bearer",
            auth_token="mytoken123",
            extra_headers={"Authorization": "Bearer mytoken123"},
        )
        client = httpx.Client()
        restore_session_to_client(client, session)
        self.assertEqual(client.headers.get("Authorization"), "Bearer mytoken123")
        client.close()

    def test_restore_cookie_sets_cookies(self):
        try:
            import httpx
        except ImportError:
            self.skipTest("httpx not installed")
        session = AuthSession(
            source_code="cellartracker",
            token_type="cookie_jar",
            cookie_jar={"sessid": "abc"},
        )
        client = httpx.Client()
        restore_session_to_client(client, session)
        self.assertEqual(client.cookies.get("sessid"), "abc")
        client.close()


class TestExtractSession(unittest.TestCase):
    def test_extract_jwt_reads_authorization_header(self):
        try:
            import httpx
        except ImportError:
            self.skipTest("httpx not installed")
        future_exp = int(time.time()) + 3600
        token = _make_jwt(exp=future_exp)
        client = httpx.Client(headers={"Authorization": f"Bearer {token}"})
        session = extract_session_from_client("idealwine", client, token_type="jwt_bearer")
        self.assertEqual(session.source_code, "idealwine")
        self.assertEqual(session.token_type, "jwt_bearer")
        self.assertEqual(session.auth_token, token)
        # expires_at should be future_exp - 60
        self.assertEqual(session.expires_at, future_exp - 60)
        client.close()

    def test_extract_cookie_jar(self):
        try:
            import httpx
        except ImportError:
            self.skipTest("httpx not installed")
        client = httpx.Client()
        client.cookies.set("sessid", "abc123")
        session = extract_session_from_client("cellartracker", client, token_type="cookie_jar")
        self.assertEqual(session.token_type, "cookie_jar")
        self.assertEqual(session.cookie_jar.get("sessid"), "abc123")
        self.assertIsNone(session.expires_at)  # uses TTL fallback
        client.close()


if __name__ == "__main__":
    unittest.main()
