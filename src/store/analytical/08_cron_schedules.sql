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

    -- dim_fund — 06:15 UTC daily (matview; feeds dim_fund_category + performance fns)
    PERFORM cron.schedule(
      'refresh-dim-fund',
      '15 6 * * *',
      'REFRESH MATERIALIZED VIEW CONCURRENTLY dim_fund'
    );

    -- fact_fund_monthly — 06:20 UTC daily (after GHA ingest at 06:00)
    PERFORM cron.schedule(
      'refresh-fact-fund-monthly',
      '20 6 * * *',
      'REFRESH MATERIALIZED VIEW CONCURRENTLY fact_fund_monthly'
    );

    -- mv_b3_isin_subtype — 06:12 UTC daily, BEFORE the fund matviews and right
    -- after the B3 ingest lands. It maps an ISIN to the fund subtype its own
    -- decisive sessions show, and vw_b3_instrument_typed falls back to it when
    -- a row's CODBDI is silent — which is what keeps an ETF classified as an
    -- ETF across the board-code change B3 made in late 2019. A stale copy just
    -- means a newly listed fund waits a day for its subtype.
    PERFORM cron.schedule(
      'refresh-b3-isin-subtype',
      '12 6 * * *',
      'REFRESH MATERIALIZED VIEW CONCURRENTLY mv_b3_isin_subtype'
    );

    -- mv_b3_monthly_activity — 06:18 UTC daily, AFTER mv_b3_isin_subtype (06:12)
    -- because it reads vw_b3_instrument_typed, which falls back to that matview
    -- for an instrument's subtype. Refreshing in the other order would bake a
    -- day-old subtype into the monthly ETF/FII splits.
    --
    -- This is the one full pass over the tape per day. It exists so the
    -- dashboard does not make five of them per build — which on 2026-08-28 ran
    -- the production build past Vercel's 45-minute ceiling and held locks long
    -- enough to fail two schema applies. Doing it here, once, at 06:18, is the
    -- whole point: nothing interactive is waiting on it.
    PERFORM cron.schedule(
      'refresh-b3-monthly-activity',
      '18 6 * * *',
      'REFRESH MATERIALIZED VIEW CONCURRENTLY mv_b3_monthly_activity'
    );

    -- fact_security_monthly — 06:25 UTC daily
    PERFORM cron.schedule(
      'refresh-fact-security-monthly',
      '25 6 * * *',
      'REFRESH MATERIALIZED VIEW CONCURRENTLY fact_security_monthly'
    );

    -- mv_period_completeness — 06:35 UTC daily, AFTER the fact refreshes it
    -- reads from; the serving clamp (latest_complete_period) must see the
    -- night's newly ingested months before the day's dashboard traffic.
    PERFORM cron.schedule(
      'refresh-period-completeness',
      '35 6 * * *',
      'REFRESH MATERIALIZED VIEW CONCURRENTLY mv_period_completeness'
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
