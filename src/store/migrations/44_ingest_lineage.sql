-- 44_ingest_lineage.sql — which code produced this data (plan 1c).
--
-- cvm_ingest_log already says WHEN a slice landed and HOW MANY rows. It did
-- not say WHICH CODE landed them, so a question like "were these FIDC rows
-- parsed before or after the field-map fix?" had no answer short of
-- correlating finished_at against the git log by hand. Two columns close it:
--
--   git_sha         the commit the ingest ran from, read from GITHUB_SHA,
--                   which GitHub Actions sets on every workflow run. NULL
--                   when unset (a local run, or any row from before this
--                   migration) — NEVER invented, never back-filled from a
--                   guess about which commit was deployed at the time.
--   parser_version  src.pipeline.ingest_log.PARSER_VERSION, a hand-bumped
--                   integer-as-text that changes whenever a parser or field
--                   map changes what a stored value MEANS. A commit sha moves
--                   on every docs edit; this moves only when the data would
--                   read differently, so "re-ingest everything below N" is a
--                   query, not an archaeology project. NULL on old rows.
--
-- Served (v34): api.coverage().landed_git_sha is the git_sha of the very run
-- that sets landed_at. The landing tables themselves are unchanged: the audit
-- row IS the lineage record, one per slice (integrity rule 3), and every data
-- row already joins to its slice through its natural keys.
--
-- Mirrored in schema.sql (CREATE TABLE body + the same guarded ALTER, so an
-- existing database reaches the columns from schema.sql alone). Idempotent
-- and psql-clean: CI applies with -v ON_ERROR_STOP=1. Nullable with no
-- default, so on PostgreSQL 11+ this is a catalog-only change — no rewrite of
-- the log.

ALTER TABLE cvm_ingest_log ADD COLUMN IF NOT EXISTS git_sha TEXT, ADD COLUMN IF NOT EXISTS parser_version TEXT;

COMMENT ON COLUMN cvm_ingest_log.git_sha IS
    'Commit the ingest ran from (GITHUB_SHA). NULL when unset — a local run, or a row older than migration 44. Never invented.';
COMMENT ON COLUMN cvm_ingest_log.parser_version IS
    'src.pipeline.ingest_log.PARSER_VERSION at run time: bumped whenever a parser or field map changes what a stored value means. NULL on rows older than migration 44.';
