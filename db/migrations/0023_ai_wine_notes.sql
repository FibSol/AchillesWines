-- Migration 0023: ai_wine_notes cache table.
-- AI-generated wine blurbs (description + anecdote/fun fact) for the tasting
-- print sheet. One row per (wine_key, locale), generated once via the
-- Anthropic API and reused on every subsequent print.

CREATE TABLE IF NOT EXISTS ai_wine_notes (
  wine_key    TEXT NOT NULL REFERENCES dim_wine(wine_key),
  locale      TEXT NOT NULL,
  description TEXT NOT NULL,
  fun_fact    TEXT NOT NULL,
  model       TEXT NOT NULL,
  created_at  TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (wine_key, locale)
);
