-- Migration 0021: wine_similarity table for vector-based recommendations
-- Stores pre-computed top-K cosine similarity scores between wines.

CREATE TABLE IF NOT EXISTS wine_similarity (
  wine_key TEXT NOT NULL,
  similar_wine_key TEXT NOT NULL,
  score REAL NOT NULL,
  computed_at TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (wine_key, similar_wine_key),
  FOREIGN KEY (wine_key) REFERENCES dim_wine(wine_key),
  FOREIGN KEY (similar_wine_key) REFERENCES dim_wine(wine_key)
);

CREATE INDEX IF NOT EXISTS idx_wine_similarity_key ON wine_similarity(wine_key, score DESC);
