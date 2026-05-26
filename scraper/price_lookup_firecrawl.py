"""
Look up wine prices using firecrawl search (reads price from search snippet descriptions).
Avoids direct Wine-Searcher scraping entirely.
Runs incrementally — saves after each wine, safe to re-run.
Usage: python price_lookup_firecrawl.py [start_index] [end_index]
       python price_lookup_firecrawl.py 50 200
"""
import json, re, subprocess, time, sys
from pathlib import Path

DATA_DIR = Path(__file__).parent / "raw" / "rvf_pages"
JSON_IN   = DATA_DIR / "rvf_ratings_sorted.json"
# Optional 3rd arg: output filename suffix (for parallel runs)
suffix = sys.argv[3] if len(sys.argv) > 3 else ""
PRICES_OUT = DATA_DIR / f"rvf_prices_found{suffix}.json"

# --- load wine list ---
raw = json.loads(JSON_IN.read_text(encoding="utf-8"))
seen = {}
for r in raw:
    key = (r["producer"], r["cuvee"])
    if key not in seen or r["score_100"] > seen[key]["score_100"]:
        seen[key] = r
unique = sorted(seen.values(), key=lambda x: -x["score_100"])

# --- load existing prices (resume support) ---
if PRICES_OUT.exists():
    prices = json.loads(PRICES_OUT.read_text(encoding="utf-8"))
else:
    prices = {}

# --- parse indices ---
start = int(sys.argv[1]) - 1 if len(sys.argv) > 1 else 0
end   = int(sys.argv[2])     if len(sys.argv) > 2 else len(unique)

# --- price extraction from firecrawl snippet ---
PRICE_PATTERNS = [
    # Wine-Searcher snippet: "Avg Price (ex-tax) $1234 / 750ml"
    r'Avg Price[^$€£]*[$€£]([\d,]+(?:\.\d+)?)',
    # Wine-Searcher snippet: "€1,234" or "€1234"
    r'€([\d][,\d]*(?:\.\d+)?)',
    # "$1234" → convert to EUR at ~0.93
    r'\$([\d,]+(?:\.\d+)?)',
    # "£1234" → convert to EUR at ~1.18
    r'£([\d,]+(?:\.\d+)?)',
]

USD_TO_EUR = 0.93
GBP_TO_EUR = 1.18

def parse_price(text):
    """Extract a EUR price from a text snippet."""
    # Try EUR first
    m = re.search(r'€([\d][,\d]*(?:\.\d+)?)', text)
    if m:
        try:
            return float(m.group(1).replace(",", "")), "EUR"
        except ValueError:
            pass
    # Try USD
    m = re.search(r'Avg Price[^$€]*\$([\d,]+(?:\.\d+)?)', text)
    if m:
        try:
            usd = float(m.group(1).replace(",", ""))
            return round(usd * USD_TO_EUR, 0), "USD→EUR"
        except ValueError:
            pass
    m = re.search(r'\$([\d,]+(?:\.\d+)?)', text)
    if m:
        try:
            usd = float(m.group(1).replace(",", ""))
            if usd > 1:  # skip things like $0.99
                return round(usd * USD_TO_EUR, 0), "USD→EUR"
        except ValueError:
            pass
    # Try GBP
    m = re.search(r'£([\d,]+(?:\.\d+)?)', text)
    if m:
        try:
            gbp = float(m.group(1).replace(",", ""))
            return round(gbp * GBP_TO_EUR, 0), "GBP→EUR"
        except ValueError:
            pass
    return None, None

FIRECRAWL_PS1 = r"C:\Users\Nicolas\AppData\Roaming\npm\firecrawl.ps1"

FIRECRAWL_PS1 = r"C:\Users\Nicolas\AppData\Roaming\npm\firecrawl.ps1"

def ascii_query(q):
    """Normalize accented characters to ASCII for safer shell queries."""
    import unicodedata
    return "".join(
        c for c in unicodedata.normalize("NFD", q)
        if unicodedata.category(c) != "Mn"
    )

def firecrawl_search(query):
    """Run firecrawl search via PowerShell and return parsed JSON."""
    # Normalize to ASCII to avoid encoding issues in PS subprocess
    safe_query = ascii_query(query).replace("'", "").replace('"', "")
    ps_cmd = f'& \'{FIRECRAWL_PS1}\' search \'{safe_query}\' --limit 3 --json'
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=90, encoding="utf-8",
            errors="replace"
        )
    except subprocess.TimeoutExpired:
        return None
    except Exception:
        return None
    if result.returncode != 0:
        return None
    # Extract JSON — PowerShell may prepend warnings
    out = result.stdout.strip()
    start = out.find('{')
    if start == -1:
        return None
    try:
        return json.loads(out[start:])
    except json.JSONDecodeError:
        return None

# --- main loop ---
total = end - start
print(f"Looking up wines {start+1}-{end} ({total} wines)...\n")

for idx in range(start, min(end, len(unique))):
    r = unique[idx]
    key = f"{r['producer']}|{r['cuvee']}"
    wine_num = idx + 1

    if key in prices:
        print(f"  {wine_num:4}. SKIP (already found): {r['producer']} - {r['cuvee'][:40]} -> {prices[key]['price_eur']}")
        continue

    # Build search query
    query = f"{r['producer']} {r['cuvee']} wine price"
    # Clean up obvious article-headline cuvees
    cuvee_words = r['cuvee'].split()
    if len(cuvee_words) > 8:
        # Long cuvee = probably article headline; use just producer + appellation
        query = f"{r['producer']} {r['appellation'] or ''} wine price EUR"

    print(f"  {wine_num:4}. {r['score_20']}/20  {r['producer'][:35]:<35} - {r['cuvee'][:40]}", end="", flush=True)

    try:
        data = firecrawl_search(query)
    except Exception:
        data = None
    found_price = None
    found_source = None
    found_note = ""

    if data and data.get("success"):
        results = data.get("data", {}).get("web", [])
        for res in results:
            # Combine title + description for price extraction
            text = f"{res.get('title', '')} {res.get('description', '')}"
            price_eur, currency = parse_price(text)
            if price_eur and price_eur > 0:
                found_price = price_eur
                found_source = res.get("url", "")
                found_note = text[:120]
                break

    entry = {
        "rank": wine_num,
        "score_20": r["score_20"],
        "producer": r["producer"],
        "cuvee": r["cuvee"],
        "vintage": r["vintage"],
        "appellation": r["appellation"],
        "price_eur": f"€{int(found_price)}" if found_price else "not found",
        "source_url": found_source or "",
        "snippet": found_note,
    }
    prices[key] = entry

    if found_price:
        print(f"  -> EUR {int(found_price)}")
    else:
        print(f"  -> not found")

    # Save after every wine
    PRICES_OUT.write_text(json.dumps(prices, indent=2, ensure_ascii=False), encoding="utf-8")

    # Delay to stay under firecrawl rate limits
    time.sleep(2)

print(f"\nDone. {sum(1 for v in prices.values() if v['price_eur'] != 'not found')} prices found out of {len(prices)} searched.")
print(f"Results saved to: {PRICES_OUT}")
