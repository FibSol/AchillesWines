"""
Analyse DLQ unmatched records for data quality before bulk-inserting into dim_wine.
"""
import sqlite3, json, os
from collections import Counter
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env", override=True)
DB_PATH = Path(__file__).parent.parent / os.getenv("DATABASE_URL", "data/achilles.db")

conn = sqlite3.connect(DB_PATH)
rows = conn.execute(
    "SELECT raw_record FROM ops_dead_letter WHERE error_class = 'unmatched_wine'"
).fetchall()
records = [json.loads(r[0]) for r in rows]

# ── 1. Suspicious score patterns ─────────────────────────────────────────────
def is_bad_score(s):
    """Score looks like two numbers run together (e.g. 92.94 = 92 and 94)."""
    if s is None:
        return False
    # Decimal part >= .5 after /5 normalisation is usually a concatenation artefact
    frac = s - int(s)
    return frac >= 0.5 and int(s) > 20   # e.g. 92.94 → suspicious

bad_scores = [r for r in records if is_bad_score(r.get("score"))]
print(f"Records with concatenated-looking scores: {len(bad_scores)}")
for r in bad_scores[:5]:
    print(f"  {r['producer']} / {r['cuvee']}  score={r['score']}")

# ── 2. Cuvée == producer (extraction error) ───────────────────────────────────
import unicodedata
def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return s.lower().strip()

same_name = [r for r in records if norm(r.get("producer","")) == norm(r.get("cuvee",""))]
print(f"\nRecords where cuvee == producer: {len(same_name)}")

# ── 3. Repeated cuvée names (section headers misread as cuvée) ────────────────
cuvees = Counter(r.get("cuvee","") for r in records)
print(f"\nCuvee names appearing 3+ times across different producers:")
for name, cnt in cuvees.most_common(20):
    if cnt >= 3:
        print(f"  {cnt}x  {name!r}")

# ── 4. Clean records ──────────────────────────────────────────────────────────
def is_clean(r):
    if is_bad_score(r.get("score")):
        return False
    if norm(r.get("producer","")) == norm(r.get("cuvee","")):
        return False
    return True

clean = [r for r in records if is_clean(r)]
print(f"\nClean records (would attempt to insert): {len(clean)}/{len(records)}")

# How many producers already exist in dim_producer?
all_producers = [r["producer"] for r in clean]
# Sample first 10 clean records
print("\nSample clean records:")
for r in clean[:10]:
    print(f"  {r['producer']} / {r['cuvee']} v{r.get('vintage')} score={r.get('score')} app={r.get('appellation')}")

conn.close()
