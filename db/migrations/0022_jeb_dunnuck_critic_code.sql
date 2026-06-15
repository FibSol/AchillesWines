-- Migration 0022: Add JD (Jeb Dunnuck) critic code.
--
-- Jeb Dunnuck previously had no proper code — he was misattributed to 'JG',
-- which is actually John Gilman / View from the Cellar (CT export column 'JG').
-- This migration adds 'JD' to the fact_rating and staging_rating_candidates
-- CHECK constraints. 'JD' is one of the six official primary-tier critics
-- (WA, Vinous, JD, JMIB, RVF, Hachette) — see lib/critics.ts.
--
-- SQLite does not support ALTER TABLE ... MODIFY COLUMN for CHECK constraints.
-- Standard workaround: rename → rebuild → copy → drop old.

PRAGMA foreign_keys = OFF;

-- ─── 1. Expand fact_rating CHECK to include JD ───────────────────────────────
CREATE TABLE `fact_rating_new` (
    `rating_event_key`    integer PRIMARY KEY AUTOINCREMENT NOT NULL,
    `wine_key`            text    NOT NULL REFERENCES `dim_wine`(`wine_key`),
    `source_key`          integer NOT NULL REFERENCES `dim_source`(`source_key`),
    `critic_code`         text    NOT NULL
        CHECK(`critic_code` IN ('WA','Vinous','BH','JMIB','RVF','Decanter','JS','JG','JD','WS','Hachette','CT','XW','WE','VI','SM')),
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

-- ─── 2. Expand staging_rating_candidates CHECK to include JD ─────────────────
CREATE TABLE `staging_rating_candidates_new` (
    `candidate_id`                 integer PRIMARY KEY AUTOINCREMENT NOT NULL,
    `wine_key`                     text    NOT NULL REFERENCES `dim_wine`(`wine_key`),
    `source_key`                   integer NOT NULL REFERENCES `dim_source`(`source_key`),
    `critic_code`                  text    NOT NULL
        CHECK(`critic_code` IN ('WA','Vinous','BH','JMIB','RVF','Decanter','JS','JG','JD','WS','Hachette','CT','XW','WE','VI','SM')),
    `reviewer_type`                text    NOT NULL
        CHECK(`reviewer_type` IN ('critic','user_aggregate')),
    `score`                        real    NOT NULL,
    `scale`                        text    NOT NULL
        CHECK(`scale` IN ('/100','/20','/5','stars')),
    `score_normalized_100`         real    NOT NULL,
    `rating_count`                 integer,
    `recorded_at`                  integer NOT NULL DEFAULT (unixepoch()),
    `source_url`                   text,
    `content_hash`                 text,
    `batch_id`                     text    NOT NULL,
    `needs_review`                 integer NOT NULL DEFAULT 1,
    `promoted_to_fact_rating_key`  integer,
    `promoted_at`                  integer,
    CONSTRAINT `chk_staging_normalized_range`
        CHECK(`score_normalized_100` BETWEEN 0 AND 100)
);

INSERT INTO `staging_rating_candidates_new`
    SELECT `candidate_id`, `wine_key`, `source_key`, `critic_code`,
           `reviewer_type`, `score`, `scale`, `score_normalized_100`,
           `rating_count`, `recorded_at`, `source_url`, `content_hash`, `batch_id`,
           `needs_review`, `promoted_to_fact_rating_key`, `promoted_at`
    FROM `staging_rating_candidates`;

DROP TABLE `staging_rating_candidates`;
ALTER TABLE `staging_rating_candidates_new` RENAME TO `staging_rating_candidates`;

CREATE INDEX `idx_staging_wine`    ON `staging_rating_candidates` (`wine_key`);
CREATE INDEX `idx_staging_critic`  ON `staging_rating_candidates` (`critic_code`);
CREATE INDEX `idx_staging_pending` ON `staging_rating_candidates` (`needs_review`, `promoted_at`);
CREATE UNIQUE INDEX IF NOT EXISTS `idx_staging_dedup`
    ON `staging_rating_candidates` (`wine_key`, `source_key`, `content_hash`);

PRAGMA foreign_keys = ON;
