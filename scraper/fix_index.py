import sqlite3
conn = sqlite3.connect('../data/achilles.db')
conn.execute("PRAGMA journal_mode=WAL")

# Check current indexes
indexes = conn.execute(
    "SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name='staging_price_candidates'"
).fetchall()
print("Current indexes on staging_price_candidates:")
for i in indexes:
    print(f"  {i[0]}: {i[1]}")

# Replace partial index with full UNIQUE index (matches Drizzle schema)
# SQLite treats NULL as distinct in UNIQUE indexes, so this is functionally equivalent
conn.execute("DROP INDEX IF EXISTS uix_staging_wine_source_hash")
conn.execute(
    "CREATE UNIQUE INDEX uix_staging_wine_source_hash "
    "ON staging_price_candidates(wine_key, source_key, content_hash)"
)
conn.commit()

print("\nAfter replacement:")
indexes2 = conn.execute(
    "SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name='staging_price_candidates'"
).fetchall()
for i in indexes2:
    print(f"  {i[0]}: {i[1]}")

# Verify no duplicates exist
dup_count = conn.execute("""
    SELECT COUNT(*) FROM (
        SELECT wine_key, source_key, content_hash
        FROM staging_price_candidates
        WHERE content_hash IS NOT NULL
        GROUP BY wine_key, source_key, content_hash
        HAVING COUNT(*) > 1
    )
""").fetchone()[0]
print(f"\nDuplicate (wine_key, source_key, content_hash) groups: {dup_count}")
conn.close()
print("Done.")
