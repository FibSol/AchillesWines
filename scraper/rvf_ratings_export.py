"""
Export all RVF fact_rating rows joined with wine/producer info,
sorted by score descending. Writes to raw/rvf_pages/rvf_ratings_sorted.json
and rvf_ratings_sorted.csv.
"""
import sqlite3, json, os, csv
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env", override=True)
DB_PATH = Path(__file__).parent.parent / os.getenv("DATABASE_URL", "data/achilles.db")
OUT_DIR  = Path(__file__).parent / "raw" / "rvf_pages"
OUT_JSON = OUT_DIR / "rvf_ratings_sorted.json"
OUT_CSV  = OUT_DIR / "rvf_ratings_sorted.csv"

conn = sqlite3.connect(DB_PATH)
rows = conn.execute("""
    SELECT
        fr.score,
        fr.scale,
        fr.score_normalized_100,
        w.vintage,
        w.cuvee_name,
        p.producer_name,
        a.appellation_name,
        w.color,
        fr.batch_id
    FROM fact_rating fr
    JOIN dim_wine      w ON w.wine_key        = fr.wine_key
    JOIN dim_producer  p ON p.producer_key    = w.producer_key
    LEFT JOIN dim_appellation a ON a.appellation_key = w.appellation_key
    WHERE fr.critic_code = 'RVF'
    ORDER BY fr.score_normalized_100 DESC, w.vintage DESC
""").fetchall()
conn.close()

cols = ["score_20", "scale", "score_100", "vintage", "cuvee", "producer", "appellation", "color", "batch_id"]
data = [dict(zip(cols, r)) for r in rows]

OUT_JSON.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"Wrote {len(data)} rows -> {OUT_JSON}")

with open(OUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=cols)
    w.writeheader()
    w.writerows(data)
print(f"Wrote {len(data)} rows -> {OUT_CSV}")

# Quick preview — top 20
print(f"\n{'Score':>6}  {'Vintage':>7}  {'Producer':<40}  {'Cuvee'}")
print("-" * 100)
for r in data[:20]:
    print(f"  {r['score_20']:>4}/20  {str(r['vintage'] or 'NV'):>6}  {r['producer']:<40}  {r['cuvee']}")
