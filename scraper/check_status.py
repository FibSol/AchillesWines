import sqlite3
conn = sqlite3.connect('../data/achilles.db')

total = conn.execute("SELECT COUNT(*) FROM fact_rating fr JOIN dim_source ds ON ds.source_key=fr.source_key WHERE ds.source_code='cellartracker'").fetchone()[0]
avg = conn.execute("SELECT AVG(score) FROM fact_rating fr JOIN dim_source ds ON ds.source_key=fr.source_key WHERE ds.source_code='cellartracker'").fetchone()[0]

recent = conn.execute("""
    SELECT batch_id, COUNT(*) c FROM fact_rating fr
    JOIN dim_source ds ON ds.source_key=fr.source_key
    WHERE ds.source_code='cellartracker'
    GROUP BY batch_id ORDER BY batch_id DESC LIMIT 8
""").fetchall()

dlq = conn.execute("""
    SELECT error_class, COUNT(*) c FROM ops_dead_letter odl
    JOIN dim_source ds ON ds.source_key = odl.source_key
    WHERE ds.source_code='cellartracker'
    GROUP BY error_class ORDER BY c DESC LIMIT 10
""").fetchall()

dlq_recent = conn.execute("""
    SELECT error_class, error_message, created_at FROM ops_dead_letter odl
    JOIN dim_source ds ON ds.source_key = odl.source_key
    WHERE ds.source_code='cellartracker'
    ORDER BY created_at DESC LIMIT 5
""").fetchall()

try:
    cursor = open('data/cellartracker_cursor.txt').read().strip()
except:
    cursor = 'missing'

print(f'Cursor        : {cursor}')
print(f'Total CT rows : {total}')
print(f'Avg score     : {avg:.1f}' if avg else 'Avg score: n/a')
print()
print('Recent batches (fact_rating):')
for r in recent:
    print(f'  {r[0]}  rows={r[1]}')
print()
print('DLQ summary:')
for r in dlq:
    print(f'  {r[0]:30s}  count={r[1]}')
if not dlq:
    print('  (none)')
print()
print('Last 5 DLQ entries:')
for r in dlq_recent:
    print(f'  [{r[2]}] {r[0]} — {str(r[1])[:80]}')
if not dlq_recent:
    print('  (none)')
