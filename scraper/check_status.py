import sqlite3
conn = sqlite3.connect('../data/achilles.db')

print("=== ops_job_queue (running/queued + last 10) ===")
rows = conn.execute("""
    SELECT s.source_code, j.status, j.started_at, j.finished_at,
           j.rows_fetched, j.rows_inserted, j.rows_dlq, j.error_message
    FROM ops_job_queue j JOIN dim_source s ON s.source_key = j.source_key
    ORDER BY j.requested_at DESC
    LIMIT 15
""").fetchall()
if not rows:
    print("  No jobs found.")
else:
    for r in rows:
        err = (str(r[7])[:50] if r[7] else "")
        print(f"  {r[0]:22s} {r[1]:8s} fetched={r[4] or 0:5d} ins={r[5] or 0:5d} dlq={r[6] or 0}  {err}")

print()
print("=== Counts ===")
s = conn.execute("SELECT COUNT(*) FROM staging_price_candidates").fetchone()[0]
f = conn.execute("SELECT COUNT(*) FROM fact_price").fetchone()[0]
pending = conn.execute(
    "SELECT COUNT(*) FROM staging_price_candidates WHERE needs_review=1 AND promoted_at IS NULL"
).fetchone()[0]
overlap = conn.execute("""
    SELECT COUNT(*) FROM (
        SELECT wine_key FROM staging_price_candidates
        WHERE needs_review=1 AND promoted_at IS NULL
        GROUP BY wine_key HAVING COUNT(DISTINCT source_key) >= 2
    )
""").fetchone()[0]
print(f"  staging rows  : {s}")
print(f"  fact_price    : {f}")
print(f"  pending promo : {pending}")
print(f"  2+ src overlap: {overlap}")
