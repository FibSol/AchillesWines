import sqlite3
conn = sqlite3.connect('../data/achilles.db')

print('Tarn/IGP appellations:')
for r in conn.execute("SELECT appellation_key, appellation_norm, appellation_name FROM dim_appellation WHERE appellation_norm LIKE '%tarn%'").fetchall():
    print(f'  {r[0]}: {r[2]!r}')

print('\nVin de France / VdF:')
for r in conn.execute("SELECT appellation_key, appellation_norm, appellation_name FROM dim_appellation WHERE appellation_norm LIKE '%vin de france%' LIMIT 3").fetchall():
    print(f'  {r[0]}: {r[2]!r}')

print('\nGaillac (confirm):')
for r in conn.execute("SELECT appellation_key, appellation_norm, appellation_name FROM dim_appellation WHERE appellation_norm LIKE '%gaillac%'").fetchall():
    print(f'  {r[0]}: {r[2]!r}')
conn.close()
