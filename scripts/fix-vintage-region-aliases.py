"""
fix-vintage-region-aliases.py — normalize a small, high-confidence set of
non-canonical dim_appellation.region values to the canonical region taxonomy
used by fact_vintage_rating / seed_vintage_ratings.mjs, so wines inherit the
existing regional vintage scores (vintages page heatmap + per-wine).

Scope: the regions that actually block cellar wines from matching a vintage
rating. These region values are unambiguously wrong (an appellation/cru name or
a plural/Anglo spelling), so the remap is globally correct, not cellar-only.
The broader ~1900-appellation region cleanup is tracked separately.

Idempotent (UPDATE by region value). 0 external calls. Touches dim_appellation
only; fact_vintage_rating is never modified.

Usage: python scripts/fix-vintage-region-aliases.py
"""
import sqlite3

DB = "C:/Claude/achilles-wines/data/achilles.db"

# non-canonical region  ->  canonical region (as used in fact_vintage_rating)
ALIAS = {
    "Mercurey 1er cru":              "Côte Chalonnaise",
    "Rully 1er cru":                 "Côte Chalonnaise",
    "Pouilly-Fuissé 1er Cru":        "Mâconnais",
    "Savigny Les Beaune 1er Cru":    "Côte de Beaune",
    "Savigny-lès-Beaune":            "Côte de Beaune",
    "Côtes du Rhône Septentrionales":"Rhône Nord",
    "Côtes du Rhône Méridionales":   "Rhône Sud",
    "Côtes du Rhône":                "Rhône Sud",
    "Ventoux":                       "Rhône Sud",
    "Vallée de la Loire":            "Loire",
    "Val de Loire":                  "Loire",
    "Touraine":                      "Loire",
    "Saumurois":                     "Loire",
    "Centre":                        "Loire",
    "Pays d'Oc":                     "Languedoc",
    "Côtes de Gascogne":             "Sud-Ouest",
}

c = sqlite3.connect(DB); c.row_factory = sqlite3.Row

def region_count_with_wines():
    return c.execute("""SELECT COUNT(DISTINCT da.region) FROM dim_appellation da
        WHERE EXISTS (SELECT 1 FROM dim_wine dw WHERE dw.appellation_key=da.appellation_key)""").fetchone()[0]

keys = [r[0] for r in c.execute("SELECT DISTINCT wine_key FROM cellar_inventory WHERE qty>0")]
def cellar_vr_coverage():
    n = 0
    for k in keys:
        w = c.execute("""SELECT dw.vintage, da.region FROM dim_wine dw
            LEFT JOIN dim_appellation da ON dw.appellation_key=da.appellation_key WHERE dw.wine_key=?""",(k,)).fetchone()
        if w["region"] and w["vintage"] and c.execute(
            "SELECT EXISTS(SELECT 1 FROM fact_vintage_rating WHERE region=? AND vintage=?)",
            (w["region"], w["vintage"])).fetchone()[0]:
            n += 1
    return n

before_regions, before_cov = region_count_with_wines(), cellar_vr_coverage()
fvr_before = c.execute("SELECT COUNT(*) FROM fact_vintage_rating").fetchone()[0]

changed = 0
for bad, good in ALIAS.items():
    cur = c.execute("UPDATE dim_appellation SET region=? WHERE region=?", (good, bad))
    changed += cur.rowcount
c.commit()

after_regions, after_cov = region_count_with_wines(), cellar_vr_coverage()
fvr_after = c.execute("SELECT COUNT(*) FROM fact_vintage_rating").fetchone()[0]

print(f"appellations remapped         : {changed}")
print(f"distinct regions (with wines) : {before_regions} -> {after_regions}  (merged {before_regions-after_regions})")
print(f"cellar vintage-rating coverage: {before_cov}/81 -> {after_cov}/81")
print(f"fact_vintage_rating rows       : {fvr_before} -> {fvr_after}  (must be unchanged)")
assert fvr_before == fvr_after, "fact_vintage_rating must not change"
# all alias targets must be canonical regions that actually carry scores
for good in set(ALIAS.values()):
    has = c.execute("SELECT EXISTS(SELECT 1 FROM fact_vintage_rating WHERE region=?)",(good,)).fetchone()[0]
    print(f"   target {good!r:22s} has vintage data: {bool(has)}")
c.close()
