# -*- coding: utf-8 -*-
"""
sanity_check_rvf_n701.py -- Sanity checks for the RVF N701 import.

Checks:
  1. Score range: all staging_rating_candidates BETWEEN 0 AND 100
  2. Appellation fallback rate: if >40% → WARNING
  3. Duplicate wine_keys: no two staging rows with same (wine_key, source_key)
  4. Non-FR wines: all dim_wine rows for this batch have country_code='FR'
  5. Negative prices: no staging_price_candidates with price_eur <= 0
  6. Score outliers: flag any score_norm > 100 or < 50
  7. Producer match rate: found vs created counts
  8. Wine key collisions: new wine_key in dim_wine with different producer/cuvée

Exits with code 0 on PASS, code 1 on FAIL.
"""

import sys
import sqlite3
import logging
from pathlib import Path

# ── path bootstrap ────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "achilles.db"

BATCH_ID = "rvf_n701_import"
RVF_SOURCE_CODE = "rvf"

logging.basicConfig(level=logging.WARNING, format="%(levelname)s  %(message)s")
log = logging.getLogger("sanity_check_rvf_n701")

# ── helpers ───────────────────────────────────────────────────────────────────

def section(title: str):
    print()
    print(f"-- {title} {'-' * max(0, 54 - len(title))}")


def ok(msg: str):
    print(f"  [OK]   {msg}")


def warn(msg: str):
    print(f"  [WARN] {msg}")


def fail(msg: str):
    print(f"  [FAIL] {msg}")


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    """Run all checks. Returns 0 = PASS, 1 = FAIL."""
    failures = []
    warnings_list = []

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Look up RVF source_key
    cur.execute("SELECT source_key FROM dim_source WHERE source_code=? LIMIT 1", (RVF_SOURCE_CODE,))
    row = cur.fetchone()
    if not row:
        print("FATAL: RVF source not found in dim_source")
        return 1
    rvf_source_key = row["source_key"]

    # France fallback key
    cur.execute("SELECT appellation_key FROM dim_appellation WHERE appellation_norm='france' LIMIT 1")
    fallback_app_key = cur.fetchone()["appellation_key"]

    print("=" * 60)
    print("  RVF N°701 Sanity Check Report")
    print(f"  batch_id : {BATCH_ID}")
    print(f"  source_key (RVF) : {rvf_source_key}")
    print("=" * 60)

    # ── Check 1: Score range ──────────────────────────────────────────────────
    section("CHECK 1: Score range (0-100)")
    cur.execute("""
        SELECT COUNT(*) FROM staging_rating_candidates
        WHERE batch_id=? AND (score_normalized_100 < 0 OR score_normalized_100 > 100)
    """, (BATCH_ID,))
    bad_scores = cur.fetchone()[0]
    if bad_scores > 0:
        fail(f"{bad_scores} rating(s) with score_normalized_100 outside [0,100]")
        cur.execute("""
            SELECT wine_key, score_normalized_100
            FROM staging_rating_candidates
            WHERE batch_id=? AND (score_normalized_100 < 0 OR score_normalized_100 > 100)
        """, (BATCH_ID,))
        for r in cur.fetchall():
            print(f"         wine_key={r[0]}  score={r[1]}")
        failures.append("score_range")
    else:
        cur.execute("SELECT COUNT(*) FROM staging_rating_candidates WHERE batch_id=?", (BATCH_ID,))
        n = cur.fetchone()[0]
        ok(f"All {n} scores are within [0, 100]")

    # ── Check 2: Appellation fallback rate ───────────────────────────────────
    section("CHECK 2: Appellation fallback rate")
    cur.execute("""
        SELECT COUNT(*) FROM staging_rating_candidates src
        JOIN dim_wine dw ON dw.wine_key = src.wine_key
        WHERE src.batch_id=? AND dw.appellation_key=?
    """, (BATCH_ID, fallback_app_key))
    fallback_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM staging_rating_candidates WHERE batch_id=?", (BATCH_ID,))
    total_ratings = cur.fetchone()[0]
    if total_ratings > 0:
        fallback_pct = 100 * fallback_count / total_ratings
    else:
        fallback_pct = 0.0

    if fallback_count == 0:
        ok(f"No appellation fallbacks (0 / {total_ratings})")
    elif fallback_pct > 40:
        warn(f"High fallback rate: {fallback_count}/{total_ratings} = {fallback_pct:.1f}% (threshold: 40%)")
        warnings_list.append(f"appellation_fallback_rate={fallback_pct:.1f}%")
        # List which wines fell back
        cur.execute("""
            SELECT src.wine_key, dw.cuvee_name, dw.vintage
            FROM staging_rating_candidates src
            JOIN dim_wine dw ON dw.wine_key = src.wine_key
            WHERE src.batch_id=? AND dw.appellation_key=?
        """, (BATCH_ID, fallback_app_key))
        for r in cur.fetchall():
            print(f"         fallback wine: {r['wine_key']} | {r['cuvee_name']} | {r['vintage']}")
    else:
        warn(f"Some fallbacks: {fallback_count}/{total_ratings} = {fallback_pct:.1f}%")
        warnings_list.append(f"appellation_fallbacks={fallback_count}")

    # ── Check 3: Duplicate wine_keys in staging ───────────────────────────────
    section("CHECK 3: Duplicate (wine_key, source_key) in staging_rating_candidates")
    cur.execute("""
        SELECT wine_key, source_key, COUNT(*) as cnt
        FROM staging_rating_candidates
        WHERE batch_id=?
        GROUP BY wine_key, source_key
        HAVING cnt > 1
    """, (BATCH_ID,))
    dupes = cur.fetchall()
    if dupes:
        fail(f"{len(dupes)} duplicate (wine_key, source_key) pair(s) found")
        for d in dupes:
            print(f"         wine_key={d['wine_key']}  source_key={d['source_key']}  count={d['cnt']}")
        failures.append("duplicate_wine_keys")
    else:
        ok("No duplicate (wine_key, source_key) pairs")

    # ── Check 4: Non-FR wines ─────────────────────────────────────────────────
    section("CHECK 4: All imported wines have country_code='FR'")
    cur.execute("""
        SELECT DISTINCT dp.country_code, dp.producer_name, dw.wine_key
        FROM staging_rating_candidates src
        JOIN dim_wine dw ON dw.wine_key = src.wine_key
        JOIN dim_producer dp ON dp.producer_key = dw.producer_key
        WHERE src.batch_id=? AND dp.country_code != 'FR'
    """, (BATCH_ID,))
    non_fr = cur.fetchall()
    if non_fr:
        fail(f"{len(non_fr)} non-FR wine(s) found in dim_wine for this batch")
        for r in non_fr:
            print(f"         country={r['country_code']}  producer={r['producer_name']}  wine_key={r['wine_key']}")
        failures.append("non_fr_wines")
    else:
        ok("All imported wines have country_code='FR'")

    # ── Check 5: Negative prices ──────────────────────────────────────────────
    section("CHECK 5: No negative prices in staging_price_candidates")
    cur.execute("""
        SELECT COUNT(*) FROM staging_price_candidates
        WHERE batch_id=? AND (amount_eur <= 0 OR amount_local <= 0)
    """, (BATCH_ID,))
    neg_prices = cur.fetchone()[0]
    if neg_prices > 0:
        fail(f"{neg_prices} price row(s) with amount_eur <= 0")
        cur.execute("""
            SELECT wine_key, amount_eur FROM staging_price_candidates
            WHERE batch_id=? AND (amount_eur <= 0 OR amount_local <= 0)
        """, (BATCH_ID,))
        for r in cur.fetchall():
            print(f"         wine_key={r['wine_key']}  price={r['amount_eur']}")
        failures.append("negative_prices")
    else:
        cur.execute("SELECT COUNT(*) FROM staging_price_candidates WHERE batch_id=?", (BATCH_ID,))
        np_count = cur.fetchone()[0]
        ok(f"All {np_count} prices are positive")

    # ── Check 6: Score outliers ───────────────────────────────────────────────
    section("CHECK 6: Score outliers (>100 or <50)")
    cur.execute("""
        SELECT wine_key, score_normalized_100 FROM staging_rating_candidates
        WHERE batch_id=? AND score_normalized_100 > 100
    """, (BATCH_ID,))
    over_100 = cur.fetchall()
    cur.execute("""
        SELECT wine_key, score_normalized_100 FROM staging_rating_candidates
        WHERE batch_id=? AND score_normalized_100 < 50
    """, (BATCH_ID,))
    under_50 = cur.fetchall()

    if over_100:
        fail(f"{len(over_100)} score(s) > 100 (impossible)")
        for r in over_100:
            print(f"         wine_key={r['wine_key']}  score={r['score_normalized_100']}")
        failures.append("score_over_100")
    else:
        ok("No scores > 100")

    if under_50:
        warn(f"{len(under_50)} score(s) < 50 — unusual for RVF")
        for r in under_50:
            print(f"         wine_key={r['wine_key']}  score={r['score_normalized_100']}")
        warnings_list.append(f"scores_under_50={len(under_50)}")
    else:
        ok("No scores < 50")

    # ── Check 7: Producer match rate ─────────────────────────────────────────
    section("CHECK 7: Producer match rate (found vs created)")
    # Producers for wines in this batch, using first_seen_at to detect newly created ones
    cur.execute("""
        SELECT COUNT(DISTINCT dp.producer_key) as total,
               SUM(CASE WHEN dp.first_seen_at = dp.last_seen_at
                        AND dp.first_seen_at > strftime('%s','now') - 86400 THEN 1 ELSE 0 END) as created_today
        FROM staging_rating_candidates src
        JOIN dim_wine dw ON dw.wine_key = src.wine_key
        JOIN dim_producer dp ON dp.producer_key = dw.producer_key
        WHERE src.batch_id=?
    """, (BATCH_ID,))
    pm = cur.fetchone()
    total_producers = pm["total"]
    created_producers = pm["created_today"]
    found_producers = total_producers - created_producers
    ok(f"Producers found (pre-existing) : {found_producers}")
    ok(f"Producers created (new)        : {created_producers}")
    ok(f"Total unique producers         : {total_producers}")

    # ── Check 8: Wine key collisions ─────────────────────────────────────────
    section("CHECK 8: Wine key collisions (same key, different producer/cuvée)")
    cur.execute("""
        SELECT src.wine_key, dw.cuvee_name, dw.producer_key, dp.producer_name
        FROM staging_rating_candidates src
        JOIN dim_wine dw ON dw.wine_key = src.wine_key
        JOIN dim_producer dp ON dp.producer_key = dw.producer_key
        WHERE src.batch_id=?
    """, (BATCH_ID,))
    batch_wines = {r["wine_key"]: (r["producer_key"], r["producer_name"], r["cuvee_name"]) for r in cur.fetchall()}

    # Check if any wine_key in the batch exists in dim_wine with a DIFFERENT producer_key or cuvee
    # (shouldn't be possible due to wine_key computation, but worth verifying)
    conflicts = []
    for wk, (pk, pname, cname) in batch_wines.items():
        cur.execute("SELECT producer_key, cuvee_name FROM dim_wine WHERE wine_key=? LIMIT 1", (wk,))
        dw = cur.fetchone()
        if dw and (dw["producer_key"] != pk or dw["cuvee_name"] != cname):
            conflicts.append({
                "wine_key": wk,
                "batch_producer": pname,
                "batch_cuvee": cname,
                "db_producer_key": dw["producer_key"],
                "db_cuvee": dw["cuvee_name"],
            })

    if conflicts:
        warn(f"{len(conflicts)} wine_key collision(s) — same key, different producer/cuvée in dim_wine")
        for c in conflicts:
            print(f"         key={c['wine_key']}")
            print(f"           batch: producer={c['batch_producer']!r}  cuvee={c['batch_cuvee']!r}")
            print(f"           db   : producer_key={c['db_producer_key']}  cuvee={c['db_cuvee']!r}")
        warnings_list.append(f"wine_key_collisions={len(conflicts)}")
    else:
        ok(f"No wine key collisions ({len(batch_wines)} unique wine_keys checked)")

    # ── Final summary ─────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("  SUMMARY")
    print("=" * 60)
    cur.execute("SELECT COUNT(*) FROM staging_rating_candidates WHERE batch_id=?", (BATCH_ID,))
    total_r = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM staging_price_candidates WHERE batch_id=?", (BATCH_ID,))
    total_p = cur.fetchone()[0]
    cur.execute("SELECT MIN(score_normalized_100), MAX(score_normalized_100), AVG(score_normalized_100) FROM staging_rating_candidates WHERE batch_id=?", (BATCH_ID,))
    score_stats = cur.fetchone()

    print(f"  Ratings in staging  : {total_r}")
    print(f"  Prices in staging   : {total_p}")
    print(f"  Score min/max/avg   : {score_stats[0]:.1f} / {score_stats[1]:.1f} / {score_stats[2]:.2f}")
    if warnings_list:
        print(f"  Warnings            : {len(warnings_list)}")
        for w in warnings_list:
            print(f"    - {w}")
    if failures:
        print(f"  Failures            : {len(failures)}")
        for f_name in failures:
            print(f"    - {f_name}")
    print()

    conn.close()

    if failures:
        print("RESULT: FAIL")
        return 1
    else:
        print("RESULT: PASS")
        return 0


if __name__ == "__main__":
    sys.exit(main())
