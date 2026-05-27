import sqlite3
conn = sqlite3.connect('../data/achilles.db')
try:
    total = conn.execute("SELECT COUNT(*) FROM fact_rating fr JOIN dim_source ds ON ds.source_key=fr.source_key WHERE ds.source_code='cellartracker'").fetchone()[0]
    row = conn.execute("SELECT AVG(score) FROM fact_rating fr JOIN dim_source ds ON ds.source_key=fr.source_key WHERE ds.source_code='cellartracker'").fetchone()
    avg_score = row[0] if row[0] is not None else 0.0
    cursor = open('data/cellartracker_cursor.txt').read().strip()
    print(f'total_ct_rows={total}  avg_score={avg_score:.1f}  cursor={cursor}')
except Exception as e:
    print('sanity_check_error: ' + str(e))
