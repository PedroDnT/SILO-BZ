-- 68_ingest_log_rows_deleted.sql: how many stored rows a slice removed.
--
-- The daily run re-reads the four CDA blocks of every month until month M+5
-- ends (issue #551, PR #554), and a fund may re-file in that time. Re-reads
-- used to be upsert-only, so a position a fund dropped stayed stored, and a
-- changed block-6 row (key ends in row_hash) landed beside the old one. A
-- monthly CDA slice now makes every fund present in the file hold exactly the
-- rows the file carries for it, in one transaction per batch of whole funds
-- (src/store/pg_client.py replace_scoped_rows). Funds absent from the file
-- keep every stored row.
--
--   rows_deleted   stored rows that replace removed for this slice. NULL for
--                  every slice that does not replace (all others, and every
--                  row older than this migration), 0 for a replace that
--                  removed nothing. On an error row it counts what the
--                  batches committed before the failure removed.
--
-- Mirrored in schema.sql (CREATE TABLE body plus the same guarded ALTER).
-- Idempotent and psql-clean. Nullable with no default, so a catalog-only
-- change with no rewrite of the log.

ALTER TABLE cvm_ingest_log ADD COLUMN IF NOT EXISTS rows_deleted INT;

COMMENT ON COLUMN cvm_ingest_log.rows_deleted IS
    'Stored rows a per-fund replace removed for this slice (monthly CDA blocks, migration 68). NULL when the slice does not replace.';
