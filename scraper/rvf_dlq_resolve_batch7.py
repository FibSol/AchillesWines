"""
rvf_dlq_resolve_batch7.py — Final sweep of all remaining unresolved RVF DLQ records.

Strategy: for every entry that has a score AND a vintage >= 2000 AND an appellation
that can be mapped to dim_appellation, we create the missing dim_producer + dim_wine
entries and write a fact_rating row.

Entries without score, without vintage, or whose appellation cannot be resolved are
marked 'unresolvable' so they no longer pollute the unresolved queue.

Uses the canonical compute_wine_key (sha1 + bottle_ml=750) from identity.py so
wines are properly reachable by live scrapers.

Usage:
    .venv/Scripts/python.exe rvf_dlq_resolve_batch7.py [--dry-run]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import unicodedata
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
    clean_producer_display,
    clean_cuvee_display,
)

load_dotenv(Path(__file__).parent.parent / ".env", override=True)
DB_PATH = Path(__file__).parent.parent / os.getenv("DATABASE_URL", "data/achilles.db")

SOURCE_CODE = "rvf_magazine"
CRITIC_CODE = "RVF"
SCALE = "/20"
BATCH_ID = f"rvfmag-batch7-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return s.lower().strip()


def score_to_100(score_raw: float) -> float:
    if score_raw > 20:
        return round(score_raw, 1)
    return round((score_raw / 20.0) * 100.0, 1)


# Explicit overrides for ambiguous appellation names (RVF label → appellation_key)
_APP_OVERRIDES: dict[str, int] = {
    "vallee de la loire": 1126,   # Loire (generic)
    "vallee du rhone":    1123,   # Rhône (generic)
    "cotes-de-provence":  238,    # Côtes de Provence
    "macon et macon-villages": 366,  # Mâcon-Villages
    "roussillon":         277,    # Côtes du Roussillon
    "cote-d or":          382,    # Bourgogne Côte d'Or (OCR variant)
    "alsace":             376,    # Alsace
}

# Build appellation lookup: norm(appellation_name) → appellation_key
def build_app_lookup(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        "SELECT appellation_key, appellation_name FROM dim_appellation"
    ).fetchall()
    lookup: dict[str, int] = {}
    for key, name in rows:
        lookup[norm(name)] = key
    lookup.update(_APP_OVERRIDES)
    return lookup


def resolve_appellation(raw_app: str, app_lookup: dict[str, int]) -> Optional[int]:
    n = norm(raw_app)
    if n in app_lookup:
        return app_lookup[n]
    # Try partial: look for an appellation name that contains the raw norm
    for k, v in app_lookup.items():
        if n and (n in k or k in n):
            return v
    return None


def get_or_create_producer(
    conn: sqlite3.Connection,
    raw_producer: str,
    appellation_key: int,
    dry_run: bool,
) -> Optional[int]:
    display = clean_producer_display(raw_producer)
    p_norm = normalize_producer(display)
    if not p_norm:
        return None

    # Try exact norm match first
    row = conn.execute(
        "SELECT producer_key FROM dim_producer WHERE producer_norm = ?", (p_norm,)
    ).fetchone()
    if row:
        return row[0]

    # Look up region from appellation
    app_row = conn.execute(
        "SELECT region, country_code FROM dim_appellation WHERE appellation_key = ?",
        (appellation_key,),
    ).fetchone()
    region = app_row[0] if app_row else None
    country_code = app_row[1] if app_row else "FR"

    if dry_run:
        print(f"      DRY create producer: {display!r} (norm={p_norm!r}) region={region}")
        # Return a placeholder so wine creation can proceed in dry-run
        return -1

    conn.execute(
        """INSERT INTO dim_producer
           (producer_name, producer_norm, country_code, region, coverage_tier)
           VALUES (?, ?, ?, ?, 'long_tail')""",
        (display, p_norm, country_code, region),
    )
    pk = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    print(f"      CREATED producer: pk={pk} {display!r}")
    return pk


def get_or_create_wine(
    conn: sqlite3.Connection,
    producer_key: int,
    producer_norm: str,
    appellation_key: int,
    raw_cuvee: str,
    raw_producer: str,
    vintage: Optional[int],
    color: Optional[str],
    dry_run: bool,
) -> Optional[str]:
    cuvee_display = clean_cuvee_display(raw_cuvee, clean_producer_display(raw_producer))
    if not cuvee_display:
        cuvee_display = clean_producer_display(raw_producer)

    cuvee_n = normalize_cuvee(cuvee_display, strip_words=[producer_norm])
    if not cuvee_n:
        cuvee_n = producer_norm

    wine_key = compute_wine_key(producer_norm, cuvee_n, vintage)

    if dry_run and producer_key == -1:
        print(f"      DRY wine_key={wine_key} cuvee={cuvee_display!r} v={vintage}")
        return wine_key

    existing = conn.execute(
        "SELECT wine_key FROM dim_wine WHERE wine_key = ?", (wine_key,)
    ).fetchone()
    if existing:
        return wine_key

    canonical = cuvee_display
    if vintage:
        canonical = f"{cuvee_display} {vintage}"

    if dry_run:
        print(f"      DRY create wine: {wine_key} cuvee={cuvee_display!r} v={vintage} [{color}]")
        return wine_key

    conn.execute(
        """INSERT OR IGNORE INTO dim_wine
           (wine_key, producer_key, appellation_key,
            cuvee_name, cuvee_norm, color, vintage, is_non_vintage,
            bottle_ml, canonical_name)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 750, ?)""",
        (
            wine_key, producer_key, appellation_key,
            cuvee_display, cuvee_n,
            color or "red",
            vintage if vintage else None,
            1 if not vintage else 0,
            canonical,
        ),
    )
    print(f"      CREATED wine: {wine_key} {cuvee_display!r} v={vintage}")
    return wine_key


def write_fact_rating(
    conn: sqlite3.Connection,
    wine_key: str,
    source_key: int,
    score_raw: float,
    dry_run: bool,
) -> None:
    score_20 = score_raw if score_raw <= 20 else round(score_raw / 5.0, 2)
    norm_score = score_to_100(score_raw)
    content_hash = hashlib.sha256(
        json.dumps(
            {"wine_key": wine_key, "critic": CRITIC_CODE,
             "score": score_20, "source": SOURCE_CODE},
            sort_keys=True,
        ).encode()
    ).hexdigest()

    if dry_run:
        print(f"      DRY fact_rating score={score_20}/20 ({norm_score}/100)")
        return

    conn.execute(
        """INSERT OR IGNORE INTO fact_rating
           (wine_key, source_key, critic_code, reviewer_type,
            score, scale, score_normalized_100,
            source_url, content_hash, batch_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            wine_key, source_key, CRITIC_CODE, "critic",
            score_20, SCALE, norm_score,
            "https://www.larvf.com", content_hash, BATCH_ID,
        ),
    )


def mark_resolved(conn, dlq_id: int, resolver: str, dry_run: bool) -> None:
    if dry_run:
        return
    conn.execute(
        "UPDATE ops_dead_letter SET resolution='auto_resolved', resolved_at=?, resolved_by=? WHERE dlq_id=?",
        (int(datetime.now().timestamp()), resolver, dlq_id),
    )


def mark_unresolvable(conn, dlq_id: int, reason: str, dry_run: bool) -> None:
    if dry_run:
        return
    conn.execute(
        "UPDATE ops_dead_letter SET resolution='unresolvable', resolved_at=?, resolved_by=?, error_message=? WHERE dlq_id=?",
        (int(datetime.now().timestamp()), "rvf_dlq_resolve_batch7.py", reason, dlq_id),
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

    app_lookup = build_app_lookup(conn)

    rows = conn.execute(
        "SELECT dlq_id, raw_record FROM ops_dead_letter "
        "WHERE source_key = 52 AND error_class = 'unmatched_wine' "
        "AND (resolved_at IS NULL)"
    ).fetchall()
    print(f"Unresolved rvf_magazine DLQ rows: {len(rows)}")
    print()

    resolved = 0
    unresolvable = 0
    skipped = 0

    for row in rows:
        dlq_id = row["dlq_id"]
        try:
            rec = json.loads(row["raw_record"]) if row["raw_record"] else {}
        except Exception:
            mark_unresolvable(conn, dlq_id, "json_parse_error", args.dry_run)
            unresolvable += 1
            continue

        raw_producer = (rec.get("producer") or "").strip()
        raw_cuvee = (rec.get("cuvee") or "").strip()
        vintage = rec.get("vintage")
        score = rec.get("score")
        raw_app = (rec.get("appellation") or "").strip()
        color = rec.get("color")

        # Skip/mark-unresolvable cases
        if not score:
            mark_unresolvable(conn, dlq_id, "no_score_in_raw_record", args.dry_run)
            unresolvable += 1
            continue

        if not vintage or (isinstance(vintage, (int, float)) and int(vintage) < 2000):
            mark_unresolvable(
                conn, dlq_id,
                f"vintage={vintage} pre-2000 or missing",
                args.dry_run,
            )
            unresolvable += 1
            continue

        if not raw_producer:
            mark_unresolvable(conn, dlq_id, "no_producer_in_raw_record", args.dry_run)
            unresolvable += 1
            continue

        appellation_key = resolve_appellation(raw_app, app_lookup)
        if appellation_key is None:
            mark_unresolvable(
                conn, dlq_id,
                f"appellation not found: {raw_app!r}",
                args.dry_run,
            )
            unresolvable += 1
            if args.dry_run:
                print(f"  UNRESOLVABLE dlq={dlq_id}: appellation={raw_app!r} prod={raw_producer!r}")
            continue

        print(f"  dlq={dlq_id} [{vintage}] {raw_producer!r} / {raw_cuvee!r} app={raw_app!r} score={score}")

        producer_key = get_or_create_producer(conn, raw_producer, appellation_key, args.dry_run)
        if producer_key is None:
            mark_unresolvable(conn, dlq_id, "producer_norm_empty", args.dry_run)
            unresolvable += 1
            continue

        # Get producer_norm for wine_key computation
        if producer_key == -1:
            producer_norm_val = normalize_producer(clean_producer_display(raw_producer))
        else:
            prod_row = conn.execute(
                "SELECT producer_norm FROM dim_producer WHERE producer_key = ?", (producer_key,)
            ).fetchone()
            producer_norm_val = prod_row[0] if prod_row else normalize_producer(raw_producer)

        wine_key = get_or_create_wine(
            conn, producer_key, producer_norm_val,
            appellation_key, raw_cuvee, raw_producer,
            int(vintage), color, args.dry_run,
        )
        if wine_key is None:
            mark_unresolvable(conn, dlq_id, "wine_key_computation_failed", args.dry_run)
            unresolvable += 1
            continue

        write_fact_rating(conn, wine_key, source_key, float(score), args.dry_run)
        mark_resolved(conn, dlq_id, "rvf_dlq_resolve_batch7.py", args.dry_run)
        resolved += 1

    if not args.dry_run:
        conn.commit()
    conn.close()

    print()
    print("=" * 55)
    print(f"Resolved        : {resolved}")
    print(f"Marked unresolvable: {unresolvable}")
    print(f"Skipped         : {skipped}")
    if args.dry_run:
        print("(dry run — nothing written)")
    else:
        print(f"Batch ID: {BATCH_ID}")


if __name__ == "__main__":
    main()
