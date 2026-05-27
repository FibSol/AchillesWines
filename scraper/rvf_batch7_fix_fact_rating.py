"""
rvf_batch7_fix_fact_rating.py — Back-fills the missing fact_rating rows for the 210
wines that rvf_dlq_resolve_batch7.py resolved.

Background
----------
batch7 successfully created dim_producer + dim_wine entries and marked the DLQ
rows as auto_resolved, but the fact_rating INSERT never committed.  Root cause:
the INSERT was inside the same transaction as the dim_wine creation — if batch7
was interrupted after commit() but before the fact_rating inserts were persisted,
or if there was a silent IGNORE triggered by some transient state, the ratings
were lost while the structural data survived.

This script:
  1. Reads every DLQ row resolved by batch7 (resolved_by='rvf_dlq_resolve_batch7.py')
  2. Re-computes the wine_key using the same logic (cuvee_norm falls back to
     producer_norm when empty — mirrors batch7's get_or_create_wine logic)
  3. Finds the dim_wine entry (must already exist)
  4. Inserts the fact_rating row if it is still missing

Usage:
    .venv/Scripts/python.exe rvf_batch7_fix_fact_rating.py [--dry-run]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

import sys
sys.path.insert(0, str(Path(__file__).parent))
from achilles_scraper.identity import (
    normalize_producer,
    normalize_cuvee,
    compute_wine_key,
    clean_producer_display,
    clean_cuvee_display,
)

load_dotenv(Path(__file__).parent.parent / ".env", override=True)
DB_PATH = Path(__file__).parent.parent / os.getenv("DATABASE_URL", "data/achilles.db")

SOURCE_CODE = "rvf_magazine"
CRITIC_CODE = "RVF"
SCALE = "/20"
BATCH_ID = f"rvfmag-batch7b-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"


def score_to_100(score_raw: float) -> float:
    if score_raw > 20:
        return round(score_raw, 1)
    return round((score_raw / 20.0) * 100.0, 1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    source_key = conn.execute(
        "SELECT source_key FROM dim_source WHERE source_code = ?", (SOURCE_CODE,)
    ).fetchone()[0]

    # Load all DLQ rows that batch7 resolved
    rows = conn.execute(
        "SELECT dlq_id, raw_record FROM ops_dead_letter "
        "WHERE source_key = 52 AND resolved_by = 'rvf_dlq_resolve_batch7.py' "
        "AND resolution = 'auto_resolved'"
    ).fetchall()
    print(f"batch7 auto_resolved DLQ rows: {len(rows)}")

    inserted = 0
    skipped_no_wine = 0
    skipped_already_exists = 0
    errors = 0

    for row in rows:
        try:
            rec = json.loads(row["raw_record"]) if row["raw_record"] else {}
        except Exception:
            errors += 1
            continue

        raw_producer = (rec.get("producer") or "").strip()
        raw_cuvee = (rec.get("cuvee") or "").strip()
        vintage = rec.get("vintage")
        score = rec.get("score")

        if not score or not raw_producer:
            errors += 1
            continue

        # Replicate batch7's wine_key computation exactly
        p_disp = clean_producer_display(raw_producer)
        p_norm = normalize_producer(p_disp)
        c_disp = clean_cuvee_display(raw_cuvee or raw_producer, p_disp)
        if not c_disp:
            c_disp = p_disp
        c_norm = normalize_cuvee(c_disp, strip_words=[p_norm])
        if not c_norm:
            c_norm = p_norm  # same fallback as batch7

        wine_key = compute_wine_key(p_norm, c_norm, int(vintage) if vintage else None)

        # Confirm dim_wine exists (batch7 should have created it)
        dw = conn.execute(
            "SELECT wine_key FROM dim_wine WHERE wine_key = ?", (wine_key,)
        ).fetchone()
        if not dw:
            print(f"  SKIP dlq={row['dlq_id']}: dim_wine missing for {wine_key}")
            skipped_no_wine += 1
            continue

        # Check if fact_rating already exists (content_hash is not unique-indexed,
        # but check by wine_key+source_key to avoid exact duplicates)
        existing_fr = conn.execute(
            "SELECT 1 FROM fact_rating WHERE wine_key = ? AND source_key = ?",
            (wine_key, source_key),
        ).fetchone()
        if existing_fr:
            skipped_already_exists += 1
            continue

        score_raw = float(score)
        score_20 = score_raw if score_raw <= 20 else round(score_raw / 5.0, 2)
        norm_score = score_to_100(score_raw)
        content_hash = hashlib.sha256(
            json.dumps(
                {"wine_key": wine_key, "critic": CRITIC_CODE,
                 "score": score_20, "source": SOURCE_CODE},
                sort_keys=True,
            ).encode()
        ).hexdigest()

        if args.dry_run:
            print(f"  DRY INSERT dlq={row['dlq_id']} wine_key={wine_key} v={vintage} score={score_20}/20")
            inserted += 1
            continue

        conn.execute(
            """INSERT OR IGNORE INTO fact_rating
               (wine_key, source_key, critic_code, reviewer_type,
                score, scale, score_normalized_100,
                source_url, content_hash, batch_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (wine_key, source_key, CRITIC_CODE, "critic",
             score_20, SCALE, norm_score,
             "https://www.larvf.com", content_hash, BATCH_ID),
        )
        inserted += 1

    if not args.dry_run:
        conn.commit()
    conn.close()

    print()
    print("=" * 55)
    print(f"Inserted         : {inserted}")
    print(f"Skipped (no wine): {skipped_no_wine}")
    print(f"Already existed  : {skipped_already_exists}")
    print(f"Errors           : {errors}")
    if args.dry_run:
        print("(dry run — nothing written)")
    else:
        print(f"Batch ID: {BATCH_ID}")


if __name__ == "__main__":
    main()
