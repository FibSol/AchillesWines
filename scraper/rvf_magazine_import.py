"""
Step 3 — RVF magazine importer: read ratings.json extracted by step 2,
fuzzy-match against dim_wine, write to fact_rating (staging via DLQ for
unmatched rows).

Usage:
    python rvf_magazine_import.py [--dry-run]
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
from rapidfuzz import fuzz

load_dotenv(Path(__file__).parent.parent / ".env", override=True)

DB_PATH   = Path(__file__).parent.parent / os.getenv("DATABASE_URL", "data/achilles.db")
RATINGS   = Path(__file__).parent / "raw" / "rvf_pages" / "ratings.json"
SOURCE_CODE = "rvf_magazine"
CRITIC_CODE = "RVF"
SCALE       = "/20"
MATCH_THRESHOLD = 72  # fuzz.token_sort_ratio minimum


def norm(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return s.lower().strip()


def normalise_score(score: float) -> tuple[float, str]:
    """Return (score_on_20, scale_string).
    RVF uses /20 historically but some recent sections use 100-pt.
    Heuristic: if score > 20 treat as 100-pt and convert."""
    if score > 20:
        # 100-point scale — convert to /20 for consistent storage
        return round(score / 5.0, 2), "/100"
    return score, "/20"


def score_to_100(score_on_20: float) -> float:
    return round((score_on_20 / 20.0) * 100.0, 1)


def ensure_source(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT source_key FROM dim_source WHERE source_code=?", (SOURCE_CODE,)).fetchone()
    if row:
        return row[0]
    conn.execute(
        """INSERT INTO dim_source
           (source_code, source_name, source_tier, cadence, base_url, license_class, enabled, requires_auth, notes)
           VALUES (?,?,?,?,?,?,1,0,?)""",
        (SOURCE_CODE, "La Revue du Vin de France (magazine PDF)",
         "A_premium_press", "monthly",
         "https://www.larvf.com",
         "subscriber_only",
         "Ratings extracted via Claude Vision from subscriber PDF issues"),
    )
    conn.commit()
    return conn.execute("SELECT source_key FROM dim_source WHERE source_code=?", (SOURCE_CODE,)).fetchone()[0]


def load_wines(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """SELECT w.wine_key, w.cuvee_norm, w.vintage,
                  p.producer_norm, p.producer_name,
                  a.appellation_norm
           FROM dim_wine w
           JOIN dim_producer p ON p.producer_key = w.producer_key
           LEFT JOIN dim_appellation a ON a.appellation_key = w.appellation_key"""
    ).fetchall()
    return [
        {"wine_key": r[0], "cuvee_norm": r[1], "vintage": r[2],
         "producer_norm": r[3], "producer_name": r[4], "appellation_norm": r[5]}
        for r in rows
    ]


def find_match(wine_db: list[dict], producer: str, cuvee: str, vintage) -> dict | None:
    p_norm = norm(producer)
    c_norm = norm(cuvee)
    best_score = 0
    best = None
    for w in wine_db:
        if vintage and w["vintage"] and w["vintage"] != vintage:
            continue
        ps = fuzz.token_sort_ratio(p_norm, w["producer_norm"])
        cs = fuzz.token_sort_ratio(c_norm, w["cuvee_norm"])
        combined = ps * 0.5 + cs * 0.5
        if combined > best_score:
            best_score = combined
            best = w
    if best_score >= MATCH_THRESHOLD:
        return best
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not RATINGS.exists():
        print(f"ERROR: {RATINGS} not found. Run rvf_magazine_extract.py first.")
        return

    data = json.loads(RATINGS.read_text(encoding="utf-8"))
    ratings = data["ratings"]
    print(f"Loaded {len(ratings)} extracted wine rows")

    conn = sqlite3.connect(DB_PATH)
    source_key = ensure_source(conn)
    wine_db = load_wines(conn)
    print(f"DB has {len(wine_db)} dim_wine rows for matching")

    batch_id = f"rvfmag-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    inserted = matched = dlq = 0

    for r in ratings:
        producer = (r.get("producer") or "").strip()
        cuvee    = (r.get("cuvee") or "").strip()
        vintage  = r.get("vintage")
        score    = r.get("score")

        if not producer or not cuvee or score is None:
            continue

        match = find_match(wine_db, producer, cuvee, vintage)
        if not match:
            if not args.dry_run:
                conn.execute(
                    "INSERT INTO ops_dead_letter (source_key, batch_id, error_class, error_message, raw_record) VALUES (?,?,?,?,?)",
                    (source_key, batch_id, "unmatched_wine",
                     f"no dim_wine match for {producer!r} / {cuvee!r} v{vintage}",
                     json.dumps(r)),
                )
            dlq += 1
            continue

        matched += 1
        score_20, scale = normalise_score(score)
        norm_score = score_to_100(score_20)
        content_hash = hashlib.sha256(
            json.dumps({"wine_key": match["wine_key"], "critic": CRITIC_CODE,
                        "score": score_20, "source": SOURCE_CODE}, sort_keys=True).encode()
        ).hexdigest()

        if args.dry_run:
            print(f"  DRY {match['wine_key']} — {score_20}/20 ({scale}) → {norm_score}/100")
            inserted += 1
            continue

        conn.execute(
            """INSERT OR IGNORE INTO fact_rating
               (wine_key, source_key, critic_code, reviewer_type,
                score, scale, score_normalized_100,
                source_url, content_hash, batch_id)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (match["wine_key"], source_key, CRITIC_CODE, "critic",
             score_20, scale, norm_score,
             f"https://www.larvf.com", content_hash, batch_id),
        )
        if conn.total_changes:
            inserted += 1

    if not args.dry_run:
        conn.commit()

    conn.close()
    print(f"\nMatched: {matched} | Inserted: {inserted} | DLQ (unmatched): {dlq}")
    if args.dry_run:
        print("(dry run — nothing written)")


if __name__ == "__main__":
    main()
