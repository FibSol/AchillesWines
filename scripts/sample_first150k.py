"""Download and sample winemag-data_first150k.csv — print first 200 rows as a table."""
import tempfile, os, csv, zipfile
from kaggle.api.kaggle_api_extended import KaggleApi

api = KaggleApi()
api.authenticate()

DATASET = "zynicide/wine-reviews"
FNAME   = "winemag-data_first150k.csv"

with tempfile.TemporaryDirectory() as tmp:
    api.dataset_download_file(DATASET, FNAME, path=tmp, quiet=True)
    zpath = os.path.join(tmp, FNAME + ".zip")
    with zipfile.ZipFile(zpath) as z:
        z.extractall(tmp)
    csvpath = os.path.join(tmp, FNAME)
    with open(csvpath, encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = [r for _, r in zip(range(200), reader)]

cols = list(rows[0].keys()) if rows else []
print(f"Total columns ({len(cols)}): {cols}\n")

# Print 10 sample rows showing all fields
print("--- 10 sample rows ---")
for i, r in enumerate(rows[:10]):
    print(f"\nRow {i+1}:")
    for k, v in r.items():
        if v and k not in ('description',):
            print(f"  {k:30s} = {str(v)[:80]}")

# Stats on key fields across 200 rows
print("\n--- Field coverage across 200 rows ---")
for col in cols:
    filled = sum(1 for r in rows if r.get(col, '').strip())
    print(f"  {col:30s}: {filled}/200 filled")

# Check if any row has something that looks like a title (winery + year)
import re
print("\n--- Vintage extraction test (winery field, first 10 rows) ---")
for r in rows[:10]:
    winery = r.get('winery','')
    desig  = r.get('designation','')
    region = r.get('region_1','') or r.get('province','')
    variety= r.get('variety','')
    # Try to find a year in any field
    for field, val in r.items():
        m = re.search(r'\b(19[5-9]\d|20[0-3]\d)\b', val or '')
        if m:
            print(f"  vintage {m.group(1)} found in field '{field}': {str(val)[:60]}")
            break
    else:
        print(f"  no vintage found — winery={winery!r} desig={desig!r}")
