"""Fix partially-applied migration 0014 and apply 0015."""
import sqlite3

conn = sqlite3.connect("data/achilles.db")
conn.row_factory = sqlite3.Row

# Check current state
tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
print("Tables before:", sorted(tables))

if "staging_rating_candidates_new" in tables and "staging_rating_candidates" not in tables:
    print("Completing migration 0014: renaming staging_rating_candidates_new")
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("ALTER TABLE staging_rating_candidates_new RENAME TO staging_rating_candidates")
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_staging_rating_wine
                    ON staging_rating_candidates (wine_key)""")
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_staging_rating_review
                    ON staging_rating_candidates (needs_review, recorded_at)""")
    conn.execute("""CREATE UNIQUE INDEX IF NOT EXISTS uix_staging_rating_wine_source_hash
                    ON staging_rating_candidates (wine_key, source_key, content_hash)
                    WHERE content_hash IS NOT NULL""")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.commit()
    print("Migration 0014 completed OK")

# Apply migration 0015
print("Applying migration 0015...")
sql = open("db/migrations/0015_vivino_source.sql").read()
conn.executescript(sql)
conn.commit()
print("Migration 0015 applied OK")

# Verify
tables_after = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
print("Tables after:", sorted(tables_after))

# Verify vivino dim_source
vivino = conn.execute("SELECT * FROM dim_source WHERE source_code='vivino'").fetchone()
print("Vivino dim_source:", dict(vivino) if vivino else "NOT FOUND")
conn.close()
