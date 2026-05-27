import sqlite3
conn = sqlite3.connect('../data/achilles.db')
rows = conn.execute("SELECT appellation_key, appellation_name FROM dim_appellation WHERE appellation_norm='macon' LIMIT 3").fetchall()
print('Macon exact:', rows)
rows2 = conn.execute("SELECT appellation_key, appellation_name FROM dim_appellation WHERE appellation_name='Macon' LIMIT 3").fetchall()
print('Macon display:', rows2)
conn.close()
