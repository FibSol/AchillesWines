from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, TypeVar

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

from ..retry import RetryConfig, with_retry

T = TypeVar("T")


@dataclass
class ScrapeResult:
    rows_fetched: int = 0
    rows_inserted: int = 0
    rows_dlq: int = 0
    rows_skipped_unchanged: int = 0
    batch_id: str = ""
    error: str | None = None


class BaseScraper(ABC):
    source_code: str = ""

    # Subclasses may override this to tune retry behaviour per scraper.
    retry_config: RetryConfig = field(default_factory=RetryConfig)  # type: ignore[assignment]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Ensure each subclass gets its own RetryConfig instance so mutations
        # on one scraper class don't bleed into others.
        if "retry_config" not in cls.__dict__:
            cls.retry_config = RetryConfig()

    def _fetch(
        self,
        fn: Callable[[], T],
        *,
        config: Optional[RetryConfig] = None,
        logger=None,
    ) -> T:
        """
        Execute an HTTP callable ``fn`` with exponential-backoff retry.

        Parameters
        ----------
        fn:
            Zero-argument callable that performs a single HTTP request and
            returns its result (e.g. ``lambda: client.get(url)``).  May raise
            ``httpx.HTTPStatusError``, ``httpx.RequestError``, ``AuthError``,
            or ``AuthMissingError``.
        config:
            Override the scraper-level ``retry_config`` for this call.
        logger:
            rich Console (or any object with ``.print``).  Falls back to
            ``builtins.print``.

        Returns
        -------
        Whatever ``fn()`` returns on success.

        Raises
        ------
        AuthError / AuthMissingError:
            Immediately, without retrying.
        Exception:
            After all retry attempts are exhausted.
        """
        return with_retry(fn, config=config or self.retry_config, logger=logger)

    @abstractmethod
    def run(self, limit=None) -> ScrapeResult:
        ...
