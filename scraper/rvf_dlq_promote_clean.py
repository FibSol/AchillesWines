"""
rvf_dlq_promote_clean.py — For unresolved RVF DLQ records whose wine_key
can be computed via compute_wine_key and already exists in dim_wine,
write fact_rating and mark the DLQ row resolved.

This clears the 'clean_but_unmatched' backlog that remained because the
importer ran BEFORE the resolver created the dim_wine entries.

Usage:
    python rvf_dlq_promote_clean.py [--dry-run]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import unicodedata
import uuid
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

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
BATCH_ID = f"rvfmag-promote-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"


def score_to_100(score_raw: float) -> float:
    if score_raw > 20:
        return round(score_raw, 1)
    return round((score_raw / 20.0) * 100.0, 1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)

    source_key = conn.execute(
        "SELECT source_key FROM dim_source WHERE source_code=?", (SOURCE_CODE,)
    ).fetchone()[0]

    rows = conn.execute(
        "SELECT dlq_id, raw_record FROM ops_dead_letter "
        "WHERE source_key = 52 AND error_class = 'unmatched_wine' "
        "AND (resolution IS NULL OR resolution = 'pending')"
    ).fetchall()
    print(f"Unresolved rvf_magazine DLQ rows: {len(rows)}")

    matched = 0
    not_found = 0
    skipped_bad = 0

    for dlq_id, raw in rows:
        try:
            r = json.loads(raw)
        except Exception:
            continue

        raw_producer = (r.get("producer") or "").strip()
        raw_cuvee = (r.get("cuvee") or "").strip()
        vintage = r.get("vintage")
        score = r.get("score")

        if not raw_producer or not raw_cuvee or score is None:
            skipped_bad += 1
            continue

        # Use the same pipeline as rvf_dlq_resolve.py
        producer_display = clean_producer_display(raw_producer)
        cuvee_display = clean_cuvee_display(raw_cuvee, producer_display)
        if not cuvee_display:
            cuvee_display = raw_cuvee

        producer_norm = normalize_producer(producer_display)
        cuvee_norm = normalize_cuvee(cuvee_display, strip_words=[producer_norm])

        if not producer_norm or not cuvee_norm:
            skipped_bad += 1
            continue

        wine_key = compute_wine_key(producer_norm, cuvee_norm, vintage)

        existing = conn.execute(
            "SELECT wine_key FROM dim_wine WHERE wine_key=?", (wine_key,)
        ).fetchone()
        if not existing:
            not_found += 1
            continue

        # Wine exists — write fact_rating and resolve DLQ
        score_20 = score if score <= 20 else round(score / 5.0, 2)
        norm_score = score_to_100(score)
        content_hash = hashlib.sha256(
            json.dumps({"wine_key": wine_key, "critic": CRITIC_CODE,
                        "score": score_20, "source": SOURCE_CODE}, sort_keys=True).encode()
        ).hexdigest()

        if args.dry_run:
            if matched < 20:
                print(f"  DRY dlq={dlq_id} wine={wine_key} prod={producer_display!r} cuvee={cuvee_display!r} v={vintage} score={score_20}/20")
            matched += 1
            continue

        conn.execute(
            """INSERT OR IGNORE INTO fact_rating
               (wine_key, source_key, critic_code, reviewer_type,
                score, scale, score_normalized_100,
                source_url, content_hash, batch_id)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (wine_key, source_key, CRITIC_CODE, "critic",
             score_20, SCALE, norm_score,
             "https://www.larvf.com", content_hash, BATCH_ID),
        )
        conn.execute(
            "UPDATE ops_dead_letter SET resolution='auto_resolved', resolved_at=?, resolved_by=? WHERE dlq_id=?",
            (int(datetime.now().timestamp()), "rvf_dlq_promote_clean.py", dlq_id),
        )
        matched += 1

    if not args.dry_run:
        conn.commit()
    conn.close()

    print(f"\n{'='*55}")
    print(f"Promoted + resolved : {matched}")
    print(f"No dim_wine found   : {not_found}")
    print(f"Skipped (bad data)  : {skipped_bad}")
    if args.dry_run:
        print("(dry run -- nothing written)")
    else:
        print(f"Batch ID : {BATCH_ID}")


if __name__ == "__main__":
    main()
