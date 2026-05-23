import sqlite3
conn = sqlite3.connect('../data/achilles.db')

# Check topwijnen_be duplicate issue
tw_key = conn.execute("SELECT source_key FROM dim_source WHERE source_code='topwijnen_be'").fetchone()[0]
total = conn.execute("SELECT COUNT(*) FROM staging_price_candidates WHERE source_key=?", (tw_key,)).fetchone()[0]
distinct_wines = conn.execute("SELECT COUNT(DISTINCT wine_key) FROM staging_price_candidates WHERE source_key=?", (tw_key,)).fetchone()[0]
distinct_hashes = conn.execute("SELECT COUNT(DISTINCT content_hash) FROM staging_price_candidates WHERE source_key=?", (tw_key,)).fetchone()[0]
print(f'topwijnen_be staging: {total} rows, {distinct_wines} distinct wine_keys, {distinct_hashes} distinct hashes')
print(f'Average rows per wine_key: {total/distinct_wines:.1f}')

# Check a specific wine_key that has many rows
rows = conn.execute("""SELECT wine_key, COUNT(*) as cnt
    FROM staging_price_candidates WHERE source_key=?
    GROUP BY wine_key ORDER BY cnt DESC LIMIT 5""", (tw_key,)).fetchall()
print('\nTop wine_keys by row count:')
for r in rows:
    # Get wine name
    w = conn.execute("SELECT canonical_name FROM dim_wine WHERE wine_key=?", (r[0],)).fetchone()
    name = w[0] if w else '?'
    # Get all prices for this wine from topwijnen_be
    prices = conn.execute("SELECT amount_eur, content_hash FROM staging_price_candidates WHERE wine_key=? AND source_key=? LIMIT 5", (r[0], tw_key)).fetchall()
    print(f'  [{r[0]}] {name[:50]}: {r[1]} rows')
    for p in prices: print(f'    EUR {p[0]} hash={p[1][:16]}')

# Check how many topwijnen_be job batches ran
batches = conn.execute("""SELECT DISTINCT batch_id FROM staging_price_candidates WHERE source_key=?""", (tw_key,)).fetchall()
print(f'\nBatches: {[b[0] for b in batches]}')
