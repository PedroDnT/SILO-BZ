-- sentinel_readonly_role.sql — the Sentinel agent's read-only login.
--
-- WHO RUNS THIS. The owner, by hand, once (and again only to rotate the
-- password). Not applied by CI, apply_schema.py or apply_analytical.sh, and
-- not a migration: it creates a LOGIN role with a password, which no
-- automated path in this repo does. See docs/planning/AGENTS.md
-- ("Sentinel credential").
--
-- HOW. psql as the database owner (postgres on Supabase), password passed as a
-- psql variable so it is never typed into this file or a shell history line:
--
--   read -rs SENTINEL_PW    # type or paste it; nothing is echoed
--   psql "$OWNER_DATABASE_URL" -v ON_ERROR_STOP=1 \
--        -v sentinel_password="$SENTINEL_PW" \
--        -f docs/security/sentinel_readonly_role.sql
--   unset SENTINEL_PW
--
-- Re-running is safe: an existing role gets its password reset and the same
-- grants re-applied (GRANT is idempotent).
--
-- WHAT IT GRANTS, AND NOTHING ELSE:
--   CONNECT  on this database
--   USAGE    on schemas public and api
--   SELECT   on public.cvm_ingest_log, public.fnet_document
--   EXECUTE  on api.coverage(), api.metric_coverage()
--   statement_timeout = 30s on the role
-- No INSERT/UPDATE/DELETE anywhere, no other table, no other function.
-- api.coverage() and api.metric_coverage() are SECURITY DEFINER, so they read
-- their sources as the owner; the role itself cannot read those sources.
--
-- NOT SET HERE: default_transaction_read_only. AGENTS.md §2 describes the
-- Sentinel's posture as "the same as health.yml" (read-only by default); this
-- script was scoped to the list above. Add
--   ALTER ROLE silo_sentinel SET default_transaction_read_only = on;
-- if you want that belt as well as the grants.
--
-- AFTER. The connection string (on Supabase's pooler the user is
-- silo_sentinel.<project-ref>) goes in the Sentinel routine's environment
-- secret, never in this repo. If api.coverage() or api.metric_coverage() is
-- ever DROPped and re-created (CREATE OR REPLACE keeps grants; DROP does not),
-- re-run this script.

\set ON_ERROR_STOP on

-- Refuse (non-zero exit, nothing created) when the password was not passed.
\if :{?sentinel_password}
\else
    DO $$ BEGIN RAISE EXCEPTION 'sentinel_password is not set: pass -v sentinel_password=... (see the header)'; END $$;
\endif

BEGIN;

SELECT NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'silo_sentinel') AS sentinel_missing
\gset

\if :sentinel_missing
    CREATE ROLE silo_sentinel LOGIN PASSWORD :'sentinel_password';
\else
    ALTER ROLE silo_sentinel LOGIN PASSWORD :'sentinel_password';
\endif

COMMENT ON ROLE silo_sentinel IS
    'Sentinel agent (docs/planning/AGENTS.md): CONNECT; USAGE on public, api; SELECT on cvm_ingest_log, fnet_document; EXECUTE on api.coverage(), api.metric_coverage(). Created by docs/security/sentinel_readonly_role.sql.';

ALTER ROLE silo_sentinel SET statement_timeout = '30s';

GRANT CONNECT ON DATABASE :"DBNAME" TO silo_sentinel;

GRANT USAGE ON SCHEMA public TO silo_sentinel;
GRANT USAGE ON SCHEMA api    TO silo_sentinel;

GRANT SELECT ON TABLE public.cvm_ingest_log TO silo_sentinel;
GRANT SELECT ON TABLE public.fnet_document  TO silo_sentinel;

GRANT EXECUTE ON FUNCTION api.coverage()        TO silo_sentinel;
GRANT EXECUTE ON FUNCTION api.metric_coverage() TO silo_sentinel;

COMMIT;
