-- =============================================================================
-- 12_grants_and_rls.sql
-- Roles + grants for the read side (SERVING.md Step 6: the privilege boundary
-- is real). All CVM data is public information, but the *landing* tables are
-- an ingest surface, not a client surface.
--
-- Posture:
--   * Client reads go through schema `api` (19_api_contract.sql): owner-
--     privileged views + SECURITY DEFINER functions. Reading api.* therefore
--     requires NO grant on any landing table.
--   * Landing tables (cvm_*, b3_cotahist, cvm_ingest_log) and the raw B3
--     tape views get no grants to anon / authenticated.
--     Earlier revisions of this file granted them; because a GRANT persists on
--     the live database until revoked, the revokes below are applied on every
--     run (REVOKE is idempotent).
--   * `silo_api` (created here; its api.* grants live at the end of
--     19_api_contract.sql, which applies after this file) is the NOLOGIN
--     privilege bundle serve/ connects through via a LOGIN member role.
--   * Aggregated analytical objects (dim_* / fact_* / vw_* cross-domain views
--     and the SECURITY INVOKER analytical functions) keep anon/authenticated
--     access: they are public aggregates the Evidence dashboards may read via
--     the Data API. An INVOKER function that touches a revoked landing table
--     now fails loudly for anon ("permission denied"), which is the intended
--     behavior — the boundary is the table grant, never a silent filter.
--
-- Future: when per-user watchlists or private annotations are added, add
-- RLS policies using the pattern:
--   USING (user_id = (SELECT auth.uid()))   <- wrap in SELECT for 100x perf
-- NOT:
--   USING (user_id = auth.uid())            <- called per-row, catastrophically slow
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- Read role: silo_api (NOLOGIN privilege bundle)
-- ---------------------------------------------------------------------------
-- Guarded so re-runs are clean under ON_ERROR_STOP=1. The inner exception
-- handler only absorbs the create/create race between two concurrent applies —
-- either way the role exists afterwards, which is the postcondition we need.
DO $do$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'silo_api') THEN
        CREATE ROLE silo_api NOLOGIN;
    END IF;
EXCEPTION WHEN duplicate_object THEN
    NULL;  -- created by a concurrent apply; role exists, which is all we need
END
$do$;

COMMENT ON ROLE silo_api IS
    'Read-only privilege bundle for serve/ (schema api only). NOLOGIN; connect via a LOGIN member role.';

-- Runtime guardrails live on the role, not on an apply-time session (the SET
-- statement_timeout inside 19_api_contract.sql only protects its own DDL
-- transaction). 15s: the worst honest api.panel (50 ids x 10 metrics x 20y,
-- capped at ~100k rows) completes in low single-digit seconds on Supabase;
-- 15s leaves cold-cache headroom while killing any runaway scan long before
-- it saturates the pooler.
ALTER ROLE silo_api SET statement_timeout = '15s';
-- Belt-and-suspenders: the role holds no INSERT/UPDATE/DELETE grants anywhere
-- (that absence is the real boundary); read-only-by-default also stops
-- accidental writes through owner-privileged paths.
ALTER ROLE silo_api SET default_transaction_read_only = on;

-- Operator step (one time, run as postgres in the Supabase SQL editor — a
-- password must NEVER be committed to this repo):
--
--   CREATE ROLE silo_api_login LOGIN PASSWORD '<generate-a-strong-password>'
--       IN ROLE silo_api INHERIT;
--
-- Then point serve/ at the Supabase *transaction* pooler (port 6543) with:
--
--   SILO_API_DATABASE_URL=postgresql://silo_api_login.<project-ref>:<password>@<pooler-host>:6543/postgres?sslmode=require
--
-- and re-deploy serve/. Rotating the password touches only silo_api_login;
-- the grants stay on silo_api.

-- ---------------------------------------------------------------------------
-- Landing tables: no client-role access.
--
-- DENY BY DEFAULT. This used to be the hand-written list below and nothing
-- else, and an allowlist of revokes cannot track an append-only schema.
-- Measured on production 2026-08-28, `anon` still held SELECT on 77 objects in
-- `public`, among them every b3_cotahist_* and cvm_fi_diario_* PARTITION (the
-- list revokes only the parent, and partitions carry their own ACLs), all 31M
-- rows of cia_account, cvm_fi_balancete, the cia_* company tables, bacen_*,
-- and 21 views. Verified reachable: with `Accept-Profile: public` the
-- publishable key reads public.cvm_fi_balancete and public.cia_account over
-- PostgREST, straight past the api contract this file exists to enforce.
--
-- Nothing private leaked — it is all CVM/BACEN/B3 open data, and the leftover
-- app tables (messages, profiles, threads*) have RLS on and returned []. But
-- the whole 78 GB warehouse was anonymously scannable, which is an egress and
-- load exposure on a database already short of disk, and it made SERVING.md's
-- "landing tables revoked" claim false.
--
-- Every new dataset arrives granted, because Supabase's default privileges
-- grant anon SELECT on new tables in public. So the sweep below runs FIRST and
-- the explicit GRANTs that follow are the entire client surface. Adding a
-- dataset can no longer quietly widen it; forgetting to grant something breaks
-- loudly, which is the failure direction to prefer.
--
-- SCOPE: tables with RLS DISABLED, which is exactly the set that is actually
-- reachable. Deliberately NOT `ALL TABLES IN SCHEMA public`: this database also
-- holds another application's tables (messages, profiles, threads,
-- thread_participants, thread_summaries — the Edge Functions' data). Those have
-- RLS enabled, so RLS is their boundary and they are already closed to anon;
-- stripping `authenticated` from them would break an app whose privilege needs
-- this repo cannot see. A sweep that fixes our exposure by breaking someone
-- else's app is not a fix.
--
-- No ALTER DEFAULT PRIVILEGES here for the same reason: it would apply to every
-- future table in `public`, that other application's included. The sweep instead
-- runs on every analytical apply, so a newly added table is client-visible for
-- at most one deploy cycle — and only ever with published CVM/BACEN/B3 data.
-- ---------------------------------------------------------------------------
DO $revoke$
DECLARE
    t RECORD;
    n INT := 0;
BEGIN
    FOR t IN
        SELECT c.oid::regclass AS obj
        FROM pg_class c
        JOIN pg_namespace ns ON ns.oid = c.relnamespace
        WHERE ns.nspname = 'public'
          AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
          AND NOT c.relrowsecurity
    LOOP
        EXECUTE format('REVOKE ALL ON %s FROM anon, authenticated', t.obj);
        n := n + 1;
    END LOOP;
    RAISE NOTICE 'revoked anon/authenticated on % RLS-disabled public objects', n;
END
$revoke$;

-- The named revokes are kept below the sweep. They are now redundant for
-- privileges and load-bearing as documentation: this is the list someone reads
-- to see which tables are deliberately client-invisible, and each one still
-- fails loudly here if the object is ever dropped.
REVOKE ALL ON TABLE cvm_fund_registry      FROM anon, authenticated;
REVOKE ALL ON TABLE cvm_fi_diario          FROM anon, authenticated;
REVOKE ALL ON TABLE cvm_fi_cda             FROM anon, authenticated;
REVOKE ALL ON TABLE cvm_fi_perfil          FROM anon, authenticated;
REVOKE ALL ON TABLE cvm_fidc_mensal        FROM anon, authenticated;
REVOKE ALL ON TABLE cvm_fidc_tranche       FROM anon, authenticated;
REVOKE ALL ON TABLE cvm_fidc_tranche_flows FROM anon, authenticated;
REVOKE ALL ON TABLE cvm_fidc_aging         FROM anon, authenticated;
REVOKE ALL ON TABLE cvm_fiagro_mensal      FROM anon, authenticated;
REVOKE ALL ON TABLE cvm_fip_periodic       FROM anon, authenticated;
REVOKE ALL ON TABLE cvm_fii_mensal         FROM anon, authenticated;
REVOKE ALL ON TABLE cvm_fii_periodic       FROM anon, authenticated;
REVOKE ALL ON TABLE cvm_securit_mensal     FROM anon, authenticated;
REVOKE ALL ON TABLE cvm_securit_serie      FROM anon, authenticated;
REVOKE ALL ON TABLE cvm_securit_fluxo      FROM anon, authenticated;
REVOKE ALL ON TABLE cvm_securit_dfin       FROM anon, authenticated;
-- The audit log is operator-only ("What we will not do": never expose it).
REVOKE ALL ON TABLE cvm_ingest_log         FROM anon, authenticated;
-- The B3 tape: neither the option-heavy parent nor the raw cash view. Cash
-- quotes are served through the owner-privileged api.quotes
-- (analytical/19_api_contract.sql) — one door, not two.
REVOKE ALL ON TABLE b3_cotahist            FROM anon, authenticated;
REVOKE ALL ON TABLE vw_b3_quote_vista      FROM anon, authenticated;
REVOKE ALL ON TABLE vw_b3_instrument_typed FROM anon, authenticated;

-- ---------------------------------------------------------------------------
-- Materialized views (analytical facts) — aggregated, public
-- ---------------------------------------------------------------------------
GRANT SELECT ON fact_fund_monthly      TO anon, authenticated;
GRANT SELECT ON fact_security_monthly  TO anon, authenticated;
-- Serving-readiness classification (04): tiny, aggregated, no fund identities
-- beyond a count — the dashboards' spines clamp on it.
GRANT SELECT ON mv_period_completeness TO anon, authenticated;

-- ---------------------------------------------------------------------------
-- Dimension views
-- ---------------------------------------------------------------------------
GRANT SELECT ON dim_fund               TO anon, authenticated;
GRANT SELECT ON dim_security           TO anon, authenticated;

-- ---------------------------------------------------------------------------
-- Cross-domain and helper views
-- ---------------------------------------------------------------------------
GRANT SELECT ON vw_fidc_tranche_detail     TO anon, authenticated;
GRANT SELECT ON vw_fii_vs_fiagro           TO anon, authenticated;
GRANT SELECT ON vw_securit_emission_trend  TO anon, authenticated;
GRANT SELECT ON vw_fund_security_yield     TO anon, authenticated;

-- ---------------------------------------------------------------------------
-- Analytical functions (callable via supabase.rpc()). All SECURITY INVOKER,
-- so a function that reads a landing table revoked above fails loudly for
-- anon/authenticated instead of leaking it. ingest_log_summary is revoked
-- outright: it exists for operators, and its subject (cvm_ingest_log) is
-- explicitly not part of the user API.
-- ---------------------------------------------------------------------------
GRANT EXECUTE ON FUNCTION fund_profile(TEXT)                                                      TO anon, authenticated;
GRANT EXECUTE ON FUNCTION search_funds(TEXT, TEXT, INT)                                           TO anon, authenticated;
GRANT EXECUTE ON FUNCTION new_funds_per_period(TEXT[], DATE, DATE)                                TO anon, authenticated;
GRANT EXECUTE ON FUNCTION fund_nav_series(TEXT, DATE, DATE, TEXT)                                  TO anon, authenticated;
GRANT EXECUTE ON FUNCTION fund_flow_trend(TEXT, DATE, DATE, TEXT)                                  TO anon, authenticated;
GRANT EXECUTE ON FUNCTION industry_aum_trend(TEXT[], DATE, DATE)                                  TO anon, authenticated;
GRANT EXECUTE ON FUNCTION yield_distribution(TEXT, DATE, NUMERIC)                                 TO anon, authenticated;
GRANT EXECUTE ON FUNCTION fund_ranking(TEXT, TEXT, DATE, INT)                                     TO anon, authenticated;
GRANT EXECUTE ON FUNCTION market_concentration(TEXT, DATE)                                        TO anon, authenticated;
GRANT EXECUTE ON FUNCTION entity_monthly_stats(TEXT, DATE, DATE)                                  TO anon, authenticated;
GRANT EXECUTE ON FUNCTION cross_entity_comparison(TEXT[], TEXT, DATE, DATE)                       TO anon, authenticated;
GRANT EXECUTE ON FUNCTION quotaholder_trend(TEXT, DATE, DATE)                                     TO anon, authenticated;
GRANT EXECUTE ON FUNCTION fidc_tranche_performance(TEXT, DATE, DATE)                              TO anon, authenticated;
GRANT EXECUTE ON FUNCTION fidc_delinquency_trend(DATE, DATE, TEXT)                                TO anon, authenticated;
GRANT EXECUTE ON FUNCTION fidc_subordination_trend(TEXT, DATE, DATE)                              TO anon, authenticated;
GRANT EXECUTE ON FUNCTION security_issuance_trend(TEXT, DATE, DATE)                               TO anon, authenticated;
GRANT EXECUTE ON FUNCTION security_maturity_ladder(TEXT, DATE)                                    TO anon, authenticated;
GRANT EXECUTE ON FUNCTION distressed_securities(TEXT, DATE)                                       TO anon, authenticated;
GRANT EXECUTE ON FUNCTION yield_universe(TEXT[], TEXT[], DATE, DATE, NUMERIC)                     TO anon, authenticated;
GRANT EXECUTE ON FUNCTION data_coverage(TEXT, DATE, DATE)                                         TO anon, authenticated;
REVOKE ALL ON FUNCTION ingest_log_summary(DATE, DATE)                                             FROM anon, authenticated;

COMMIT;
