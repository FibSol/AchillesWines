-- Migration 0009: WERC production stats table + expanded criticCode enum
-- Adds crowd-source critic codes: XW (X-Wines/Vivino), WE (WineEnthusiast/Kaggle)

-- ─── 1. fact_werc_stats ──────────────────────────────────────────────────────
-- Stores selected WERC megafile metrics (vine area, wine production) in
-- a narrow EAV format so new sheets can be added without schema changes.
CREATE TABLE `fact_werc_stats` (
    `stat_id`       integer PRIMARY KEY AUTOINCREMENT NOT NULL,
    `source_key`    integer NOT NULL REFERENCES `dim_source`(`source_key`),
    `country_code`  text    NOT NULL,
    `year`          integer NOT NULL,
    `metric`        text    NOT NULL,   -- 'vine_area_kha' | 'wine_production_kl'
    `value`         real    NOT NULL,
    `unit`          text    NOT NULL,
    `batch_id`      text    NOT NULL,
    `created_at`    integer NOT NULL DEFAULT (unixepoch())
);
CREATE UNIQUE INDEX `idx_werc_unique`       ON `fact_werc_stats` (`country_code`, `year`, `metric`);
CREATE        INDEX `idx_werc_country_year` ON `fact_werc_stats` (`country_code`, `year`);
CREATE        INDEX `idx_werc_metric`       ON `fact_werc_stats` (`metric`);

-- ─── 2. Expand fact_rating.critic_code to include XW and WE ─────────────────
-- SQLite does not support ALTER TABLE ... MODIFY COLUMN.
-- Standard workaround: rename → rebuild → copy → drop old.
PRAGMA foreign_keys = OFF;

CREATE TABLE `fact_rating_new` (
    `rating_event_key`    integer PRIMARY KEY AUTOINCREMENT NOT NULL,
    `wine_key`            text    NOT NULL REFERENCES `dim_wine`(`wine_key`),
    `source_key`          integer NOT NULL REFERENCES `dim_source`(`source_key`),
    `critic_code`         text    NOT NULL
        CHECK(`critic_code` IN ('WA','Vinous','BH','JMIB','RVF','Decanter','JS','JG','WS','Hachette','CT','XW','WE')),
    `reviewer_type`       text    NOT NULL
        CHECK(`reviewer_type` IN ('critic','user_aggregate')),
    `score`               real    NOT NULL,
    `scale`               text    NOT NULL
        CHECK(`scale` IN ('/100','/20','/5','stars')),
    `score_normalized_100` real   NOT NULL,
    `rating_count`        integer,
    `recorded_at`         integer NOT NULL DEFAULT (unixepoch()),
    `source_url`          text,
    `content_hash`        text,
    `batch_id`            text    NOT NULL,
    CONSTRAINT `chk_rating_normalized_range`
        CHECK(`score_normalized_100` BETWEEN 0 AND 100)
);

INSERT INTO `fact_rating_new`
    SELECT `rating_event_key`, `wine_key`, `source_key`, `critic_code`,
           `reviewer_type`, `score`, `scale`, `score_normalized_100`,
           `rating_count`, `recorded_at`, `source_url`, `content_hash`, `batch_id`
    FROM `fact_rating`;

DROP TABLE `fact_rating`;
ALTER TABLE `fact_rating_new` RENAME TO `fact_rating`;

CREATE INDEX `idx_rating_wine`        ON `fact_rating` (`wine_key`);
CREATE INDEX `idx_rating_critic`      ON `fact_rating` (`critic_code`);
CREATE INDEX `idx_rating_wine_critic` ON `fact_rating` (`wine_key`, `critic_code`);

PRAGMA foreign_keys = ON;

-- ─── 3. Seed dim_source rows ─────────────────────────────────────────────────
INSERT OR IGNORE INTO `dim_source`
    (source_code, source_name, source_tier, country_code, base_url, license_class, cadence, requires_auth)
VALUES
    ('werc',           'WERC Global Wine Markets 1835-2024',     'A_official',    NULL, 'https://economics.adelaide.edu.au/wine-economics', 'public_open',         'annual',   0),
    ('xwines',         'X-Wines (Vivino crowd ratings)',         'D_user_aggregate', NULL, 'https://github.com/rogerioxavier/X-Wines',         'public_open',         'annual',   0),
    ('kaggle_reviews', 'Kaggle WineEnthusiast Reviews',         'D_user_aggregate', NULL, 'https://www.kaggle.com/datasets/zynicide/wine-reviews', 'public_check_terms', 'one_shot', 0);
