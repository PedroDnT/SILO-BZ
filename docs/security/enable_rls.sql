-- =============================================================================
-- enable_rls.sql — Row-Level Security remediation for the public schema
--
-- ⚠️ REVIEW-ONLY — NOT auto-applied. This file lives OUTSIDE src/store/migrations/
-- on purpose: the CI apply-schema action runs every migration on every daily cron,
-- and enabling RLS is a security posture change the operator should apply
-- deliberately, not have slipped in by a schema bootstrap. Apply it by hand after
-- review:
--
--     psql "$POSTGRES_URL" -v ON_ERROR_STOP=1 -f docs/security/enable_rls.sql
--
-- -----------------------------------------------------------------------------
-- WHY
-- -----------------------------------------------------------------------------
-- A Supabase audit found 52 of 59 public tables with RLS OFF (pg_class.relrowsecurity
-- = false). With RLS off, the anon / publishable client key — which the dashboard and
-- webapp ship to the browser — can read every row, and (depending on table GRANTs)
-- potentially write too. All CVM/BACEN data here is public, so READ access for anon
-- is intended; unrestricted WRITE access from a browser key is not.
--
-- This script, for every public BASE TABLE:
--   1. ENABLEs row-level security, and
--   2. adds a read-only policy `anon_read` granting SELECT to anon + authenticated.
--
-- With RLS enabled and ONLY a SELECT policy present, Postgres default-denies
-- INSERT/UPDATE/DELETE for those roles — so the browser key becomes read-only while
-- the dashboard keeps working unchanged.
--
-- -----------------------------------------------------------------------------
-- WHY THE READ POLICY IS NON-NEGOTIABLE
-- -----------------------------------------------------------------------------
-- Enabling RLS WITHOUT a SELECT policy returns ZERO rows to anon — the dashboard and
-- webapp would go blank. That is why ENABLE + the `anon_read` policy happen in the
-- SAME transaction below: there is never a window where anon can authenticate but
-- reads are silently empty.
--
-- -----------------------------------------------------------------------------
-- WHY THE PIPELINE IS UNAFFECTED
-- -----------------------------------------------------------------------------
-- The ingestion pipeline connects via POSTGRES_URL as the table owner / a role with
-- BYPASSRLS (Supabase's service role and the `postgres` superuser both bypass RLS).
-- We deliberately do NOT use FORCE ROW LEVEL SECURITY, so the owner/service path that
-- runs every upsert is never subject to these policies — only client (anon /
-- authenticated) keys are. Ingestion, migrations, and analytical refresh keep working.
--
-- -----------------------------------------------------------------------------
-- IDEMPOTENT & DYNAMIC
-- -----------------------------------------------------------------------------
-- The DO block loops over every current public base table, so it cannot drift out of
-- sync with a hand-maintained list as new datasets are added. It DROPs the policy
-- before re-creating it, so re-running is safe. Re-run it after adding a new table
-- (or fold the two EXECUTEs into that dataset's migration if you prefer per-table
-- control).
-- =============================================================================

BEGIN;

DO $$
DECLARE
    t regclass;
BEGIN
    FOR t IN
        SELECT c.oid::regclass
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind IN ('r', 'p')   -- ordinary + partitioned parents (not views/matviews)
        ORDER BY c.relname
    LOOP
        EXECUTE format('ALTER TABLE %s ENABLE ROW LEVEL SECURITY;', t);
        EXECUTE format('DROP POLICY IF EXISTS anon_read ON %s;', t);
        EXECUTE format(
            'CREATE POLICY anon_read ON %s FOR SELECT TO anon, authenticated USING (true);',
            t
        );
        RAISE NOTICE 'RLS enabled + anon_read policy on %', t;
    END LOOP;
END $$;

COMMIT;

-- -----------------------------------------------------------------------------
-- VERIFY (run after applying): every public base table should be relrowsecurity = t
-- and have exactly one SELECT policy named anon_read.
-- -----------------------------------------------------------------------------
-- SELECT c.relname, c.relrowsecurity, p.polname, p.polcmd
-- FROM pg_class c
-- JOIN pg_namespace n ON n.oid = c.relnamespace
-- LEFT JOIN pg_policy p ON p.polrelid = c.oid
-- WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
-- ORDER BY c.relname;
--
-- Tables still showing relrowsecurity = f after this runs would be a bug in the loop;
-- there should be none.
