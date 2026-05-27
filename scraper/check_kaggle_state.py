import sqlite3
conn = sqlite3.connect('../data/achilles.db')

# Check staging_price_candidates for Kaggle rows
staging = conn.execute(
    "SELECT COUNT(*) FROM staging_price_candidates WHERE source_key=41"
).fetchone()[0]
print(f"staging_price_candidates source_key=41: {staging}")

# Check fact_rating for Kaggle reviews
ratings = conn.execute(
    "SELECT COUNT(*) FROM fact_rating WHERE source_key=41"
).fetchone()[0]
print(f"fact_rating source_key=41: {ratings}")

# Source info
src = conn.execute("SELECT source_key, source_code, source_name FROM dim_source WHERE source_key=41").fetchone()
print(f"source_key=41: {src}")

conn.close()
