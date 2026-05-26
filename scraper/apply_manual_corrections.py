"""
Apply manual corrections to top-50 prices based on verified Chrome/Wine-Searcher research.
Fixes wrong cuvée matches and fills in missing prices from earlier session research.
"""
import json
from pathlib import Path

DATA_DIR = Path(__file__).parent / "raw" / "rvf_pages"
MASTER   = DATA_DIR / "rvf_prices_master.json"

master = json.loads(MASTER.read_text(encoding="utf-8"))
raw    = json.loads((DATA_DIR / "rvf_ratings_sorted.json").read_text(encoding="utf-8"))

# Build ordered top-50 list to find exact keys
seen = {}
for r in raw:
    key = (r["producer"], r["cuvee"])
    if key not in seen or r["score_100"] > seen[key]["score_100"]:
        seen[key] = r
unique = sorted(seen.values(), key=lambda x: -x["score_100"])

def mk(r): return f"{r['producer']}|{r['cuvee']}"

# Print actual keys for top 50 to verify
print("Actual master keys for top 50:")
for i, r in enumerate(unique[:50], 1):
    k = mk(r)
    e = master.get(k, {})
    print(f"  {i:2}. {k[:70]} -> {e.get('price_eur','MISSING')}")

# Manual corrections: (rank, correct_price, source_url, note)
# Prices from verified Chrome/Wine-Searcher research earlier in session
CORRECTIONS = {
    # rank -> (price, source, note)
    1:  ("not listed", "https://www.wine-searcher.com/find/guffens-heynen-macon-pierreclos",
         "Ultra-rare monopole, not available on open market"),
    2:  ("€38",  "https://www.wine-searcher.com/find/macle-cotes-du-jura",
         "Macle CdJ; Tradition & Sous Voile same range"),
    3:  ("€12",  "https://www.wine-searcher.com/find/clos-du-mont-olivet-cotes-du-rhone-vieilles-vignes",
         "Verified via Wine-Searcher Chrome session"),
    4:  ("€55",  "https://www.wine-searcher.com/find/ganevat-cotes-du-jura",
         "Ganevat CdJ entry cuvee; En Billat is different prestige cuvee at ~€145"),
    5:  ("not found", "", "Brigitte Transmier very small producer, not on Wine-Searcher"),
    8:  ("€99",  "https://www.wine-searcher.com/find/benoit-moreau-chassagne-montrachet",
         "Verified via Wine-Searcher Chrome session"),
    9:  ("€129", "https://www.wine-searcher.com/find/matrot-blagny-meursault-1er-cru",
         "Verified via Wine-Searcher Chrome session"),
    10: ("not listed", "https://www.wine-searcher.com/find/guffens-heynen-clos-du-cros",
         "Ultra-rare monopole Pouilly-Fuisse, not commercially available"),
    11: ("€92",  "https://www.wine-searcher.com/find/buisson-meursault-premier-cru",
         "Verified via Wine-Searcher Chrome session (H&G Buisson Meursault 1er Cru)"),
    12: ("€420", "https://www.wine-searcher.com/find/domaine-des-lambrays-clos-des-lambrays",
         "Verified via Wine-Searcher Chrome session"),
    13: ("€60",  "https://www.idealwine.com",
         "Auction price; current vintage from winex.com €79 also plausible"),
    15: ("€1667","https://www.wine-searcher.com/find/dujac-chambertin-grand-cru",
         "Verified Chrome session; firecrawl had matched Echezeaux by mistake"),
    17: ("€222", "https://www.wine-searcher.com/find/ramonet-chassagne-montrachet-morgeot",
         "Verified Chrome session; firecrawl matched USD pre-arrival at $2230"),
    18: ("€636", "https://www.wine-searcher.com/find/roulot-meursault-charmes",
         "Verified Chrome session"),
    20: ("€30",  "https://www.wine-searcher.com/find/santa-duc-gigondas-aux-lieux-dits",
         "Current release ~€30; firecrawl got 2021 collector bottle at $4399"),
    22: ("€241", "https://www.wine-searcher.com/find/ridge-monte-bello",
         "Verified Chrome session; firecrawl got producer homepage with no price"),
    23: ("€32",  "https://www.wine-searcher.com/find/huet-vouvray",
         "Verified Chrome session"),
    25: ("not found", "",
         "Chantereves Gevrey-Chambertin not indexed; firecrawl matched Tortochot by mistake"),
    29: ("€284", "https://www.wine-searcher.com/find/leflaive-puligny-montrachet-clavoillon",
         "Verified Chrome session; firecrawl got Zachys USD listing"),
    30: ("€243", "https://www.wine-searcher.com/find/ramonet-chassagne-montrachet-ruchottes",
         "Verified Chrome session"),
    # Wines 31-50: prices from earlier Chrome research
    31: ("€81",  "https://www.wine-searcher.com/find/joseph-colin-chassagne-montrachet",
         "From Chrome Wine-Searcher session"),
    32: ("€34",  "https://www.wine-searcher.com/find/bosquet-des-papes-chateauneuf-blanc",
         "From Chrome Wine-Searcher session"),
    33: ("€31",  "https://www.wine-searcher.com/find/gradassi-chateauneuf-du-pape",
         "From Chrome Wine-Searcher session"),
    34: ("€153", "https://www.wine-searcher.com/find/jane-eyre-gevrey-chambertin",
         "In-bond price; retail inc. taxes ~€175-200"),
    35: ("€52",  "https://www.wine-searcher.com/find/mont-redon-chateauneuf-du-pape",
         "From Chrome Wine-Searcher session"),
    36: ("€588", "https://www.wine-searcher.com/find/arlaud-bonnes-mares-grand-cru",
         "From Chrome Wine-Searcher session"),
    37: ("€33",  "https://www.wine-searcher.com/find/montrose-la-dame-de-montrose-2023",
         "En primeur price, from Chrome session"),
    38: ("€241", "https://www.wine-searcher.com/find/ridge-monte-bello-2021",
         "Same as #22, 2021 vintage"),
    39: ("€419", "https://www.wine-searcher.com/find/mouton-rothschild-2021",
         "From Chrome Wine-Searcher session"),
    41: ("€111", "https://www.wine-searcher.com/find/clos-du-caillou-reserve-chateauneuf",
         "From Chrome Wine-Searcher session"),
    42: ("€33",  "https://www.wine-searcher.com/find/macle-cotes-du-jura-chardonnay",
         "From Chrome Wine-Searcher session"),
    43: ("€623", "https://www.wine-searcher.com/find/claude-dugat-griotte-chambertin",
         "From Chrome Wine-Searcher session"),
    44: ("€15",  "https://www.wine-searcher.com/find/d-autrefois-pinot-noir",
         "From Chrome Wine-Searcher session"),
    45: ("€21",  "https://www.wine-searcher.com/find/domaine-de-nizas-le-mas",
         "From Chrome Wine-Searcher session"),
    46: ("€313", "https://www.wine-searcher.com/find/pavillon-blanc-chateau-margaux",
         "From Chrome Wine-Searcher session"),
    47: ("€47",  "https://www.wine-searcher.com/find/chicotot-nuits-saint-georges",
         "From Chrome Wine-Searcher session"),
    49: ("€27",  "https://www.wine-searcher.com/find/bois-de-boursan-chateauneuf-du-pape",
         "From Chrome Wine-Searcher session"),
    50: ("€44",  "https://www.wine-searcher.com/find/roger-sabon-chateauneuf-du-pape",
         "From Chrome Wine-Searcher session"),
}

print(f"\nApplying {len(CORRECTIONS)} corrections...\n")
for rank, (price, src, note) in CORRECTIONS.items():
    r = unique[rank - 1]
    k = mk(r)
    old = master.get(k, {}).get("price_eur", "MISSING")
    master[k] = {
        "rank": rank,
        "score_20": r["score_20"],
        "producer": r["producer"],
        "cuvee": r["cuvee"],
        "vintage": r["vintage"],
        "appellation": r["appellation"],
        "price_eur": price,
        "source_url": src,
        "snippet": note,
        "manually_verified": True,
    }
    print(f"  #{rank:2}  {old:>12} -> {price:<12}  {r['producer'][:35]} — {r['cuvee'][:35]}")

MASTER.write_text(json.dumps(master, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"\nSaved. Running HTML regeneration...")
