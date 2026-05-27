import sqlite3, unicodedata
from rapidfuzz import fuzz

def norm(s):
    s = unicodedata.normalize('NFKD', s or '').encode('ascii', 'ignore').decode()
    return s.lower().strip()

conn = sqlite3.connect('../data/achilles.db')
db_producers = [(r[0], r[1], r[2]) for r in conn.execute(
    'SELECT producer_key, producer_norm, producer_name FROM dim_producer'
).fetchall()]

more = [
    ('Les Vignerons d Ajaccio', 'ajaccio'),
    ('Cave de Julienas Chaintre', 'julien'),
    ('Verizet', 'ver'),
    ('Vignerons d Ige', 'ige'),
    ('Vignobles de Montesquieu', 'montesquieu'),
    ('Huton Beaunoy', 'beaunoy'),
    ('Christophe Avi', 'avi'),
]
for term, hint in more:
    n = norm(term)
    # Try hint first
    hint_matches = [(fuzz.token_sort_ratio(n, p[1]), p[0], p[2]) for p in db_producers if hint in p[1]]
    hint_matches.sort(reverse=True)
    top3 = sorted([(fuzz.token_sort_ratio(n, p[1]), p[0], p[2]) for p in db_producers], reverse=True)[:3]
    if hint_matches and hint_matches[0][0] >= 70:
        print(f'{term!r}: hint={hint_matches[:2]}')
    else:
        print(f'{term!r}: NO HINT MATCH; top3={top3}')

conn.close()
