# REGISTER_IN_CLI = True
"""
Wine-Searcher scraper stub — not yet implemented.

Wine-Searcher requires a paid API subscription (Pro plan) for bulk price access.
The dim_source row is registered (source_key = wine_searcher) but scraping
is deferred until the subscription is confirmed.

See: https://www.wine-searcher.com/api.lml
"""
import sqlite3
from typing import Optional

from .base import BaseScraper, ScrapeResult


class WineSearcherScraper(BaseScraper):
    source_code = "wine_searcher"

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def run(self, limit: Optional[int] = None) -> ScrapeResult:
        return ScrapeResult(error="wine_searcher: not implemented — subscription required")
