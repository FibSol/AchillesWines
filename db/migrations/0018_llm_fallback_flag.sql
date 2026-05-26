-- ADR-011 extension: per-source LLM fallback flag for email newsletter parsers.
-- When use_llm_fallback=1, the EmailNewsletterScraper retries emails that yield
-- 0 offers from the heuristic parser by sending the plain text to Claude Haiku.
-- Gated so API costs only apply to opted-in sources.
ALTER TABLE dim_source ADD COLUMN use_llm_fallback INTEGER NOT NULL DEFAULT 0;

-- Enable for email newsletter sources that frequently hit DLQ:
UPDATE dim_source SET use_llm_fallback = 1 WHERE source_code IN (
  'idealwine_email', 'millesima_email', 'ventealapropriete_email', 'lavinia_email'
);
