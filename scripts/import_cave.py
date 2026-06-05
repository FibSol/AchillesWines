"""
Idempotent loader for the personal cave file (achille_wines_caveAvecPrix).
Loads: missing producers, appellations, varieties, the 86 wines, researched
ratings (verified + estimation), and cellar inventory.

Re-runnable: producers/appellations/varieties/wines are upserted by natural key;
ratings for BATCH_ID are deleted+reinserted; inventory is upserted by
(wine_key, location_id).

Owner: cave import (manual research). Source provenance:
  - cave_research  : verified ratings found via web research (critic_code = real critic)
  - cave_estimate  : reasoned aggregate estimations (critic_code 'VI', user_aggregate)
"""
import sqlite3, json, re, unicodedata, hashlib, sys, os
sys.stdout.reconfigure(encoding="utf-8")

DB = r"C:\Claude\achilles-wines\data\achilles.db"
BATCH_ID = "cave_manual_import_20260605"
RDIR = r"C:\Claude\achilles-wines\scripts\research"

# ---------------------------------------------------------------- identity (mirror lib/identity.ts)
def norm_text(s):
    if not s: return ""
    out = "".join(c for c in unicodedata.normalize("NFKD", str(s)) if not unicodedata.combining(c))
    out = out.lower()
    out = re.sub(r"[,.'\"/\-()\[\]_&+]", " ", out)
    return re.sub(r"\s+", " ", out).strip()

def normalize_producer(name):
    n = re.sub(r"\b(19|20)\d{2}\b", " ", norm_text(name))
    n = re.sub(r"\s+", " ", n).strip()
    for pat, repl in [(r"^d\s+", "domaine "), (r"^dom\s+", "domaine "), (r"^ch\s+", "chateau ")]:
        if re.match(pat, n):
            n = re.sub(pat, repl, n); break
    return n

CUVEE_TAILS = [
    r"\b1\s*er\s+(grand\s+)?cru(\s+classe)?\b",
    r"\b[2-5](\s*e|eme|ème)\s+cru(\s+classe)?\b",
    r"\bgrand\s+cru(\s+classe)?\b",
    r"\b(19|20)\d{2}\b",
    r"\b\d+\s*ml\b", r"\b\d+\s*cl\b",
    r"\b(magnum|jeroboam|mathusalem|salmanazar|balthazar|nabuchodonosor)\b",
]
def clean_cuvee_tails(n):
    for pat in CUVEE_TAILS:
        n = re.sub(pat, " ", n)
    return re.sub(r"\s+", " ", n).strip()

def normalize_cuvee(name, strip_words=None):
    base = norm_text(name)
    for w in (strip_words or []):
        if w:
            base = re.sub(rf"\b{re.escape(w)}\b", " ", base)
    base = re.sub(r"\s+", " ", base).strip()
    return clean_cuvee_tails(base)

def strip_appellation_suffix(name):
    n = norm_text(name)
    n = re.sub(r"\b(aoc|aop|aoc?p|igp|igt|doc|docg|do|dop|vdp|vdf)\b", " ", n)
    n = re.sub(r"\bappellation( d origine)?( controlee| protegee)?\b", " ", n)
    return re.sub(r"\s+", " ", n).strip()

def wine_key(producer_norm, cuvee_norm, vintage, bottle_ml=750):
    v = "NV" if vintage is None else str(vintage)
    raw = f"{producer_norm}|{cuvee_norm}|{v}|{bottle_ml}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]

COUNTRY = {"France":"FR","Italie":"IT","Japon":"JP","Portugal":"PT","Roumanie":"RO"}

def map_color(cave_color, appellation):
    a = norm_text(appellation)
    if any(x in a for x in ["champagne","cremant","prosecco","cava","franciacorta","sekt","spumante"]):
        return "sparkling"
    c = (cave_color or "").lower()
    if c.startswith("roug"): return "red"
    if c.startswith("ros"):  return "rosé"
    if c.startswith("blan"): return "white"
    if c == "sake":          return "white"
    return "white"

def appellation_level(name):
    n = norm_text(name)
    if "grand cru" in n: return "grand_cru"
    if "premier cru" in n or re.search(r"\b1\s*er\b", n): return "premier_cru"
    if any(x in n for x in ["igp","igt","vin de france","vdf"]): return "regional"
    return "village"

def norm_score_100(scale, score, critic_code):
    if score is None: return None
    if scale == "/100": v = score
    elif scale == "/20": v = score/20*100
    elif scale == "/5":  v = score/5*100
    elif scale == "stars":
        v = score/3*100 if critic_code == "Hachette" else score/5*100
    else: v = score
    return max(0.0, min(100.0, round(v, 1)))

AGG_CODES = {"VI","CT","XW"}

# ---------------------------------------------------------------- load inputs
cave = json.load(open(r"C:\Claude\achilles-wines\scripts\_cave.json", encoding="utf-8"))
pmap = json.load(open(r"C:\Claude\achilles-wines\scripts\_producer_map.json", encoding="utf-8"))
merged = json.load(open(os.path.join(RDIR, "_merged.json"), encoding="utf-8"))  # keyed by str(id)

db = sqlite3.connect(DB)
db.execute("PRAGMA foreign_keys=ON")
cur = db.cursor()

def scalar(q, *a):
    r = cur.execute(q, a).fetchone()
    return r[0] if r else None

stats = {k:0 for k in ["sources","producers_new","producers_existing","appellations_new",
                       "varieties_new","wines_new","wines_existing","ratings","inventory"]}

# ---------------------------------------------------------------- 1. sources
def ensure_source(code, name, tier):
    k = scalar("SELECT source_key FROM dim_source WHERE source_code=?", code)
    if k: return k
    cur.execute("""INSERT INTO dim_source(source_code,source_name,source_tier,cadence,enabled,notes)
                   VALUES(?,?,?,?,1,?)""",
                (code, name, tier, "one_shot", "Personal cave import (manual web research)"))
    stats["sources"] += 1
    return cur.lastrowid

SRC_RESEARCH = ensure_source("cave_research", "Achilles Cave — recherche manuelle (web)", "E_press_critic")
SRC_ESTIMATE = ensure_source("cave_estimate", "Achilles Cave — estimation agrégée", "D_user_aggregate")

# ---------------------------------------------------------------- 2. producers
ALIAS_EXTRA = {
    "Domaine de l'Olive (G. Jacumin)": ["Domaine L'Or de Line", "Or de Line", "Domaine de l'Olive"],
}
producer_key_by_name = {}   # cave producer name -> producer_key
for name, mapped in pmap.items():
    if isinstance(mapped, int):
        producer_key_by_name[name] = mapped
        stats["producers_existing"] += 1
        continue
    # NEW: find enrichment from any wine row with this producer
    enr = None
    for d_i, d in enumerate(cave):
        if d["producer"] == name:
            e = merged.get(str(d_i), {}).get("producer_enrichment")
            if e: enr = e; break
    cc = (enr or {}).get("producer_country_code") or COUNTRY.get(
        next((d["country"] for d in cave if d["producer"]==name), "France"), "FR")
    pnorm = normalize_producer(name)
    existing = scalar("SELECT producer_key FROM dim_producer WHERE producer_norm=? AND country_code=?", pnorm, cc)
    if existing:
        producer_key_by_name[name] = existing
        stats["producers_existing"] += 1
        continue
    aliases = ALIAS_EXTRA.get(name, [])
    cur.execute("""INSERT INTO dim_producer
        (producer_name,producer_norm,country_code,region,subregion,allowed_appellations,aliases,
         website,latitude,longitude,status,notes,coverage_tier)
        VALUES(?,?,?,?,?,?,?,?,?,?, 'active', ?, 'long_tail')""",
        (name, pnorm, cc, (enr or {}).get("producer_region"), (enr or {}).get("producer_subregion"),
         "[]", json.dumps(aliases, ensure_ascii=False),
         (enr or {}).get("producer_website"), (enr or {}).get("producer_latitude"),
         (enr or {}).get("producer_longitude"),
         "Cave import. " + ((enr or {}).get("producer_notes") or "")))
    producer_key_by_name[name] = cur.lastrowid
    stats["producers_new"] += 1

# ---------------------------------------------------------------- 3. appellations
appellation_key_cache = {}
def resolve_appellation(country_name, appellation_name, region):
    cc = COUNTRY.get(country_name, "FR")
    anorm = strip_appellation_suffix(appellation_name)
    key = (cc, anorm)
    if key in appellation_key_cache:
        return appellation_key_cache[key]
    k = scalar("SELECT appellation_key FROM dim_appellation WHERE country_code=? AND appellation_norm=?", cc, anorm)
    if not k:
        cur.execute("""INSERT INTO dim_appellation
            (country_code,region,subregion,appellation_name,appellation_norm,level)
            VALUES(?,?,?,?,?,?)""",
            (cc, region or "Autre", None, appellation_name, anorm, appellation_level(appellation_name)))
        k = cur.lastrowid
        stats["appellations_new"] += 1
    appellation_key_cache[key] = k
    return k

# ---------------------------------------------------------------- 4. varieties
variety_key_cache = {}
def resolve_variety(vname, wine_color):
    vnorm = norm_text(vname)
    if not vnorm: return None
    if vnorm in variety_key_cache: return variety_key_cache[vnorm]
    k = scalar("SELECT variety_key FROM dim_variety WHERE variety_norm=?", vnorm)
    if not k:
        fam = {"red":"red","white":"white","rosé":"red","sparkling":"white"}.get(wine_color, "other")
        cur.execute("INSERT INTO dim_variety(variety_name,variety_norm,color_family) VALUES(?,?,?)",
                    (vname.strip(), vnorm, fam))
        k = cur.lastrowid
        stats["varieties_new"] += 1
    variety_key_cache[vnorm] = k
    return k

def parse_grapes(s):
    """Return list of (variety_name, share_pct|None)."""
    if not s: return []
    out = []
    for part in re.split(r"[,/;]", s):
        part = part.strip()
        if not part: continue
        m = re.search(r"(\d+(?:[.,]\d+)?)\s*%", part)
        share = float(m.group(1).replace(",", ".")) if m else None
        nm = re.sub(r"\(.*?\)", "", part)
        nm = re.sub(r"\d+(?:[.,]\d+)?\s*%", "", nm).strip()
        nm = re.sub(r"\s+", " ", nm)
        # drop generic/blend words
        if nm.lower() in ("assemblage", "assemblage rose", "rose", "a confirmer", ""):
            continue
        if nm: out.append((nm, share))
    return out

# ---------------------------------------------------------------- 5/6/7/8 wines, ratings, varieties, inventory
# delete prior ratings for this batch (idempotent)
cur.execute("DELETE FROM fact_rating WHERE batch_id=?", (BATCH_ID,))

inv_agg = {}  # (wine_key, location_id) -> [qty, price]
for i, d in enumerate(cave):
    pkey = producer_key_by_name[d["producer"]]
    color = map_color(d["color"], d["appellation"])
    # vintage / NV
    vtg_raw = d["vintage"]
    if vtg_raw is None or (isinstance(vtg_raw, str) and not str(vtg_raw).strip().isdigit()):
        vintage, is_nv = None, 1
    else:
        vintage, is_nv = int(vtg_raw), 0
    bottle_ml = int(d["format_ml"])
    pnorm = normalize_producer(d["producer"])
    anorm = strip_appellation_suffix(d["appellation"])
    cnorm = normalize_cuvee(d["wine_name"], strip_words=[pnorm, anorm])
    if not cnorm:
        cnorm = norm_text(d["wine_name"]) or "cuvee"
    wk = wine_key(pnorm, cnorm, vintage, bottle_ml)
    appk = resolve_appellation(d["country"], d["appellation"], d["region"])

    e = merged.get(str(i), {})
    abv = e.get("abv_pct") if e.get("abv_pct") is not None else d.get("abv_pct")
    vtxt = f" {vintage}" if vintage else (" NV" if is_nv else "")
    canonical = f"{d['producer']} — {d['wine_name']}{vtxt}".strip()

    existing_wine = scalar("SELECT wine_key FROM dim_wine WHERE wine_key=?", wk)
    if existing_wine:
        cur.execute("UPDATE dim_wine SET alcohol_pct=COALESCE(alcohol_pct,?), last_seen_at=unixepoch() WHERE wine_key=?",
                    (abv, wk))
        stats["wines_existing"] += 1
    else:
        cur.execute("""INSERT INTO dim_wine
            (wine_key,producer_key,appellation_key,cuvee_name,cuvee_norm,color,vintage,is_non_vintage,
             bottle_ml,alcohol_pct,canonical_name)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (wk, pkey, appk, d["wine_name"], cnorm, color, vintage, is_nv, bottle_ml, abv, canonical))
        stats["wines_new"] += 1

    # varieties (skip sake)
    if d["color"].lower() != "sake":
        for vname, share in parse_grapes(d["grape_varieties"]):
            vk = resolve_variety(vname, color)
            if vk:
                cur.execute("""INSERT OR IGNORE INTO bridge_wine_variety(wine_key,variety_key,share_pct,source_confidence)
                               VALUES(?,?,?,?)""", (wk, vk, share, 0.8))

    # ratings
    for r in (e.get("ratings") or []):
        cc = r.get("critic_code"); scale = r.get("scale"); score = r.get("score")
        if cc is None or scale is None or score is None: continue
        kind = r.get("kind", "verified")
        src = SRC_ESTIMATE if kind == "estimation" else SRC_RESEARCH
        rtype = "user_aggregate" if cc in AGG_CODES else "critic"
        n100 = norm_score_100(scale, score, cc)
        if n100 is None: continue
        chash = ("estimation: " + (r.get("estimation_reason") or "")) if kind=="estimation" else None
        cur.execute("""INSERT INTO fact_rating
            (wine_key,source_key,critic_code,reviewer_type,score,scale,score_normalized_100,
             rating_count,source_url,content_hash,batch_id)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (wk, src, cc, rtype, float(score), scale, n100, r.get("rating_count"),
             r.get("source_url"), chash, BATCH_ID))
        stats["ratings"] += 1

    # inventory
    m = re.match(r"Stockage\s+(\d+)", str(d["storage_zone"]))
    loc = int(m.group(1)) if m else None
    if loc:
        agg = inv_agg.setdefault((wk, loc), [0, None, d.get("notes")])
        agg[0] += int(d["quantity"])
        if d.get("purchase_price_eur") is not None:
            agg[1] = d["purchase_price_eur"]

# write inventory (upsert by wine_key, location_id)
for (wk, loc), (qty, price, notes) in inv_agg.items():
    exist = scalar("SELECT inventory_id FROM cellar_inventory WHERE wine_key=? AND location_id=?", wk, loc)
    if exist:
        cur.execute("""UPDATE cellar_inventory SET qty=?, purchase_price_eur=COALESCE(?,purchase_price_eur),
                       notes=COALESCE(notes,?) WHERE inventory_id=?""", (qty, price, notes, exist))
    else:
        cur.execute("""INSERT INTO cellar_inventory(wine_key,location_id,qty,purchase_price_eur,purchase_source,notes)
                       VALUES(?,?,?,?,?,?)""", (wk, loc, qty, price, "Cave import", notes))
    stats["inventory"] += 1

db.commit()
print("=== IMPORT DONE ===")
for k, v in stats.items():
    print(f"  {k:22s} {v}")
print("\nfact_rating for batch:", scalar("SELECT COUNT(*) FROM fact_rating WHERE batch_id=?", BATCH_ID))
print("cellar_inventory total:", scalar("SELECT COUNT(*) FROM cellar_inventory"))
db.close()
