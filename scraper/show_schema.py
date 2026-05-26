import sqlite3, os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env", override=True)
DB_PATH = Path(__file__).parent.parent / os.getenv("DATABASE_URL", "data/achilles.db")
conn = sqlite3.connect(DB_PATH)
for t in ["dim_wine", "dim_producer", "dim_appellation"]:
    print(conn.execute(f"SELECT sql FROM sqlite_master WHERE name='{t}'").fetchone()[0])
    print()
conn.close()
