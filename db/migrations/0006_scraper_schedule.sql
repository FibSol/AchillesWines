CREATE TABLE `ops_scraper_schedule` (
	`source_code` text PRIMARY KEY NOT NULL,
	`cron_expr` text,
	`updated_at` integer DEFAULT (unixepoch()) NOT NULL
);
