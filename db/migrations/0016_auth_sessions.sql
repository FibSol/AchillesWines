-- Migration 0016: ops_auth_sessions — scraper auth session cache (#22)
-- Stores JWT bearer tokens and cookie jars so scrapers skip re-login between batches.

CREATE TABLE IF NOT EXISTS ops_auth_sessions (
    session_key   INTEGER PRIMARY KEY AUTOINCREMENT,
    source_code   TEXT    NOT NULL UNIQUE,
    token_type    TEXT    NOT NULL CHECK (token_type IN ('cookie_jar', 'jwt_bearer')),
    cookie_jar    TEXT,
    auth_token    TEXT,
    extra_headers TEXT,
    created_at    INTEGER NOT NULL DEFAULT (unixepoch()),
    expires_at    INTEGER,
    last_used_at  INTEGER NOT NULL DEFAULT (unixepoch())
);
