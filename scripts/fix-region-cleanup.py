"""
Region cleanup for dim_appellation.
Run from project root: python scripts/fix-region-cleanup.py
"""
import sqlite3

DB = "data/achilles.db"
conn = sqlite3.connect(DB)
c = conn.cursor()
c.execute("PRAGMA foreign_keys=OFF")

total = 0

def upd(sql, params=()):
    global total
    c.execute(sql, params)
    n = c.rowcount
    total += n
    return n

print("=== 1. Country-code fixes (no UNIQUE conflict) ===")
# These have no correct counterpart yet → safe to change country_code directly
for key, cc in [(527, 'ZA'), (545, 'ZA'), (283, 'CH'), (854, 'CH'), (421, 'CL'), (985, 'JP'), (2353, 'LT')]:
    n = upd("UPDATE dim_appellation SET country_code=? WHERE appellation_key=?", (cc, key))
    row = c.execute("SELECT appellation_name FROM dim_appellation WHERE appellation_key=?", (key,)).fetchone()
    print(f"  key={key} ({row[0] if row else '?'}) → {cc}: {n} row")

print()
print("=== 2. Constantia (558): re-link wines to correct ZA key 2550, then delete ===")
n = upd("UPDATE dim_wine SET appellation_key=2550 WHERE appellation_key=558")
print(f"  Re-linked {n} dim_wine rows to key 2550")
n = upd("DELETE FROM dim_appellation WHERE appellation_key=558")
print(f"  Deleted bad FR row: {n}")

print()
print("=== 3. Espagne catch-all (1131): re-link to a real ES appellation or just update country ===")
# No ZA/ES norm conflict check needed — appellation_norm='espagne' is unique to this row for ES
# But check first:
conflict = c.execute("SELECT appellation_key FROM dim_appellation WHERE country_code='ES' AND appellation_norm='espagne'").fetchone()
if conflict:
    n = upd("UPDATE dim_wine SET appellation_key=? WHERE appellation_key=1131", (conflict[0],))
    print(f"  Re-linked {n} wines to existing ES espagne key={conflict[0]}")
    n = upd("DELETE FROM dim_appellation WHERE appellation_key=1131")
    print(f"  Deleted duplicate: {n}")
else:
    n = upd("UPDATE dim_appellation SET country_code='ES' WHERE appellation_key=1131")
    print(f"  Changed country_code to ES: {n}")

print()
print("=== 4. Casing normalization (FR) ===")
for old, new in [("LANGUEDOC", "Languedoc"), ("PROVENCE", "Provence"), ("DIVERS", "Unknown")]:
    n = upd("UPDATE dim_appellation SET region=? WHERE region=? AND country_code='FR'", (new, old))
    if n: print(f"  {old!r} → {new!r}: {n} rows")

print()
print("=== 5. Languedoc variant consolidation ===")
n = upd("UPDATE dim_appellation SET region='Languedoc-Roussillon' WHERE region='Languedoc Roussillon' AND country_code='FR'")
print(f"  'Languedoc Roussillon' → 'Languedoc-Roussillon': {n} rows")

print()
print("=== 6. IT: Toscana → Toscane ===")
n = upd("UPDATE dim_appellation SET region='Toscane' WHERE region='Toscana' AND country_code='IT'")
print(f"  Toscana → Toscane: {n} rows")

print()
print("=== 7. Appellation names used as region → parent region ===")
mappings = [
    # Côte de Nuits
    ("Chambertin Grand Cru",              "Côte de Nuits",  "FR"),
    ("Chambertin-Clos-de-Bèze Grand Cru", "Côte de Nuits",  "FR"),
    ("Clos de Tart Grand Cru",            "Côte de Nuits",  "FR"),
    ("Clos de Vougeot Grand Cru",         "Côte de Nuits",  "FR"),
    ("Echezeaux Grand Cru",               "Côte de Nuits",  "FR"),
    ("Gevrey Chambertin 1er cru",         "Côte de Nuits",  "FR"),
    # Côte de Beaune
    ("Corton Grand Cru",                  "Côte de Beaune", "FR"),
    ("Beaune 1er cru",                    "Côte de Beaune", "FR"),
    ("Hautes Côtes de Beaune",            "Côte de Beaune", "FR"),
    ("Pernand-Vergelesses 1er Cru",       "Côte de Beaune", "FR"),
    # Bordeaux
    ("Bordeaux Blanc",                    "Bordeaux",       "FR"),
    ("Bordeaux Rosé",                     "Bordeaux",       "FR"),
    ("Cadillac - Côtes de Bordeaux",      "Bordeaux",       "FR"),
    ("Côtes de Bordeaux",                 "Bordeaux",       "FR"),
    ("Côtes de Castillon",                "Bordeaux",       "FR"),
    ("Saint-Emilion Grand Cru",           "Libournais",     "FR"),
    # Roussillon
    ("Banyuls",                           "Roussillon",     "FR"),
    ("Rivesaltes",                        "Roussillon",     "FR"),
    # Corse
    ("Figari",                            "Corse",          "FR"),
    # Sud-Ouest
    ("Agenais",                           "Sud-Ouest",      "FR"),
    ("Chalosse",                          "Sud-Ouest",      "FR"),
    ("Lot",                               "Sud-Ouest",      "FR"),
    ("Marcillac",                         "Sud-Ouest",      "FR"),
    ("Monbazillac",                       "Sud-Ouest",      "FR"),
    # Touraine
    ("St Nicolas de Bourgueil",           "Touraine",       "FR"),
    # Provence
    ("Palette",                           "Provence",       "FR"),
    ("Var",                               "Provence",       "FR"),
    # Rhône
    ("Collines Rhodaniennes",             "Côtes du Rhône", "FR"),
    # Vallée de la Loire
    ("Pays nantais",                      "Vallée de la Loire", "FR"),
    # Non-region values
    ("Vin Mousseux",                      "Unknown",        "FR"),
]

for old_region, new_region, cc in mappings:
    n = upd("UPDATE dim_appellation SET region=? WHERE region=? AND country_code=?",
            (new_region, old_region, cc))
    if n:
        print(f"  {old_region!r} → {new_region!r}: {n} rows")

conn.commit()
conn.close()
print(f"\n✓ Done — {total} total rows updated")
