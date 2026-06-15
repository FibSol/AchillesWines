"""
enrich-cellar-completeness.py — fill safe, non-fabricated data gaps for wines
currently held in the cellar (cellar_inventory.qty > 0).

Idempotent. Two enrichments, both 0-credit / no external scraping except OSM geocode:
  1. classification = '1er Cru' where BOTH the cuvee name and the appellation say so
     (premier_cru level, or appellation+cuvee both contain '1er cru').
  2. producer latitude/longitude backfill for cellar producers missing geo —
     from the appellation centroid already in dim_appellation, else an OSM/Nominatim
     geocode of the appellation name. Coords are APPROXIMATE and flagged in
     dim_producer.notes with '[geo~approx <date>: <source>]'.

Deliberately NOT done (would fabricate or needs a decision):
  - alcohol_pct, grape varieties for sake / undocumented new-vintage wines
  - prices (CLAUDE.md rule 34: fact_price from scrapers only)
  - vintage ratings: data largely exists but needs a region-mapping layer
    (dim_appellation.region granularity vs fact_vintage_rating taxonomy) — app-wide.

Usage:  python scripts/enrich-cellar-completeness.py [--date YYYY-MM-DD]
"""
import sqlite3, json, time, sys, urllib.parse, urllib.request

DB = "C:/Claude/achilles-wines/data/achilles.db"
STAMP_DATE = "2026-06-15"
if "--date" in sys.argv:
    STAMP_DATE = sys.argv[sys.argv.index("--date") + 1]

c = sqlite3.connect(DB)
c.row_factory = sqlite3.Row
keys = [r[0] for r in c.execute("SELECT DISTINCT wine_key FROM cellar_inventory WHERE qty>0")]
ph = ",".join("?" * len(keys))

# ── 1. classification: 1er Cru (certain only) ───────────────────────────────
cands = c.execute(f"""
    SELECT dw.wine_key, dw.canonical_name
    FROM dim_wine dw JOIN dim_appellation da ON dw.appellation_key=da.appellation_key
    WHERE dw.wine_key IN ({ph})
      AND (dw.classification IS NULL OR dw.classification='')
      AND ( da.level='premier_cru'
            OR (LOWER(da.appellation_name) LIKE '%1er cru%' AND LOWER(dw.cuvee_name) LIKE '%1er cru%') )
""", keys).fetchall()
for r in cands:
    c.execute("UPDATE dim_wine SET classification='1er Cru' WHERE wine_key=?", (r["wine_key"],))
c.commit()
print(f"[1] classification '1er Cru' applied: {len(cands)}")
for r in cands:
    print(f"      {r['canonical_name']}")

# ── 2. producer geo backfill ────────────────────────────────────────────────
def geocode_osm(q):
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": q, "format": "json", "limit": 1})
    req = urllib.request.Request(url, headers={"User-Agent": "achilles-wines-cellar/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            d = json.load(resp)
        return (float(d[0]["lat"]), float(d[0]["lon"]), d[0].get("display_name", "")[:60]) if d else None
    except Exception as e:
        print(f"      OSM error for {q!r}: {e}")
        return None

OSM_OVERRIDE = {  # appellation/wine names that are not geocodable places
    "Amarone della Valpolicella": "Valpolicella, Veneto, Italy",
}

producers = {}
for r in c.execute(f"""
   SELECT dp.producer_key, dp.producer_name, dp.notes,
          da.appellation_name, da.country_code, da.latitude app_lat, da.longitude app_lon
   FROM dim_wine dw JOIN dim_producer dp ON dw.producer_key=dp.producer_key
   LEFT JOIN dim_appellation da ON dw.appellation_key=da.appellation_key
   WHERE dw.wine_key IN ({ph}) AND (dp.latitude IS NULL OR dp.longitude IS NULL)
""", keys):
    producers.setdefault(r["producer_key"], {"name": r["producer_name"], "notes": r["notes"], "apps": []})
    producers[r["producer_key"]]["apps"].append(
        (r["appellation_name"], r["country_code"], r["app_lat"], r["app_lon"]))

centroid = osm = skip = 0
for pk, p in producers.items():
    app_geo = next((a for a in p["apps"] if a[2] is not None), None)
    if app_geo:
        lat, lon, src = app_geo[2], app_geo[3], f"appellation centroid: {app_geo[0]}"
    else:
        app = p["apps"][0]
        q = OSM_OVERRIDE.get(app[0], f"{app[0]}, {app[1] or ''}".strip(", "))
        time.sleep(1.1)
        g = geocode_osm(q)
        if not g:
            skip += 1
            continue
        lat, lon, disp = g
        src = f"OSM geocode '{q}' -> {disp}"
    stamp = f"[geo~approx {STAMP_DATE}: {src}]"
    note = (p["notes"] or "")
    new_note = note if stamp in note else (note + " " + stamp).strip()
    c.execute("UPDATE dim_producer SET latitude=?, longitude=?, notes=? WHERE producer_key=?",
              (round(lat, 5), round(lon, 5), new_note, pk))
    if app_geo: centroid += 1
    else: osm += 1
c.commit()
print(f"[2] producer geo: centroid={centroid} osm={osm} skipped={skip}")

# ── final verification ──────────────────────────────────────────────────────
def miss(sql, *a):
    return c.execute(sql, a).fetchone()[0]
n = len(keys)
no_geo = miss(f"""SELECT COUNT(DISTINCT dw.wine_key) FROM dim_wine dw
   JOIN dim_producer dp ON dw.producer_key=dp.producer_key
   WHERE dw.wine_key IN ({ph}) AND (dp.latitude IS NULL OR dp.longitude IS NULL)""", *keys)
no_class = miss(f"""SELECT COUNT(*) FROM dim_wine dw JOIN dim_appellation da ON dw.appellation_key=da.appellation_key
   WHERE dw.wine_key IN ({ph}) AND (dw.classification IS NULL OR dw.classification='')
     AND (da.level='premier_cru' OR (LOWER(da.appellation_name) LIKE '%1er cru%' AND LOWER(dw.cuvee_name) LIKE '%1er cru%'))""", *keys)
print(f"\nVERIFY ({n} cellar wines): producer-geo missing={no_geo}  certain-classification missing={no_class}")
c.close()
