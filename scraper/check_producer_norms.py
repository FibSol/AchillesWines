import sqlite3, unicodedata
from rapidfuzz import fuzz

def norm(s):
    s = unicodedata.normalize('NFKD', s or '').encode('ascii', 'ignore').decode()
    return s.lower().strip()

conn = sqlite3.connect('../data/achilles.db')

# Check stored norms for specific producers
keys_to_check = [
    (647, 'Domaine Olivier Pithon', 'OLIVIER PITHON'),
    (58937, 'Domaine Roland Van Hecke', 'ROLAND VAN HECKE'),
    (6989, 'Chateau Prieure-Lichine', 'CHATEAU PRIEURE-LICHINE'),
    (48080, 'Domaine Tinel-Blondelet', 'DOMAINE TINEL-BLONDELET'),
    (58174, 'Dagueneau (Didier/Louis-Benjamin)', 'DOMAINE LOUIS-BENJAMIN DAGUENEAU'),
    (8402, 'Cave du Viel Armand', 'LA CAVE DU VIEL ARMAND'),
    (3360, "Domaine d'Edouard", "LE DOMAINE D EDOUARD"),
]

for pk, label, dlq_name in keys_to_check:
    row = conn.execute(
        "SELECT producer_key, producer_name, producer_norm FROM dim_producer WHERE producer_key=?", (pk,)
    ).fetchone()
    if row:
        stored_norm = row[2]
        computed_norm = norm(row[1])
        dlq_norm = norm(dlq_name)
        score = fuzz.token_sort_ratio(dlq_norm, stored_norm)
        same = stored_norm == computed_norm
        print(f"pk={pk} {label!r}")
        print(f"  stored_norm=    {stored_norm!r}")
        print(f"  computed_norm=  {computed_norm!r}")
        print(f"  dlq_norm=       {dlq_norm!r}")
        print(f"  score={score:.1f}%  norm_consistent={same}")
    else:
        print(f"pk={pk}: NOT FOUND")

conn.close()
