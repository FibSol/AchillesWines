"""
Unit tests for achilles_scraper.retry.

All tests mock ``time.sleep`` to avoid real waits.
"""
import unittest
from unittest.mock import MagicMock, patch, call

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

from achilles_scraper.errors import AuthError, AuthMissingError
from achilles_scraper.retry import RetryConfig, with_retry, _delay_for_attempt


def _make_response(status_code: int) -> "httpx.Response":
    """Build a minimal fake httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    return resp


def _http_status_error(status_code: int) -> "httpx.HTTPStatusError":
    """Build an httpx.HTTPStatusError for *status_code*."""
    resp = _make_response(status_code)
    return httpx.HTTPStatusError(
        message=f"HTTP {status_code}",
        request=MagicMock(),
        response=resp,
    )


def _request_error() -> "httpx.RequestError":
    return httpx.ConnectError("connection refused")


# ---------------------------------------------------------------------------
# RetryConfig defaults
# ---------------------------------------------------------------------------

class RetryConfigDefaultsTests(unittest.TestCase):
    def test_defaults(self):
        cfg = RetryConfig()
        self.assertEqual(cfg.max_attempts, 3)
        self.assertEqual(cfg.base_delay_seconds, 30.0)
        self.assertEqual(cfg.max_delay_seconds, 1800.0)
        self.assertEqual(cfg.backoff_factor, 10.0)
        self.assertIn(429, cfg.retryable_status_codes)
        self.assertIn(500, cfg.retryable_status_codes)
        self.assertIn(502, cfg.retryable_status_codes)
        self.assertIn(503, cfg.retryable_status_codes)
        self.assertIn(504, cfg.retryable_status_codes)


class DelayCalculationTests(unittest.TestCase):
    def test_attempt_1_is_base(self):
        cfg = RetryConfig(base_delay_seconds=30.0, backoff_factor=10.0, max_delay_seconds=1800.0)
        self.assertAlmostEqual(_delay_for_attempt(1, cfg), 30.0)

    def test_attempt_2_is_base_times_factor(self):
        cfg = RetryConfig(base_delay_seconds=30.0, backoff_factor=10.0, max_delay_seconds=1800.0)
        self.assertAlmostEqual(_delay_for_attempt(2, cfg), 300.0)

    def test_attempt_3_is_capped(self):
        cfg = RetryConfig(base_delay_seconds=30.0, backoff_factor=10.0, max_delay_seconds=1800.0)
        # 30 * 10^2 = 3000 → capped at 1800
        self.assertAlmostEqual(_delay_for_attempt(3, cfg), 1800.0)


# ---------------------------------------------------------------------------
# with_retry behaviour
# ---------------------------------------------------------------------------

@unittest.skipUnless(HAS_HTTPX, "httpx not installed")
class WithRetrySuccessTests(unittest.TestCase):
    @patch("time.sleep")
    def test_succeeds_on_first_attempt(self, mock_sleep):
        fn = MagicMock(return_value="ok")
        result = with_retry(fn)
        self.assertEqual(result, "ok")
        fn.assert_called_once()
        mock_sleep.assert_not_called()

    @patch("time.sleep")
    def test_succeeds_on_second_attempt_after_transient_failure(self, mock_sleep):
        """First call raises a 503 status error; second call succeeds."""
        fn = MagicMock(side_effect=[_http_status_error(503), "ok"])
        cfg = RetryConfig(max_attempts=3, base_delay_seconds=30.0, backoff_factor=10.0)
        result = with_retry(fn, config=cfg)
        self.assertEqual(result, "ok")
        self.assertEqual(fn.call_count, 2)
        mock_sleep.assert_called_once_with(30.0)

    @patch("time.sleep")
    def test_succeeds_on_second_attempt_after_request_error(self, mock_sleep):
        """First call raises a ConnectError; second call succeeds."""
        fn = MagicMock(side_effect=[_request_error(), "response"])
        cfg = RetryConfig(max_attempts=2, base_delay_seconds=5.0, backoff_factor=2.0)
        result = with_retry(fn, config=cfg)
        self.assertEqual(result, "response")
        self.assertEqual(fn.call_count, 2)
        mock_sleep.assert_called_once_with(5.0)


@unittest.skipUnless(HAS_HTTPX, "httpx not installed")
class WithRetryExhaustionTests(unittest.TestCase):
    @patch("time.sleep")
    def test_exhausts_all_attempts_and_reraises(self, mock_sleep):
        """Three consecutive 502 errors should exhaust all attempts."""
        exc = _http_status_error(502)
        fn = MagicMock(side_effect=exc)
        cfg = RetryConfig(max_attempts=3, base_delay_seconds=30.0, backoff_factor=10.0, max_delay_seconds=1800.0)
        with self.assertRaises(httpx.HTTPStatusError) as ctx:
            with_retry(fn, config=cfg)
        self.assertIs(ctx.exception, exc)
        self.assertEqual(fn.call_count, 3)
        # Slept after attempt 1 (30 s) and attempt 2 (300 s), NOT after attempt 3
        self.assertEqual(mock_sleep.call_count, 2)
        mock_sleep.assert_any_call(30.0)
        mock_sleep.assert_any_call(300.0)

    @patch("time.sleep")
    def test_single_attempt_config_reraises_immediately(self, mock_sleep):
        exc = _http_status_error(500)
        fn = MagicMock(side_effect=exc)
        cfg = RetryConfig(max_attempts=1)
        with self.assertRaises(httpx.HTTPStatusError):
            with_retry(fn, config=cfg)
        fn.assert_called_once()
        mock_sleep.assert_not_called()


@unittest.skipUnless(HAS_HTTPX, "httpx not installed")
class WithRetryNoRetryTests(unittest.TestCase):
    @patch("time.sleep")
    def test_does_not_retry_on_auth_error(self, mock_sleep):
        fn = MagicMock(side_effect=AuthError("bad creds"))
        with self.assertRaises(AuthError):
            with_retry(fn)
        fn.assert_called_once()
        mock_sleep.assert_not_called()

    @patch("time.sleep")
    def test_does_not_retry_on_auth_missing_error(self, mock_sleep):
        fn = MagicMock(side_effect=AuthMissingError("no env var"))
        with self.assertRaises(AuthMissingError):
            with_retry(fn)
        fn.assert_called_once()
        mock_sleep.assert_not_called()

    @patch("time.sleep")
    def test_does_not_retry_on_non_retryable_404(self, mock_sleep):
        """404 is not in the default retryable_status_codes."""
        fn = MagicMock(side_effect=_http_status_error(404))
        with self.assertRaises(httpx.HTTPStatusError):
            with_retry(fn)
        fn.assert_called_once()
        mock_sleep.assert_not_called()

    @patch("time.sleep")
    def test_does_not_retry_on_403(self, mock_sleep):
        """403 is not in the default retryable_status_codes."""
        fn = MagicMock(side_effect=_http_status_error(403))
        with self.assertRaises(httpx.HTTPStatusError):
            with_retry(fn)
        fn.assert_called_once()
        mock_sleep.assert_not_called()

    @patch("time.sleep")
    def test_does_not_retry_on_non_http_value_error(self, mock_sleep):
        """Plain ValueError is not retryable."""
        fn = MagicMock(side_effect=ValueError("bad input"))
        with self.assertRaises(ValueError):
            with_retry(fn)
        fn.assert_called_once()
        mock_sleep.assert_not_called()


@unittest.skipUnless(HAS_HTTPX, "httpx not installed")
class WithRetryDelayAccuracyTests(unittest.TestCase):
    @patch("time.sleep")
    def test_delay_sequence_30_300_cap(self, mock_sleep):
        """Verify exact delay values: 30 s, 300 s; no sleep on last failure."""
        fn = MagicMock(side_effect=_http_status_error(503))
        cfg = RetryConfig(max_attempts=3, base_delay_seconds=30.0, backoff_factor=10.0, max_delay_seconds=1800.0)
        with self.assertRaises(httpx.HTTPStatusError):
            with_retry(fn, config=cfg)
        self.assertEqual(mock_sleep.call_args_list, [call(30.0), call(300.0)])

    @patch("time.sleep")
    def test_delay_is_capped_at_max(self, mock_sleep):
        """With 4 attempts the third delay must be capped at max_delay_seconds."""
        fn = MagicMock(side_effect=_http_status_error(500))
        cfg = RetryConfig(
            max_attempts=4,
            base_delay_seconds=30.0,
            backoff_factor=10.0,
            max_delay_seconds=1800.0,
        )
        with self.assertRaises(httpx.HTTPStatusError):
            with_retry(fn, config=cfg)
        # Delays after attempts 1, 2, 3: 30, 300, 1800 (capped from 3000)
        self.assertEqual(
            mock_sleep.call_args_list,
            [call(30.0), call(300.0), call(1800.0)],
        )

    @patch("time.sleep")
    def test_custom_retryable_status_codes(self, mock_sleep):
        """Only retry on codes explicitly in retryable_status_codes."""
        cfg = RetryConfig(max_attempts=2, base_delay_seconds=1.0, retryable_status_codes=(418,))
        # 418 → retryable
        fn = MagicMock(side_effect=[_http_status_error(418), "ok"])
        result = with_retry(fn, config=cfg)
        self.assertEqual(result, "ok")
        mock_sleep.assert_called_once_with(1.0)

        mock_sleep.reset_mock()

        # 503 not in custom list → not retried
        fn2 = MagicMock(side_effect=_http_status_error(503))
        with self.assertRaises(httpx.HTTPStatusError):
            with_retry(fn2, config=cfg)
        mock_sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
