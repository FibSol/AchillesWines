"""
Fix topwijnen_be duplication bug.

Root cause: staging_price_candidates has no UNIQUE constraint on
(wine_key, source_key, content_hash), so every run inserts new rows
even when the same product was already staged.

Steps:
1. Delete ALL topwijnen_be rows from fact_price
2. Keep only the MIN(candidate_id) per (wine_key, source_key, content_hash)
   in staging_price_candidates for topwijnen_be
3. Reset kept rows back to needs_review=1 so the promoter can re-process
4. Add a UNIQUE INDEX to prevent this happening again
5. Report final state
"""
import sqlite3
import sys

DB = "../data/achilles.db"
conn = sqlite3.connect(DB)
conn.execute("PRAGMA journal_mode=WAL")

tw_key = conn.execute(
    "SELECT source_key FROM dim_source WHERE source_code='topwijnen_be'"
).fetchone()[0]
print(f"topwijnen_be source_key = {tw_key}")

# ── Step 0: report before state ─────────────────────────────────────────────
s_before = conn.execute(
    "SELECT COUNT(*) FROM staging_price_candidates WHERE source_key=?", (tw_key,)
).fetchone()[0]
f_before = conn.execute(
    "SELECT COUNT(*) FROM fact_price WHERE source_key=?", (tw_key,)
).fetchone()[0]
print(f"\nBEFORE: staging={s_before}, fact_price={f_before}")

# ── Step 1: delete topwijnen_be rows from fact_price ────────────────────────
print("\n[1] Deleting topwijnen_be rows from fact_price...")
conn.execute("DELETE FROM fact_price WHERE source_key=?", (tw_key,))
f_after_step1 = conn.execute("SELECT COUNT(*) FROM fact_price WHERE source_key=?", (tw_key,)).fetchone()[0]
print(f"    fact_price topwijnen_be rows remaining: {f_after_step1}")

# ── Step 2: find duplicate staging rows (keep MIN(candidate_id) per group) ──
print("\n[2] Deduplicating staging_price_candidates for topwijnen_be...")
# Find all candidate_ids that are NOT the minimum for their group
dupes = conn.execute("""
    SELECT candidate_id FROM staging_price_candidates
    WHERE source_key = ?
      AND candidate_id NOT IN (
          SELECT MIN(candidate_id)
          FROM staging_price_candidates
          WHERE source_key = ?
          GROUP BY wine_key, source_key, content_hash
      )
""", (tw_key, tw_key)).fetchall()
dupe_count = len(dupes)
print(f"    Duplicate candidate_ids to delete: {dupe_count}")

conn.execute("""
    DELETE FROM staging_price_candidates
    WHERE source_key = ?
      AND candidate_id NOT IN (
          SELECT MIN(candidate_id)
          FROM staging_price_candidates
          WHERE source_key = ?
          GROUP BY wine_key, source_key, content_hash
      )
""", (tw_key, tw_key))
s_after_step2 = conn.execute(
    "SELECT COUNT(*) FROM staging_price_candidates WHERE source_key=?", (tw_key,)
).fetchone()[0]
print(f"    Staging rows remaining for topwijnen_be: {s_after_step2}")

# ── Step 3: reset kept rows to needs_review=1 ───────────────────────────────
print("\n[3] Resetting topwijnen_be staging rows to needs_review=1...")
conn.execute("""
    UPDATE staging_price_candidates
    SET needs_review = 1, promoted_at = NULL, promoted_to_fact_price_key = NULL
    WHERE source_key = ?
""", (tw_key,))
print("    Done.")

# ── Step 4: add UNIQUE INDEX to prevent future duplication ───────────────────
print("\n[4] Adding UNIQUE INDEX on (wine_key, source_key, content_hash)...")
# SQLite supports partial unique index (WHERE content_hash IS NOT NULL)
try:
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uix_staging_wine_source_hash
        ON staging_price_candidates(wine_key, source_key, content_hash)
        WHERE content_hash IS NOT NULL
    """)
    print("    UNIQUE INDEX created.")
except Exception as e:
    print(f"    WARNING: {e}")

# ── Step 5: commit and report ────────────────────────────────────────────────
conn.commit()

s_final = conn.execute(
    "SELECT COUNT(*) FROM staging_price_candidates WHERE source_key=?", (tw_key,)
).fetchone()[0]
s_total = conn.execute("SELECT COUNT(*) FROM staging_price_candidates").fetchone()[0]
f_total = conn.execute("SELECT COUNT(*) FROM fact_price").fetchone()[0]
tw_distinct = conn.execute(
    "SELECT COUNT(DISTINCT wine_key) FROM staging_price_candidates WHERE source_key=?", (tw_key,)
).fetchone()[0]

print("\n── FINAL STATE ──────────────────────────────────────────")
print(f"topwijnen_be staging rows : {s_final}  (distinct wine_keys: {tw_distinct})")
print(f"Total staging rows        : {s_total}")
print(f"Total fact_price rows     : {f_total}")
print(f"\nDuplicates removed from staging : {dupe_count}")
print(f"fact_price topwijnen_be purged  : {f_before}")

conn.close()
print("\nDone. Run promoter next to re-populate fact_price cleanly.")
