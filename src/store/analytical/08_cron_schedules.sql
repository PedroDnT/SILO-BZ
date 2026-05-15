-- =============================================================================
-- 08_cron_schedules.sql
-- Register pg_cron jobs for daily matview refresh.
-- Scheduled after the 06:00 UTC GitHub Actions ingest cron.
--
-- NOTE: fact_bacen_monthly was removed — only fund and security matviews refresh.
--
-- Enable pg_cron: Supabase Dashboard → Database → Extensions → pg_cron
--
-- Manual refresh (run any time after ingest):
--   REFRESH MATERIALIZED VIEW CONCURRENTLY fact_fund_monthly;
--   REFRESH MATERIALIZED VIEW CONCURRENTLY fact_security_monthly;
--
-- Remove old bacen schedule if it was previously registered:
--   SELECT cron.unschedule('refresh-fact-bacen-monthly');
-- =============================================================================

BEGIN;
SET statement_timeout = '15min';

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN

    -- Remove stale bacen schedule if it exists from a previous version
    BEGIN
      PERFORM cron.unschedule('refresh-fact-bacen-monthly');
    EXCEPTION WHEN OTHERS THEN NULL;
    END;

    -- fact_fund_monthly — 06:20 UTC daily (after GHA ingest at 06:00)
    PERFORM cron.schedule(
      'refresh-fact-fund-monthly',
      '20 6 * * *',
      'REFRESH MATERIALIZED VIEW CONCURRENTLY fact_fund_monthly'
    );

    -- fact_security_monthly — 06:25 UTC daily
    PERFORM cron.schedule(
      'refresh-fact-security-monthly',
      '25 6 * * *',
      'REFRESH MATERIALIZED VIEW CONCURRENTLY fact_security_monthly'
    );

    RAISE NOTICE 'pg_cron schedules registered: refresh-fact-fund-monthly (06:20), refresh-fact-security-monthly (06:25)';

  ELSE
    RAISE NOTICE 'pg_cron not available — enable in Supabase Dashboard (Database → Extensions → pg_cron) and re-run this file';
  END IF;
END $$;

-- ---------------------------------------------------------------------------
-- To inspect registered jobs:
--   SELECT jobid, jobname, schedule, command, active FROM cron.job ORDER BY jobid;
--
-- To manually refresh:
--   REFRESH MATERIALIZED VIEW CONCURRENTLY fact_fund_monthly;
--   REFRESH MATERIALIZED VIEW CONCURRENTLY fact_security_monthly;
-- ---------------------------------------------------------------------------

COMMIT;
