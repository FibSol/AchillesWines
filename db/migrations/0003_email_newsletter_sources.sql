-- ADR-011: email newsletter sources
-- Each row represents a distinct "from:" address we parse from the dedicated
-- mailbox. Mailbox creds are shared and live in env vars (ACHILLES_MAILBOX_*),
-- not in this table. requires_auth=0 because the per-source ACHILLES_AUTH_*
-- pattern doesn't apply to email-sourced rows.

INSERT OR IGNORE INTO `dim_source`
  (`source_code`, `source_name`, `source_tier`, `cadence`, `country_code`,
   `license_class`, `enabled`, `requires_auth`, `notes`)
VALUES
  ('millesima_email', 'Millesima newsletter', 'B_retailer_major', 'on_demand',
   'FR', 'public_check_terms', 1, 0,
   'IMAP poll. from=newsletter@millesima.fr. See docs/EMAIL.md.'),
  ('idealwine_email', 'iDealwine newsletter', 'B_retailer_major', 'on_demand',
   'FR', 'public_check_terms', 1, 0,
   'IMAP poll. from=no-reply@idealwine.com. See docs/EMAIL.md.'),
  ('lavinia_email', 'Lavinia newsletter', 'B_retailer_major', 'on_demand',
   'FR', 'public_check_terms', 1, 0,
   'IMAP poll. from=newsletter@lavinia.fr. See docs/EMAIL.md.');
