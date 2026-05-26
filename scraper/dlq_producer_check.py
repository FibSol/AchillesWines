"""
Check DLQ records: how many producers exist in dim_producer but their wines
aren't in dim_wine (vintage mismatch vs. completely unknown producer)?
"""
import sqlite3, json, os, unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from dotenv import load_dotenv
from rapidfuzz import fuzz

load_dotenv(Path(__file__).parent.parent / ".env", override=True)
DB_PATH = Path(__file__).parent.parent / os.getenv("DATABASE_URL", "data/achilles.db")

def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return s.lower().strip()

def is_bad_score(s):
    if s is None:
        return False
    frac = s - int(s)
    return frac >= 0.5 and int(s) > 20

# Known section-header cuvee names (appearing 5+ times across different producers)
HEADER_CUVEES = {
    "bourgogne", "vin de france", "languedoc", "macon", "macon et macon-villages",
    "chateauneuf-du-pape", "sancerre", "pouilly-fume", "cotes du rhone",
    "cotes du roussillon", "mondeuse", "arbois-pupillin rouge", "madiran",
    "pouilly-fuisse", "pouilly-loche", "chianti classico", "grand cru clos",
    "ile de la reunion",
}

conn = sqlite3.connect(DB_PATH)

# Load DLQ
rows = conn.execute(
    "SELECT raw_record FROM ops_dead_letter WHERE error_class = 'unmatched_wine'"
).fetchall()
records = [json.loads(r[0]) for r in rows]

# Filter to clean records
def is_clean(r):
    if is_bad_score(r.get("score")):
        return False
    if norm(r.get("producer","")) == norm(r.get("cuvee","")):
        return False
    cuvee_n = norm(r.get("cuvee",""))
    if cuvee_n in HEADER_CUVEES:
        return False
    return True

clean = [r for r in records if is_clean(r)]
print(f"Clean DLQ records: {len(clean)}")

# Load dim_producer for fuzzy check
db_producers = conn.execute(
    "SELECT producer_key, producer_norm, producer_name FROM dim_producer"
).fetchall()
print(f"dim_producer rows: {len(db_producers)}")

THRESH = 85  # higher threshold for producer-only check
matched_prod = 0
unknown_prod = 0
unknown_samples = []

for r in clean:
    p_norm = norm(r.get("producer",""))
    best = max(db_producers, key=lambda x: fuzz.token_sort_ratio(p_norm, x[1]))
    best_score = fuzz.token_sort_ratio(p_norm, best[1])
    if best_score >= THRESH:
        matched_prod += 1
    else:
        unknown_prod += 1
        if len(unknown_samples) < 15:
            unknown_samples.append((r.get("producer",""), r.get("appellation",""), best_score, best[2]))

print(f"\nProducer already in dim_producer (score>=85): {matched_prod}")
print(f"Producer NOT in dim_producer:                  {unknown_prod}")

print("\nSample unknown producers (not in DB):")
for prod, app, score, closest in unknown_samples:
    print(f"  {prod!r:40s} app={app!r:20s}  closest={closest!r} ({score})")

conn.close()
