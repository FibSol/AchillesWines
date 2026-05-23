"""
Kaggle WineEnthusiast reviews importer.

Source: https://www.kaggle.com/datasets/zynicide/wine-reviews
License: CC BY-NC-SA 4.0 (non-commercial, personal use OK)
Auth:   Kaggle API key required (KAGGLE_USERNAME + KAGGLE_KEY env vars)
Cadence: One-shot (dataset is from 2017, no longer updated)

Downloads winemag-data-130k-v2.csv via the Kaggle API and imports
WineEnthusiast ratings into fact_rating:

  criticCode    = 'WE'
  reviewerType  = 'user_aggregate'  (each row is a single critic review)
  scale         = '/100'
  scoreNorm100  = points  (already on /100 scale)

CSV columns: country, description, designation, points, price, province,
             region_1, region_2, taster_name, taster_twitter_handle, title,
             variety, winery

Vintage is extracted from the title field (e.g. "Domain X 2015 Chardonnay").

Auth setup (one-time):
  1. Create a free account at kaggle.com
  2. Go to Settings → API → Create New Token → downloads kaggle.json
  3. Set env vars:
       KAGGLE_USERNAME=your_username
       KAGGLE_KEY=your_api_key
     Or place kaggle.json at ~/.kaggle/kaggle.json

The scraper degrades gracefully if the Kaggle library is missing or
credentials are absent — it will error with a clear message rather than crash.
"""
import csv
import hashlib
import io
import json
import os
import re
import sqlite3
import time
import uuid
import zipfile
from datetime import datetime, timezone
from typing import Optional

from rich.console import Console

from .base import BaseScraper, ScrapeResult
from ..identity import normalize_producer, normalize_cuvee, compute_wine_key, norm_text
from ..dlq import write_dlq

console = Console()

_DATASET_SLUG = "zynicide/wine-reviews"
_CSV_FILENAME  = "winemag-data-130k-v2.csv"

_CRITIC_CODE   = "WE"
_REVIEWER_TYPE = "user_aggregate"
_SCALE         = "/100"

# Kaggle CSV country name → ISO-3166-1 alpha-2
_COUNTRY_MAP: dict[str, str] = {
    "France": "FR",
    "Italy": "IT",
    "Spain": "ES",
    "Portugal": "PT",
    "Germany": "DE",
    "Austria": "AT",
    "Greece": "GR",
    "Hungary": "HU",
    "Bulgaria": "BG",
    "Romania": "RO",
    "Moldova": "MD",
    "Georgia": "GE",
    "Croatia": "HR",
    "Slovenia": "SI",
    "Slovakia": "SK",
    "Czech Republic": "CZ",
    "Switzerland": "CH",
    "Luxembourg": "LU",
    "Australia": "AU",
    "New Zealand": "NZ",
    "Argentina": "AR",
    "Chile": "CL",
    "Uruguay": "UY",
    "Brazil": "BR",
    "South Africa": "ZA",
    "US": "US",
    "Canada": "CA",
    "Israel": "IL",
    "Lebanon": "LB",
    "Morocco": "MA",
    "Turkey": "TR",
    "China": "CN",
    "Japan": "JP",
    "India": "IN",
    "England": "GB",
    "Ukraine": "UA",
    "Serbia": "RS",
    "Macedonia": "MK",
    "Armenia": "AM",
    "Mexico": "MX",
    "Peru": "PE",
}


def _get_source_key(conn: sqlite3.Connection, source_code: str) -> int:
    row = conn.execute(
        "SELECT source_key FROM dim_source WHERE source_code = ?", (source_code,)
    ).fetchone()
    if row is None:
        raise RuntimeError(
            f"dim_source row missing for '{source_code}'. Run migration 0009."
        )
    return row[0]


def _extract_vintage(title: str) -> Optional[int]:
    m = re.search(r"\b(19[5-9]\d|20[0-3]\d)\b", title or "")
    return int(m.group(1)) if m else None


def _ensure_producer(conn: sqlite3.Connection, producer_norm: str,
                     producer_name: str, country_code: str) -> bool:
    row = conn.execute(
        "SELECT producer_key FROM dim_producer WHERE producer_norm = ?",
        (producer_norm,),
    ).fetchone()
    if row:
        return True
    try:
        conn.execute(
            """INSERT OR IGNORE INTO dim_producer
               (producer_name, producer_norm, country_code,
                allowed_appellations, aliases, status)
               VALUES (?, ?, ?, '[]', '[]', 'pending_review')""",
            (producer_name, producer_norm, country_code),
        )
        conn.commit()
        return True
    except Exception:
        return False


def _ensure_appellation(conn: sqlite3.Connection, app_name: str,
                        country_code: str) -> Optional[int]:
    app_norm = norm_text(app_name)
    if not app_norm:
        return None
    row = conn.execute(
        "SELECT appellation_key FROM dim_appellation WHERE appellation_norm = ?",
        (app_norm,),
    ).fetchone()
    if row:
        return row[0]
    try:
        cur = conn.execute(
            """INSERT OR IGNORE INTO dim_appellation
               (country_code, region, appellation_name, appellation_norm, level)
               VALUES (?, ?, ?, ?, 'regional')""",
            (country_code, app_name, app_name, app_norm),
        )
        conn.commit()
        return cur.lastrowid or conn.execute(
            "SELECT appellation_key FROM dim_appellation WHERE appellation_norm = ?",
            (app_norm,),
        ).fetchone()[0]
    except Exception:
        return None


def _ensure_wine(conn: sqlite3.Connection, wine_key: str, producer_norm: str,
                 cuvee_name: str, cuvee_norm: str, appellation_name: str,
                 country_code: str, vintage: Optional[int]) -> bool:
    if conn.execute("SELECT 1 FROM dim_wine WHERE wine_key = ?", (wine_key,)).fetchone():
        return True
    producer_row = conn.execute(
        "SELECT producer_key FROM dim_producer WHERE producer_norm = ?",
        (producer_norm,),
    ).fetchone()
    if not producer_row:
        return False
    appellation_key = _ensure_appellation(conn, appellation_name or cuvee_name, country_code)
    if not appellation_key:
        return False
    is_nv = 1 if vintage is None else 0
    try:
        conn.execute(
            """INSERT OR IGNORE INTO dim_wine
               (wine_key, producer_key, appellation_key, cuvee_name, cuvee_norm,
                color, vintage, is_non_vintage, bottle_ml, canonical_name)
               VALUES (?, ?, ?, ?, ?, 'red', ?, ?, 750, ?)""",
            (wine_key, producer_row[0], appellation_key, cuvee_name, cuvee_norm,
             vintage, is_nv, cuvee_name),
        )
        conn.commit()
        return True
    except Exception:
        return False


def _download_via_kaggle_api(dataset_slug: str, filename: str) -> Optional[str]:
    """
    Download a Kaggle dataset file using the kaggle Python library.
    Returns the CSV text on success, None if credentials are missing.
    Raises RuntimeError on hard failures.
    """
    try:
        import kaggle
        from kaggle.api.kaggle_api_extended import KaggleApi
        api = KaggleApi()
        api.authenticate()
    except ImportError:
        raise RuntimeError(
            "kaggle library not installed. Run: pip install kaggle"
        )
    except Exception as exc:
        raise RuntimeError(
            f"Kaggle auth failed: {exc}\n"
            "Set KAGGLE_USERNAME + KAGGLE_KEY env vars, or place "
            "kaggle.json at ~/.kaggle/kaggle.json."
        )

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        api.dataset_download_files(dataset_slug, path=tmp, unzip=True, quiet=False)
        csv_path = os.path.join(tmp, filename)
        if not os.path.exists(csv_path):
            # Try to find any CSV
            csvs = [f for f in os.listdir(tmp) if f.endswith(".csv")]
            if not csvs:
                raise RuntimeError(f"No CSV found after extracting {dataset_slug}")
            csv_path = os.path.join(tmp, csvs[0])
        with open(csv_path, encoding="utf-8") as fh:
            return fh.read()


class KaggleReviewsScraper(BaseScraper):
    """
    Imports WineEnthusiast reviews from the Kaggle dataset into fact_rating.
    Requires KAGGLE_USERNAME and KAGGLE_KEY environment variables.
    """

    source_code = "kaggle_reviews"

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.batch_id: Optional[str] = None

    def run(self, limit: Optional[int] = None) -> ScrapeResult:
        source_key = _get_source_key(self.conn, self.source_code)
        batch_id = self.batch_id or (
            f"kaggle-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
            f"-{uuid.uuid4().hex[:8]}"
        )
        result = ScrapeResult(batch_id=batch_id)

        # ── Check for local override first ───────────────────────────────────
        local_path = os.environ.get("KAGGLE_REVIEWS_LOCAL_PATH")
        if local_path and os.path.exists(local_path):
            console.print(f"[cyan]kaggle_reviews[/] using local file: {local_path}")
            with open(local_path, encoding="utf-8") as fh:
                csv_text = fh.read()
        else:
            console.print("[cyan]kaggle_reviews[/] downloading via Kaggle API…")
            try:
                csv_text = _download_via_kaggle_api(_DATASET_SLUG, _CSV_FILENAME)
            except RuntimeError as exc:
                result.error = str(exc)
                console.print(f"[red]kaggle_reviews[/] {exc}")
                return result

        # ── Parse CSV ────────────────────────────────────────────────────────
        reader = csv.DictReader(io.StringIO(csv_text))
        rows = list(reader)
        console.print(f"[cyan]kaggle_reviews[/] {len(rows)} review rows loaded")
        result.rows_fetched = len(rows)

        for row in rows:
            if limit is not None and result.rows_inserted >= limit:
                result.rows_skipped_unchanged += 1
                continue

            try:
                points = int(row.get("points") or 0)
            except ValueError:
                continue
            if points < 50 or points > 100:
                continue

            winery    = (row.get("winery") or "").strip()
            title     = (row.get("title") or "").strip()
            region    = (row.get("region_1") or row.get("province") or "").strip()
            country   = (row.get("country") or "").strip()
            country_code = _COUNTRY_MAP.get(country, "FR")

            vintage = _extract_vintage(title)

            producer_norm = normalize_producer(winery)
            cuvee_norm    = normalize_cuvee(title)
            app_norm      = norm_text(region)
            if not producer_norm or not cuvee_norm:
                continue

            wine_key = compute_wine_key(producer_norm, cuvee_norm, vintage, app_norm)
            _ensure_producer(self.conn, producer_norm, winery, country_code)

            if not _ensure_wine(self.conn, wine_key, producer_norm, title,
                                cuvee_norm, region, country_code, vintage):
                write_dlq(self.conn, source_key, batch_id, "unresolved_dim",
                          f"Cannot resolve wine: {winery!r} / {title!r}",
                          {"winery": winery, "title": title, "wine_key": wine_key})
                result.rows_dlq += 1
                continue

            content_hash = hashlib.sha256(
                json.dumps({"title": title, "points": points}, sort_keys=True).encode()
            ).hexdigest()

            try:
                self.conn.execute(
                    """INSERT OR IGNORE INTO fact_rating
                       (wine_key, source_key, critic_code, reviewer_type,
                        score, scale, score_normalized_100,
                        recorded_at, content_hash, batch_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        wine_key, source_key, _CRITIC_CODE, _REVIEWER_TYPE,
                        points, _SCALE, float(points),
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
                          str(exc), {"wine_key": wine_key, "title": title})
                result.rows_dlq += 1

        self.conn.commit()
        console.print(
            f"[green]kaggle_reviews[/] done — {result.rows_inserted} inserted, "
            f"{result.rows_dlq} DLQ, {result.rows_skipped_unchanged} skipped"
        )
        return result
