import sqlite3, unicodedata
from rapidfuzz import fuzz

def norm(s):
    s = unicodedata.normalize('NFKD', s or '').encode('ascii', 'ignore').decode()
    return s.lower().strip()

conn = sqlite3.connect('../data/achilles.db')
db_producers = [(r[0], r[1], r[2]) for r in conn.execute(
    'SELECT producer_key, producer_norm, producer_name FROM dim_producer'
).fetchall()]

# Famous ones that should be in DB
header_producers = [
    ('OLIVIER PITHON', 'pithon'),
    ('Roland Van Hecke', 'van hecke'),
    ('CHATEAU PRIEURE-LICHINE', 'lichine'),
    ('DOMAINE LOUIS-BENJAMIN DAGUENEAU', 'dagueneau'),
    ('HELICON', 'helicon'),
    ('DOMAINE HELENA NOTEA', 'notea'),
    ('DOMAINE PLENIUM', 'plenium'),
    ('LE DOMAINE D EDOUARD', 'edouard'),
    ('CLOS SAINT PATRICE', 'saint patrice'),
    ('LA SOUSTO', 'sousto'),
    ('DOMAINE CHEVEAU ET GILLES', 'cheveau'),
    ('DOMAINE TINEL-BLONDELET', 'tinel'),
    ('MARIELLE MICHOT', 'michot'),
    ('LEAH ANGLES', 'angles'),
    ('DOMAINE VALLEE MORAY', 'moray'),
    ('MARIE THIBAULT', 'thibault'),
    ('LA CAVE DU VIEL ARMAND', 'armand'),
    ('DOMAINE ACHILLES', 'achilles'),
    ('DOMAINE SERES', 'seres'),
    ('COMTE DES CORNEILLES', 'corneilles'),
]

for raw_name, hint in header_producers:
    raw_norm = norm(raw_name)
    results = [(fuzz.token_sort_ratio(raw_norm, p[1]), p[0], p[2]) for p in db_producers if hint in p[1]]
    results.sort(reverse=True)
    top3 = sorted([(fuzz.token_sort_ratio(raw_norm, p[1]), p[0], p[2]) for p in db_producers], reverse=True)[:2]
    if results:
        print(f'{raw_name!r}: hint-match={results[:2]}, top2={top3}')
    else:
        print(f'{raw_name!r}: NO HINT MATCH, top2={top3}')

conn.close()
