import sqlite3, subprocess, sys
db = r'C:\Claude\achilles-wines\data\achilles.db'
c = sqlite3.connect(db)
r = c.execute("SELECT source_code,enabled,requires_auth FROM dim_source WHERE source_code='kaggle_reviews'").fetchone()
print('dim_source:', r if r else 'NOT IN dim_source')

# Check if kaggle library is installed
try:
    import kaggle
    print('kaggle lib: installed')
except ImportError:
    print('kaggle lib: NOT installed')
