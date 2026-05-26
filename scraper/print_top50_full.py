import json
from pathlib import Path

master = json.loads((Path(__file__).parent / "raw/rvf_pages/rvf_prices_master.json").read_text(encoding="utf-8"))
raw    = json.loads((Path(__file__).parent / "raw/rvf_pages/rvf_ratings_sorted.json").read_text(encoding="utf-8"))

seen = {}
for r in raw:
    key = (r["producer"], r["cuvee"])
    if key not in seen or r["score_100"] > seen[key]["score_100"]:
        seen[key] = r
unique = sorted(seen.values(), key=lambda x: -x["score_100"])

import re as _re

def value_label(score100, price_str):
    n = _re.sub(r"[^\d.]", "", price_str)
    if not n: return "  —  "
    try:
        p = float(n)
        if p <= 0: return "  —  "
        ratio = score100 / p
        if ratio >= 3.0: return "★★★★★"
        if ratio >= 1.5: return "★★★★ "
        if ratio >= 0.7: return "★★★  "
        if ratio >= 0.3: return "★★   "
        return "★    "
    except: return "  —  "

print(f"{'#':>3}  {'Score':>6}  {'Vintage':>7}  {'Price':>9}  {'Value':<7}  Producer — Wine")
print("-" * 115)
for i, r in enumerate(unique[:50], 1):
    k = f"{r['producer']}|{r['cuvee']}"
    e = master.get(k)
    price = e["price_eur"] if e else "n/a"
    v = str(r["vintage"]) if r["vintage"] else "NV"
    val = value_label(r["score_100"], price)
    prod = r["producer"][:34]
    cuv  = r["cuvee"][:38]
    print(f"{i:>3}  {r['score_20']:>6}  {v:>7}  {price:>9}  {val}  {prod} — {cuv}")
