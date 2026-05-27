import sqlite3, json
conn = sqlite3.connect('../data/achilles.db')

# Sample raw_record for parse_errors to see what the pages actually contain
rows = conn.execute("""
    SELECT error_class, error_message, raw_record, created_at
    FROM ops_dead_letter odl
    JOIN dim_source ds ON ds.source_key = odl.source_key
    WHERE ds.source_code = 'cellartracker'
    ORDER BY created_at DESC LIMIT 30
""").fetchall()

from collections import Counter
messages = Counter()
samples = {}

for r in rows:
    msg = r[1]
    messages[msg] += 1
    if msg not in samples:
        try:
            raw = json.loads(r[2]) if r[2] else {}
        except:
            raw = r[2]
        samples[msg] = raw

print("=== DLQ message breakdown (last 30) ===")
for msg, count in messages.most_common():
    print(f"  [{count:4d}x] {msg}")
    s = samples.get(msg, {})
    if isinstance(s, dict):
        for k in ('iWine', 'pairs', 'producer', 'designation', 'country'):
            if k in s:
                print(f"          {k}: {str(s[k])[:120]}")
    print()

# Also check: what do the 'pairs' look like for missing prod/desig?
print("=== Sample 'pairs' from missing-producer DLQ entries ===")
missing = conn.execute("""
    SELECT raw_record FROM ops_dead_letter odl
    JOIN dim_source ds ON ds.source_key = odl.source_key
    WHERE ds.source_code = 'cellartracker'
      AND error_message LIKE '%missing producer%'
    ORDER BY created_at DESC LIMIT 10
""").fetchall()
for (raw,) in missing:
    try:
        d = json.loads(raw) if raw else {}
        print(f"  iWine={d.get('iWine')}  pairs={d.get('pairs', {})}")
    except:
        print(f"  raw={str(raw)[:100]}")
