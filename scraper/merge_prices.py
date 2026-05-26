"""
Merge all rvf_prices_found_*.json batch files into one master file,
then regenerate the HTML price research table.
"""
import json, re
from pathlib import Path

DATA_DIR = Path(__file__).parent / "raw" / "rvf_pages"

# --- merge all batch files (but preserve manually_verified entries) ---
master_path = DATA_DIR / "rvf_prices_master.json"

# Load existing master first (may contain manually_verified corrections)
if master_path.exists():
    master = json.loads(master_path.read_text(encoding="utf-8"))
else:
    master = {}

for f in sorted(DATA_DIR.glob("rvf_prices_found*.json")):
    data = json.loads(f.read_text(encoding="utf-8"))
    for key, entry in data.items():
        existing = master.get(key, {})
        # Never overwrite manually verified entries
        if existing.get("manually_verified"):
            continue
        if key not in master:
            master[key] = entry
        else:
            # prefer entry with an actual price over "not found"
            if master[key]["price_eur"] == "not found" and entry["price_eur"] != "not found":
                master[key] = entry

# save master
master_path.write_text(json.dumps(master, indent=2, ensure_ascii=False), encoding="utf-8")

found = sum(1 for v in master.values() if v["price_eur"] != "not found")
print(f"Total wines in master: {len(master)}")
print(f"Prices found: {found} / {len(master)} ({100*found//len(master)}%)")

# --- reload wine list in order ---
raw = json.loads((DATA_DIR / "rvf_ratings_sorted.json").read_text(encoding="utf-8"))
seen = {}
for r in raw:
    key = (r["producer"], r["cuvee"])
    if key not in seen or r["score_100"] > seen[key]["score_100"]:
        seen[key] = r
unique = sorted(seen.values(), key=lambda x: -x["score_100"])

# --- generate HTML ---
def row_class(price_str):
    if price_str == "not found":
        return ""
    try:
        v = float(re.sub(r"[^\d.]", "", price_str))
        if v >= 500:  return "price-high"
        if v >= 100:  return "price-mid"
        if v >= 30:   return "price-ok"
        return "price-low"
    except Exception:
        return ""

def value_stars(score_100, price_str):
    """Return (stars_html, sort_key) based on score/price ratio."""
    n = re.sub(r"[^\d.]", "", price_str)
    if not n:
        return '<span class="val-na">—</span>', -1
    try:
        price = float(n)
        if price <= 0:
            return '<span class="val-na">—</span>', -1
        ratio = score_100 / price   # points per €
        if ratio >= 3.0:
            return '<span class="val-5">★★★★★</span>', ratio
        if ratio >= 1.5:
            return '<span class="val-4">★★★★</span>', ratio
        if ratio >= 0.7:
            return '<span class="val-3">★★★</span>', ratio
        if ratio >= 0.3:
            return '<span class="val-2">★★</span>', ratio
        return '<span class="val-1">★</span>', ratio
    except Exception:
        return '<span class="val-na">—</span>', -1

html_rows = []
for i, r in enumerate(unique, 1):
    key_str = f"{r['producer']}|{r['cuvee']}"
    entry = master.get(key_str)
    price = entry["price_eur"] if entry else "not found"
    ws_slug = re.sub(r"[^a-zA-Z0-9\s]", " ", f"{r['producer']} {r['cuvee']}")
    ws_slug = re.sub(r"\s+", "-", ws_slug.strip().lower())[:80]
    ws_url = f"https://www.wine-searcher.com/find/{ws_slug}"
    v = r["vintage"] or "NV"
    sc = r["score_20"]
    score100 = r["score_100"]
    prod = r["producer"]
    cuv = r["cuvee"]
    app = r["appellation"] or ""
    rc = row_class(price)
    val_html, _ = value_stars(score100, price)

    src_url  = (entry or {}).get("source_url", "")
    snippet  = (entry or {}).get("snippet", "").replace('"', "&quot;").replace("<", "&lt;")
    # derive short domain label for display
    import urllib.parse
    try:
        domain = urllib.parse.urlparse(src_url).netloc.replace("www.", "")[:30]
    except Exception:
        domain = ""

    # Always provide a shop/lookup link
    buy_link = src_url if src_url else ws_url
    buy_label = domain if domain else "wine-searcher.com"

    if price not in ("not found", "not listed"):
        price_cell = (
            f'<td class="price {rc}" title="{snippet}">'
            f'<span class="price-val">{price}</span>'
            f'<a class="shop-btn" href="{buy_link}" target="_blank">shop ↗</a>'
            f'</td>'
        )
    elif price == "not listed":
        price_cell = (
            f'<td class="price" title="{snippet}">'
            f'<span style="color:#888">not listed</span>'
            f'<a class="shop-btn" href="{buy_link}" target="_blank">search ↗</a>'
            f'</td>'
        )
    else:
        price_cell = (
            f'<td class="price">'
            f'<a class="shop-btn" href="{ws_url}" target="_blank">lookup ↗</a>'
            f'</td>'
        )

    html_rows.append(f'  <tr><td>{i}</td><td class="score">{sc}</td><td>{prod}</td><td>{cuv}</td><td>{v}</td><td>{app}</td>{price_cell}<td class="val">{val_html}</td></tr>')

html = (
"<!DOCTYPE html>\n<html lang='fr'>\n<head>\n<meta charset='utf-8'>\n"
"<title>RVF Top WINE_COUNT Wines - Prices</title>\n"
"<style>\n"
"  body { font-family: Arial, sans-serif; font-size: 12px; background: #0F0E17; color: #F7F4EA; margin: 16px; }\n"
"  h1 { color: #E5B25D; margin-bottom: 4px; }\n"
"  p { color: #aaa; margin: 4px 0 10px; }\n"
"  input { background: #222; color: #eee; border: 1px solid #555; padding: 5px 8px; width: 320px; margin-bottom: 8px; border-radius: 3px; }\n"
"  table { border-collapse: collapse; width: 100%; }\n"
"  th { background: #A53860; color: white; padding: 7px 5px; text-align: left; position: sticky; top: 0; z-index: 1; font-size: 11px; }\n"
"  td { padding: 4px 5px; border-bottom: 1px solid #1e1e2e; vertical-align: top; }\n"
"  tr:hover td { background: #1a1a2e; }\n"
"  .score { font-weight: bold; color: #E5B25D; white-space: nowrap; }\n"
"  .price { font-weight: bold; white-space: nowrap; }\n"
"  .price-low  { color: #5fba7d; }\n"
"  .price-ok   { color: #a8d5a2; }\n"
"  .price-mid  { color: #E5B25D; }\n"
"  .price-high { color: #ff6b6b; }\n"
"  .price a { color: #E5B25D; text-decoration: none; }\n"
"  .price a:hover { text-decoration: underline; }\n"
"  .src { color: #666; font-size: 10px; font-weight: normal; }\n"
"  .price-val { color: inherit; margin-right: 6px; }\n"
"  .shop-btn { display: inline-block; margin-left: 4px; padding: 1px 6px; background: #A53860; color: #fff !important; border-radius: 3px; font-size: 10px; font-weight: bold; text-decoration: none !important; white-space: nowrap; }\n"
"  .shop-btn:hover { background: #c04070; }\n"
"  .val { white-space: nowrap; }\n"
"  .val-5 { color: #00e676; font-size: 13px; }\n"
"  .val-4 { color: #69f0ae; font-size: 12px; }\n"
"  .val-3 { color: #a8d5a2; font-size: 12px; }\n"
"  .val-2 { color: #E5B25D; font-size: 12px; }\n"
"  .val-1 { color: #ff6b6b; font-size: 12px; }\n"
"  .val-na { color: #555; }\n"
"  .price a:hover { text-decoration: underline; }\n"
"  .stats { display: flex; gap: 20px; margin-bottom: 10px; }\n"
"  .stat { background: #1a1a2e; padding: 6px 12px; border-radius: 4px; border-left: 3px solid #A53860; }\n"
"  .stat span { color: #E5B25D; font-weight: bold; font-size: 16px; display: block; }\n"
"</style>\n"
"<script>\n"
"function filterTable() {\n"
"  var q = document.getElementById('search').value.toLowerCase();\n"
"  var rows = document.querySelectorAll('tbody tr');\n"
"  rows.forEach(r => r.style.display = r.textContent.toLowerCase().includes(q) ? '' : 'none');\n"
"}\n"
"</script>\n"
"</head>\n<body>\n"
"<h1>&#127863; RVF Top Wines - Complete Price Table</h1>\n"
"<p>WINE_COUNT unique wines &middot; FOUND_COUNT prices found (PCT% coverage) &middot; Source: Wine-Searcher via Firecrawl</p>\n"
"STATS_PLACEHOLDER\n"
"<input id='search' onkeyup='filterTable()' placeholder='Filter by producer, wine, appellation, price...'>\n"
"<table>\n<thead><tr><th>#</th><th>Score</th><th>Producer</th><th>Wine / Cuvee</th><th>Vintage</th><th>Appellation</th><th>Price</th><th title='Score / Price ratio: more stars = better value for money'>Value</th></tr></thead>\n"
"<tbody>\nROWS_PLACEHOLDER\n</tbody>\n</table>\n</body>\n</html>"
)

def safe_eur(price_str):
    n = re.sub(r"[^\d.]", "", price_str)
    try: return float(n) if n else None
    except: return None

def count_range(lo, hi):
    return sum(1 for v in master.values()
               if (p := safe_eur(v["price_eur"])) is not None and lo <= p < hi)

stats_html = f"""<div class="stats">
  <div class="stat"><span style="color:#5fba7d">{count_range(0,30)}</span>Under €30</div>
  <div class="stat"><span style="color:#a8d5a2">{count_range(30,100)}</span>€30–100</div>
  <div class="stat"><span style="color:#E5B25D">{count_range(100,500)}</span>€100–500</div>
  <div class="stat"><span style="color:#ff6b6b">{count_range(500,1e9)}</span>€500+</div>
</div>"""

html = html.replace("WINE_COUNT", str(len(unique)))
html = html.replace("FOUND_COUNT", str(found))
html = html.replace("PCT", str(100 * found // len(unique)))
html = html.replace("STATS_PLACEHOLDER", stats_html)
html = html.replace("ROWS_PLACEHOLDER", "\n".join(html_rows))
out = DATA_DIR / "rvf_price_research.html"
out.write_text(html, encoding="utf-8")
print(f"HTML written: {out}")

# --- print top 30 with prices for quick review ---
print("\nTop 30 with prices:")
print(f"{'#':>3}  {'Score':>6}  {'Producer':<40}  {'Price':>8}  Cuvee")
print("-" * 100)
for i, r in enumerate(unique[:30], 1):
    key_str = f"{r['producer']}|{r['cuvee']}"
    entry = master.get(key_str)
    price = entry["price_eur"] if entry else "n/a"
    print(f"{i:>3}  {r['score_20']:>6}  {r['producer']:<40}  {price:>10}  {r['cuvee'][:40]}")
