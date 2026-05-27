import sqlite3, unicodedata
from rapidfuzz import fuzz

def norm(s):
    s = unicodedata.normalize('NFKD', s or '').encode('ascii', 'ignore').decode()
    return s.lower().strip()

conn = sqlite3.connect('../data/achilles.db')

# Check stored norms for batch6 producers
keys = [
    (37476, 'Vignerons de Buxy', 'VIGNERONS DE BUKY'),
    (5051, 'Chateau Lafleur', 'CHATEAU LAFFEUR'),
    (451, 'Chateau Belair-Monange', 'CHATEAU BELAIR-MONANGE'),
    (3713, 'Chateau Franc Baudron', 'CHATEAU FRANC-BAUDRON'),
    (2667, 'La Clotte-Cazalis', 'CHATEAU LA CLOTTE-CAZALIS'),
    (8692, 'Domaine Ourry-Schreiber', 'DOMAINE OURY-SCHREIBER'),
]
for pk, label, dlq_name in keys:
    row = conn.execute(
        "SELECT producer_key, producer_name, producer_norm FROM dim_producer WHERE producer_key=?", (pk,)
    ).fetchone()
    if row:
        stored = row[2]
        dlq_n = norm(dlq_name)
        score = fuzz.token_sort_ratio(dlq_n, stored)
        print(f"pk={pk} {label!r}")
        print(f"  stored_norm = {stored!r}")
        print(f"  dlq_norm    = {dlq_n!r}")
        print(f"  score       = {score:.1f}%")
    else:
        print(f"pk={pk}: NOT FOUND")

# Appellation keys needed
print('\nAppellation keys:')
for search in ['saint emilion', 'fronsac', 'pomerol', 'belair']:
    rows = conn.execute(
        "SELECT appellation_key, appellation_name FROM dim_appellation WHERE appellation_norm LIKE ? ORDER BY appellation_key LIMIT 2",
        (f'%{search}%',)
    ).fetchall()
    print(f'{search}: {[(r[0], r[1]) for r in rows]}')

conn.close()
