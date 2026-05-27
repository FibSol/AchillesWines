-- Runner self-healing: sources with auto_requeue_minutes set are re-enqueued
-- by the job runner itself (requested_by='runner_heartbeat') whenever the
-- last finished job is older than that many minutes and no job is active.
-- This makes email scrapers cycle without depending on an external monitor.
ALTER TABLE dim_source ADD COLUMN auto_requeue_minutes INTEGER;

-- Email newsletter scrapers should cycle every 5 minutes to catch new mail promptly.
UPDATE dim_source
SET auto_requeue_minutes = 5
WHERE source_code IN (
    'idealwine_email', 'millesima_email',
    'ventealapropriete_email', 'lavinia_email'
);
