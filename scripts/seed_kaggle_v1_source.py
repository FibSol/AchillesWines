import sqlite3
c = sqlite3.connect(r'C:\Claude\achilles-wines\data\achilles.db')
c.execute("""INSERT OR IGNORE INTO dim_source
  (source_code, source_name, source_tier, cadence, base_url, license_class, enabled, requires_auth, notes)
  VALUES (?,?,?,?,?,?,?,?,?)""",
  ('kaggle_reviews_v1', 'WineEnthusiast 150k (Kaggle v1)', 'D_user_aggregate', 'one_shot',
   'https://www.kaggle.com/datasets/zynicide/wine-reviews', 'cc_by_nc_sa_4', 1, 0,
   'Kaggle zynicide/wine-reviews — winemag-data_first150k.csv. 150,930 rows. No title column; vintage always NV. CC BY-NC-SA 4.0.'))
c.commit()
row = c.execute("SELECT source_key, source_code FROM dim_source WHERE source_code='kaggle_reviews_v1'").fetchone()
print('seeded:', row)
