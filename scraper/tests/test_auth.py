"""Unit tests for achilles_scraper.auth."""
import os
import unittest
from unittest import mock

from achilles_scraper import auth


class EnvKeyTests(unittest.TestCase):
    def test_uppercases(self):
        self.assertEqual(auth._env_key("millesima"), "MILLESIMA")

    def test_replaces_dashes(self):
        self.assertEqual(auth._env_key("la-vinia"), "LA_VINIA")

    def test_strips_whitespace(self):
        self.assertEqual(auth._env_key("  vinatis  "), "VINATIS")


class HasCredentialsTests(unittest.TestCase):
    def test_false_when_missing(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(auth.has_credentials("millesima"))

    def test_false_when_empty(self):
        with mock.patch.dict(os.environ, {
            "ACHILLES_AUTH_MILLESIMA_USERNAME": "",
            "ACHILLES_AUTH_MILLESIMA_PASSWORD": "x",
        }, clear=True):
            self.assertFalse(auth.has_credentials("millesima"))

    def test_false_when_username_whitespace_only(self):
        # Empty-after-strip should also fail.
        with mock.patch.dict(os.environ, {
            "ACHILLES_AUTH_MILLESIMA_USERNAME": "   ",
            "ACHILLES_AUTH_MILLESIMA_PASSWORD": "x",
        }, clear=True):
            self.assertFalse(auth.has_credentials("millesima"))

    def test_true_when_both_set(self):
        with mock.patch.dict(os.environ, {
            "ACHILLES_AUTH_MILLESIMA_USERNAME": "alice",
            "ACHILLES_AUTH_MILLESIMA_PASSWORD": "s3cret",
        }, clear=True):
            self.assertTrue(auth.has_credentials("millesima"))


class GetCredentialsTests(unittest.TestCase):
    def test_returns_credentials_dataclass(self):
        with mock.patch.dict(os.environ, {
            "ACHILLES_AUTH_IDEALWINE_USERNAME": "alice",
            "ACHILLES_AUTH_IDEALWINE_PASSWORD": "s3cret",
        }, clear=True):
            creds = auth.get_credentials("idealwine")
            self.assertEqual(creds.username, "alice")
            self.assertEqual(creds.password, "s3cret")

    def test_raises_with_helpful_message_when_missing(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(auth.AuthMissingError) as cm:
                auth.get_credentials("idealwine")
            msg = str(cm.exception)
            self.assertIn("ACHILLES_AUTH_IDEALWINE_USERNAME", msg)
            self.assertIn("ACHILLES_AUTH_IDEALWINE_PASSWORD", msg)

    def test_raises_when_only_password_set(self):
        with mock.patch.dict(os.environ, {
            "ACHILLES_AUTH_RVF_PASSWORD": "x",
        }, clear=True):
            with self.assertRaises(auth.AuthMissingError) as cm:
                auth.get_credentials("rvf")
            self.assertIn("USERNAME", str(cm.exception))
            self.assertNotIn("PASSWORD", str(cm.exception))

    def test_repr_redacts_password(self):
        with mock.patch.dict(os.environ, {
            "ACHILLES_AUTH_X_USERNAME": "alice",
            "ACHILLES_AUTH_X_PASSWORD": "topsecret-do-not-leak",
        }, clear=True):
            creds = auth.get_credentials("x")
            r = repr(creds)
            self.assertNotIn("topsecret-do-not-leak", r)
            self.assertIn("alice", r)
            self.assertIn("redacted", r.lower())

    def test_source_code_with_dash(self):
        with mock.patch.dict(os.environ, {
            "ACHILLES_AUTH_WINE_SEARCHER_USERNAME": "alice",
            "ACHILLES_AUTH_WINE_SEARCHER_PASSWORD": "x",
        }, clear=True):
            creds = auth.get_credentials("wine-searcher")
            self.assertEqual(creds.username, "alice")

    def test_password_with_leading_whitespace_preserved(self):
        # Passwords are *not* stripped — some users have leading spaces.
        with mock.patch.dict(os.environ, {
            "ACHILLES_AUTH_X_USERNAME": "alice",
            "ACHILLES_AUTH_X_PASSWORD": " has-leading-space",
        }, clear=True):
            creds = auth.get_credentials("x")
            self.assertEqual(creds.password, " has-leading-space")


class TestLoginIntegrationTests(unittest.TestCase):
    """test_login() wraps authenticated_client() and never raises."""

    def _make_scraper(self, login_outcome):
        """Build a tiny AuthenticatedScraper subclass that records login calls."""
        class _Probe(auth.AuthenticatedScraper):
            source_code = "probe"
            calls = []

            def __init__(self):
                pass

            def _login(self, client, creds):
                _Probe.calls.append((creds.username, creds.password))
                if isinstance(login_outcome, Exception):
                    raise login_outcome
                return login_outcome

            def run(self, limit=None):
                raise NotImplementedError

        _Probe.calls = []
        return _Probe()

    def test_returns_false_message_when_creds_missing(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            ok, msg = self._make_scraper(login_outcome=True).test_login()
            self.assertFalse(ok)
            self.assertIn("missing credentials", msg)

    def test_returns_false_when_login_rejects(self):
        with mock.patch.dict(os.environ, {
            "ACHILLES_AUTH_PROBE_USERNAME": "alice",
            "ACHILLES_AUTH_PROBE_PASSWORD": "x",
        }, clear=True):
            ok, msg = self._make_scraper(login_outcome=False).test_login()
            self.assertFalse(ok)
            self.assertIn("auth error", msg)

    def test_returns_true_when_login_succeeds(self):
        with mock.patch.dict(os.environ, {
            "ACHILLES_AUTH_PROBE_USERNAME": "alice",
            "ACHILLES_AUTH_PROBE_PASSWORD": "x",
        }, clear=True):
            ok, msg = self._make_scraper(login_outcome=True).test_login()
            self.assertTrue(ok)
            self.assertIn("ok", msg)


if __name__ == "__main__":
    unittest.main()
