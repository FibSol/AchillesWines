"""
import-pikowines-staging.py — ingest the Piko Wines price list (scraped HTML) into
the curated DB as DIMENSIONS + STAGING candidates (needs_review=1). Fact tables are
never touched; promotion is a separate, reviewed step.

Source: https://www.pikowines.com/en/price-list/  (saved HTML in raw/pikowines_pricelist.html)
Owner : pikowines retailer price list.

What it does (idempotent — re-runnable):
  1. ensure dim_source 'pikowines' (tier B_retailer).
  2. parse 126 sections. Producer-headed (Burgundy/Beaujolais/Rhône/Loire/…) vs
     appellation-headed Bordeaux sections (château is in the wine name).
  3. create/reuse dim_producer, dim_appellation (REUSE existing appellations by
     longest-prefix norm match to avoid pollution), dim_wine (compute_wine_key,
     best-effort colour inference).
  4. stage prices  -> staging_price_candidates  (amount EUR, retailer 'Piko Wines').
  5. stage ratings -> staging_rating_candidates  (RP->WA, VN->Vinous, JM->JMIB; JD skipped — not in enum).
  6. emit scripts/_pikowines_review.csv listing every created/matched wine for audit.

Nothing is promoted to fact_price / fact_rating.
"""
import sqlite3, re, csv, hashlib, sys
from datetime import datetime, timezone
from pathlib import Path
from selectolax.parser import HTMLParser
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scraper"))
from achilles_scraper.identity import (
    norm_text, normalize_producer, normalize_cuvee, compute_wine_key, clean_cuvee_display,
)

DB = "C:/Claude/achilles-wines/data/achilles.db"
HTML = "C:/Claude/achilles-wines/raw/pikowines_pricelist.html"
REVIEW_CSV = "C:/Claude/achilles-wines/scripts/_pikowines_review.csv"
BATCH = "pikowines_pricelist_20260615"
SOURCE_URL = "https://www.pikowines.com/en/price-list/"
RECORDED_AT = int(datetime(2026, 6, 15, tzinfo=timezone.utc).timestamp())

# Bordeaux sections whose heading is the APPELLATION (château is in the wine name)
APPEL_HEADINGS = {norm_text(x) for x in
    ["Pessac-Léognan", "Pomerol", "Saint-Estèphe", "Saint-Julien", "Sauternes - Barsac", "Autres Bordeaux"]}

# producers we know are non-French (best-effort; flagged in review CSV)
COUNTRY_BY_PRODUCER = {
    "breuer georg":"DE","busch clemens":"DE","haag fritz":"DE","kuhn peter jacob":"DE",
    "molitor markus":"DE","muller egon":"DE","van volxem":"DE",
    "isole e olena":"IT","la massa":"IT","vietti":"IT",
    "quinta da pellada":"PT","madeira antonio":"PT","dumol":"US","ridge":"US","musar":"LB",
}
CRITIC_MAP = {"RP":"WA","VN":"Vinous","JM":"JMIB"}   # JD (Jeb Dunnuck) has no enum slot -> skipped

SPARKLING = ("champagne","cremant","mousseux","blanc de blancs","blanc de noirs","extra brut")
SWEET     = ("sauternes","barsac","moelleux","liquoreux","vendanges tardives","grains nobles")
WHITE_APP = ("chablis","meursault","montrachet","puligny","saint aubin","macon","mâcon","pouilly",
             "vire clesse","viré clessé","savennieres","savennières","vouvray","montlouis","sancerre",
             "l etoile","etoile","chateau chalon","château chalon","riesling","muscadet")
WHITE_KW  = ("blanc","chardonnay","riesling","chenin","sauvignon","aligote","aligoté","viognier","roussanne","marsanne","clairette")
ROSE_KW   = ("rose","rosé","clairet","corail","tavel")

def infer_color(appellation, wine_name, producer):
    t = norm_text(f"{appellation} {wine_name} {producer}")
    if any(k in t for k in (norm_text(x) for x in SWEET)):      return "sweet"
    if "brut" in t or any(norm_text(x) in t for x in SPARKLING): return "sparkling"
    if any(norm_text(x) in t for x in ROSE_KW):                  return "rosé"
    if any(norm_text(x) in t for x in WHITE_APP) or any(norm_text(x) in t for x in WHITE_KW): return "white"
    return "red"

def bottle_ml(size):
    s = size.lower().replace(" ", "")
    if "x" in s: return None            # case pricing (e.g. 6x75cl) -> skip
    m = re.search(r"(\d+[.,]?\d*)cl", s)
    if m: return int(round(float(m.group(1).replace(",", ".")) * 10))
    return 750

def parse_vintage(v):
    m = re.search(r"(19|20)\d{2}", v or "")
    return int(m.group(0)) if m else None

def price_eur(s):
    m = re.search(r"(\d+[.,]?\d*)", (s or "").replace("€", ""))
    return float(m.group(1).replace(",", ".")) if m else None

def parse_ratings(note):
    out = []
    for m in re.finditer(r"(\d{2,3})(?:\s*-\s*(\d{2,3}))?\s*\+?\s*(VN|RP|JD|JM)", note or ""):
        lo, hi, code = m.group(1), m.group(2), m.group(3)
        score = round((int(lo)+int(hi))/2) if hi else int(lo)
        out.append((score, code))
    return out

# ── parse sections ──────────────────────────────────────────────────────────
tree = HTMLParser(Path(HTML).read_text(encoding="utf-8", errors="replace"))
body = tree.body or tree.root
sections, cur_h, cur = [], None, []
for node in body.traverse(include_text=False):
    if node.tag in ("h1","h2","h3","h4","h5","strong","b"):
        t = node.text(strip=True)
        if t and len(t) < 80:
            if cur_h is not None: sections.append((cur_h, cur))
            cur_h, cur = t, []
    elif node.tag == "table" and cur_h is not None:
        for tr in node.css("tr"):
            cs = [c.text(strip=True) for c in tr.css("td")]
            if len(cs) >= 6 and cs[0]:
                cur.append(cs)
if cur_h is not None: sections.append((cur_h, cur))

# ── DB ──────────────────────────────────────────────────────────────────────
db = sqlite3.connect(DB); db.execute("PRAGMA foreign_keys=ON"); cur_db = db.cursor()
def sc(q,*a):
    r = cur_db.execute(q,a).fetchone(); return r[0] if r else None

SRC = sc("SELECT source_key FROM dim_source WHERE source_code='pikowines'")
if not SRC:
    cur_db.execute("""INSERT INTO dim_source(source_code,source_name,source_tier,country_code,base_url,
                      license_class,cadence,enabled,notes)
                      VALUES('pikowines','Piko Wines (retailer price list)','B_retailer','BE',
                      'https://www.pikowines.com','public_check_terms','one_shot',1,
                      'Belgian fine-wine retailer; prices + retailer-listed critic scores')""")
    SRC = cur_db.lastrowid

# existing appellations for reuse: norm -> (key, region, country)
appel_rows = cur_db.execute("SELECT appellation_key,appellation_norm,region,country_code FROM dim_appellation").fetchall()
appel_by_norm = {r[1]:(r[0],r[2],r[3]) for r in appel_rows}
appel_norms_sorted = sorted(appel_by_norm.keys(), key=len, reverse=True)

def match_existing_appellation(wine_name_norm, country):
    for an in appel_norms_sorted:
        if len(an) >= 4 and (wine_name_norm == an or wine_name_norm.startswith(an + " ")):
            k, region, cc = appel_by_norm[an]
            if cc == country:
                return k, region
    return None, None

def ensure_producer(name, country):
    pnorm = normalize_producer(name)
    k = sc("SELECT producer_key FROM dim_producer WHERE producer_norm=? AND country_code=?", pnorm, country)
    if k: return k, False
    cur_db.execute("""INSERT INTO dim_producer(producer_name,producer_norm,country_code,status,coverage_tier,notes)
                      VALUES(?,?,?, 'active','long_tail', ?)""",
                   (name, pnorm, country, f"Piko price-list import {BATCH}"))
    return cur_db.lastrowid, True

def ensure_appellation(name, region, country, level):
    anorm = norm_text(re.sub(r"\b(aoc|aop|igp|igt|doc|docg|do|dop|vdp|vdf)\b","",norm_text(name)))
    if anorm in appel_by_norm and appel_by_norm[anorm][2]==country:
        return appel_by_norm[anorm][0], False
    cur_db.execute("""INSERT INTO dim_appellation(country_code,region,subregion,appellation_name,appellation_norm,level)
                      VALUES(?,?,?,?,?,?)""",(country, region or "Autre", None, name, anorm, level))
    k = cur_db.lastrowid
    appel_by_norm[anorm]=(k,region or "Autre",country)
    return k, True

def strip_organic(h):
    return re.sub(r"[\s,–-]*\b(bio|biodynamie|biodynamique|biodynamic)\b\s*$","",h,flags=re.I).strip(" ,-–")

def appellation_level(name):
    n = norm_text(name)
    if "grand cru" in n: return "grand_cru"
    if "premier cru" in n or re.search(r"\b1\s*er\b", n): return "premier_cru"
    if any(x in n for x in ("igp","igt","vin de france","vdf")): return "regional"
    return "village"

# idempotent: clear this batch from staging
cur_db.execute("DELETE FROM staging_price_candidates WHERE batch_id=?", (BATCH,))
cur_db.execute("DELETE FROM staging_rating_candidates WHERE batch_id=?", (BATCH,))

st = {k:0 for k in ["prices","ratings","ratings_jd_skipped","wines_new","wines_existing",
                    "producers_new","appellations_new","rows_skipped"]}
review = []

for heading, rows in sections:
    is_appel = norm_text(heading) in APPEL_HEADINGS
    for cs in rows:
        wine_name, vtg_s, _c2, size_s, note, price_s = cs[0], cs[1], cs[2], cs[3], cs[4], cs[5]
        ml = bottle_ml(size_s)
        price = price_eur(price_s)
        if ml is None or price is None:
            st["rows_skipped"] += 1; continue
        vintage = parse_vintage(vtg_s)
        is_nv = 0 if vintage else 1

        if is_appel:
            country = "FR"
            # producer = château up to a classification/appellation tail
            prod = re.split(r"\b(1\s*er\s+grand\s+cru|grand\s+cru\s+class|grand\s+cru|cru\s+bourgeois|premier\s+grand\s+cru)\b",
                            wine_name, flags=re.I)[0].strip()
            prod = re.sub(r"\b(fronsac|barsac|sauternes|pomerol|margaux|pauillac|pessac[- ]?l[ée]ognan|saint[- ][eé]?\w+)\s*$","",prod,flags=re.I).strip()
            producer_name = prod or wine_name
            appel_name = "Sauternes" if "sauterne" in norm_text(heading) else (
                         heading if norm_text(heading)!="autres bordeaux" else "Bordeaux")
            cuvee_raw = ""   # grand vin
        else:
            country = COUNTRY_BY_PRODUCER.get(normalize_producer(strip_organic(heading)), "FR")
            producer_name = strip_organic(heading)
            mk, mregion = match_existing_appellation(norm_text(wine_name), country)
            appel_name = None; appel_key_pre = mk; appel_region = mregion
            cuvee_raw = wine_name

        color = infer_color(appel_name or (appel_region or ""), wine_name, producer_name)

        pkey, pnew = ensure_producer(producer_name, country)
        if pnew: st["producers_new"] += 1

        # appellation
        if is_appel:
            akey, anew = ensure_appellation(appel_name, "Bordeaux", country, appellation_level(wine_name))
        elif appel_key_pre:
            akey = appel_key_pre; anew = False
        else:
            # fallback: first 2 tokens of wine_name as a pseudo-appellation
            guess = " ".join(wine_name.split()[:2])
            akey, anew = ensure_appellation(guess, None, country, appellation_level(wine_name))
        if anew: st["appellations_new"] += 1

        pnorm = normalize_producer(producer_name)
        anorm_for_cuvee = norm_text(appel_name) if is_appel else ""
        cnorm = normalize_cuvee(cuvee_raw, strip_words=[pnorm, anorm_for_cuvee]) if cuvee_raw else ""
        if not cnorm and cuvee_raw:
            cnorm = norm_text(cuvee_raw)
        wk = compute_wine_key(pnorm, cnorm, vintage, bottle_ml=ml)

        vtxt = f" {vintage}" if vintage else " NV"
        cuvee_disp = clean_cuvee_display(cuvee_raw, producer_name) if cuvee_raw else ""
        canonical = f"{producer_name} — {cuvee_disp}{vtxt}".replace("  ", " ").strip(" —")

        if sc("SELECT 1 FROM dim_wine WHERE wine_key=?", wk):
            st["wines_existing"] += 1
        else:
            cur_db.execute("""INSERT INTO dim_wine(wine_key,producer_key,appellation_key,cuvee_name,cuvee_norm,
                              color,vintage,is_non_vintage,bottle_ml,canonical_name)
                              VALUES(?,?,?,?,?,?,?,?,?,?)""",
                           (wk, pkey, akey, cuvee_disp or "(grand vin)", cnorm or "grand vin",
                            color, vintage, is_nv, ml, canonical))
            st["wines_new"] += 1

        # stage price
        chash = hashlib.sha1(f"piko|{wk}|{price}|{ml}".encode()).hexdigest()
        cur_db.execute("""INSERT OR IGNORE INTO staging_price_candidates(wine_key,source_key,retailer,recorded_at,
                          currency_code,amount_local,amount_eur,source_url,content_hash,batch_id,needs_review)
                          VALUES(?,?,?,?,?,?,?,?,?,?,1)""",
                       (wk, SRC, "Piko Wines", RECORDED_AT, "EUR", price, price, SOURCE_URL, chash, BATCH))
        st["prices"] += cur_db.rowcount

        # stage ratings
        for score, code in parse_ratings(note):
            if code == "JD":
                st["ratings_jd_skipped"] += 1; continue
            cc = CRITIC_MAP[code]
            rhash = hashlib.sha1(f"piko|{wk}|{cc}|{score}".encode()).hexdigest()
            cur_db.execute("""INSERT OR IGNORE INTO staging_rating_candidates(wine_key,source_key,critic_code,reviewer_type,
                              score,scale,score_normalized_100,rating_count,recorded_at,source_url,content_hash,batch_id,needs_review)
                              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1)""",
                           (wk, SRC, cc, "critic", float(score), "/100", float(score), None,
                            RECORDED_AT, SOURCE_URL, rhash, BATCH))
            st["ratings"] += cur_db.rowcount

        review.append({"section":heading,"is_appel_section":is_appel,"producer":producer_name,
                       "country":country,"appellation_key":akey,"cuvee":cuvee_disp,"color":color,
                       "vintage":vintage or "NV","bottle_ml":ml,"price_eur":price,"note":note,"wine_key":wk})

db.commit()

with open(REVIEW_CSV, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=list(review[0].keys())); w.writeheader(); w.writerows(review)

print("=== PIKO STAGING IMPORT DONE (facts untouched) ===")
for k,v in st.items(): print(f"  {k:22s} {v}")
print(f"\nstaging_price_candidates [{BATCH}] :", sc("SELECT COUNT(*) FROM staging_price_candidates WHERE batch_id=?",BATCH))
print(f"staging_rating_candidates [{BATCH}]:", sc("SELECT COUNT(*) FROM staging_rating_candidates WHERE batch_id=?",BATCH))
print("fact_price / fact_rating unchanged (no writes).")
print("review CSV:", REVIEW_CSV)
db.close()
