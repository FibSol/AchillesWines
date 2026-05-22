CREATE TABLE `bridge_wine_variety` (
	`wine_key` text NOT NULL,
	`variety_key` integer NOT NULL,
	`share_pct` real,
	`source_confidence` real,
	PRIMARY KEY(`wine_key`, `variety_key`),
	FOREIGN KEY (`wine_key`) REFERENCES `dim_wine`(`wine_key`) ON UPDATE no action ON DELETE no action,
	FOREIGN KEY (`variety_key`) REFERENCES `dim_variety`(`variety_key`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE TABLE `cellar_consumption` (
	`consumption_id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`wine_key` text NOT NULL,
	`location_id` integer,
	`consumed_at` integer DEFAULT (unixepoch()) NOT NULL,
	`qty` integer DEFAULT 1 NOT NULL,
	`personal_score` integer,
	`occasion` text,
	`tasting_note` text,
	FOREIGN KEY (`wine_key`) REFERENCES `dim_wine`(`wine_key`) ON UPDATE no action ON DELETE no action,
	FOREIGN KEY (`location_id`) REFERENCES `cellar_locations`(`location_id`) ON UPDATE no action ON DELETE no action,
	CONSTRAINT "chk_consumption_score_range" CHECK("cellar_consumption"."personal_score" IS NULL OR ("cellar_consumption"."personal_score" BETWEEN 0 AND 100))
);
--> statement-breakpoint
CREATE INDEX `idx_consumption_date` ON `cellar_consumption` (`consumed_at`);--> statement-breakpoint
CREATE INDEX `idx_consumption_wine` ON `cellar_consumption` (`wine_key`);--> statement-breakpoint
CREATE TABLE `cellar_inventory` (
	`inventory_id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`wine_key` text NOT NULL,
	`location_id` integer NOT NULL,
	`qty` integer NOT NULL,
	`purchase_price_eur` real,
	`purchase_date` integer,
	`purchase_source` text,
	`notes` text,
	`added_at` integer DEFAULT (unixepoch()) NOT NULL,
	FOREIGN KEY (`wine_key`) REFERENCES `dim_wine`(`wine_key`) ON UPDATE no action ON DELETE no action,
	FOREIGN KEY (`location_id`) REFERENCES `cellar_locations`(`location_id`) ON UPDATE no action ON DELETE no action,
	CONSTRAINT "chk_inventory_qty_positive" CHECK("cellar_inventory"."qty" >= 0)
);
--> statement-breakpoint
CREATE UNIQUE INDEX `idx_inventory_wine_location` ON `cellar_inventory` (`wine_key`,`location_id`);--> statement-breakpoint
CREATE INDEX `idx_inventory_location` ON `cellar_inventory` (`location_id`);--> statement-breakpoint
CREATE TABLE `cellar_locations` (
	`location_id` integer PRIMARY KEY NOT NULL,
	`name` text NOT NULL,
	`capacity` integer DEFAULT 120 NOT NULL,
	`description` text,
	`temperature_zone` text DEFAULT 'cellar' NOT NULL
);
--> statement-breakpoint
CREATE TABLE `dim_appellation` (
	`appellation_key` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`country_code` text NOT NULL,
	`region` text NOT NULL,
	`subregion` text,
	`appellation_name` text NOT NULL,
	`appellation_norm` text NOT NULL,
	`level` text NOT NULL,
	`inao_code` text,
	`geo_polygon` text,
	`latitude` real,
	`longitude` real
);
--> statement-breakpoint
CREATE UNIQUE INDEX `idx_appellation_norm` ON `dim_appellation` (`country_code`,`appellation_norm`);--> statement-breakpoint
CREATE INDEX `idx_appellation_region` ON `dim_appellation` (`country_code`,`region`);--> statement-breakpoint
CREATE TABLE `dim_producer` (
	`producer_key` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`producer_name` text NOT NULL,
	`producer_norm` text NOT NULL,
	`country_code` text NOT NULL,
	`region` text,
	`subregion` text,
	`allowed_appellations` text DEFAULT '[]' NOT NULL,
	`aliases` text DEFAULT '[]' NOT NULL,
	`website` text,
	`latitude` real,
	`longitude` real,
	`tier` integer,
	`status` text DEFAULT 'active' NOT NULL,
	`first_seen_at` integer DEFAULT (unixepoch()) NOT NULL,
	`last_seen_at` integer DEFAULT (unixepoch()) NOT NULL,
	`notes` text
);
--> statement-breakpoint
CREATE UNIQUE INDEX `idx_producer_norm` ON `dim_producer` (`producer_norm`,`country_code`);--> statement-breakpoint
CREATE INDEX `idx_producer_country_region` ON `dim_producer` (`country_code`,`region`);--> statement-breakpoint
CREATE INDEX `idx_producer_status` ON `dim_producer` (`status`);--> statement-breakpoint
CREATE TABLE `dim_source` (
	`source_key` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`source_code` text NOT NULL,
	`source_name` text NOT NULL,
	`source_tier` text NOT NULL,
	`country_code` text,
	`base_url` text,
	`license_class` text DEFAULT 'public_check_terms' NOT NULL,
	`cadence` text NOT NULL,
	`enabled` integer DEFAULT true NOT NULL,
	`last_success_at` integer,
	`notes` text
);
--> statement-breakpoint
CREATE UNIQUE INDEX `dim_source_source_code_unique` ON `dim_source` (`source_code`);--> statement-breakpoint
CREATE INDEX `idx_source_tier` ON `dim_source` (`source_tier`);--> statement-breakpoint
CREATE TABLE `dim_variety` (
	`variety_key` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`variety_name` text NOT NULL,
	`variety_norm` text NOT NULL,
	`color_family` text NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `dim_variety_variety_norm_unique` ON `dim_variety` (`variety_norm`);--> statement-breakpoint
CREATE TABLE `dim_wine` (
	`wine_key` text PRIMARY KEY NOT NULL,
	`producer_key` integer NOT NULL,
	`appellation_key` integer NOT NULL,
	`cuvee_name` text NOT NULL,
	`cuvee_norm` text NOT NULL,
	`color` text NOT NULL,
	`vintage` integer,
	`is_non_vintage` integer DEFAULT false NOT NULL,
	`bottle_ml` integer DEFAULT 750 NOT NULL,
	`alcohol_pct` real,
	`classification` text,
	`canonical_name` text NOT NULL,
	`first_seen_at` integer DEFAULT (unixepoch()) NOT NULL,
	`last_seen_at` integer DEFAULT (unixepoch()) NOT NULL,
	FOREIGN KEY (`producer_key`) REFERENCES `dim_producer`(`producer_key`) ON UPDATE no action ON DELETE no action,
	FOREIGN KEY (`appellation_key`) REFERENCES `dim_appellation`(`appellation_key`) ON UPDATE no action ON DELETE no action,
	CONSTRAINT "chk_wine_vintage_or_nv" CHECK(("dim_wine"."is_non_vintage" = 1 AND "dim_wine"."vintage" IS NULL) OR ("dim_wine"."is_non_vintage" = 0 AND "dim_wine"."vintage" IS NOT NULL))
);
--> statement-breakpoint
CREATE INDEX `idx_wine_producer` ON `dim_wine` (`producer_key`);--> statement-breakpoint
CREATE INDEX `idx_wine_appellation` ON `dim_wine` (`appellation_key`);--> statement-breakpoint
CREATE INDEX `idx_wine_vintage` ON `dim_wine` (`vintage`);--> statement-breakpoint
CREATE INDEX `idx_wine_color` ON `dim_wine` (`color`);--> statement-breakpoint
CREATE TABLE `fact_price` (
	`price_event_key` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`wine_key` text NOT NULL,
	`source_key` integer NOT NULL,
	`retailer` text,
	`recorded_at` integer DEFAULT (unixepoch()) NOT NULL,
	`price_kind` text NOT NULL,
	`currency_code` text DEFAULT 'EUR' NOT NULL,
	`amount_local` real NOT NULL,
	`fx_to_eur` real,
	`amount_eur` real,
	`in_stock` integer,
	`promo_flag` integer DEFAULT false NOT NULL,
	`promo_delta_pct` real,
	`source_url` text,
	`content_hash` text,
	`batch_id` text NOT NULL,
	FOREIGN KEY (`wine_key`) REFERENCES `dim_wine`(`wine_key`) ON UPDATE no action ON DELETE no action,
	FOREIGN KEY (`source_key`) REFERENCES `dim_source`(`source_key`) ON UPDATE no action ON DELETE no action,
	CONSTRAINT "chk_price_positive" CHECK("fact_price"."amount_local" > 0)
);
--> statement-breakpoint
CREATE INDEX `idx_price_wine` ON `fact_price` (`wine_key`);--> statement-breakpoint
CREATE INDEX `idx_price_recorded` ON `fact_price` (`recorded_at`);--> statement-breakpoint
CREATE INDEX `idx_price_wine_retailer` ON `fact_price` (`wine_key`,`retailer`);--> statement-breakpoint
CREATE INDEX `idx_price_promo` ON `fact_price` (`promo_flag`,`recorded_at`);--> statement-breakpoint
CREATE TABLE `fact_rating` (
	`rating_event_key` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`wine_key` text NOT NULL,
	`source_key` integer NOT NULL,
	`critic_code` text NOT NULL,
	`reviewer_type` text NOT NULL,
	`score` real NOT NULL,
	`scale` text NOT NULL,
	`score_normalized_100` real NOT NULL,
	`rating_count` integer,
	`recorded_at` integer DEFAULT (unixepoch()) NOT NULL,
	`source_url` text,
	`content_hash` text,
	`batch_id` text NOT NULL,
	FOREIGN KEY (`wine_key`) REFERENCES `dim_wine`(`wine_key`) ON UPDATE no action ON DELETE no action,
	FOREIGN KEY (`source_key`) REFERENCES `dim_source`(`source_key`) ON UPDATE no action ON DELETE no action,
	CONSTRAINT "chk_rating_normalized_range" CHECK("fact_rating"."score_normalized_100" BETWEEN 0 AND 100)
);
--> statement-breakpoint
CREATE INDEX `idx_rating_wine` ON `fact_rating` (`wine_key`);--> statement-breakpoint
CREATE INDEX `idx_rating_critic` ON `fact_rating` (`critic_code`);--> statement-breakpoint
CREATE INDEX `idx_rating_wine_critic` ON `fact_rating` (`wine_key`,`critic_code`);--> statement-breakpoint
CREATE TABLE `fact_vintage_rating` (
	`vintage_rating_key` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`country_code` text NOT NULL,
	`region` text NOT NULL,
	`subregion` text,
	`color` text NOT NULL,
	`vintage` integer NOT NULL,
	`source_key` integer NOT NULL,
	`score` real NOT NULL,
	`scale` text NOT NULL,
	`score_normalized_100` real NOT NULL,
	`character_notes` text,
	`source_url` text,
	`recorded_at` integer DEFAULT (unixepoch()) NOT NULL,
	FOREIGN KEY (`source_key`) REFERENCES `dim_source`(`source_key`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE INDEX `idx_vintage_region` ON `fact_vintage_rating` (`country_code`,`region`,`vintage`);--> statement-breakpoint
CREATE UNIQUE INDEX `idx_vintage_unique` ON `fact_vintage_rating` (`country_code`,`region`,`subregion`,`color`,`vintage`,`source_key`);--> statement-breakpoint
CREATE TABLE `ops_batch_log` (
	`batch_id` text PRIMARY KEY NOT NULL,
	`source_key` integer,
	`started_at` integer NOT NULL,
	`finished_at` integer,
	`status` text DEFAULT 'running' NOT NULL,
	`rows_fetched` integer DEFAULT 0 NOT NULL,
	`rows_inserted` integer DEFAULT 0 NOT NULL,
	`rows_updated` integer DEFAULT 0 NOT NULL,
	`rows_dlq` integer DEFAULT 0 NOT NULL,
	`rows_skipped_unchanged` integer DEFAULT 0 NOT NULL,
	`notes` text,
	FOREIGN KEY (`source_key`) REFERENCES `dim_source`(`source_key`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE INDEX `idx_batch_source` ON `ops_batch_log` (`source_key`,`started_at`);--> statement-breakpoint
CREATE TABLE `ops_content_hashes` (
	`url` text PRIMARY KEY NOT NULL,
	`source_key` integer,
	`last_hash` text NOT NULL,
	`last_etag` text,
	`last_modified_http` text,
	`last_fetched_at` integer DEFAULT (unixepoch()) NOT NULL,
	`last_changed_at` integer DEFAULT (unixepoch()) NOT NULL,
	`fetch_count` integer DEFAULT 1 NOT NULL,
	FOREIGN KEY (`source_key`) REFERENCES `dim_source`(`source_key`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE TABLE `ops_dead_letter` (
	`dlq_id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`source_key` integer,
	`batch_id` text NOT NULL,
	`error_class` text NOT NULL,
	`error_message` text NOT NULL,
	`source_record_id` text,
	`raw_record` text,
	`raw_object_path` text,
	`created_at` integer DEFAULT (unixepoch()) NOT NULL,
	`resolved_at` integer,
	`resolved_by` text,
	`resolution` text DEFAULT 'pending' NOT NULL,
	FOREIGN KEY (`source_key`) REFERENCES `dim_source`(`source_key`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE INDEX `idx_dlq_source` ON `ops_dead_letter` (`source_key`);--> statement-breakpoint
CREATE INDEX `idx_dlq_class` ON `ops_dead_letter` (`error_class`);--> statement-breakpoint
CREATE INDEX `idx_dlq_resolution` ON `ops_dead_letter` (`resolution`,`created_at`);--> statement-breakpoint
CREATE TABLE `staging_price_candidates` (
	`candidate_id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`wine_key` text NOT NULL,
	`source_key` integer NOT NULL,
	`retailer` text,
	`recorded_at` integer NOT NULL,
	`currency_code` text DEFAULT 'EUR' NOT NULL,
	`amount_local` real NOT NULL,
	`amount_eur` real,
	`source_url` text,
	`content_hash` text,
	`batch_id` text NOT NULL,
	`needs_review` integer DEFAULT true NOT NULL,
	`promoted_to_fact_price_key` integer,
	`promoted_at` integer,
	FOREIGN KEY (`wine_key`) REFERENCES `dim_wine`(`wine_key`) ON UPDATE no action ON DELETE no action,
	FOREIGN KEY (`source_key`) REFERENCES `dim_source`(`source_key`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE INDEX `idx_staging_price_wine` ON `staging_price_candidates` (`wine_key`);--> statement-breakpoint
CREATE INDEX `idx_staging_price_review` ON `staging_price_candidates` (`needs_review`,`recorded_at`);