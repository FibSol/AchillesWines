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

print(f"{'#':>3}  {'Score':>6}  {'Price':>9}  {'OK?':<4}  Source snippet")
print("-" * 110)
for i, r in enumerate(unique[:50], 1):
    k = f"{r['producer']}|{r['cuvee']}"
    e = master.get(k)
    if e and e["price_eur"] != "not found":
        src   = e.get("source_url", "")
        snip  = e.get("snippet", "")[:90]
        print(f"{i:>3}  {r['score_20']:>6}  {e['price_eur']:>9}  ???   {snip}")
    else:
        print(f"{i:>3}  {r['score_20']:>6}  {'—':>9}       {r['producer'][:40]} — {r['cuvee'][:40]}")
