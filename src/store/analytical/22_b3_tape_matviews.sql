-- =============================================================================
-- 22_b3_tape_matviews.sql
-- Refresh the two matviews schema.sql owns: mv_b3_isin_subtype and
-- mv_b3_monthly_activity.
--
-- WHY THIS FILE EXISTS (docs/planning/OPEN_ITEMS.md item 16, found 2026-09-29).
-- Every other matview is dropped and re-created by this layer, so applying the
-- layer IS their daily refresh. These two are not. vw_b3_instrument_typed
-- depends on the first, so both are created in schema.sql (CREATE ... IF NOT
-- EXISTS, WITH NO DATA), and schema.sql refreshes them only while they are
-- empty. Their daily refresh was the pair of pg_cron jobs in
-- 08_cron_schedules.sql, and the live database has no pg_cron. So nothing
-- refreshed them. On 2026-09-29 both still held what they held on 2026-08-28:
-- /markets, /etf and /flows showed August with 19 of its 21 sessions and no
-- September, and nine fund ISINs listed since then had no subtype.
--
-- WHY HERE AND NOT IN 08. scripts/apply_analytical.sh downgrades a failure of
-- 08 to a warning whenever its output mentions pg_cron, and 08's own NOTICE
-- does. A REFRESH that failed there would be swallowed. Here it fails the
-- apply, which is the signal this repository requires.
--
-- WHY NOT schema.sql. That runs before run_daily, in every mode, so it would
-- refresh yesterday's tape, and under the schema apply's 15s lock_timeout.
--
-- ORDER. mv_b3_isin_subtype first. mv_b3_monthly_activity reads
-- vw_b3_instrument_typed, which falls back to the ISIN map for a fund quota's
-- subtype, so the other order would bake a day-old subtype into the monthly
-- ETF/FII splits. One transaction, so the second statement sees the first.
--
-- CONCURRENTLY while the matview is populated, so api.fund_quotas, the quote
-- views and a dashboard build are never blocked while it rebuilds. A plain
-- REFRESH while it is empty, because CONCURRENTLY refuses an unpopulated
-- matview. Both carry the unique index CONCURRENTLY needs (uq_b3_isin_subtype,
-- uq_b3_monthly_activity). A missing matview makes the plain REFRESH raise.
--
-- mv_b3_monthly_activity is the one full pass over the tape per day (about
-- 17M rows on 2026-09-30). Its first population took 2 min 10 s on production
-- (Daily CVM Ingest run 33207753376, 2026-08-28, default planner settings).
-- Same session settings as 04_fact_fund_monthly.sql, for the same reasons: no
-- parallel workers and no JIT bound the memory peak on a small instance, at
-- the price of a slower scan, and the timeout is LOCAL so a pooler that
-- ignores a session SET still honours it.
--
-- pg_cron stays optional. If it is ever enabled, 08's two jobs refresh the
-- same matviews again, which costs a scan and changes nothing.
-- =============================================================================

BEGIN;
SET LOCAL statement_timeout = '30min';
SET LOCAL max_parallel_workers_per_gather = 0;
SET LOCAL jit = off;

DO $silo_refresh_mv_b3_isin_subtype$
BEGIN
  IF (
    SELECT c.relispopulated
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relname = 'mv_b3_isin_subtype'
      AND c.relkind = 'm'
  ) THEN
    REFRESH MATERIALIZED VIEW CONCURRENTLY public.mv_b3_isin_subtype;
  ELSE
    REFRESH MATERIALIZED VIEW public.mv_b3_isin_subtype;
  END IF;
END
$silo_refresh_mv_b3_isin_subtype$;

DO $silo_refresh_mv_b3_monthly_activity$
BEGIN
  IF (
    SELECT c.relispopulated
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relname = 'mv_b3_monthly_activity'
      AND c.relkind = 'm'
  ) THEN
    REFRESH MATERIALIZED VIEW CONCURRENTLY public.mv_b3_monthly_activity;
  ELSE
    REFRESH MATERIALIZED VIEW public.mv_b3_monthly_activity;
  END IF;
END
$silo_refresh_mv_b3_monthly_activity$;

COMMIT;
