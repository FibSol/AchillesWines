import sqlite3
conn = sqlite3.connect('../data/achilles.db')
# Get main Macon appellation key
for r in conn.execute("SELECT appellation_key, appellation_name FROM dim_appellation WHERE appellation_norm LIKE '%macon%' ORDER BY appellation_key LIMIT 5").fetchall():
    print(f'  {r[0]}: {r[1]!r}')
# Check Domaine Achillee for Alsace
from rapidfuzz import fuzz
import unicodedata
def norm(s):
    s = unicodedata.normalize('NFKD', s or '').encode('ascii', 'ignore').decode()
    return s.lower().strip()
db_producers = [(r[0], r[1], r[2]) for r in conn.execute('SELECT producer_key, producer_norm, producer_name FROM dim_producer').fetchall()]
for term in ['domaine achillee', 'achillee', 'achilles']:
    n = norm(term)
    top3 = sorted([(fuzz.token_sort_ratio(n, p[1]), p[0], p[2]) for p in db_producers if fuzz.token_sort_ratio(n, p[1]) > 70], reverse=True)[:3]
    if top3:
        print(f'{term}: {top3}')
conn.close()
