import sqlite3
conn = sqlite3.connect('../data/achilles.db')
tw_key = conn.execute(
    "SELECT source_key FROM dim_source WHERE source_code='topwijnen_be'"
).fetchone()[0]

# Sample topwijnen_be dups
sample = conn.execute("""
    SELECT wine_key, content_hash, COUNT(*) as cnt
    FROM staging_price_candidates WHERE source_key=?
    GROUP BY wine_key, content_hash HAVING COUNT(*) > 1
    LIMIT 5
""", (tw_key,)).fetchall()
print("Sample topwijnen_be remaining dups (wine_key, content_hash, count):")
for r in sample:
    rows = conn.execute(
        "SELECT candidate_id, amount_eur, batch_id FROM staging_price_candidates "
        "WHERE wine_key=? AND source_key=? AND content_hash=?",
        (r[0], tw_key, r[1])
    ).fetchall()
    print(f"  wine={r[0][:20]} hash={str(r[1])[:20]} cnt={r[2]}")
    for row in rows[:3]:
        print(f"    id={row[0]} price={row[1]} batch={str(row[2])[:20]}")

# How many distinct batches for topwijnen_be?
batches = conn.execute(
    "SELECT DISTINCT batch_id FROM staging_price_candidates WHERE source_key=?", (tw_key,)
).fetchall()
print(f"\nDistinct batches for topwijnen_be: {len(batches)}")
for b in batches[:5]:
    print(f"  {b[0]}")

# Total topwijnen_be rows
total = conn.execute(
    "SELECT COUNT(*) FROM staging_price_candidates WHERE source_key=?", (tw_key,)
).fetchone()[0]
distinct_hash = conn.execute(
    "SELECT COUNT(DISTINCT content_hash) FROM staging_price_candidates WHERE source_key=?", (tw_key,)
).fetchone()[0]
print(f"\nTotal topwijnen_be staging rows: {total}")
print(f"Distinct content_hashes: {distinct_hash}")
print(f"Ratio: {total/distinct_hash:.2f}x")

# Is the dedup correct? Check if same wine_key appears with different hashes
multi_hash = conn.execute("""
    SELECT wine_key, COUNT(DISTINCT content_hash) as nhash
    FROM staging_price_candidates WHERE source_key=?
    GROUP BY wine_key HAVING nhash > 1
    LIMIT 5
""", (tw_key,)).fetchall()
print(f"\nWine_keys with multiple different hashes: {len(multi_hash)}")
for r in multi_hash[:3]:
    print(f"  wine={r[0][:20]} distinct_hashes={r[1]}")
