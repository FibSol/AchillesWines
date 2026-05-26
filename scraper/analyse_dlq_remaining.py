"""Analyse remaining unresolved RVF DLQ records to guide next batch."""
import sqlite3, json, unicodedata
from collections import Counter

def norm(s):
    s = unicodedata.normalize('NFKD', s or '').encode('ascii', 'ignore').decode()
    return s.lower().strip()

conn = sqlite3.connect('../data/achilles.db')
rows = conn.execute(
    "SELECT dlq_id, raw_record FROM ops_dead_letter "
    "WHERE source_key=52 AND error_class='unmatched_wine' "
    "AND (resolution IS NULL OR resolution='pending')"
).fetchall()
print(f"Total remaining: {len(rows)}")

# Categorise by pattern
ceqp = []    # cuvee == producer
header = []  # cuvee looks like appellation header
other = []

HEADER_NORMS = {norm(x) for x in [
    "Bourgogne", "Vin de France", "Languedoc", "Macon", "Macon et Macon-villages",
    "Chateauneuf-du-Pape", "Sancerre", "Pouilly-Fume", "Cotes du Rhone",
    "Cotes du Roussillon", "Arbois-Pupillin Rouge", "Madiran",
    "Pouilly-Fuisse", "Pouilly-Loche", "Chianti Classico", "Grand cru Clos",
    "Alsace", "Pomerol", "Saint-Emilion Grand Cru",
    "Margaux", "Saint-Julien", "Pessac-Leognan", "Sauternes", "Savoie",
    "Vallee de la Loire",
]}

prod_counter = Counter()

for dlq_id, raw in rows:
    try:
        r = json.loads(raw)
    except:
        continue
    p_n = norm(r.get('producer',''))
    c_n = norm(r.get('cuvee',''))
    if p_n == c_n:
        ceqp.append((dlq_id, r))
        prod_counter[p_n] += 1
    elif c_n in HEADER_NORMS:
        header.append((dlq_id, r))
    else:
        other.append((dlq_id, r))

print(f"  cuvee==producer: {len(ceqp)}")
print(f"  header cuvee:    {len(header)}")
print(f"  other:           {len(other)}")

print(f"\nTop 30 cuvee==producer producers (need online lookup):")
for pname, cnt in prod_counter.most_common(30):
    # Show one sample record
    for dlq_id, r in ceqp:
        if norm(r.get('producer','')) == pname:
            print(f"  x{cnt:2d}  {r.get('producer')!r:40s}  app={r.get('appellation')!r}")
            break

print(f"\nHeader-cuvee producers (no match at threshold 85+):")
header_prod = Counter()
for dlq_id, r in header:
    header_prod[norm(r.get('producer',''))] += 1
for pname, cnt in header_prod.most_common(20):
    for dlq_id, r in header:
        if norm(r.get('producer','')) == pname:
            print(f"  x{cnt:2d}  {r.get('producer')!r:40s}  cuvee={r.get('cuvee')!r}  app={r.get('appellation')!r}")
            break

if other:
    print(f"\nOther (sample 20):")
    other_prod = Counter()
    for dlq_id, r in other:
        other_prod[norm(r.get('producer',''))] += 1
    for pname, cnt in list(other_prod.most_common(20)):
        for dlq_id, r in other:
            if norm(r.get('producer','')) == pname:
                print(f"  x{cnt:2d}  {r.get('producer')!r:40s}  cuvee={r.get('cuvee')!r}  app={r.get('appellation')!r}")
                break

conn.close()
