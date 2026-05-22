CREATE TABLE `ops_job_queue` (
	`job_id` text PRIMARY KEY NOT NULL,
	`source_key` integer,
	`requested_by` text DEFAULT 'ui' NOT NULL,
	`requested_at` integer DEFAULT (unixepoch()) NOT NULL,
	`status` text DEFAULT 'queued' NOT NULL,
	`started_at` integer,
	`finished_at` integer,
	`rows_fetched` integer DEFAULT 0 NOT NULL,
	`rows_inserted` integer DEFAULT 0 NOT NULL,
	`rows_dlq` integer DEFAULT 0 NOT NULL,
	`error_message` text,
	`batch_id` text,
	`params` text,
	FOREIGN KEY (`source_key`) REFERENCES `dim_source`(`source_key`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE INDEX `idx_job_status` ON `ops_job_queue` (`status`,`requested_at`);--> statement-breakpoint
CREATE INDEX `idx_job_source` ON `ops_job_queue` (`source_key`);
