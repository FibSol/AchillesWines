"""
rvf_dlq_resolve_cuvee_eq_producer.py — Resolve DLQ records where cuvee_name
== producer_name (standard for Bordeaux chateaux, single-domain estates).

Strategy:
  1. Fuzzy-match producer to dim_producer (thresh=85)
  2. Fuzzy-match appellation to dim_appellation (thresh=78)
  3. Create dim_wine with cuvee = cleaned producer name (sans entity prefix)
  4. Write fact_rating, mark DLQ resolved

Usage:
    python rvf_dlq_resolve_cuvee_eq_producer.py [--dry-run]
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
from rapidfuzz import fuzz

sys.path.insert(0, str(Path(__file__).parent))
from achilles_scraper.identity import (
    normalize_producer,
    clean_producer_display,
    clean_cuvee_display,
)

load_dotenv(Path(__file__).parent.parent / ".env", override=True)
DB_PATH = Path(__file__).parent.parent / os.getenv("DATABASE_URL", "data/achilles.db")

SOURCE_CODE = "rvf_magazine"
CRITIC_CODE = "RVF"
SCALE = "/20"
BATCH_ID = f"rvfmag-ceqp-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"

PRODUCER_MATCH_THRESH = 95
APPELLATION_MATCH_THRESH = 78

# VdF fallback appellation key
VDF_APP_KEY = None  # filled at runtime


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return s.lower().strip()


def score_to_100(score_raw: float) -> float:
    if score_raw > 20:
        return round(score_raw, 1)
    return round((score_raw / 20.0) * 100.0, 1)


def main():
    global VDF_APP_KEY
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    source_key = conn.execute(
        "SELECT source_key FROM dim_source WHERE source_code=?", (SOURCE_CODE,)
    ).fetchone()[0]

    # VdF fallback
    vdf_row = conn.execute(
        "SELECT appellation_key FROM dim_appellation WHERE appellation_norm LIKE '%vin de france%' LIMIT 1"
    ).fetchone()
    VDF_APP_KEY = vdf_row[0] if vdf_row else None

    db_producers = [
        {"pk": r[0], "pnorm": r[1], "pname": r[2], "country": r[3]}
        for r in conn.execute(
            "SELECT producer_key, producer_norm, producer_name, country_code FROM dim_producer"
        ).fetchall()
    ]
    db_apps = [
        {"ak": r[0], "anorm": r[1], "aname": r[2]}
        for r in conn.execute(
            "SELECT appellation_key, appellation_norm, appellation_name FROM dim_appellation"
        ).fetchall()
    ]

    rows = conn.execute(
        "SELECT dlq_id, raw_record FROM ops_dead_letter "
        "WHERE source_key = 52 AND error_class = 'unmatched_wine' "
        "AND (resolution IS NULL OR resolution = 'pending')"
    ).fetchall()
    print(f"Unresolved: {len(rows)}")

    resolved = 0
    no_producer = 0
    no_cuvee = 0
    not_cuvee_eq_prod = 0

    for dlq_id, raw in rows:
        try:
            r = json.loads(raw)
        except Exception:
            continue

        producer_raw = (r.get("producer") or "").strip()
        cuvee_raw = (r.get("cuvee") or "").strip()
        vintage = r.get("vintage")
        appellation_raw = (r.get("appellation") or "").strip()
        score = r.get("score")
        if score is None:
            continue

        p_n = norm(producer_raw)
        c_n = norm(cuvee_raw)

        # Only handle cuvee_eq_producer records
        if p_n != c_n:
            not_cuvee_eq_prod += 1
            continue

        if not p_n:
            no_cuvee += 1
            continue

        # Fuzzy match producer
        best_prod = None
        best_ps = 0
        for p in db_producers:
            s = fuzz.token_sort_ratio(p_n, p["pnorm"])
            if s > best_ps:
                best_ps = s
                best_prod = p
        if best_ps < PRODUCER_MATCH_THRESH or not best_prod:
            no_producer += 1
            continue

        producer_key = best_prod["pk"]
        # Skip non-French producers (Italian etc.)
        if best_prod["country"] and best_prod["country"] != "FR":
            no_producer += 1
            continue

        # Fuzzy match appellation
        app_n = norm(appellation_raw)
        app_match = None
        best_as = 0
        for a in db_apps:
            s = fuzz.token_sort_ratio(app_n, a["anorm"])
            if s > best_as:
                best_as = s
                app_match = a
        if best_as >= APPELLATION_MATCH_THRESH and app_match:
            appellation_key = app_match["ak"]
        else:
            appellation_key = VDF_APP_KEY

        # Build cuvee_display = cleaned producer name (remove Chateau/Domaine prefix)
        producer_display = clean_producer_display(producer_raw)
        cuvee_display = producer_display  # cuvee IS the estate name
        cuvee_norm_val = norm(cuvee_display)
        if not cuvee_norm_val:
            no_cuvee += 1
            continue

        # Compute wine_key
        prod_row = conn.execute(
            "SELECT producer_norm FROM dim_producer WHERE producer_key=?", (producer_key,)
        ).fetchone()
        if not prod_row:
            no_producer += 1
            continue
        pnorm_stored = prod_row[0]
        vintage_str = str(vintage) if vintage else "NV"
        wine_key = hashlib.sha256(
            f"{pnorm_stored}|{cuvee_norm_val}|{vintage_str}".encode()
        ).hexdigest()[:16]

        # Guess color from appellation
        app_text = (appellation_raw + " " + (app_match["aname"] if app_match else "")).lower()
        if any(k in app_text for k in ("blanc", "pouilly", "sancerre", "muscadet", "riesling",
                                        "gewurz", "muscat", "alsace", "chablis", "meursault",
                                        "puligny", "chassagne", "vouvray", "fume", "viognier")):
            color = "white"
        elif any(k in app_text for k in ("champagne", "cremant", "prosecco", "brut")):
            color = "sparkling"
        elif any(k in app_text for k in ("sauternes", "barsac", "monbazillac", "moelleux", "liquoreux")):
            color = "sweet"
        else:
            color = "red"

        # Ensure dim_wine
        existing = conn.execute("SELECT wine_key FROM dim_wine WHERE wine_key=?", (wine_key,)).fetchone()
        if not existing:
            if args.dry_run:
                if resolved < 15:
                    print(f"  DRY new wine: {wine_key} | {best_prod['pname']!r} / {cuvee_display!r} v{vintage} [{color}]")
            else:
                conn.execute(
                    """INSERT OR IGNORE INTO dim_wine
                       (wine_key, producer_key, appellation_key,
                        cuvee_name, cuvee_norm, color, vintage, is_non_vintage,
                        bottle_ml, canonical_name)
                       VALUES (?,?,?,?,?,?,?,?,750,?)""",
                    (wine_key, producer_key, appellation_key,
                     cuvee_display, cuvee_norm_val, color,
                     vintage if vintage else None, 1 if not vintage else 0,
                     f"{cuvee_display}" + (f" {vintage}" if vintage else "")),
                )

        # Write fact_rating and resolve
        score_20 = score if score <= 20 else round(score / 5.0, 2)
        norm_score = score_to_100(score)
        content_hash = hashlib.sha256(
            json.dumps({"wine_key": wine_key, "critic": CRITIC_CODE,
                        "score": score_20, "source": SOURCE_CODE}, sort_keys=True).encode()
        ).hexdigest()

        if args.dry_run:
            resolved += 1
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
            (int(datetime.now().timestamp()), "rvf_dlq_resolve_cuvee_eq_producer.py", dlq_id),
        )
        resolved += 1

    if not args.dry_run:
        conn.commit()
    conn.close()

    print(f"\n{'='*55}")
    print(f"Resolved            : {resolved}")
    print(f"No producer match   : {no_producer}")
    print(f"No cuvee            : {no_cuvee}")
    print(f"Not cuvee==producer : {not_cuvee_eq_prod}")
    if args.dry_run:
        print("(dry run -- nothing written)")
    else:
        print(f"Batch ID: {BATCH_ID}")


if __name__ == "__main__":
    main()
