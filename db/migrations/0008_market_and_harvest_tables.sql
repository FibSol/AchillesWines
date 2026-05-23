-- Migration 0008: market index + harvest volume tables
-- Supports EC Agri-food wine API and Eurostat tag00121 scrapers.

CREATE TABLE `fact_market_index` (
    `market_index_id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
    `source_key`      integer NOT NULL REFERENCES `dim_source`(`source_key`),
    `country_code`    text    NOT NULL,
    `wine_category`   text    NOT NULL,
    `price_eur_hl`    real    NOT NULL,
    `week_begin_date` text    NOT NULL,
    `week_end_date`   text    NOT NULL,
    `batch_id`        text    NOT NULL,
    `created_at`      integer NOT NULL DEFAULT (unixepoch())
);
CREATE INDEX       `idx_market_country_date` ON `fact_market_index` (`country_code`, `week_begin_date`);
CREATE INDEX       `idx_market_category`     ON `fact_market_index` (`wine_category`);
CREATE UNIQUE INDEX `idx_market_unique`      ON `fact_market_index` (`source_key`, `country_code`, `wine_category`, `week_begin_date`);

CREATE TABLE `fact_harvest_volume` (
    `harvest_id`         integer PRIMARY KEY AUTOINCREMENT NOT NULL,
    `source_key`         integer NOT NULL REFERENCES `dim_source`(`source_key`),
    `country_code`       text    NOT NULL,
    `year`               integer NOT NULL,
    `crop_type`          text    NOT NULL CHECK(`crop_type` IN ('all_grapes','wine_grapes','table_grapes','raisin_grapes')),
    `volume_1000_tonnes` real    NOT NULL,
    `batch_id`           text    NOT NULL,
    `created_at`         integer NOT NULL DEFAULT (unixepoch())
);
CREATE INDEX        `idx_harvest_country_year` ON `fact_harvest_volume` (`country_code`, `year`);
CREATE UNIQUE INDEX `idx_harvest_unique`       ON `fact_harvest_volume` (`source_key`, `country_code`, `year`, `crop_type`);

-- Seed new dim_source rows
INSERT OR IGNORE INTO `dim_source`
    (source_code, source_name, source_tier, country_code, base_url, license_class, cadence, requires_auth)
VALUES
    ('ec_agrifood',       'EC Agri-food Wine API',              'A_official',      NULL, 'https://api.tech.ec.europa.eu/agrifood', 'public_open',         'weekly',  0),
    ('eurostat_harvest',  'Eurostat Grape Harvest (tag00121)',   'A_official',      NULL, 'https://ec.europa.eu/eurostat',          'public_open',         'annual',  0),
    ('christies',         'Christie''s Wine & Spirits Auctions','B_retailer_major','GB', 'https://www.christies.com',              'public_check_terms',  'monthly', 0);
