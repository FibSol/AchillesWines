-- Migration 0024: tasting_sessions + tasting_session_wines.
-- Saved tasting flights: the user snapshots a flight, rates each wine
-- (personal_score /100) and removes the tasted bottles from the cellar in one
-- click. Removal creates a cellar_consumption row whose id is kept on the
-- session wine so a rating set after removal still syncs to the drink log.

CREATE TABLE IF NOT EXISTS tasting_sessions (
  session_id INTEGER PRIMARY KEY AUTOINCREMENT,
  mode       TEXT NOT NULL,
  created_at INTEGER NOT NULL DEFAULT (unixepoch())
);

CREATE TABLE IF NOT EXISTS tasting_session_wines (
  session_wine_id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id      INTEGER NOT NULL REFERENCES tasting_sessions(session_id),
  wine_key        TEXT NOT NULL REFERENCES dim_wine(wine_key),
  position        INTEGER NOT NULL,
  personal_score  INTEGER,
  consumed_at     INTEGER,
  consumption_id  INTEGER REFERENCES cellar_consumption(consumption_id),
  CONSTRAINT chk_session_score_range
    CHECK (personal_score IS NULL OR (personal_score BETWEEN 0 AND 100))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_session_wine
  ON tasting_session_wines (session_id, wine_key);
