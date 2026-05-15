-- =============================================================================
-- 08_cron_schedules.sql
-- Register pg_cron jobs to refresh the analytical materialized views daily.
-- Scheduled 15-25 min after the 06:00 UTC GitHub Actions ingest cron.
--
-- pg_cron is optional — if it is not installed the DO block emits a NOTICE
-- and the file exits cleanly. Enable via Supabase Dashboard:
--   Database → Extensions → pg_cron → Enable
--
-- Manual refresh commands (run any time after ingest):
--   REFRESH MATERIALIZED VIEW CONCURRENTLY fact_bacen_monthly;
--   REFRESH MATERIALIZED VIEW CONCURRENTLY fact_fund_monthly;
--   REFRESH MATERIALIZED VIEW CONCURRENTLY fact_security_monthly;
--
-- CONCURRENTLY requires the unique indexes created by files 03-05.
-- =============================================================================

BEGIN;
SET statement_timeout = '15min';

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN

    -- -----------------------------------------------------------------------
    -- fact_bacen_monthly  — runs first (benchmarks needed by fund/security views)
    -- 06:15 UTC daily
    -- -----------------------------------------------------------------------
    PERFORM cron.schedule(
      'refresh-fact-bacen-monthly',
      '15 6 * * *',
      'REFRESH MATERIALIZED VIEW CONCURRENTLY fact_bacen_monthly'
    );

    -- -----------------------------------------------------------------------
    -- fact_fund_monthly  — 06:20 UTC daily
    -- -----------------------------------------------------------------------
    PERFORM cron.schedule(
      'refresh-fact-fund-monthly',
      '20 6 * * *',
      'REFRESH MATERIALIZED VIEW CONCURRENTLY fact_fund_monthly'
    );

    -- -----------------------------------------------------------------------
    -- fact_security_monthly  — 06:25 UTC daily
    -- -----------------------------------------------------------------------
    PERFORM cron.schedule(
      'refresh-fact-security-monthly',
      '25 6 * * *',
      'REFRESH MATERIALIZED VIEW CONCURRENTLY fact_security_monthly'
    );

    RAISE NOTICE 'pg_cron schedules registered: refresh-fact-bacen-monthly (06:15), refresh-fact-fund-monthly (06:20), refresh-fact-security-monthly (06:25)';

  ELSE
    RAISE NOTICE 'pg_cron not available — run REFRESH MATERIALIZED VIEW manually or enable pg_cron in Supabase Dashboard (Database → Extensions → pg_cron)';
  END IF;
END $$;

-- ---------------------------------------------------------------------------
-- To inspect registered jobs after enabling pg_cron:
--   SELECT jobid, jobname, schedule, command, active FROM cron.job ORDER BY jobid;
--
-- To remove a job:
--   SELECT cron.unschedule('refresh-fact-fund-monthly');
--   SELECT cron.unschedule('refresh-fact-security-monthly');
--   SELECT cron.unschedule('refresh-fact-bacen-monthly');
--
-- To force an immediate sequential refresh outside cron:
--   REFRESH MATERIALIZED VIEW CONCURRENTLY fact_bacen_monthly;
--   REFRESH MATERIALIZED VIEW CONCURRENTLY fact_fund_monthly;
--   REFRESH MATERIALIZED VIEW CONCURRENTLY fact_security_monthly;
-- ---------------------------------------------------------------------------

COMMIT;
