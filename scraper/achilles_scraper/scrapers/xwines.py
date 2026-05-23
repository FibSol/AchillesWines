"""
X-Wines crowd ratings importer.

Source: https://github.com/rogerioxavier/X-Wines
License: CC0 (public domain)
Auth:   None
Cadence: Annual

Downloads two CSVs from GitHub:
  - XWines_Test_100_wines.csv    (wine master: WineID, WineName, WineryName,
                                   Type, Grapes, Country, RegionName, Vintages)
  - XWines_Test_1K_ratings.csv   (ratings: RatingID, UserID, WineID, Vintage,
                                   Rating[1-5], Date)

Wine matching strategy (no wine_key available in X-Wines):
  1. normalize_producer(WineryName) → look up in dim_producer
  2. normalize_cuvee(WineName)       → compute wine_key
  3. If dim_wine row already exists: link rating
  4. If producer not in dim_producer: insert as pending_review; wine pending
     FK resolution (will be picked up in next reconciliation pass)

Ratings stored in fact_rating with:
  criticCode    = 'XW'
  reviewerType  = 'user_aggregate'
  scale         = '/5'
  scoreNorm100  = (avg_rating / 5) * 100
  ratingCount   = number of individual user ratings per (WineID, Vintage)

The full dataset (21 M ratings) is large — use --limit to sample.
The test dataset (100 wines / ~1K ratings) is used by default from GitHub.
"""
import csv
import io
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from collections import defaultdict
from typing import Optional

import httpx
from rich.console import Console

from .base import BaseScraper, ScrapeResult
from ..identity import normalize_producer, normalize_cuvee, compute_wine_key, norm_text
from ..dlq import write_dlq

console = Console()

# Test dataset — 100 wines + ~1K ratings, plain CSV (no zip)
_WINES_URL_SLIM = (
    "https://raw.githubusercontent.com/rogerioxavier/X-Wines/main/"
    "Dataset/last/XWines_Test_100_wines.csv"
)
_RATINGS_URL_SLIM = (
    "https://raw.githubusercontent.com/rogerioxavier/X-Wines/main/"
    "Dataset/last/XWines_Test_1K_ratings.csv"
)

# Full dataset lives on Google Drive — set XWINES_FULL_WINES_PATH /
# XWINES_FULL_RATINGS_PATH env vars to local file paths if pre-downloaded.
_ENV_WINES_PATH   = "XWINES_FULL_WINES_PATH"
_ENV_RATINGS_PATH = "XWINES_FULL_RATINGS_PATH"

_CRITIC_CODE   = "XW"
_REVIEWER_TYPE = "user_aggregate"
_SCALE         = "/5"


def _get_source_key(conn: sqlite3.Connection, source_code: str) -> int:
    row = conn.execute(
        "SELECT source_key FROM dim_source WHERE source_code = ?", (source_code,)
    ).fetchone()
    if row is None:
        raise RuntimeError(
            f"dim_source row missing for '{source_code}'. Run migration 0009."
        )
    return row[0]


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


def _ensure_wine(
    conn: sqlite3.Connection,
    wine_key: str,
    producer_norm: str,
    cuvee_name: str,
    cuvee_norm: str,
    country_code: str,
    color: str,
    vintage: Optional[int],
) -> bool:
    if conn.execute("SELECT 1 FROM dim_wine WHERE wine_key = ?", (wine_key,)).fetchone():
        return True

    producer_row = conn.execute(
        "SELECT producer_key FROM dim_producer WHERE producer_norm = ?",
        (producer_norm,),
    ).fetchone()
    if not producer_row:
        return False

    # Find or create a generic "country-level" appellation
    appellation_norm = f"{country_code.lower()}_generic"
    app_row = conn.execute(
        "SELECT appellation_key FROM dim_appellation WHERE appellation_norm = ?",
        (appellation_norm,),
    ).fetchone()
    if app_row:
        appellation_key = app_row[0]
    else:
        try:
            cur = conn.execute(
                """INSERT OR IGNORE INTO dim_appellation
                   (country_code, region, appellation_name, appellation_norm, level)
                   VALUES (?, 'Unknown', ?, ?, 'regional')""",
                (country_code, f"{country_code} Generic", appellation_norm),
            )
            conn.commit()
            appellation_key = cur.lastrowid
            if not appellation_key:
                row2 = conn.execute(
                    "SELECT appellation_key FROM dim_appellation WHERE appellation_norm = ?",
                    (appellation_norm,),
                ).fetchone()
                appellation_key = row2[0] if row2 else None
        except Exception:
            return False

    if not appellation_key:
        return False

    is_nv = 1 if vintage is None else 0
    try:
        conn.execute(
            """INSERT OR IGNORE INTO dim_wine
               (wine_key, producer_key, appellation_key, cuvee_name, cuvee_norm,
                color, vintage, is_non_vintage, bottle_ml, canonical_name)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 750, ?)""",
            (wine_key, producer_row[0], appellation_key, cuvee_name, cuvee_norm,
             color, vintage, is_nv, cuvee_name),
        )
        conn.commit()
        return True
    except Exception:
        return False


def _xwines_type_to_color(wine_type: str) -> str:
    mapping = {
        "Red": "red",
        "White": "white",
        "Rosé": "rosé",
        "Rose": "rosé",
        "Sparkling": "sparkling",
        "Dessert/Port": "fortified",
        "Fortified": "fortified",
        "Sweet": "sweet",
    }
    return mapping.get(wine_type, "red")


class XWinesScraper(BaseScraper):
    """
    Imports X-Wines wine catalog and aggregated crowd ratings into
    fact_rating (criticCode='XW', reviewerType='user_aggregate').

    By default uses the slim dataset (1 K wines / 150 K ratings) from GitHub.
    Set XWINES_FULL_WINES_PATH + XWINES_FULL_RATINGS_PATH to local file paths
    for the full 100 K wine / 21 M rating dataset downloaded from Google Drive.
    """

    source_code = "xwines"

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.batch_id: Optional[str] = None

    def run(self, limit: Optional[int] = None) -> ScrapeResult:
        import os

        source_key = _get_source_key(self.conn, self.source_code)
        batch_id = self.batch_id or (
            f"xwines-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
            f"-{uuid.uuid4().hex[:8]}"
        )
        result = ScrapeResult(batch_id=batch_id)

        # ── Load wines CSV ───────────────────────────────────────────────────
        wines_path = os.environ.get(_ENV_WINES_PATH)
        if wines_path:
            console.print(f"[cyan]xwines[/] loading wines from local file: {wines_path}")
            with open(wines_path, encoding="utf-8") as fh:
                wines_text = fh.read()
        else:
            console.print("[cyan]xwines[/] downloading slim wines CSV from GitHub…")
            with httpx.Client(timeout=60, follow_redirects=True) as client:
                try:
                    resp = self._fetch(lambda: client.get(_WINES_URL_SLIM))
                    resp.raise_for_status()
                    wines_text = resp.text
                except Exception as exc:
                    result.error = f"Wines download failed: {exc}"
                    return result

        # ── Parse wines → wine_id_map ────────────────────────────────────────
        wine_id_map: dict[str, dict] = {}   # WineID → parsed card
        reader = csv.DictReader(io.StringIO(wines_text))
        for row in reader:
            wine_id = row.get("WineID", "").strip()
            if not wine_id:
                continue
            wine_id_map[wine_id] = {
                "name": row.get("WineName", "").strip(),
                "winery": row.get("WineryName", "").strip(),
                "type": row.get("Type", "").strip(),
                "country": row.get("Code", row.get("Country", "FR")).strip().upper(),
            }

        console.print(f"[cyan]xwines[/] {len(wine_id_map)} wines loaded")

        # ── Load ratings ─────────────────────────────────────────────────────
        ratings_path = os.environ.get(_ENV_RATINGS_PATH)
        if ratings_path:
            console.print(f"[cyan]xwines[/] loading ratings from local file: {ratings_path}")
            with open(ratings_path, encoding="utf-8") as fh:
                ratings_text = fh.read()
        else:
            console.print("[cyan]xwines[/] downloading test ratings CSV from GitHub…")
            with httpx.Client(timeout=120, follow_redirects=True) as client:
                try:
                    resp = self._fetch(lambda: client.get(_RATINGS_URL_SLIM))
                    resp.raise_for_status()
                    ratings_text = resp.text
                except Exception as exc:
                    result.error = f"Ratings download failed: {exc}"
                    return result

        # ── Aggregate ratings: (WineID, Vintage) → [scores] ─────────────────
        aggregated: dict[tuple[str, Optional[int]], list[float]] = defaultdict(list)
        rdr = csv.DictReader(io.StringIO(ratings_text))
        for row in rdr:
            wine_id = row.get("WineID", "").strip()
            vintage_raw = row.get("Vintage", "").strip()
            try:
                vintage: Optional[int] = int(vintage_raw) if vintage_raw and vintage_raw != "N.V." else None
            except ValueError:
                vintage = None
            try:
                score = float(row.get("Rating", 0))
            except ValueError:
                continue
            if score < 0 or score > 5:
                continue
            aggregated[(wine_id, vintage)].append(score)

        console.print(
            f"[cyan]xwines[/] {sum(len(v) for v in aggregated.values())} ratings → "
            f"{len(aggregated)} (wine, vintage) pairs"
        )
        result.rows_fetched = sum(len(v) for v in aggregated.values())

        # ── Insert into fact_rating ──────────────────────────────────────────
        for (wine_id, vintage), scores in aggregated.items():
            if limit is not None and result.rows_inserted >= limit:
                result.rows_skipped_unchanged += 1
                continue

            card = wine_id_map.get(wine_id)
            if not card:
                continue

            raw_name     = card["name"]
            winery_name  = card["winery"]
            country_code = card["country"] or "FR"
            color        = _xwines_type_to_color(card["type"])

            producer_norm = normalize_producer(winery_name)
            cuvee_norm    = normalize_cuvee(raw_name)
            if not producer_norm or not cuvee_norm:
                continue

            wine_key = compute_wine_key(producer_norm, cuvee_norm, vintage, "")
            _ensure_producer(self.conn, producer_norm, winery_name, country_code)

            if not _ensure_wine(
                self.conn, wine_key, producer_norm,
                raw_name, cuvee_norm, country_code, color, vintage,
            ):
                write_dlq(self.conn, source_key, batch_id, "unresolved_dim",
                          f"Cannot resolve wine: {winery_name!r} / {raw_name!r}",
                          {"wine_id": wine_id, "wine_key": wine_key})
                result.rows_dlq += 1
                continue

            avg_score = sum(scores) / len(scores)
            score_norm = round((avg_score / 5.0) * 100, 2)
            import hashlib, json
            content_hash = hashlib.sha256(
                json.dumps({"wine_id": wine_id, "vintage": vintage}).encode()
            ).hexdigest()

            try:
                self.conn.execute(
                    """INSERT OR IGNORE INTO fact_rating
                       (wine_key, source_key, critic_code, reviewer_type,
                        score, scale, score_normalized_100, rating_count,
                        recorded_at, content_hash, batch_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        wine_key, source_key, _CRITIC_CODE, _REVIEWER_TYPE,
                        round(avg_score, 3), _SCALE, score_norm, len(scores),
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
                          str(exc), {"wine_key": wine_key, "wine_id": wine_id})
                result.rows_dlq += 1

        self.conn.commit()
        console.print(
            f"[green]xwines[/] done — {result.rows_inserted} inserted, "
            f"{result.rows_dlq} DLQ, {result.rows_skipped_unchanged} skipped"
        )
        return result
