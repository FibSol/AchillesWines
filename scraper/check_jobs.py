import sqlite3
conn = sqlite3.connect('../data/achilles.db')
rows = conn.execute("""SELECT s.source_code, j.status, j.error_message
    FROM ops_job_queue j JOIN dim_source s ON s.source_key=j.source_key
    WHERE j.status IN ('failed','running')
    ORDER BY j.requested_at DESC LIMIT 5""").fetchall()
for r in rows:
    print(f'{r[0]}: {r[1]} -- {str(r[2])[:100]}')
