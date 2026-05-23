-- Add UNIQUE INDEX to staging_price_candidates to prevent duplicate inserts.
-- Root cause: scrapers running multi-page catalogues would insert the same
-- product multiple times (catalogue pages overlap, or scraper runs multiple times).
-- The INSERT OR IGNORE in the Python scrapers now correctly deduplicates.
-- SQLite treats NULL values as distinct in UNIQUE indexes, so rows without a
-- content_hash (content_hash IS NULL) are never blocked by this constraint.
CREATE UNIQUE INDEX IF NOT EXISTS `uix_staging_wine_source_hash`
  ON `staging_price_candidates` (`wine_key`, `source_key`, `content_hash`);
