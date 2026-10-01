-- =============================================================================
-- Migration 54 — drop mv_etf_landscape, a matview this repository never owned
--
-- WHY
-- mv_etf_landscape exists on the live database and is defined nowhere in this
-- repository or its git history, so nothing refreshes it: it holds whatever it
-- held when someone created it by hand. Measured on 2026-09-30:
--
--   187 rows, 96 kB, owner postgres, no grant to any other role;
--   no view, matview or function depends on it (pg_depend);
--   seq_scan = 0 and idx_scan = 0 in pg_stat_all_tables, so it has never been
--   read since the statistics began;
--   no statement in pg_stat_statements (reset 2026-09-15) mentions it.
--
-- Nothing is lost. It is a rank() over cvm_etf_registry, which stays. This was
-- its definition, if it is ever wanted again (as a plain view it would always
-- be current, which the matview never was):
--
--   SELECT ticker, cnpj, fund_name, gestor, admin, provider, underlying_index,
--          segment, classe_anbima, taxa_adm, taxa_perfm, dt_reg, is_active,
--          situacao, dt_cancel, vl_patrim_liq, dt_patrim_liq,
--          rank() OVER (ORDER BY vl_patrim_liq DESC NULLS LAST) AS aum_rank
--     FROM cvm_etf_registry;
--
-- Found with the two frozen B3 matviews (docs/planning/OPEN_ITEMS.md item 16).
-- Idempotent: a no-op on every later apply and on a fresh database, so
-- schema.sql needs no change.
--
-- GUARDED (2026-10-01). The first apply, in the 03:00 UTC-3 daily run of
-- 2026-10-01 (run 36822760975), failed with "cannot drop materialized view
-- mv_etf_landscape because other objects depend on it". That run's ingest,
-- ANALYZE, analytical apply and deploy were all skipped. Something on the
-- live database now depends on the matview, and nothing in this repository
-- defines it. So the drop runs only when nothing depends on it. Otherwise it
-- raises a NOTICE naming each dependent and leaves everything in place. Never
-- CASCADE: that would drop an object nobody has looked at.
-- =============================================================================

DO $$
DECLARE
    deps TEXT;
BEGIN
    IF to_regclass('public.mv_etf_landscape') IS NULL THEN
        RETURN;
    END IF;
    -- Views and matviews depend through their rewrite rule (pg_rewrite);
    -- anything else (a function's SQL body, a constraint) through pg_depend
    -- directly.
    SELECT string_agg(DISTINCT dep, ', ') INTO deps
      FROM (
        SELECT COALESCE(r.ev_class::regclass::text,
                        pg_describe_object(d.classid, d.objid, d.objsubid)) AS dep
          FROM pg_depend d
          LEFT JOIN pg_rewrite r
            ON d.classid = 'pg_rewrite'::regclass AND r.oid = d.objid
         WHERE d.refobjid = 'public.mv_etf_landscape'::regclass
           AND d.deptype = 'n'   -- an index or the row type is 'a'/'i', and DROP takes it
           AND COALESCE(r.ev_class, 0) <> 'public.mv_etf_landscape'::regclass
      ) s;
    IF deps IS NOT NULL THEN
        RAISE NOTICE 'mv_etf_landscape kept: % depend(s) on it (migration 54)', deps;
        RETURN;
    END IF;
    DROP MATERIALIZED VIEW public.mv_etf_landscape;
END $$;
