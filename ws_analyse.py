import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from scraper.achilles_scraper.config import config
from scraper.achilles_scraper.db import get_db
from datetime import datetime, timezone
config.ensure_dirs()
conn = get_db(config.db_path)

now    = int(datetime.now(timezone.utc).timestamp())
cutoff = now - 30 * 86400
src    = conn.execute("SELECT source_key FROM dim_source WHERE source_code='wine_searcher'").fetchone()
source_key = src[0]

done      = conn.execute("SELECT COUNT(*) FROM ops_content_hashes WHERE url LIKE 'ws_cuvee:%' AND source_key=? AND last_fetched_at>=?", (source_key, cutoff)).fetchone()[0]
total_q   = 19838
remaining = total_q - done

staging = conn.execute("""
    SELECT COUNT(*) rows,
           COUNT(DISTINCT spc.wine_key) wines,
           COUNT(DISTINCT spc.retailer) retailers,
           MIN(spc.amount_eur) min_eur,
           MAX(spc.amount_eur) max_eur,
           AVG(spc.amount_eur) avg_eur
    FROM staging_price_candidates spc
    JOIN dim_source ds ON ds.source_key = spc.source_key
    WHERE ds.source_code = 'wine_searcher'
""").fetchone()

hits = conn.execute("""
    SELECT COUNT(DISTINCT p.producer_norm || '|' || COALESCE(w.cuvee_norm,''))
    FROM staging_price_candidates spc
    JOIN dim_wine w ON w.wine_key = spc.wine_key
    JOIN dim_producer p ON p.producer_key = w.producer_key
    JOIN dim_source ds ON ds.source_key = spc.source_key
    WHERE ds.source_code = 'wine_searcher'
      AND spc.retailer != 'wine-searcher.com'
""").fetchone()[0]

old_rows = conn.execute("""
    SELECT COUNT(*) FROM staging_price_candidates spc
    JOIN dim_source ds ON ds.source_key = spc.source_key
    WHERE ds.source_code = 'wine_searcher' AND spc.retailer = 'wine-searcher.com'
""").fetchone()[0]

retailers = conn.execute("""
    SELECT spc.retailer, COUNT(*) n
    FROM staging_price_candidates spc
    JOIN dim_source ds ON ds.source_key = spc.source_key
    WHERE ds.source_code = 'wine_searcher' AND spc.retailer != 'wine-searcher.com'
    GROUP BY spc.retailer ORDER BY n DESC LIMIT 12
""").fetchall()

top_wines = conn.execute("""
    SELECT p.producer_name, w.cuvee_name, w.vintage,
           COUNT(*) offers,
           ROUND(MIN(spc.amount_eur)) min_eur,
           ROUND(MAX(spc.amount_eur)) max_eur
    FROM staging_price_candidates spc
    JOIN dim_wine w ON w.wine_key = spc.wine_key
    JOIN dim_producer p ON p.producer_key = w.producer_key
    JOIN dim_source ds ON ds.source_key = spc.source_key
    WHERE ds.source_code = 'wine_searcher' AND spc.retailer != 'wine-searcher.com'
    GROUP BY spc.wine_key ORDER BY offers DESC LIMIT 12
""").fetchall()

dlq = conn.execute("""
    SELECT error_class, COUNT(*) n FROM ops_dead_letter
    WHERE source_key = ? GROUP BY error_class ORDER BY n DESC
""", (source_key,)).fetchall()

# Price distribution buckets
buckets = conn.execute("""
    SELECT
      COUNT(CASE WHEN amount_eur < 20   THEN 1 END) under20,
      COUNT(CASE WHEN amount_eur < 50   AND amount_eur >= 20  THEN 1 END) b20_50,
      COUNT(CASE WHEN amount_eur < 100  AND amount_eur >= 50  THEN 1 END) b50_100,
      COUNT(CASE WHEN amount_eur < 200  AND amount_eur >= 100 THEN 1 END) b100_200,
      COUNT(CASE WHEN amount_eur >= 200 THEN 1 END) over200
    FROM staging_price_candidates spc
    JOIN dim_source ds ON ds.source_key = spc.source_key
    WHERE ds.source_code = 'wine_searcher' AND spc.retailer != 'wine-searcher.com'
""").fetchone()

print("=" * 62)
print("  WINE-SEARCHER SCRAPE — LIVE ANALYSIS")
print("=" * 62)
print(f"\n  PROGRESS")
print(f"  Cuvees attempted : {done:,} / {total_q:,}  ({done/total_q*100:.1f}%)")
print(f"  Remaining        : {remaining:,}  (~{remaining*2/3600:.1f}h at 2s/cuvee)")

print(f"\n  STAGING CANDIDATES  (excl. {old_rows} legacy avg-price rows)")
real_rows = (staging[0] or 0) - old_rows
print(f"  Price rows       : {real_rows:,}")
print(f"  Distinct wines   : {staging[1]:,}")
print(f"  Distinct retailers: {staging[2]:,}")
if staging[3]:
    print(f"  Price range      : EUR {staging[3]:.0f} - {staging[4]:.0f}  (avg EUR {staging[5]:.0f})")

print(f"\n  HIT RATE")
print(f"  Cuvees with results : {hits:,} / {done:,}  ({hits/done*100:.1f}%)" if done else "  No data")
proj_hits = int(hits / done * total_q) if done else 0
print(f"  Projected total hits: ~{proj_hits:,} cuvees with WS data")

print(f"\n  PRICE DISTRIBUTION (real merchant rows)")
total_real = sum(buckets)
if total_real:
    print(f"  < EUR 20   : {buckets[0]:4}  ({buckets[0]/total_real*100:.0f}%)")
    print(f"  EUR 20-50  : {buckets[1]:4}  ({buckets[1]/total_real*100:.0f}%)")
    print(f"  EUR 50-100 : {buckets[2]:4}  ({buckets[2]/total_real*100:.0f}%)")
    print(f"  EUR 100-200: {buckets[3]:4}  ({buckets[3]/total_real*100:.0f}%)")
    print(f"  > EUR 200  : {buckets[4]:4}  ({buckets[4]/total_real*100:.0f}%)")

print(f"\n  TOP RETAILERS")
for r in retailers:
    bar = "#" * (r[1] // 5)
    print(f"  {r[0][:38]:38} {r[1]:4}  {bar}")

print(f"\n  TOP WINES BY OFFER COUNT")
for r in top_wines:
    print(f"  {r[0][:28]:28} {str(r[1] or '')[:22]:22} {str(r[2] or 'NV'):4}  {r[3]} offers  EUR {r[4]:.0f}-{r[5]:.0f}")

print(f"\n  DLQ")
if dlq:
    for r in dlq:
        print(f"  {r[0]:30} {r[1]:4}")
else:
    print("  (none)")
print()
