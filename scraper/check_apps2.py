import sqlite3
conn = sqlite3.connect('../data/achilles.db')

searches = [
    ('saumur', 'Saumur/Saumur-Champigny'),
    ('saint.est', 'Saint-Estephe'),
    ('chinian', 'Saint-Chinian'),
    ('saint.ver', 'Saint-Veran'),
    ('laudun', 'Laudun'),
    ('ajaccio', 'Ajaccio'),
    ('bordeaux', 'Bordeaux'),
]

for pattern, label in searches:
    import re
    rows = conn.execute(
        "SELECT appellation_key, appellation_norm, appellation_name FROM dim_appellation WHERE appellation_norm LIKE ? ORDER BY appellation_key LIMIT 5",
        (f'%{pattern.replace(".", "_")}%',)
    ).fetchall()
    print(f'\n{label}:')
    for r in rows:
        print(f'  key={r[0]}: {r[2]!r}')

conn.close()
