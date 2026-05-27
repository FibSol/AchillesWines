import json
from pathlib import Path

data = json.loads((Path(__file__).parent / "raw/rvf_pages/rvf_ratings_sorted.json").read_text(encoding="utf-8"))

# Deduplicate: keep highest score per (producer, cuvee)
seen = {}
for r in data:
    key = (r["producer"], r["cuvee"])
    if key not in seen or r["score_100"] > seen[key]["score_100"]:
        seen[key] = r

unique = sorted(seen.values(), key=lambda x: -x["score_100"])
print(f"Total unique wines: {len(unique)}")
print()
for i, r in enumerate(unique[:50], 1):
    v = r["vintage"] or "NV"
    print(f"{i:2}. {r['score_20']}/20  {r['producer']}  |  {r['cuvee']}  ({v})  [{r['appellation']}]")
