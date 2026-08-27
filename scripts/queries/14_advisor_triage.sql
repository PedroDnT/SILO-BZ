-- Classify Supabase Performance Advisor lints against this warehouse.
-- Read-only. Paste into psql $POSTGRES_URL -f scripts/queries/14_advisor_triage.sql
--
-- Do NOT add PRIMARY KEYs or DROP INDEX to silence the dashboard. See
-- docs/DATABASE_MAINTENANCE.md §10.

\echo '=== 1. public tables that are not ours (leftovers) ==='
-- Anything here is not created by schema.sql / migrations. `messages` belongs
-- on this list if the advisor mentioned messages_sender_id_fkey.
SELECT n.nspname AS schema, c.relname AS relation,
       CASE c.relkind
         WHEN 'r' THEN 'table'
         WHEN 'p' THEN 'partitioned'
         WHEN 'v' THEN 'view'
         WHEN 'm' THEN 'matview'
         ELSE c.relkind::text
       END AS kind,
       c.reltuples::bigint AS est_rows
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relkind IN ('r', 'p', 'v', 'm')
  AND c.relname !~ '^(cvm_|bacen_|cia_|b3_|etf_|anbima_|dim_|fact_|fraud_|fund_|mv_|instrument_|vw_)'
  AND c.relispartition IS NOT TRUE
ORDER BY 1, 2;

\echo '=== 2. no_primary_key — partition children vs real gaps ==='
SELECT
    n.nspname AS schema,
    c.relname AS table_name,
    CASE
      WHEN c.relispartition THEN 'partition child (linter false positive)'
      WHEN c.relkind = 'p'  THEN 'partitioned parent (UNIQUE on natural key is enough)'
      ELSE 'real: no PK and not a partition'
    END AS classification,
    EXISTS (
        SELECT 1 FROM pg_constraint u
        WHERE u.conrelid = c.oid AND u.contype = 'u'
    ) AS has_unique
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relkind IN ('r', 'p')
  AND NOT EXISTS (
      SELECT 1 FROM pg_constraint p
      WHERE p.conrelid = c.oid AND p.contype = 'p'
  )
ORDER BY classification, table_name;

\echo '=== 3. unused_index (idx_scan = 0) — size, not a drop list ==='
SELECT
    s.schemaname,
    s.relname AS table_name,
    s.indexrelname AS index_name,
    s.idx_scan,
    pg_size_pretty(pg_relation_size(s.indexrelid)) AS index_size,
    i.indisunique AS is_unique
FROM pg_stat_user_indexes s
JOIN pg_index i ON i.indexrelid = s.indexrelid
WHERE s.schemaname = 'public'
  AND s.idx_scan = 0
  AND NOT i.indisprimary
ORDER BY pg_relation_size(s.indexrelid) DESC, s.relname, s.indexrelname;

\echo '=== 4. foreign keys in public (this warehouse does not declare any) ==='
-- An FK here is almost certainly leftover. The advisor's unindexed-FK hit
-- `messages_sender_id_fkey` is this case.
SELECT
    c.conrelid::regclass AS table_name,
    c.conname AS fk_name,
    pg_get_constraintdef(c.oid) AS definition
FROM pg_constraint c
JOIN pg_class t ON t.oid = c.conrelid
JOIN pg_namespace n ON n.oid = t.relnamespace
WHERE c.contype = 'f'
  AND n.nspname = 'public'
ORDER BY 1, 2;
