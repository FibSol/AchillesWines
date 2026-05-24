-- Migration 0014: staging_rating_candidates
-- Staging buffer for critic/user-aggregate rating rows that don't yet have
-- ≥2 distinct source_key values for their wine_key.  Mirrors fact_rating
-- columns plus needs_review and promotion tracking fields.

CREATE TABLE `staging_rating_candidates` (
    `candidate_id`               integer PRIMARY KEY AUTOINCREMENT NOT NULL,
    `wine_key`                   text    NOT NULL REFERENCES `dim_wine`(`wine_key`),
    `source_key`                 integer NOT NULL REFERENCES `dim_source`(`source_key`),
    `critic_code`                text    NOT NULL
        CHECK(`critic_code` IN ('WA','Vinous','BH','JMIB','RVF','Decanter','JS','JG','WS','Hachette','CT','XW','WE')),
    `reviewer_type`              text    NOT NULL
        CHECK(`reviewer_type` IN ('critic','user_aggregate')),
    `score`                      real    NOT NULL,
    `scale`                      text    NOT NULL
        CHECK(`scale` IN ('/100','/20','/5','stars')),
    `score_normalized_100`       real    NOT NULL,
    `rating_count`               integer,
    `recorded_at`                integer NOT NULL DEFAULT (unixepoch()),
    `source_url`                 text,
    `content_hash`               text,
    `batch_id`                   text    NOT NULL,
    -- Promotion tracking
    `needs_review`               integer NOT NULL DEFAULT 1,
    `promoted_to_fact_rating_key` integer,
    `promoted_at`                integer,
    CONSTRAINT `chk_staging_rating_normalized`
        CHECK(`score_normalized_100` BETWEEN 0 AND 100)
);

CREATE INDEX `idx_staging_rating_wine`
    ON `staging_rating_candidates` (`wine_key`);

CREATE INDEX `idx_staging_rating_review`
    ON `staging_rating_candidates` (`needs_review`, `recorded_at`);

-- Prevent duplicate inserts: same wine from same source with same content hash
CREATE UNIQUE INDEX `uix_staging_rating_wine_source_hash`
    ON `staging_rating_candidates` (`wine_key`, `source_key`, `content_hash`)
    WHERE `content_hash` IS NOT NULL;
