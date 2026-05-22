-- Add James Suckling as a source (critic scraper, critic_code = 'JS').
-- Also set requires_auth=1 for idealwine, lavinia, vinatis, rvf (ADR-010, Sprint 8 cleanup).

INSERT OR IGNORE INTO `dim_source`
  (`source_code`, `source_name`, `source_tier`, `cadence`,
   `base_url`, `license_class`, `enabled`, `requires_auth`, `notes`)
VALUES
  ('james_suckling', 'James Suckling', 'E_press_critic', 'monthly',
   'https://www.jamessuckling.com', 'public_check_terms', 1, 0,
   'Top-100 public list; full ratings require subscription.');
--> statement-breakpoint
UPDATE `dim_source` SET `requires_auth` = 1
WHERE `source_code` IN ('idealwine', 'lavinia', 'vinatis', 'rvf');
