"""
Fill missing prices for wines >= 16/20 using firecrawl search.
Accepts args: start end suffix
Run multiple instances in parallel with different ranges + suffixes.
"""
import json, re, subprocess, time, sys, unicodedata
from pathlib import Path

DATA_DIR  = Path(__file__).parent / "raw" / "rvf_pages"
MASTER    = DATA_DIR / "rvf_prices_master.json"
FIRECRAWL = r"C:\Users\Nicolas\AppData\Roaming\npm\firecrawl.ps1"

START  = int(sys.argv[1]) if len(sys.argv) > 1 else 0
END    = int(sys.argv[2]) if len(sys.argv) > 2 else 200
SUFFIX = sys.argv[3] if len(sys.argv) > 3 else ""

OUT_FILE = DATA_DIR / f"rvf_prices_fill{SUFFIX}.json"

# Load current master to skip already-found wines
master = json.loads(MASTER.read_text(encoding="utf-8"))

# Build ordered list of wines >= 16/20 missing prices
raw    = json.loads((DATA_DIR / "rvf_ratings_sorted.json").read_text(encoding="utf-8"))
seen = {}
for r in raw:
    k = (r["producer"], r["cuvee"])
    if k not in seen or r["score_100"] > seen[k]["score_100"]:
        seen[k] = r
unique = sorted(seen.values(), key=lambda x: -x["score_100"])

missing = []
for r in unique:
    if r["score_20"] < 16.0:
        continue
    k = r["producer"] + "|" + r["cuvee"]
    e = master.get(k, {})
    p = e.get("price_eur", "not found")
    if p in ("not found", "MISSING") or not e:
        missing.append(r)

batch = missing[START:END]
print(f"Batch {SUFFIX}: wines {START}-{END} ({len(batch)} to search)")

# Load incremental output if resuming
if OUT_FILE.exists():
    results = json.loads(OUT_FILE.read_text(encoding="utf-8"))
    print(f"  Resuming: {len(results)} already done")
else:
    results = {}


def ascii_q(q):
    return "".join(c for c in unicodedata.normalize("NFD", q)
                   if unicodedata.category(c) != "Mn")


def search(query):
    safe = ascii_q(query).replace("'", "").replace('"', "")
    ps   = f"& '{FIRECRAWL}' search '{safe}' --limit 3 --json"
    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, text=True, timeout=90,
            encoding="utf-8", errors="replace")
        out = r.stdout.strip()
        start = out.find("{")
        return json.loads(out[start:]) if start != -1 else None
    except Exception:
        return None


def parse_price(text):
    # EUR
    m = re.search(r"€\s*([\d][,\d]*(?:\.\d+)?)", text)
    if m:
        try:
            v = float(m.group(1).replace(",", ""))
            if v > 1:
                return f"€{int(v)}", "EUR"
        except Exception:
            pass
    # Avg Price USD snippet from Wine-Searcher
    m = re.search(r"Avg Price[^$€£]*\$([\d,]+(?:\.\d+)?)", text)
    if m:
        try:
            return f"€{int(float(m.group(1).replace(',', '')) * 0.93)}", "USD"
        except Exception:
            pass
    # GBP
    m = re.search(r"£([\d,]+(?:\.\d+)?)", text)
    if m:
        try:
            v = float(m.group(1).replace(",", ""))
            if v > 1:
                return f"€{int(v * 1.18)}", "GBP"
        except Exception:
            pass
    # plain USD
    m = re.search(r"\$([\d,]+(?:\.\d+)?)", text)
    if m:
        try:
            v = float(m.group(1).replace(",", ""))
            if v > 5:
                return f"€{int(v * 0.93)}", "USD"
        except Exception:
            pass
    return None, None


found_count = 0
for i, r in enumerate(batch):
    key = r["producer"] + "|" + r["cuvee"]
    if key in results:
        continue  # already done in a previous run

    prod  = ascii_q(r["producer"])
    cuv   = ascii_q(r["cuvee"])[:40]
    app   = ascii_q(r["appellation"] or "")[:30]
    vint  = str(r["vintage"]) if r["vintage"] else ""

    # Build a focused query
    query = f"{prod} {cuv} {vint} price EUR wine-searcher"
    if len(query) > 120:
        query = f"{prod} {cuv[:25]} price EUR wine-searcher"

    data = search(query)
    price, cur = None, None
    src_url, snippet = "", ""

    if data and data.get("success"):
        web = data.get("data", {}).get("web", [])
        for res in web:
            text = f"{res.get('title','')} {res.get('description','')}"
            price, cur = parse_price(text)
            if price:
                src_url = res.get("url", "")
                snippet = text[:200]
                break

    results[key] = {
        "rank": None,
        "score_20": r["score_20"],
        "producer": r["producer"],
        "cuvee": r["cuvee"],
        "vintage": r["vintage"],
        "appellation": r["appellation"],
        "price_eur": price if price else "not found",
        "source_url": src_url,
        "snippet": snippet,
        "currency": cur or "",
    }

    status = f"{price or 'not found':>10}"
    pct = (i + 1) * 100 // len(batch)
    print(f"  [{pct:>3}%] {status}  {r['producer'][:35]} — {r['cuvee'][:35]}")

    if price:
        found_count += 1

    # Save incrementally every 10 wines
    if (i + 1) % 10 == 0:
        OUT_FILE.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    time.sleep(2)

OUT_FILE.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"\nDone. Found {found_count}/{len(batch)} prices. Saved to {OUT_FILE.name}")
