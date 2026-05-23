import sqlite3
c = sqlite3.connect(r'C:\Claude\achilles-wines\data\achilles.db')
rows = c.execute("SELECT source_code FROM dim_source WHERE source_code LIKE 'kaggle%'").fetchall()
print(rows)
