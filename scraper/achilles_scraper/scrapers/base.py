from abc import ABC, abstractmethod
from dataclasses import dataclass, field

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

    @abstractmethod
    def run(self, limit=None) -> ScrapeResult:
        ...
