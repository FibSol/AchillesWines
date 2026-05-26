import sqlite3
conn = sqlite3.connect('../data/achilles.db')
total = conn.execute("SELECT COUNT(*) FROM ops_dead_letter WHERE source_key=52 AND error_class='unmatched_wine' AND (resolution IS NULL OR resolution='pending')").fetchone()[0]
print(f'Remaining DLQ: {total}')
by_res = conn.execute("SELECT resolution, COUNT(*) FROM ops_dead_letter WHERE source_key=52 AND error_class='unmatched_wine' GROUP BY resolution").fetchall()
for r in by_res:
    print(f'  {r[0]}: {r[1]}')
conn.close()
