import json, sys
from pathlib import Path

start = int(sys.argv[1]) if len(sys.argv) > 1 else 51
end   = int(sys.argv[2]) if len(sys.argv) > 2 else 150

data = json.loads((Path(__file__).parent / "raw/rvf_pages/rvf_ratings_sorted.json").read_text(encoding="utf-8"))
seen = {}
for r in data:
    key = (r["producer"], r["cuvee"])
    if key not in seen or r["score_100"] > seen[key]["score_100"]:
        seen[key] = r
unique = sorted(seen.values(), key=lambda x: -x["score_100"])
print(f"Total unique: {len(unique)}")
for i, r in enumerate(unique[start-1:end], start):
    v = r["vintage"] or "NV"
    sc = r["score_20"]
    prod = r["producer"][:45]
    cuv  = r["cuvee"][:50]
    app  = r["appellation"] or ""
    print(f"{i:3}. {sc}/20  {prod:<45}  {cuv:<50}  ({v})  [{app}]")
