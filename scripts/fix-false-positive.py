"""Revert the C'D'C' Rosso false positives from fix-cuvee-display-names.py"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "achilles.db"
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

wine_key = "0187d6c0c1952b8b"
cur.execute("SELECT wine_key, cuvee_name, canonical_name FROM dim_wine WHERE wine_key = ?", (wine_key,))
row = cur.fetchone()
print(f"Before: {row}")

cur.execute(
    "UPDATE dim_wine SET cuvee_name = \"C'D'C' Rosso\", canonical_name = \"Baglio del Cristo di Campobello C'D'C' Rosso\" WHERE wine_key = ?",
    (wine_key,),
)
conn.commit()

cur.execute("SELECT wine_key, cuvee_name, canonical_name FROM dim_wine WHERE wine_key = ?", (wine_key,))
print(f"After:  {cur.fetchone()}")
conn.close()
