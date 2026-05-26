import sqlite3, json, os
from collections import Counter
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env", override=True)
DB_PATH = Path(__file__).parent.parent / os.getenv("DATABASE_URL", "data/achilles.db")

conn = sqlite3.connect(DB_PATH)
rows = conn.execute(
    "SELECT raw_record FROM ops_dead_letter WHERE error_class = 'unmatched_wine' ORDER BY rowid DESC LIMIT 2000"
).fetchall()

records = [json.loads(r[0]) for r in rows]
print(f"Total DLQ unmatched: {len(records)}")

producers = Counter(r.get("producer", "") for r in records)
print(f"Unique producers: {len(producers)}")

print("\nSample records:")
for r in records[:10]:
    print(f"  {r.get('producer','?')} / {r.get('cuvee','?')} v{r.get('vintage')} score={r.get('score')}")

apps = Counter(r.get("appellation", "") for r in records)
print("\nTop appellations:")
for app, cnt in apps.most_common(20):
    print(f"  {cnt:4d}  {app}")

# How many have all required fields?
complete = sum(1 for r in records if r.get("producer") and r.get("cuvee"))
print(f"\nRecords with producer+cuvee: {complete}/{len(records)}")

conn.close()
