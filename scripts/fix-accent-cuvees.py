"""
Fix the 4 confirmed accent-difference cuvée name pairs.
Each pair has one row with missing/wrong accent and one with correct.
We update the bad-accent cuvee_name to match the correct one
(wine_key is left unchanged — a separate dedup pass is needed to merge rows).

Run with --dry-run to preview.
"""
import sys
import sqlite3
from pathlib import Path

DRY_RUN = "--dry-run" in sys.argv
DB_PATH = Path(__file__).parent.parent / "data" / "achilles.db"

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# Manual list of (producer_key, bad_cuvee_name, canonical_cuvee_name)
# Determined from audit-similarity analysis.
FIXES = [
    # Château Angélus: "Angelus" → "Angélus"
    (449, "Le Carillon d'Angelus",  "Le Carillon d'Angélus"),
    (449, "Tempo d'Angelus",        "Tempo d'Angélus"),
    # Château Néni
    (6389, "Fugue de Nenin",        "Fugue de Néni"),
    # Château Pavie
    (448,  "Aromes de Pavie",       "Arômes de Pavie"),
    # Jean-Luc Colombo
    (2725, "Terres Brulees",        "Terres Brûlées"),
    (2725, "Terres Brulées",   "Terres Brûlées"),  # mixed partial accent
]

updates = []
for pk, bad, good in FIXES:
    cur.execute(
        "SELECT wine_key, cuvee_name, canonical_name FROM dim_wine WHERE producer_key=? AND cuvee_name=?",
        (pk, bad),
    )
    rows = cur.fetchall()
    for wk, cn, canon in rows:
        if cn == good:
            continue
        # Fix cuvee_name and also update canonical_name if it contains the bad form
        new_canon = canon.replace(bad, good) if canon and bad in canon else canon
        updates.append((wk, cn, good, canon, new_canon))

print(f"Found {len(updates)} rows to fix:")
for wk, old_cn, new_cn, old_ca, new_ca in updates:
    print(f"  [{wk}]  cuvee_name: {old_cn!r}  ->  {new_cn!r}")
    if old_ca != new_ca:
        print(f"         canonical:  {old_ca!r}  ->  {new_ca!r}")

if not DRY_RUN and updates:
    for wk, _, new_cn, _, new_ca in updates:
        cur.execute("UPDATE dim_wine SET cuvee_name=?, canonical_name=? WHERE wine_key=?",
                    (new_cn, new_ca, wk))
    conn.commit()
    print(f"\nApplied {len(updates)} fixes.")
else:
    print("\n[dry-run] No changes written." if DRY_RUN else "\nNo fixes needed.")

conn.close()
