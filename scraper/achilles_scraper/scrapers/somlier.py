"""
soMLier / Mendeley Data wine dataset importer.

Manual download required
------------------------
The soMLier dataset is published on Mendeley Data and requires a free account to
download.  The DOI is 10.17632/m9gfj7nhkv.1 (soMLier: A dataset for wine and
food pairing).

To activate this importer:
  1. Create a free account at https://data.mendeley.com
  2. Navigate to https://data.mendeley.com/datasets/m9gfj7nhkv
  3. Download the CSV file (typically "somlier_wines.csv" or similar)
  4. Place it at: data/somlier.csv   (relative to the project root)
  5. Run: achilles-scraper run --source somlier

Expected CSV columns (approximate):
  wine_name     — full wine name (producer + cuvée often combined)
  winery        — producer/winery name
  region        — wine region / appellation
  variety       — grape variety
  vintage       — vintage year (may be absent / null for NV)
  rating        — score, scale varies (check header; usually /100 or /5)
  rating_count  — number of individual user ratings (optional)
  country       — country of origin (filter: keep France only)

Column mapping:
  producer_norm   ← normalize_producer(winery or wine_name prefix)
  cuvee_norm      ← normalize_cuvee(wine_name)
  vintage         ← int(vintage) or None for NV
  appellation_norm ← normalize appellation from region column
  score_norm100   ← normalize_score_to_100(rating, scale)

Source metadata:
  critic_code    = 'SM'
  reviewer_type  = 'user_aggregate'
  tier           = 'D_user_aggregate'
  cadence        = 'one_shot'
  needs_review   = 1 (crowd data — staging only, tiebreaker policy)
"""
import csv
import hashlib
import json
import logging
import os
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from rich.console import Console

from .base import BaseScraper, ScrapeResult
from ..dlq import write_dlq
from ..identity import normalize_producer, normalize_cuvee, compute_wine_key

console = Console()
_logger = logging.getLogger(__name__)

_CRITIC_CODE = "SM"
_REVIEWER_TYPE = "user_aggregate"
_SCALE_DEFAULT = "/100"

# The user must place the downloaded CSV here (relative to project root)
_DEFAULT_CSV_PATH = "data/somlier.csv"
# Override via environment variable
_ENV_CSV_PATH = "SOMLIER_CSV_PATH"

# Mendeley Data metadata for the error message
_MENDELEY_DOI = "10.17632/m9gfj7nhkv.1"
_MENDELEY_URL = "https://data.mendeley.com/datasets/m9gfj7nhkv"


def _get_source_key(conn: sqlite3.Connection, source_code: str) -> int:
    row = conn.execute(
        "SELECT source_key FROM dim_source WHERE source_code = ?", (source_code,)
    ).fetchone()
    if row is None:
        raise RuntimeError(
            f"dim_source row missing for '{source_code}'. Run migration 0020."
        )
    return row[0]


def _detect_scale(headers: list[str]) -> str:
    """Best-effort detection of rating scale from CSV headers."""
    lh = [h.lower() for h in headers]
    if "rating_100" in lh or any("100" in h for h in lh):
        return "/100"
    if "rating_5" in lh or any("_5" in h for h in lh):
        return "/5"
    if "rating_20" in lh or any("_20" in h for h in lh):
        return "/20"
    # Default assumption
    return "/100"


def _normalize_score(score_str: str, scale: str) -> Optional[float]:
    """Convert raw score string to /100. Returns None if invalid."""
    try:
        score = float(score_str.strip())
    except (ValueError, AttributeError):
        return None
    if scale == "/100":
        if 0 <= score <= 100:
            return round(score, 2)
    elif scale == "/5":
        if 0 <= score <= 5:
            return round(score / 5.0 * 100, 2)
    elif scale == "/20":
        if 0 <= score <= 20:
            return round(score / 20.0 * 100, 2)
    return None


class SoMLierScraper(BaseScraper):
    """
    Imports soMLier / Mendeley Data wine dataset into staging_rating_candidates.

    This scraper is a MANUAL-DOWNLOAD stub.  It requires the user to first
    download the dataset CSV from Mendeley Data (DOI: 10.17632/m9gfj7nhkv.1)
    and place it at data/somlier.csv (or set SOMLIER_CSV_PATH env var).

    If the CSV is absent, the scraper logs a DLQ entry with
    error_class='scraper_not_applicable' and returns cleanly — it does NOT crash.

    When the CSV IS present, it:
      - Parses every row
      - Keeps France-only wines (country_code='FR')
      - Normalizes producer + cuvée names
      - Normalizes score to /100
      - Inserts into staging_rating_candidates with needs_review=1
      - Deduplicates via content_hash (wine_id hash)
    """

    source_code = "somlier"

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.batch_id: Optional[str] = None

    def run(self, limit: Optional[int] = None) -> ScrapeResult:
        source_key = _get_source_key(self.conn, self.source_code)
        batch_id = self.batch_id or (
            f"somlier-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
            f"-{uuid.uuid4().hex[:8]}"
        )
        result = ScrapeResult(batch_id=batch_id)

        # ── Locate the CSV file ──────────────────────────────────────────────
        csv_path_str = os.environ.get(_ENV_CSV_PATH, _DEFAULT_CSV_PATH)
        # Resolve relative to project root (3 levels up from this file)
        project_root = Path(__file__).resolve().parent.parent.parent.parent
        csv_path = Path(csv_path_str)
        if not csv_path.is_absolute():
            csv_path = project_root / csv_path

        if not csv_path.exists():
            msg = (
                f"soMLier dataset requires manual download from Mendeley Data "
                f"(DOI: {_MENDELEY_DOI}); "
                f"place CSV at data/somlier.csv to activate. "
                f"URL: {_MENDELEY_URL}"
            )
            console.print(
                f"[yellow]somlier[/] dataset CSV not found at {csv_path}. "
                f"Logging scraper_not_applicable DLQ entry."
            )
            write_dlq(
                self.conn,
                source_key,
                batch_id,
                "scraper_not_applicable",
                msg,
                {"expected_path": str(csv_path), "doi": _MENDELEY_DOI},
            )
            self.conn.commit()
            result.rows_dlq += 1
            return result

        console.print(f"[cyan]somlier[/] loading CSV from {csv_path}")

        # ── Parse CSV ────────────────────────────────────────────────────────
        with open(csv_path, encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames is None:
                result.error = "soMLier CSV is empty or has no header row"
                return result

            headers = list(reader.fieldnames)
            scale = _detect_scale(headers)
            console.print(f"[cyan]somlier[/] columns: {headers[:8]}... scale={scale}")

            # Column name candidates (case-insensitive)
            lh = {h.lower(): h for h in headers}

            def _col(*candidates: str) -> Optional[str]:
                for c in candidates:
                    if c in lh:
                        return lh[c]
                return None

            col_wine   = _col("wine_name", "wine", "name", "title")
            col_winery = _col("winery", "producer", "domaine", "domaine_name")
            col_region = _col("region", "appellation", "area", "zone")
            col_vintage = _col("vintage", "year", "millesime")
            col_country = _col("country", "pays", "country_code")
            col_rating  = _col("rating", "score", "points", "rating_100", "rating_5")
            col_count   = _col("rating_count", "ratings_count", "num_ratings", "n_ratings")

            rows_read = 0
            for row in reader:
                rows_read += 1
                result.rows_fetched += 1

                # Country filter — France only
                country_raw = (row.get(col_country) or "").strip().upper() if col_country else ""
                if country_raw and country_raw not in ("FR", "FRANCE", "FRA"):
                    result.rows_skipped_unchanged += 1
                    continue

                # Extract fields
                wine_name   = (row.get(col_wine) or "").strip() if col_wine else ""
                winery_name = (row.get(col_winery) or "").strip() if col_winery else ""
                region_raw  = (row.get(col_region) or "").strip() if col_region else ""
                vintage_raw = (row.get(col_vintage) or "").strip() if col_vintage else ""
                rating_raw  = (row.get(col_rating) or "").strip() if col_rating else ""
                count_raw   = (row.get(col_count) or "").strip() if col_count else ""

                if not wine_name and not winery_name:
                    result.rows_skipped_unchanged += 1
                    continue

                if not rating_raw:
                    result.rows_skipped_unchanged += 1
                    continue

                # Normalize score
                score_norm = _normalize_score(rating_raw, scale)
                if score_norm is None:
                    write_dlq(self.conn, source_key, batch_id, "validation_error",
                              f"Invalid score: {rating_raw!r} (scale={scale})",
                              {"wine": wine_name, "winery": winery_name})
                    result.rows_dlq += 1
                    continue

                raw_score = float(rating_raw)

                # Vintage
                try:
                    vintage: Optional[int] = int(vintage_raw) if vintage_raw else None
                except ValueError:
                    vintage = None

                # Normalize identity
                display_name = wine_name or winery_name
                producer_norm = normalize_producer(winery_name or wine_name)
                cuvee_norm = normalize_cuvee(wine_name or winery_name)
                if not producer_norm or not cuvee_norm:
                    result.rows_skipped_unchanged += 1
                    continue

                wine_key = compute_wine_key(producer_norm, cuvee_norm, vintage, "")

                # Rating count
                try:
                    rating_count: Optional[int] = int(count_raw) if count_raw else None
                except ValueError:
                    rating_count = None

                # Content hash  — dedup key: (wine_key, critic_code, scale, raw_score)
                content_hash = hashlib.sha256(
                    json.dumps({
                        "wine_key": wine_key,
                        "critic_code": _CRITIC_CODE,
                        "raw_score": rating_raw,
                    }).encode()
                ).hexdigest()

                # Insert into staging
                try:
                    self.conn.execute(
                        """INSERT OR IGNORE INTO staging_rating_candidates
                           (wine_key, source_key, critic_code, reviewer_type,
                            score, scale, score_normalized_100, rating_count,
                            recorded_at, content_hash, batch_id, needs_review)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                        (
                            wine_key, source_key, _CRITIC_CODE, _REVIEWER_TYPE,
                            round(raw_score, 4), scale, score_norm, rating_count,
                            int(time.time()), content_hash, batch_id,
                        ),
                    )
                    changed = self.conn.execute("SELECT changes()").fetchone()[0]
                    if changed:
                        result.rows_inserted += 1
                    else:
                        result.rows_skipped_unchanged += 1
                except Exception as exc:
                    write_dlq(self.conn, source_key, batch_id, "validation_error",
                              str(exc), {"wine_key": wine_key, "wine": display_name})
                    result.rows_dlq += 1

                if limit is not None and result.rows_inserted >= limit:
                    break

        self.conn.commit()
        console.print(
            f"[green]somlier[/] done — {result.rows_inserted} inserted, "
            f"{result.rows_dlq} DLQ, {result.rows_skipped_unchanged} skipped"
        )
        return result
