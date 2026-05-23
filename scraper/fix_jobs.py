import sqlite3
import time

conn = sqlite3.connect('../data/achilles.db')

# Show all running/queued jobs
rows = conn.execute("""
    SELECT j.job_id, s.source_code, j.status, j.started_at, j.rows_fetched, j.rows_inserted
    FROM ops_job_queue j JOIN dim_source s ON s.source_key = j.source_key
    WHERE j.status IN ('running', 'queued')
    ORDER BY j.requested_at DESC
""").fetchall()

print(f"Stale jobs found: {len(rows)}")
for r in rows:
    print(f"  job_id={r[0]} source={r[1]} status={r[2]} started={r[3]} fetched={r[4]} ins={r[5]}")

# Reset all running/queued jobs with 0 fetched to 'failed'
# (they were orphaned when the job runner process was killed)
now = int(time.time())
updated = conn.execute("""
    UPDATE ops_job_queue
    SET status = 'failed',
        finished_at = ?,
        error_message = 'Job runner process was killed — job never executed (rows_fetched=0). Reset by fix_jobs.py.'
    WHERE status IN ('running', 'queued')
      AND (rows_fetched IS NULL OR rows_fetched = 0)
""", (now,)).rowcount
conn.commit()

print(f"\nReset {updated} orphaned jobs to 'failed'.")

# Confirm nothing left running
remaining = conn.execute("""
    SELECT COUNT(*) FROM ops_job_queue WHERE status IN ('running', 'queued')
""").fetchone()[0]
print(f"Remaining running/queued jobs: {remaining}")
conn.close()
