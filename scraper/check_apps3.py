import sqlite3, unicodedata
from rapidfuzz import fuzz

def norm(s):
    s = unicodedata.normalize('NFKD', s or '').encode('ascii', 'ignore').decode()
    return s.lower().strip()

conn = sqlite3.connect('../data/achilles.db')

# Appellation lookups
for search in ['gevrey', 'nuits', 'macon', 'pic saint', 'buzet', 'limoux', 'cairanne']:
    rows = conn.execute(
        "SELECT appellation_key, appellation_name FROM dim_appellation WHERE appellation_norm LIKE ? ORDER BY appellation_key LIMIT 3",
        (f'%{search}%',)
    ).fetchall()
    print(f'{search}: {[(r[0], r[1]) for r in rows]}')

# Check Vignobles de Montesquieu / Domaine de Montesquieu
db_producers = [(r[0], r[1], r[2]) for r in conn.execute(
    'SELECT producer_key, producer_norm, producer_name FROM dim_producer'
).fetchall()]

for term in ['Montesquieu', 'Verizet', 'Domaine Achilles', 'Vignobles de Montesquieu']:
    n = norm(term)
    top3 = sorted([(fuzz.token_sort_ratio(n, p[1]), p[0], p[2]) for p in db_producers], reverse=True)[:3]
    print(f'{term!r}: {top3}')

conn.close()
