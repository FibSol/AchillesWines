"""
Targeted price corrections for top-50 wines that had wrong matches or missing prices.
Runs firecrawl with precise queries and updates rvf_prices_master.json.
"""
import json, re, subprocess, time
from pathlib import Path

DATA_DIR   = Path(__file__).parent / "raw" / "rvf_pages"
MASTER     = DATA_DIR / "rvf_prices_master.json"
FIRECRAWL  = r"C:\Users\Nicolas\AppData\Roaming\npm\firecrawl.ps1"

master = json.loads(MASTER.read_text(encoding="utf-8"))

def ascii_q(q):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", q) if unicodedata.category(c) != "Mn")

def search(query):
    safe = ascii_q(query).replace("'","").replace('"','')
    ps   = f"& '{FIRECRAWL}' search '{safe}' --limit 3 --json"
    try:
        r = subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-Command",ps],
                           capture_output=True, text=True, timeout=90, encoding="utf-8", errors="replace")
        out = r.stdout.strip()
        start = out.find('{')
        return json.loads(out[start:]) if start != -1 else None
    except Exception:
        return None

def parse_price(text):
    m = re.search(r'€([\d][,\d]*(?:\.\d+)?)', text)
    if m:
        try:
            v = float(m.group(1).replace(",",""))
            return f"€{int(v)}", "EUR"
        except: pass
    m = re.search(r'Avg Price[^$€]*\$([\d,]+(?:\.\d+)?)', text)
    if m:
        try:
            return f"€{int(float(m.group(1).replace(',','')) * 0.93)}", "USD"
        except: pass
    m = re.search(r'\$([\d,]+(?:\.\d+)?)', text)
    if m:
        try:
            v = float(m.group(1).replace(",",""))
            if v > 5:
                return f"€{int(v * 0.93)}", "USD"
        except: pass
    return None, None

def fix(key, query, note=""):
    """Search and update master entry."""
    data = search(query)
    if not data or not data.get("success"):
        print(f"  FAILED  {key[:60]}")
        return
    results = data.get("data",{}).get("web",[])
    for res in results:
        text = f"{res.get('title','')} {res.get('description','')}"
        price, cur = parse_price(text)
        if price:
            old = master.get(key, {}).get("price_eur","—")
            master[key] = {
                "price_eur": price,
                "source_url": res.get("url",""),
                "snippet": text[:150],
                "fixed": True,
                "query_used": query,
            }
            print(f"  {price:>9}  [{old} -> {price}]  {text[:70]}")
            return
    print(f"  not found  {key[:60]}")
    if key in master:
        master[key]["price_eur"] = "not found"
        master[key]["fixed"] = True
    time.sleep(2)

FIXES = [
    # (master_key, targeted_query)
    # Wrong cuvée / wrong producer fixes
    ("Domaine Guffens-Heynen|Clos de Mornantely",
     "guffens heynen clos mornantely pouilly fuisse price"),
    ("Domaine Macle|Cotes du Jura Tradition",
     "domaine macle cotes du jura tradition prix"),
    ("Domaine Ganevat|Cotes du Jura",
     "ganevat cotes du jura price EUR wine-searcher"),
    ("DOMAINE BRIGITTE TRANSMIER|Chateau du Jura",
     "brigitte transmier chateau du jura 2018 prix wine"),
    ("Domaine Guffens-Heynen|Clos du Cros 2023",
     "guffens heynen clos du cros pouilly fuisse 2023 price"),
    ("Domaine Henri & Gilles Buisson|Meursault Premier Cru",
     "buisson freres meursault premier cru price wine-searcher"),
    ("Domaine Dujac|Chambertin",
     "domaine dujac chambertin grand cru price wine-searcher"),
    ("Domaine Santa Duc|Gigondas Aux Lieux-Dits",
     "santa duc gigondas aux lieux dits 2022 price EUR"),
    ("Ridge|Monte Bello",
     "ridge monte bello 2021 price EUR wine-searcher"),
    ("Domaine Huet|Vouvray",
     "domaine huet vouvray price EUR wine-searcher"),
    ("Domaine Chanterves|Gevrey-Chambertin",
     "domaine chantereves gevrey chambertin price wine-searcher"),
    # Missing prices (31-50)
    ("Domaine Joseph Colin|Chassagne-Montrachet Village",
     "joseph colin chassagne montrachet village price EUR"),
    ("Domaine Bosquet des Papes|Chateauneuf-du-Pape Blanc",
     "bosquet des papes chateauneuf du pape blanc price"),
    ("Domaine Jerome Gradassi|Chateauneuf-du-Pape Rouge",
     "gradassi chateauneuf du pape rouge price EUR"),
    ("Maison Jane Eyre|Gevrey-Chambertin 1er cru",
     "maison jane eyre gevrey chambertin premier cru price"),
    ("Chateau Mont-Redon|Chateauneuf-du-Pape",
     "chateau mont redon chateauneuf du pape rouge price EUR"),
    ("Domaine Arlaud|Bonnes-Mares Grand Cru",
     "domaine arlaud bonnes mares grand cru 2024 price"),
    ("Chateau Montrose|La Dame de Montrose",
     "la dame de montrose 2023 price EUR"),
    ("Ridge Vineyards|Monte Bello - Ridge Vineyard",
     "ridge monte bello 2021 price EUR"),
    ("Chateau Mouton Rothschild|Chateau Mouton Rothshild",
     "mouton rothschild 2021 price EUR wine-searcher"),
    ("Domaine Ganevat|En Bilat",
     "ganevat en bilat jura price EUR"),
    ("Le Clos du Caillou|Reserve le Clos du Caillou",
     "clos du caillou reserve chateauneuf du pape price EUR"),
    ("Domaine Macle|Cotes du Jura Chardonnay",
     "macle cotes du jura chardonnay sous voile price EUR"),
    ("Domaine Claude Dugat|Griotte-Chambertin",
     "claude dugat griotte chambertin grand cru price wine-searcher"),
    ("D'Autrefois|Pinot Noir",
     "d autrefois pinot noir igp pays oc price"),
    ("Domaine de Nizas|Le Mas",
     "domaine de nizas le mas languedoc price EUR"),
    ("Chateau Margaux|Pavillon Blanc de Chateau Margau",
     "pavillon blanc chateau margaux price EUR wine-searcher"),
    ("Domaine Georges Chicotot|Nuits-Saint-Georges a Nuits-Saint-Georges",
     "chicotot nuits saint georges price EUR"),
    ("Domaine Bois de Boursan|BOIS DE BOURSAN",
     "bois de boursan chateauneuf du pape price EUR"),
    ("Domaine Roger Sabon|ROGER SABON",
     "roger sabon chateauneuf du pape reserve price EUR"),
]

print(f"Fixing {len(FIXES)} wines...\n")
for key, query in FIXES:
    # Find the actual key in master (fuzzy match on prefix)
    actual_key = None
    for k in master:
        prod, cuv = k.split("|", 1)
        search_prod = ascii_q(key.split("|")[0]).lower()
        search_cuv  = ascii_q(key.split("|")[1]).lower()
        if ascii_q(prod).lower().startswith(search_prod[:12]) and \
           ascii_q(cuv).lower()[:15] in ascii_q(search_cuv).lower()[:25] or \
           ascii_q(search_cuv).lower()[:15] in ascii_q(cuv).lower()[:25]:
            actual_key = k
            break
    if not actual_key:
        # Try looser match
        for k in master:
            prod = ascii_q(k.split("|")[0]).lower()
            if ascii_q(key.split("|")[0]).lower()[:12] in prod:
                actual_key = k
                break
    if not actual_key:
        actual_key = key  # will create new entry

    label = actual_key[:65]
    print(f"\n{label}")
    fix(actual_key, query)
    time.sleep(2)

MASTER.write_text(json.dumps(master, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"\nSaved {len(master)} entries to master.")
