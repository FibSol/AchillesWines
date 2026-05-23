-- Register CellarTracker as a crowd-aggregator critic source.
-- The scraper iterates wine.asp?iWine=N (1 .. ~6.5M) and writes
-- community average scores to fact_rating with critic_code='CT',
-- reviewer_type='crowd'.
--
-- requires_auth=1 because the wine summary pages return a degraded
-- (no-score) view to anonymous sessions on roughly 1/3 of wines.

INSERT OR IGNORE INTO `dim_source`
  (`source_code`, `source_name`, `source_tier`, `cadence`,
   `base_url`, `license_class`, `enabled`, `requires_auth`, `notes`)
VALUES
  ('cellartracker', 'CellarTracker', 'F_crowd_aggregator', 'on_demand',
   'https://www.cellartracker.com', 'public_check_terms', 1, 1,
   'Community wine DB. Sweep wine.asp?iWine=N with checkpoint cursor. CT 100-point scale.');
