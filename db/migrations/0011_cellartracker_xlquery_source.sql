-- Register CellarTracker's official xlquery.asp data-export endpoint as a
-- separate source. Unlike the iWine-sweep scraper (cellartracker), this one
-- bypasses Kasada entirely and pulls 30+ pre-aggregated critic scores per
-- wine for wines in the logged-in user's CT cellar.
--
-- Discovered via getcontent.asp (Partner Integrations page) — CT openly
-- exposes this endpoint for partner sync apps (mobile, 3rd-party trackers).

INSERT OR IGNORE INTO `dim_source`
  (`source_code`, `source_name`, `source_tier`, `cadence`,
   `base_url`, `license_class`, `enabled`, `requires_auth`, `notes`)
VALUES
  ('cellartracker_xlquery', 'CellarTracker (xlquery)', 'F_crowd_aggregator', 'on_demand',
   'https://www.cellartracker.com', 'public_check_terms', 1, 1,
   'Official partner data-export. xlquery.asp?Format=tab&Table={List|Inventory|Notes}. One row per cellar wine with WA/WS/AG/JR/BH/DR/JS/JM/JH/WAL/WD/JG/GV/CT scores pre-aggregated. Bypasses Kasada.');
