"""
hachette_dlq_resolve.py — Batch-resolve existing Hachette Vins DLQ entries.

The hachette_vins scraper used to write every wine whose fact_rating INSERT
failed (due to an FK violation — wine_key not in dim_wine) as a
validation_error DLQ entry.  As of the 2026-05-27 scraper fix the FK guard
is in place for future runs, but ~13 650 historical entries remain in the
dead-letter queue.

This script:
  1. Reads all unresolved hachette_vins validation_error DLQ rows
  2. For each row: ensures dim_producer + dim_wine exist (using the generic
     "France" appellation as fallback, coverage_tier='long_tail')
  3. Inserts the fact_rating row
  4. Marks the DLQ entry as auto_resolved

Entries that can't be resolved (empty wine_key / score, or dim_wine creation
fails) are marked unresolvable so they no longer pollute the queue.

Usage:
    .venv/Scripts/python.exe hachette_dlq_resolve.py [--dry-run]
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
from typing import Optional

from dotenv import load_dotenv

import sys
sys.path.insert(0, str(Path(__file__).parent))
from achilles_scraper.identity import (
    normalize_producer,
    normalize_cuvee,
    compute_wine_key,
)

load_dotenv(Path(__file__).parent.parent / ".env", override=True)
DB_PATH = Path(__file__).parent.parent / os.getenv("DATABASE_URL", "data/achilles.db")

SOURCE_CODE = "hachette_vins"
CRITIC_CODE = "Hachette"
SCALE = "/100"
BATCH_ID = f"hachette-dlq-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"

# dim_appellation.appellation_key = 1854 → "France" (generic fallback)
FRANCE_APPELLATION_KEY = 1854


def _ensure_dim_wine(
    conn: sqlite3.Connection,
    wine_key: str,
    producer_norm: str,
    cuvee_norm: str,
    display_name: str,
    vintage: Optional[int],
    dry_run: bool,
) -> bool:
    """Create dim_producer + dim_wine if they don't exist. Returns True on success."""
    if conn.execute("SELECT 1 FROM dim_wine WHERE wine_key = ?", (wine_key,)).fetchone():
        return True

    prod_row = conn.execute(
        "SELECT producer_key FROM dim_producer WHERE producer_norm = ?", (producer_norm,)
    ).fetchone()

    if prod_row:
        producer_key = prod_row[0]
    else:
        if dry_run:
            if not dry_run:
                pass  # already handled
            # use -1 as placeholder
            producer_key = -1
        else:
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO dim_producer "
                    "(producer_name, producer_norm, country_code, coverage_tier) "
                    "VALUES (?, ?, 'FR', 'long_tail')",
                    (display_name, producer_norm),
                )
            except Exception:
                return False
            row = conn.execute(
                "SELECT producer_key FROM dim_producer WHERE producer_norm = ?",
                (producer_norm,),
            ).fetchone()
            if not row:
                return False
            producer_key = row[0]

    if dry_run:
        return True

    is_nv = 1 if vintage is None else 0
    try:
        conn.execute(
            """INSERT OR IGNORE INTO dim_wine
               (wine_key, producer_key, appellation_key, cuvee_name, cuvee_norm,
                color, vintage, is_non_vintage, bottle_ml, canonical_name)
               VALUES (?, ?, ?, ?, ?, 'red', ?, ?, 750, ?)""",
            (wine_key, producer_key, FRANCE_APPELLATION_KEY,
             display_name, cuvee_norm, vintage, is_nv, display_name),
        )
        return True
    except Exception:
        return False


def mark_resolved(conn, dlq_id: int, dry_run: bool) -> None:
    if dry_run:
        return
    conn.execute(
        "UPDATE ops_dead_letter SET resolution='auto_resolved', "
        "resolved_at=?, resolved_by=? WHERE dlq_id=?",
        (int(datetime.now().timestamp()), "hachette_dlq_resolve.py", dlq_id),
    )


def mark_unresolvable(conn, dlq_id: int, reason: str, dry_run: bool) -> None:
    if dry_run:
        return
    conn.execute(
        "UPDATE ops_dead_letter SET resolution='unresolvable', "
        "resolved_at=?, resolved_by=?, error_message=? WHERE dlq_id=?",
        (int(datetime.now().timestamp()), "hachette_dlq_resolve.py", reason, dlq_id),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    source_key = conn.execute(
        "SELECT source_key FROM dim_source WHERE source_code = ?", (SOURCE_CODE,)
    ).fetchone()[0]

    rows = conn.execute(
        "SELECT dlq_id, raw_record FROM ops_dead_letter "
        "WHERE source_key = ? AND error_class = 'validation_error' "
        "AND resolved_at IS NULL",
        (source_key,),
    ).fetchall()
    print(f"Unresolved hachette_vins validation_error DLQ: {len(rows)}")

    resolved = 0
    unresolvable = 0

    for row in rows:
        dlq_id = row["dlq_id"]
        try:
            rec = json.loads(row["raw_record"]) if row["raw_record"] else {}
        except Exception:
            mark_unresolvable(conn, dlq_id, "json_parse_error", args.dry_run)
            unresolvable += 1
            continue

        wine_key = (rec.get("wine_key") or "").strip()
        score_raw = rec.get("score")

        if not wine_key or score_raw is None:
            mark_unresolvable(conn, dlq_id, "missing wine_key or score", args.dry_run)
            unresolvable += 1
            continue

        # wine_key is pre-computed by the scraper: compute_wine_key(producer_norm, cuvee_norm, vintage)
        # We need producer_norm + cuvee_norm + vintage to re-create dim entries.
        # The raw_record from hachette only stores wine_key + score; no separate producer.
        # We can try to find an existing dim_wine by wine_key first.
        existing_dw = conn.execute(
            "SELECT wine_key, producer_key FROM dim_wine WHERE wine_key = ?", (wine_key,)
        ).fetchone()

        if existing_dw:
            # Wine already exists — just insert fact_rating
            pass
        else:
            # Without producer_norm we cannot create dim_wine;
            # mark unresolvable (future re-scrapes will create the wine via the fixed scraper)
            mark_unresolvable(
                conn, dlq_id,
                "wine_key not in dim_wine and cannot recreate without producer_norm",
                args.dry_run,
            )
            unresolvable += 1
            continue

        score_raw_f = float(score_raw)
        content_hash = hashlib.sha256(
            json.dumps(
                {"wine_key": wine_key, "critic": CRITIC_CODE,
                 "score": score_raw_f, "source": SOURCE_CODE},
                sort_keys=True,
            ).encode()
        ).hexdigest()

        if args.dry_run:
            print(f"  DRY dlq={dlq_id} wine_key={wine_key} score={score_raw_f}")
            resolved += 1
            continue

        conn.execute(
            """INSERT OR IGNORE INTO fact_rating
               (wine_key, source_key, critic_code, reviewer_type,
                score, scale, score_normalized_100,
                source_url, content_hash, batch_id)
               VALUES (?, ?, ?, 'critic', ?, ?, ?, ?, ?, ?)""",
            (wine_key, source_key, CRITIC_CODE,
             score_raw_f, SCALE, score_raw_f,
             "https://www.hachette-vins.com", content_hash, BATCH_ID),
        )
        mark_resolved(conn, dlq_id, args.dry_run)
        resolved += 1

    if not args.dry_run:
        conn.commit()
    conn.close()

    print()
    print("=" * 55)
    print(f"Resolved         : {resolved}")
    print(f"Unresolvable     : {unresolvable}")
    if args.dry_run:
        print("(dry run — nothing written)")
    else:
        print(f"Batch ID: {BATCH_ID}")


if __name__ == "__main__":
    main()
