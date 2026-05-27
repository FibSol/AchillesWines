import sqlite3, json, unicodedata
from rapidfuzz import fuzz

def norm(s):
    s = unicodedata.normalize('NFKD', s or '').encode('ascii', 'ignore').decode()
    return s.lower().strip()

conn = sqlite3.connect('../data/achilles.db')

# Count remaining
total = conn.execute(
    "SELECT COUNT(*) FROM ops_dead_letter WHERE source_key=52 AND error_class='unmatched_wine' AND (resolution IS NULL OR resolution='pending')"
).fetchone()[0]
print(f'Remaining DLQ: {total}')

# Look up Cotes du Rhone appellation keys
print('\nRhone appellations:')
rhone_apps = conn.execute(
    "SELECT appellation_key, appellation_norm, appellation_name FROM dim_appellation WHERE appellation_norm LIKE '%rhone%' ORDER BY appellation_key"
).fetchall()
for r in rhone_apps[:10]:
    print(f'  app {r[0]}: {r[2]!r}')

# Gaillac
print('\nGaillac appellations:')
gaillac_apps = conn.execute(
    "SELECT appellation_key, appellation_norm, appellation_name FROM dim_appellation WHERE appellation_norm LIKE '%gaillac%'"
).fetchall()
for r in gaillac_apps:
    print(f'  app {r[0]}: {r[2]!r}')

# Look up specific DLQ records for our target producers
print('\nTarget DLQ records (cuvee==producer):')
rows = conn.execute(
    "SELECT dlq_id, raw_record FROM ops_dead_letter WHERE source_key=52 AND error_class='unmatched_wine' AND (resolution IS NULL OR resolution='pending')"
).fetchall()
targets = ['vignals', 'barry', 'brousse', 'annabel', 'arnelin', 'gaillarde', 'bonnefil', 'carlines', 'bissy']
for dlq_id, raw in rows:
    try:
        r = json.loads(raw)
        p = norm(r.get('producer', ''))
        c = norm(r.get('cuvee', ''))
        for t in targets:
            if t in p:
                print(f'  DLQ {dlq_id}: prod={r.get("producer")!r} cuvee={r.get("cuvee")!r} app={r.get("appellation")!r} v={r.get("vintage")} score={r.get("score")}')
    except:
        pass

conn.close()
