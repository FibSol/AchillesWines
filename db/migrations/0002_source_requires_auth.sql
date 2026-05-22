-- ADR-010: per-source authentication (form login)
-- Adds a `requires_auth` flag on dim_source so /admin/auth knows which
-- sources need credentials (ACHILLES_AUTH_<source>_USERNAME / _PASSWORD).
ALTER TABLE `dim_source` ADD `requires_auth` integer NOT NULL DEFAULT 0;
