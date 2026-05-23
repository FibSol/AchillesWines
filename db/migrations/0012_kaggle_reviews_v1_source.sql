-- Register WineEnthusiast first-150k dataset (v1 schema, no title column) as a
-- separate dim_source. The v2 dataset (kaggle_reviews) has taster names and title;
-- the v1 has winery/designation/variety/region_1/price only — 150,930 rows.
-- Prices from v1 are also written to staging_price_candidates as editorial context.

INSERT OR IGNORE INTO `dim_source`
  (`source_code`, `source_name`, `source_tier`, `cadence`,
   `base_url`, `license_class`, `enabled`, `requires_auth`, `notes`)
VALUES
  ('kaggle_reviews_v1', 'WineEnthusiast 150k (Kaggle v1)', 'D_user_aggregate', 'one_shot',
   'https://www.kaggle.com/datasets/zynicide/wine-reviews', 'cc_by_nc_sa_4',
   1, 0,
   'Kaggle zynicide/wine-reviews — winemag-data_first150k.csv. 150,930 rows. No title column; vintage always NV. CC BY-NC-SA 4.0.');
