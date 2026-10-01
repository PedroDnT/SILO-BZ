-- =============================================================================
-- Migration 58 — drop api.mv_etf_landscape, then public.mv_etf_landscape
--
-- WHY
-- Migration 54 meant to drop the hand-made matview public.mv_etf_landscape
-- (defined nowhere in this repository, never refreshed, never read). On its
-- first production apply it could not: the guarded drop logged
--
--   NOTICE: mv_etf_landscape kept: api.mv_etf_landscape depend(s) on it
--
-- (daily_ingest run 36842444079, 2026-10-01). api.mv_etf_landscape is just as
-- unowned: no file here defines it, it is not in api.catalog(), the OpenAPI
-- spec or the MCP contract, and the dashboard does not read it. Owner's call
-- on 2026-10-01: drop both. Its useful columns (net assets, their date, and the
-- rank by size) are now on /etf's "ETF Universe" table, computed from the live
-- registry (dashboard/sources/supabase/etf_list.sql), so they never go stale.
--
-- HOW
-- Each drop is guarded like migration 54: it runs only when no OTHER object
-- has a normal dependency on the relation, and otherwise raises a NOTICE naming
-- the dependents and keeps everything. Never CASCADE. The api object is dropped
-- by its actual kind (view or materialized view). A no-op once both are gone,
-- and on a fresh database.
-- =============================================================================

DO $$
DECLARE
    target TEXT;
    kind   "char";
    deps   TEXT;
BEGIN
    FOREACH target IN ARRAY ARRAY['api.mv_etf_landscape', 'public.mv_etf_landscape'] LOOP
        IF to_regclass(target) IS NULL THEN
            CONTINUE;
        END IF;
        SELECT relkind INTO kind FROM pg_class WHERE oid = to_regclass(target);
        SELECT string_agg(DISTINCT dep, ', ') INTO deps
          FROM (
            SELECT COALESCE(r.ev_class::regclass::text,
                            pg_describe_object(d.classid, d.objid, d.objsubid)) AS dep
              FROM pg_depend d
              LEFT JOIN pg_rewrite r
                ON d.classid = 'pg_rewrite'::regclass AND r.oid = d.objid
             WHERE d.refobjid = to_regclass(target)
               AND d.deptype = 'n'   -- an index or the row type is 'a'/'i', and DROP takes it
               AND COALESCE(r.ev_class, 0) <> to_regclass(target)
          ) s;
        IF deps IS NOT NULL THEN
            RAISE NOTICE '% kept: % depend(s) on it (migration 58)', target, deps;
            -- The public matview cannot go while the api object stays.
            EXIT;
        END IF;
        IF kind = 'm' THEN
            EXECUTE format('DROP MATERIALIZED VIEW %s', target);
        ELSIF kind = 'v' THEN
            EXECUTE format('DROP VIEW %s', target);
        ELSE
            RAISE NOTICE '% kept: it is relkind %, not a view (migration 58)', target, kind;
            EXIT;
        END IF;
        RAISE NOTICE '% dropped (migration 58)', target;
    END LOOP;
END $$;
