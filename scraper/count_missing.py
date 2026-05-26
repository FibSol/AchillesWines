import json, re
from pathlib import Path
DATA_DIR = Path(__file__).parent / "raw" / "rvf_pages"
master = json.loads((DATA_DIR / "rvf_prices_master.json").read_text(encoding="utf-8"))
raw    = json.loads((DATA_DIR / "rvf_ratings_sorted.json").read_text(encoding="utf-8"))
seen = {}
for r in raw:
    k = (r["producer"], r["cuvee"])
    if k not in seen or r["score_100"] > seen[k]["score_100"]:
        seen[k] = r
unique = sorted(seen.values(), key=lambda x: -x["score_100"])

wines_16 = [r for r in unique if r["score_20"] >= 16.0]
missing = []
for r in wines_16:
    k = r["producer"] + "|" + r["cuvee"]
    e = master.get(k, {})
    p = e.get("price_eur", "not found")
    if p in ("not found", "MISSING") or not e:
        missing.append((r, k))

print(f"Wines >= 16/20: {len(wines_16)}")
print(f"Missing prices: {len(missing)}")
print(f"Coverage: {len(wines_16)-len(missing)}/{len(wines_16)} ({100*(len(wines_16)-len(missing))//len(wines_16)}%)")
print()
print("First 30 missing:")
for r, k in missing[:30]:
    sc = r["score_20"]
    prod = r["producer"][:40]
    cuv = r["cuvee"][:40]
    print(f"  {sc:>5}  {prod:<42}  {cuv}")
