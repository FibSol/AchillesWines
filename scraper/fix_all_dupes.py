"""
Comprehensive dedup fix for staging_price_candidates and fact_price.

Root cause: no UNIQUE constraint on (wine_key, source_key, content_hash),
so the same product can be inserted multiple times within or across batches
(e.g. topwijnen_be catalogue pages overlap; wijnhuis pages overlap too).

Fix:
1. Identify all sources with duplicates
2. For each: delete from fact_price, dedup staging, reset to needs_review=1
3. Add UNIQUE INDEX to prevent recurrence
4. Run promoter logic to re-populate fact_price cleanly
"""
import sqlite3
import sys
import time

DB = "../data/achilles.db"
conn = sqlite3.connect(DB)
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA busy_timeout=30000")

# ── 0. Before state ──────────────────────────────────────────────────────────
print("=" * 60)
print("BEFORE STATE")
print("=" * 60)
total_s = conn.execute("SELECT COUNT(*) FROM staging_price_candidates").fetchone()[0]
total_f = conn.execute("SELECT COUNT(*) FROM fact_price").fetchone()[0]
print(f"staging_price_candidates: {total_s}")
print(f"fact_price: {total_f}")

dup_by_source = conn.execute("""
    WITH dup_rows AS (
        SELECT wine_key, source_key, content_hash, COUNT(*) as cnt
        FROM staging_price_candidates
        WHERE content_hash IS NOT NULL
        GROUP BY wine_key, source_key, content_hash
        HAVING COUNT(*) > 1
    )
    SELECT s.source_code, s.source_key,
           COUNT(*) as dup_groups,
           SUM(dr.cnt - 1) as extra_rows
    FROM dup_rows dr
    JOIN dim_source s ON s.source_key = dr.source_key
    GROUP BY s.source_code, s.source_key
    ORDER BY extra_rows DESC
""").fetchall()

print("\nDuplicate groups by source:")
for r in dup_by_source:
    print(f"  {r[0]}: {r[2]} groups, {r[3]} extra rows")

print()

# ── 1. Delete fact_price rows for affected sources ────────────────────────────
affected_source_keys = [r[1] for r in dup_by_source]
print(f"[1] Deleting fact_price rows for {len(affected_source_keys)} sources with duplicates...")
for sk in affected_source_keys:
    src = conn.execute(
        "SELECT source_code FROM dim_source WHERE source_key=?", (sk,)
    ).fetchone()[0]
    deleted = conn.execute(
        "DELETE FROM fact_price WHERE source_key=?", (sk,)
    ).rowcount
    print(f"    {src}: deleted {deleted} fact_price rows")

# ── 2. Global dedup: keep MIN(candidate_id) per (wine_key, source_key, content_hash) ──
print("\n[2] Deduplicating ALL staging_price_candidates...")
before_dedup = conn.execute("SELECT COUNT(*) FROM staging_price_candidates").fetchone()[0]

conn.execute("""
    DELETE FROM staging_price_candidates
    WHERE content_hash IS NOT NULL
      AND candidate_id NOT IN (
          SELECT MIN(candidate_id)
          FROM staging_price_candidates
          WHERE content_hash IS NOT NULL
          GROUP BY wine_key, source_key, content_hash
      )
""")

after_dedup = conn.execute("SELECT COUNT(*) FROM staging_price_candidates").fetchone()[0]
removed = before_dedup - after_dedup
print(f"    Removed {removed} duplicate rows ({before_dedup} -> {after_dedup})")

# ── 3. Reset affected-source staging rows to needs_review=1 ──────────────────
print("\n[3] Resetting affected source staging rows to needs_review=1...")
for sk in affected_source_keys:
    src = conn.execute(
        "SELECT source_code FROM dim_source WHERE source_key=?", (sk,)
    ).fetchone()[0]
    updated = conn.execute("""
        UPDATE staging_price_candidates
        SET needs_review=1, promoted_at=NULL, promoted_to_fact_price_key=NULL
        WHERE source_key=?
    """, (sk,)).rowcount
    print(f"    {src}: reset {updated} rows")

# ── 4. Create UNIQUE INDEX ────────────────────────────────────────────────────
print("\n[4] Creating UNIQUE INDEX on (wine_key, source_key, content_hash)...")
try:
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uix_staging_wine_source_hash
        ON staging_price_candidates(wine_key, source_key, content_hash)
        WHERE content_hash IS NOT NULL
    """)
    print("    UNIQUE INDEX created successfully.")
except Exception as e:
    # If it still fails, there are still dupes - show them
    remaining = conn.execute("""
        SELECT wine_key, source_key, content_hash, COUNT(*) as cnt
        FROM staging_price_candidates
        WHERE content_hash IS NOT NULL
        GROUP BY wine_key, source_key, content_hash
        HAVING COUNT(*) > 1
        LIMIT 5
    """).fetchall()
    print(f"    ERROR: {e}")
    print("    Remaining duplicate groups:")
    for r in remaining:
        print(f"      {r}")

# ── 5. Commit ─────────────────────────────────────────────────────────────────
conn.commit()

# ── 6. Final state ────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("FINAL STATE")
print("=" * 60)

final_s = conn.execute("SELECT COUNT(*) FROM staging_price_candidates").fetchone()[0]
final_f = conn.execute("SELECT COUNT(*) FROM fact_price").fetchone()[0]
print(f"staging_price_candidates: {final_s}")
print(f"fact_price: {final_f}")
print(f"Rows removed from staging: {total_s - final_s}")
print(f"Rows removed from fact_price: {total_f - final_f}")

# Per-source staging summary
print("\nPer-source staging summary:")
rows = conn.execute("""
    SELECT s.source_code, COUNT(*) as cnt, COUNT(DISTINCT spc.wine_key) as wines
    FROM staging_price_candidates spc
    JOIN dim_source s ON s.source_key = spc.source_key
    GROUP BY s.source_code
    ORDER BY cnt DESC
""").fetchall()
for r in rows:
    print(f"  {r[0]}: {r[1]} staging rows, {r[2]} distinct wine_keys")

# Verify no more dupes
dup_check = conn.execute("""
    SELECT COUNT(*) FROM (
        SELECT wine_key, source_key, content_hash
        FROM staging_price_candidates
        WHERE content_hash IS NOT NULL
        GROUP BY wine_key, source_key, content_hash
        HAVING COUNT(*) > 1
    )
""").fetchone()[0]
print(f"\nRemaining duplicate (wine_key, source_key, content_hash) groups: {dup_check}")

# Overlap for promoter
overlap = conn.execute("""
    SELECT COUNT(*) FROM (
        SELECT wine_key FROM staging_price_candidates
        WHERE needs_review=1 AND promoted_at IS NULL
        GROUP BY wine_key HAVING COUNT(DISTINCT source_key) >= 2
    )
""").fetchone()[0]
print(f"Wine keys with 2+ sources (ready for promoter): {overlap}")

conn.close()
print("\nNext step: run promoter to repopulate fact_price cleanly.")
