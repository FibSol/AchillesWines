"""
Eurostat grape harvest importer — dataset tag00121.

Source: https://ec.europa.eu/eurostat/databrowser/view/tag00121
API:    https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/tag00121
Auth:   None (public Eurostat REST API)
Cadence: Annual (run in June after harvest data is published)

Data: Annual grape harvest in 1 000 tonnes by country and crop type.
Useful as a vintage quality proxy — large harvests often signal diluted vintages.

Writes to fact_harvest_volume.
"""
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx
from rich.console import Console

from .base import BaseScraper, ScrapeResult
from ..dlq import write_dlq

console = Console()

_API_URL = (
    "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/tag00121"
)

_CROP_CODE_MAP = {
    "W1000": "all_grapes",
    "W1100": "wine_grapes",
    "W1200": "table_grapes",
    "W1300": "raisin_grapes",
}

# EU wine-producing countries + EU27 aggregate
_RELEVANT_GEOS = frozenset({
    "FR", "IT", "ES", "DE", "PT", "AT", "GR", "HU", "BG", "RO",
    "CZ", "SK", "SI", "HR", "EU27_2020",
})

_ENSURE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS fact_harvest_volume (
    harvest_id         integer PRIMARY KEY AUTOINCREMENT NOT NULL,
    source_key         integer NOT NULL REFERENCES dim_source(source_key),
    country_code       text    NOT NULL,
    year               integer NOT NULL,
    crop_type          text    NOT NULL
        CHECK(crop_type IN ('all_grapes','wine_grapes','table_grapes','raisin_grapes')),
    volume_1000_tonnes real    NOT NULL,
    batch_id           text    NOT NULL,
    created_at         integer NOT NULL DEFAULT (unixepoch())
);
"""
_ENSURE_IDX_UNIQUE = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_harvest_unique
ON fact_harvest_volume(source_key, country_code, year, crop_type);
"""
_ENSURE_IDX_COUNTRY = """
CREATE INDEX IF NOT EXISTS idx_harvest_country_year
ON fact_harvest_volume(country_code, year);
"""


def _get_source_key(conn: sqlite3.Connection, source_code: str) -> int:
    row = conn.execute(
        "SELECT source_key FROM dim_source WHERE source_code = ?", (source_code,)
    ).fetchone()
    if row is None:
        raise RuntimeError(
            f"dim_source row missing for '{source_code}'. "
            "Run migration 0008 or seed manually."
        )
    return row[0]


def _build_pos_map(dim_info: dict) -> dict[int, str]:
    """Build {position → code} from a Eurostat SDMX-JSON dimension block."""
    cat = dim_info["category"]
    index_map = {v: k for k, v in cat["index"].items()}
    return {pos: code for pos, code in index_map.items()}


class EurostatHarvestScraper(BaseScraper):
    """Imports annual grape harvest volumes from Eurostat tag00121."""

    source_code = "eurostat_harvest"

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.batch_id: Optional[str] = None

    def _ensure_tables(self) -> None:
        self.conn.execute(_ENSURE_TABLE_SQL)
        self.conn.execute(_ENSURE_IDX_UNIQUE)
        self.conn.execute(_ENSURE_IDX_COUNTRY)
        self.conn.commit()

    def run(self, limit: Optional[int] = None) -> ScrapeResult:
        self._ensure_tables()
        source_key = _get_source_key(self.conn, self.source_code)
        batch_id = self.batch_id or f"eurostat-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        result = ScrapeResult(batch_id=batch_id)

        console.print("[cyan]eurostat_harvest[/] fetching tag00121…")
        with httpx.Client(timeout=60, follow_redirects=True) as client:
            try:
                resp = self._fetch(
                    lambda: client.get(_API_URL, params={"format": "JSON", "lang": "EN"})
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                write_dlq(self.conn, source_key, batch_id, "parse_error", str(exc), {
                    "url": _API_URL
                })
                result.rows_dlq += 1
                result.error = str(exc)
                return result

        dims = data.get("dimension", {})
        values = data.get("value", {})

        if not dims or not values:
            result.error = "Unexpected response structure from Eurostat API"
            return result

        try:
            crop_map = _build_pos_map(dims["crops"])   # 4 crop types
            geo_map = _build_pos_map(dims["geo"])       # 43 geographies
            time_map = _build_pos_map(dims["time"])     # years
        except KeyError as exc:
            result.error = f"Missing dimension key: {exc}"
            return result

        n_crops = len(crop_map)
        n_geo = len(geo_map)

        console.print(
            f"[cyan]eurostat_harvest[/] {len(values)} data points, "
            f"{n_crops} crops × {n_geo} geos × {len(time_map)} years"
        )
        result.rows_fetched = len(values)

        for idx_str, volume in values.items():
            if volume is None:
                continue

            idx = int(idx_str)
            # SDMX-JSON flat index: crops vary fastest, then geo, then time
            # index = crop_pos + geo_pos * n_crops + time_pos * n_crops * n_geo
            time_pos = idx // (n_crops * n_geo)
            remainder = idx % (n_crops * n_geo)
            geo_pos = remainder // n_crops
            crop_pos = remainder % n_crops

            crop_code = crop_map.get(crop_pos)
            geo_code = geo_map.get(geo_pos)
            year_str = time_map.get(time_pos)

            if not crop_code or not geo_code or not year_str:
                continue
            if geo_code not in _RELEVANT_GEOS:
                continue
            crop_type = _CROP_CODE_MAP.get(crop_code)
            if not crop_type:
                continue

            if limit is not None and result.rows_inserted >= limit:
                result.rows_skipped_unchanged += 1
                continue

            try:
                self.conn.execute(
                    """
                    INSERT OR REPLACE INTO fact_harvest_volume
                        (source_key, country_code, year, crop_type, volume_1000_tonnes, batch_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (source_key, geo_code, int(year_str), crop_type, float(volume), batch_id),
                )
                result.rows_inserted += 1
            except Exception as exc:
                write_dlq(self.conn, source_key, batch_id, "validation_error", str(exc), {
                    "geo": geo_code, "year": year_str, "crop": crop_type, "volume": volume
                })
                result.rows_dlq += 1

        self.conn.commit()
        console.print(
            f"[green]eurostat_harvest[/] done — "
            f"{result.rows_inserted} inserted / {result.rows_skipped_unchanged} skipped"
        )
        return result
