"""Check which batch5 producers exist in dim_producer."""
import sqlite3, unicodedata
from rapidfuzz import fuzz

def norm(s):
    s = unicodedata.normalize('NFKD', s or '').encode('ascii', 'ignore').decode()
    return s.lower().strip()

conn = sqlite3.connect('../data/achilles.db')
db_producers = [(r[0], r[1], r[2]) for r in conn.execute(
    'SELECT producer_key, producer_norm, producer_name FROM dim_producer'
).fetchall()]

searches = [
    # (search_term, hint_word, notes)
    ('Camille Cayran', 'cayran', 'Cave de Cairanne cooperative'),
    ('Les Vignerons des 4 Chemins', 'chemins', 'Laudun cooperative'),
    ('Les Vignerons d Ajaccio', 'ajaccio', 'Ajaccio cooperative'),
    ('Fabien Duveau', 'duveau', 'Saumur-Champigny estate'),
    ('Christophe Avi', 'avi', 'Buzet/Brulhois estate'),
    ('Domaine de Bonnefil', 'bonnefil', 'Gaillac (already created)'),
    ('Leo de Prades', 'prades', 'Saint-Estephe cooperative label'),
    ('Tutiac', 'tutiac', 'Bordeaux cooperative (Turtac OCR)'),
    ('Cave des Demoiselles', 'demoiselles', 'Corbieres'),
    ('Cellier des Demoiselles', 'demoiselles', 'Corbieres alt name'),
    ('Cave de Castelmaure', 'castelmaure', 'Corbieres cooperative'),
    ('Castelmaure', 'castelmaure', 'Corbieres alt'),
    ('Cave de Saint Chinian', 'chinian', 'Saint-Chinian cooperative'),
    ('Cave Anne de Joyeuse', 'joyeuse', 'Languedoc cooperative'),
    ('La Romaine', 'romaine', 'Gigondas cooperative Vaison'),
    ('Cave La Romaine', 'romaine', 'Gigondas cooperative alt name'),
    ('Terres Secretes', 'terres', 'Saint-Veran cooperative'),
    ('Vignerons des Terres Secretes', 'terres', 'Saint-Veran alt'),
]

for search_term, hint, notes in searches:
    search_n = norm(search_term)
    hint_n = norm(hint)
    # Hint search first
    hint_matches = [(fuzz.token_sort_ratio(search_n, p[1]), p[0], p[2]) for p in db_producers if hint_n in p[1]]
    hint_matches.sort(reverse=True)
    top2 = sorted([(fuzz.token_sort_ratio(search_n, p[1]), p[0], p[2]) for p in db_producers], reverse=True)[:2]
    if hint_matches:
        best = hint_matches[0]
        status = "FOUND" if best[0] >= 85 else f"LOW({best[0]:.0f}%)"
        print(f"[{status}] {search_term!r} [{notes}]")
        print(f"  hint: {hint_matches[:2]}")
    else:
        print(f"[NO HINT] {search_term!r} [{notes}]")
        print(f"  top2: {top2}")

# Also check appellation keys
print('\nAppellation keys needed:')
for app_name in ['Saumur-Champigny', 'Buzet', 'Saint-Estephe', 'Corbieres', 'Saint-Chinian', 'Languedoc', 'Gigondas', 'Saint-Veran', 'Cairanne']:
    row = conn.execute(
        "SELECT appellation_key, appellation_name FROM dim_appellation WHERE appellation_norm LIKE ? LIMIT 1",
        (f'%{norm(app_name)}%',)
    ).fetchone()
    if row:
        print(f"  {app_name}: key={row[0]} ({row[1]!r})")
    else:
        print(f"  {app_name}: NOT FOUND")

conn.close()
