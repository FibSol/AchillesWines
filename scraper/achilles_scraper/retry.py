"""
Retry + exponential backoff for HTTP scrapers.

Usage::

    from achilles_scraper.retry import RetryConfig, with_retry

    config = RetryConfig()  # 3 attempts, 30s→300s→1800s cap

    resp = with_retry(lambda: client.get(url), config=config, logger=console)

Rules
-----
- Retryable errors: ``httpx.RequestError`` (network/timeout) **and**
  ``httpx.HTTPStatusError`` whose status code is in
  ``RetryConfig.retryable_status_codes``.
- ``AuthError`` / ``AuthMissingError``: re-raised immediately — wrong credentials
  are not transient.
- Non-retryable 4xx (e.g. 404): re-raised immediately.
- After ``max_attempts`` exhausted: re-raises the **last** exception.
- Uses ``time.sleep`` (synchronous) — the scraper layer is sync.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, TypeVar

try:
    import httpx
    HAS_HTTPX = True
except ImportError:  # pragma: no cover
    HAS_HTTPX = False
    httpx = None  # type: ignore[assignment]

from .errors import AuthError, AuthMissingError

T = TypeVar("T")


@dataclass
class RetryConfig:
    """Configuration for the exponential-backoff retry wrapper."""

    max_attempts: int = 3
    base_delay_seconds: float = 30.0
    max_delay_seconds: float = 1800.0   # 30 min cap
    backoff_factor: float = 10.0        # delay[n] = min(base * factor^(n-1), max)
    # Attempt 1 fails → sleep base*1   = 30 s
    # Attempt 2 fails → sleep base*10  = 300 s (5 min)
    # Attempt 3 fails → give up (no more sleep)
    retryable_status_codes: tuple[int, ...] = field(
        default_factory=lambda: (429, 500, 502, 503, 504)
    )


def _delay_for_attempt(attempt: int, config: RetryConfig) -> float:
    """Return sleep duration (seconds) after the n-th failed attempt (1-based)."""
    raw = config.base_delay_seconds * (config.backoff_factor ** (attempt - 1))
    return min(raw, config.max_delay_seconds)


def with_retry(
    fn: Callable[[], T],
    *,
    config: RetryConfig | None = None,
    logger=None,
) -> T:
    """
    Call ``fn()`` with retry + exponential backoff.

    Parameters
    ----------
    fn:
        Zero-argument callable.  May raise ``httpx.HTTPStatusError``,
        ``httpx.RequestError``, ``AuthError``, or ``AuthMissingError``.
    config:
        ``RetryConfig`` instance; defaults to ``RetryConfig()`` if omitted.
    logger:
        Optional object with a ``print`` method (e.g. ``rich.console.Console``).
        Falls back to ``builtins.print`` if *None*.

    Returns
    -------
    Whatever ``fn()`` returns on a successful call.

    Raises
    ------
    AuthError / AuthMissingError:
        Immediately, without retrying.
    Exception:
        The **last** exception raised after all attempts are exhausted.
    """
    if config is None:
        config = RetryConfig()

    _log = logger.print if logger is not None else print

    last_exc: Exception | None = None

    for attempt in range(1, config.max_attempts + 1):
        try:
            return fn()

        except (AuthError, AuthMissingError):
            # Credentials are wrong — retrying will not help.
            raise

        except Exception as exc:
            # Determine whether the error is retryable.
            retryable = _is_retryable(exc, config)

            if not retryable:
                raise

            last_exc = exc

            if attempt < config.max_attempts:
                delay = _delay_for_attempt(attempt, config)
                _log(
                    f"[yellow]Retry {attempt}/{config.max_attempts - 1} after "
                    f"{_format_delay(delay)} — {_exc_summary(exc)}[/yellow]"
                )
                time.sleep(delay)
            else:
                _log(
                    f"[red]All {config.max_attempts} attempts failed — "
                    f"{_exc_summary(exc)}[/red]"
                )

    # Should not be reachable if max_attempts >= 1, but keeps type-checker happy.
    assert last_exc is not None
    raise last_exc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_retryable(exc: Exception, config: RetryConfig) -> bool:
    """Return True iff the exception warrants a retry."""
    if not HAS_HTTPX:
        return False

    # Network / timeout errors — always retryable
    if isinstance(exc, httpx.RequestError):
        return True

    # HTTP status errors — only if the status code is in the retryable set
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in config.retryable_status_codes

    return False


def _exc_summary(exc: Exception) -> str:
    t = type(exc).__name__
    msg = str(exc)
    return f"{t}: {msg[:120]}" if msg else t


def _format_delay(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    return f"{seconds / 60:.0f}m"
