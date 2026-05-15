-- Operational monitoring: ingest pipeline health and data-coverage alerts.
-- Run: psql $SUPABASE_DB_URL -f scripts/queries/08_ingest_health.sql

-- Ingest log summary: success/failure counts, rows upserted, duration.
-- Trailing 30 days by default; adjust p_days as needed.
SELECT *
FROM   ingest_log_summary(
           p_days => 30
       )
ORDER  BY run_date DESC, entity_type;

-- Data-coverage check with staleness filter:
-- flags any entity/period combination where no report arrived in 2+ months.
-- This catches silent failures not visible in the ingest log
-- (e.g. CVM upstream delays or parser regressions).
SELECT *
FROM   data_coverage(
           p_entity_types             => NULL,          -- all entity types
           p_start_date               => CURRENT_DATE - INTERVAL '6 months',
           p_end_date                 => CURRENT_DATE,
           p_months_since_last_report => 2              -- alert threshold
       )
WHERE  months_since_last_report >= 2
ORDER  BY months_since_last_report DESC, entity_type;
