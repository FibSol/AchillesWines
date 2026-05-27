import sqlite3
conn = sqlite3.connect('../data/achilles.db')
try:
    total = conn.execute("SELECT COUNT(*) FROM fact_rating fr JOIN dim_source ds ON ds.source_key=fr.source_key WHERE ds.source_code='cellartracker'").fetchone()[0]
    print('existing_ct_rows=' + str(total))
except Exception as e:
    print('error: ' + str(e))
