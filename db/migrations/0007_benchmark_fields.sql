ALTER TABLE `dim_source` ADD `recommended_batch_size` integer;
ALTER TABLE `dim_source` ADD `last_benchmark_at` integer;
ALTER TABLE `dim_source` ADD `benchmark_success_rate` real;
ALTER TABLE `dim_source` ADD `benchmark_notes` text;
