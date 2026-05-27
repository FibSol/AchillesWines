import sqlite3, unicodedata
from rapidfuzz import fuzz

def norm(s):
    s = unicodedata.normalize('NFKD', s or '').encode('ascii', 'ignore').decode()
    return s.lower().strip()

conn = sqlite3.connect('../data/achilles.db')
db_producers = [(r[0], r[1], r[2]) for r in conn.execute(
    'SELECT producer_key, producer_norm, producer_name FROM dim_producer'
).fetchall()]

checks = [
    'vignerons de buxy', 'belair monange', 'chateau belair', 'mauvinon',
    'franc baudron', 'clotte cazalis', 'maison boiteau', 'domaine des buis',
    'longues vignes', 'oury schreiber', 'cordeliers', 'colombiere',
    'terrasses du larzac'
]

for term in checks:
    n = norm(term)
    top3 = sorted([(fuzz.token_sort_ratio(n, p[1]), p[0], p[2]) for p in db_producers], reverse=True)[:3]
    print(f'{term!r}: {top3}')

conn.close()
