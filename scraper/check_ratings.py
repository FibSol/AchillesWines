import sqlite3
conn = sqlite3.connect('../data/achilles.db')
dim = conn.execute('SELECT COUNT(*) FROM dim_wine').fetchone()[0]
print(f'dim_wine entries: {dim}')
fp_in_dim = conn.execute('''
    SELECT COUNT(DISTINCT fp.wine_key)
    FROM fact_price fp
    WHERE EXISTS (SELECT 1 FROM dim_wine dw WHERE dw.wine_key = fp.wine_key)
''').fetchone()[0]
print(f'fact_price wine_keys in dim_wine: {fp_in_dim}')

# Rating scraper jobs
jobs = conn.execute("""
    SELECT s.source_code, j.status, j.rows_inserted, j.rows_dlq, j.error_message
    FROM ops_job_queue j JOIN dim_source s ON s.source_key = j.source_key
    WHERE s.source_code IN ('decanter','rvf','james_suckling','hachette_vins','hachette_vins_shop')
    ORDER BY j.requested_at DESC LIMIT 10
""").fetchall()
print('Rating scraper jobs:')
for j in jobs:
    print(f'  {j[0]}: {j[1]} ins={j[2]} dlq={j[3]} err={str(j[4])[:60] if j[4] else None}')
