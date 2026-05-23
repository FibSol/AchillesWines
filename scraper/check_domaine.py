import sqlite3
conn = sqlite3.connect('../data/achilles.db')

# Find a producer with fact_price data
rows = conn.execute("""
    SELECT dp.producer_name, dp.producer_key, COUNT(DISTINCT fp.wine_key) as wines, COUNT(fp.price_event_key) as prices
    FROM fact_price fp
    JOIN dim_wine dw ON dw.wine_key = fp.wine_key
    JOIN dim_producer dp ON dp.producer_key = dw.producer_key
    GROUP BY dp.producer_key
    ORDER BY prices DESC
    LIMIT 10
""").fetchall()
print('Producers with most fact_price data:')
for r in rows:
    print(f'  [{r[1]}] {r[0]}: {r[2]} wines, {r[3]} price records')
