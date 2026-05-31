-- =============================================================================
-- 10_fix_etf_view_kind.sql
-- Guard migration: prevent migration 06_etf.sql from re-creating etf_daily
-- and etf_latest as MATERIALIZED VIEWs after 01_convert_matviews.sql has
-- converted them to plain views.
--
-- CONTEXT:
--   Migration 06_etf.sql contains a DO block with the logic:
--     IF relkind IS DISTINCT FROM 'm' THEN CREATE MATERIALIZED VIEW ...
--   After 01_convert_matviews.sql runs, relkind = 'v' (plain view).
--   On the next workflow run, migration 06 fires again and sees relkind='v' ≠ 'm',
--   drops the plain view, and recreates it as a matview — undoing the fix.
--
-- FIX:
--   This migration runs AFTER migration 06 in lexicographic order (10 > 06).
--   It immediately converts any matview back to a plain view. The net effect is:
--     06 fires → may (re)create matviews → 10 fires → converts back to views.
--   This is a one-statement, near-instant operation — the pipeline incurs no
--   meaningful overhead.
--
-- LONG-TERM:
--   The correct fix is to edit 06_etf.sql to check relkind IN ('v','m') and skip
--   recreation when a plain view already exists. This migration is the safe interim
--   guard that requires no history-rewrite of 06_etf.sql.
--
-- IDEMPOTENT: DROP IF EXISTS + CREATE OR REPLACE. Safe to run multiple times.
-- =============================================================================

DO $$
DECLARE
    daily_kind  "char" := (SELECT relkind FROM pg_class WHERE oid = to_regclass('public.etf_daily'));
    latest_kind "char" := (SELECT relkind FROM pg_class WHERE oid = to_regclass('public.etf_latest'));
BEGIN
    IF daily_kind = 'm' OR latest_kind = 'm' THEN
        RAISE NOTICE 'Migration 10: etf matviews detected — converting to plain views.';

        -- Drop matviews (CASCADE handles etf_latest depending on etf_daily)
        EXECUTE 'DROP MATERIALIZED VIEW IF EXISTS etf_latest CASCADE';
        EXECUTE 'DROP MATERIALIZED VIEW IF EXISTS etf_daily  CASCADE';

        -- Also drop any plain view remnants from partial runs
        EXECUTE 'DROP VIEW IF EXISTS etf_latest CASCADE';
        EXECUTE 'DROP VIEW IF EXISTS etf_daily  CASCADE';

        -- Recreate as plain views
        EXECUTE $view$
            CREATE VIEW etf_daily AS
            SELECT
                e.ticker,
                e.cnpj,
                e.fund_name,
                e.provider,
                e.underlying_index,
                e.segment,
                e.is_active,
                d.dt_comptc,
                d.vl_quota,
                d.vl_patrim_liq                                          AS aum,
                d.nr_cotst                                               AS quotaholders,
                d.captc_dia,
                d.resg_dia,
                (COALESCE(d.captc_dia, 0) - COALESCE(d.resg_dia, 0))    AS net_flow,
                e.taxa_adm,
                e.taxa_perfm,
                d.vl_quota / NULLIF(
                    LAG(d.vl_quota) OVER (PARTITION BY e.ticker ORDER BY d.dt_comptc),
                    0
                ) - 1                                                    AS daily_return
            FROM cvm_etf_registry e
            JOIN cvm_fi_diario     d ON d.cnpj = e.cnpj
        $view$;

        EXECUTE $view$
            CREATE VIEW etf_latest AS
            SELECT DISTINCT ON (ticker)
                ticker, cnpj, fund_name, provider, underlying_index,
                segment, is_active, dt_comptc, vl_quota, aum,
                quotaholders, net_flow, taxa_adm, taxa_perfm
            FROM etf_daily
            ORDER BY ticker, dt_comptc DESC
        $view$;

        RAISE NOTICE 'Migration 10: plain views created successfully.';
    ELSE
        RAISE NOTICE 'Migration 10: etf_daily/etf_latest are already plain views (relkind=%) — no action.', daily_kind;
    END IF;
END $$;

-- Assert both views accessible
SELECT 'etf_daily'::regclass AS etf_daily_ok,
       'etf_latest'::regclass AS etf_latest_ok;
