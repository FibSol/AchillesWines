"""
Unit tests for the Millesima buildId cache logic.

Tests cover:
- Fresh fetch succeeds → cache file written with correct keys
- Homepage down, cache exists → cached buildId returned + warning logged
- Homepage down, no cache → exception re-raised
- Cache file is updated when a fresh fetch succeeds after a previous cache

All tests mock httpx.Client, time.sleep, and file I/O so no real HTTP calls
are made and the test suite stays fast.
"""
import json
import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

# ---------------------------------------------------------------------------
# Helpers to build minimal fake HTTP responses
# ---------------------------------------------------------------------------

def _make_response(html: str, status_code: int = 200) -> "MagicMock":
    resp = MagicMock(spec=httpx.Response if HAS_HTTPX else object)
    resp.status_code = status_code
    resp.text = html
    return resp


def _homepage_html(build_id: str) -> str:
    return (
        f'<html><head></head><body>'
        f'<script id="__NEXT_DATA__" type="application/json">'
        f'{{"buildId": "{build_id}", "other": "data"}}'
        f'</script></body></html>'
    )


def _homepage_html_no_build_id() -> str:
    return '<html><body><script id="__NEXT_DATA__" type="application/json">{}</script></body></html>'


# ---------------------------------------------------------------------------
# Import the module under test AFTER the helpers (avoids import-time side
# effects if selectolax is absent, though we skip tests below if needed).
# ---------------------------------------------------------------------------

try:
    from achilles_scraper.scrapers.millesima import (
        _fetch_build_id,
        _load_cached_build_id,
        _save_cached_build_id,
        _build_id_cache_path,
    )
    HAS_MODULE = True
except ImportError:
    HAS_MODULE = False


@unittest.skipUnless(HAS_HTTPX and HAS_MODULE, "httpx or selectolax not installed")
class BuildIdCachePathTests(unittest.TestCase):
    """_build_id_cache_path() honours ACHILLES_DATA_DIR."""

    def test_default_data_dir(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ACHILLES_DATA_DIR", None)
            path = _build_id_cache_path()
        self.assertEqual(path, Path("data") / "millesima_build_id.json")

    def test_custom_data_dir(self):
        with patch.dict(os.environ, {"ACHILLES_DATA_DIR": "/tmp/achilles"}):
            path = _build_id_cache_path()
        self.assertEqual(path, Path("/tmp/achilles") / "millesima_build_id.json")


@unittest.skipUnless(HAS_HTTPX and HAS_MODULE, "httpx or selectolax not installed")
class SaveAndLoadCacheTests(unittest.TestCase):
    """Round-trip: _save_cached_build_id → _load_cached_build_id."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig = os.environ.get("ACHILLES_DATA_DIR")
        os.environ["ACHILLES_DATA_DIR"] = self._tmpdir.name

    def tearDown(self):
        self._tmpdir.cleanup()
        if self._orig is None:
            os.environ.pop("ACHILLES_DATA_DIR", None)
        else:
            os.environ["ACHILLES_DATA_DIR"] = self._orig

    def test_save_creates_file_with_correct_keys(self):
        _save_cached_build_id("abc123")
        cache_path = _build_id_cache_path()
        self.assertTrue(cache_path.exists())
        with cache_path.open() as fh:
            data = json.load(fh)
        self.assertEqual(data["build_id"], "abc123")
        self.assertIn("cached_at", data)
        self.assertTrue(data["cached_at"])  # non-empty ISO timestamp

    def test_load_returns_none_when_file_absent(self):
        result = _load_cached_build_id()
        self.assertIsNone(result)

    def test_load_returns_build_id_and_cached_at(self):
        _save_cached_build_id("xyz789")
        result = _load_cached_build_id()
        self.assertIsNotNone(result)
        build_id, cached_at = result
        self.assertEqual(build_id, "xyz789")
        self.assertIn("T", cached_at)  # ISO 8601 has a 'T' separator

    def test_load_returns_none_on_corrupt_json(self):
        cache_path = _build_id_cache_path()
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text("NOT JSON", encoding="utf-8")
        result = _load_cached_build_id()
        self.assertIsNone(result)

    def test_load_returns_none_when_build_id_missing_from_json(self):
        cache_path = _build_id_cache_path()
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text('{"cached_at": "2026-01-01T00:00:00+00:00"}', encoding="utf-8")
        result = _load_cached_build_id()
        self.assertIsNone(result)


@unittest.skipUnless(HAS_HTTPX and HAS_MODULE, "httpx or selectolax not installed")
class FetchBuildIdSuccessTests(unittest.TestCase):
    """Fresh fetch succeeds → cache file written with correct keys."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig = os.environ.get("ACHILLES_DATA_DIR")
        os.environ["ACHILLES_DATA_DIR"] = self._tmpdir.name

    def tearDown(self):
        self._tmpdir.cleanup()
        if self._orig is None:
            os.environ.pop("ACHILLES_DATA_DIR", None)
        else:
            os.environ["ACHILLES_DATA_DIR"] = self._orig

    def test_returns_build_id_on_success(self):
        fetch_fn = MagicMock(return_value=_make_response(_homepage_html("build-001")))
        client = MagicMock()
        result = _fetch_build_id(client, fetch_fn=fetch_fn)
        self.assertEqual(result, "build-001")

    def test_cache_file_written_on_success(self):
        fetch_fn = MagicMock(return_value=_make_response(_homepage_html("build-002")))
        client = MagicMock()
        _fetch_build_id(client, fetch_fn=fetch_fn)
        result = _load_cached_build_id()
        self.assertIsNotNone(result)
        build_id, cached_at = result
        self.assertEqual(build_id, "build-002")
        self.assertTrue(cached_at)

    def test_cache_file_updated_on_subsequent_success(self):
        """Calling _fetch_build_id twice with different ids overwrites the cache."""
        client = MagicMock()

        fetch_fn_first = MagicMock(return_value=_make_response(_homepage_html("first-id")))
        _fetch_build_id(client, fetch_fn=fetch_fn_first)
        cached_first = _load_cached_build_id()
        self.assertEqual(cached_first[0], "first-id")

        fetch_fn_second = MagicMock(return_value=_make_response(_homepage_html("second-id")))
        _fetch_build_id(client, fetch_fn=fetch_fn_second)
        cached_second = _load_cached_build_id()
        self.assertEqual(cached_second[0], "second-id")


@unittest.skipUnless(HAS_HTTPX and HAS_MODULE, "httpx or selectolax not installed")
class FetchBuildIdFallbackTests(unittest.TestCase):
    """Homepage down scenarios."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig = os.environ.get("ACHILLES_DATA_DIR")
        os.environ["ACHILLES_DATA_DIR"] = self._tmpdir.name

    def tearDown(self):
        self._tmpdir.cleanup()
        if self._orig is None:
            os.environ.pop("ACHILLES_DATA_DIR", None)
        else:
            os.environ["ACHILLES_DATA_DIR"] = self._orig

    def test_homepage_down_cache_exists_returns_cached_build_id(self):
        """When fetch raises and a cache exists, return the cached value."""
        # Seed the cache first
        _save_cached_build_id("cached-build-id")

        fetch_fn = MagicMock(side_effect=httpx.ConnectError("connection refused"))
        client = MagicMock()

        result = _fetch_build_id(client, fetch_fn=fetch_fn)
        self.assertEqual(result, "cached-build-id")

    def test_homepage_down_cache_exists_logs_warning(self):
        """Warning must mention 'cached' or 'homepage unreachable'."""
        _save_cached_build_id("cached-build-id")

        fetch_fn = MagicMock(side_effect=httpx.ConnectError("connection refused"))
        client = MagicMock()

        with self.assertLogs("achilles_scraper.scrapers.millesima", level=logging.WARNING) as cm:
            _fetch_build_id(client, fetch_fn=fetch_fn)

        # At least one warning message should reference homepage or cached
        combined = " ".join(cm.output).lower()
        self.assertTrue(
            "homepage" in combined or "cached" in combined,
            msg=f"Expected 'homepage' or 'cached' in log output; got: {cm.output}",
        )

    def test_homepage_down_no_cache_reraises_exception(self):
        """When fetch raises and NO cache exists, re-raise the original exception."""
        exc = httpx.ConnectError("connection refused")
        fetch_fn = MagicMock(side_effect=exc)
        client = MagicMock()

        with self.assertRaises(httpx.ConnectError) as ctx:
            _fetch_build_id(client, fetch_fn=fetch_fn)
        self.assertIs(ctx.exception, exc)

    def test_homepage_down_no_cache_reraises_timeout(self):
        """Also re-raises on timeout when no cache exists."""
        exc = httpx.TimeoutException("timed out")
        fetch_fn = MagicMock(side_effect=exc)
        client = MagicMock()

        with self.assertRaises(httpx.TimeoutException):
            _fetch_build_id(client, fetch_fn=fetch_fn)

    def test_cache_updated_after_recovery(self):
        """After a down period, a successful fetch overwrites the stale cache."""
        # Put a stale cached value
        _save_cached_build_id("stale-id")

        # Now the homepage is back up with a new buildId
        fetch_fn = MagicMock(return_value=_make_response(_homepage_html("fresh-id")))
        client = MagicMock()

        result = _fetch_build_id(client, fetch_fn=fetch_fn)
        self.assertEqual(result, "fresh-id")

        # Cache must be updated
        cached = _load_cached_build_id()
        self.assertEqual(cached[0], "fresh-id")


if __name__ == "__main__":
    unittest.main()
