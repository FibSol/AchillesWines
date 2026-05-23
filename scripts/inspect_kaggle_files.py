"""Inspect the two Kaggle wine-reviews CSV files to see if they overlap or add data."""
import tempfile, os
from kaggle.api.kaggle_api_extended import KaggleApi
import csv, io

api = KaggleApi()
api.authenticate()

DATASET = "zynicide/wine-reviews"
FILES = ["winemag-data-130k-v2.csv", "winemag-data_first150k.csv"]

for fname in FILES:
    print(f"\n{'='*60}")
    print(f"File: {fname}")
    with tempfile.TemporaryDirectory() as tmp:
        api.dataset_download_file(DATASET, fname, path=tmp, quiet=False)
        # file may be zipped
        candidates = os.listdir(tmp)
        print(f"  Downloaded: {candidates}")
        # find the file
        for f in candidates:
            fpath = os.path.join(tmp, f)
            if f.endswith(".zip"):
                import zipfile
                with zipfile.ZipFile(fpath) as z:
                    z.extractall(tmp)
                candidates = [x for x in os.listdir(tmp) if not x.endswith(".zip")]
        for f in candidates:
            if f.endswith(".csv"):
                fpath = os.path.join(tmp, f)
                with open(fpath, encoding="utf-8") as fh:
                    reader = csv.DictReader(fh)
                    rows = list(reader)
                print(f"  Rows: {len(rows)}")
                print(f"  Columns: {list(rows[0].keys()) if rows else 'n/a'}")
                # Sample first row
                if rows:
                    r = rows[0]
                    print(f"  Sample: country={r.get('country')}, points={r.get('points')}, title={r.get('title','')[:60]}")
                # Check for columns unique to this file
                extra_cols = [k for k in (rows[0].keys() if rows else [])
                              if k not in ['','country','description','designation',
                                           'points','price','province','region_1',
                                           'region_2','taster_name','taster_twitter_handle',
                                           'title','variety','winery']]
                if extra_cols:
                    print(f"  Extra columns vs v2: {extra_cols}")
