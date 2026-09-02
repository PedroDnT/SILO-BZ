-- DISK: what is actually reclaimable, before anything is dropped
--
-- The warehouse is at ~104 GB of a 135 GB allowance and the next backfills
-- want room. docs/DATABASE_MAINTENANCE.md §9 forbids the two easy answers —
-- dropping landing tables, and VACUUM FULL on balancete from CI — and names
-- the one sanctioned reclaim: dropping indexes that have never served a
-- query, with migration 22 as the precedent. Migration 22 was written from a
-- measurement, not a hunch. This file is that measurement, refreshed, and it
-- is read-only on purpose: it answers "where would space come from" so that
-- any DROP is a separate, reviewed migration citing these numbers.
--
-- Every block is catalog/statistics only (pg_class, pg_stat_*). No table is
-- scanned. Sizes are pg_relation_size, which is on-disk truth, not an
-- estimate.
--
-- Read in this order:
--   1. stats_reset — if NOT NULL and recent, every idx_scan = 0 below is a
--      false zero and NOTHING in block 3 may be dropped on this evidence.
--   2. heap / index / toast split — says whether the bytes are rows, B-trees,
--      or the `raw` JSONB. Only the middle column is reclaimable by DROP INDEX.
--   3. never-used large indexes — the migration-22 shape. UNIQUE/PK rows are
--      listed for completeness but are the ON CONFLICT probes; they stay.
--   4. structurally redundant indexes — a non-unique index whose columns are
--      a leading prefix of a sibling's. The planner can use the sibling.
--   5. dead tuples — bloat autovacuum returns for REUSE but never shrinks;
--      it is why the file grows even when the row count does not. A high
--      ratio on a table upsert_rows rewrites daily is the bloat generator.

-- 1. Are idx_scan zeros trustworthy?
SELECT datname, stats_reset,
       CASE WHEN stats_reset IS NULL THEN 'never reset — idx_scan is cumulative since creation'
            ELSE 'RESET at ' || stats_reset::text || ' — treat idx_scan = 0 as UNKNOWN' END AS reading
  FROM pg_stat_database
 WHERE datname = current_database();

-- 2. Where the bytes are: top 20 relations split heap / indexes / toast.
SELECT c.relname,
       pg_size_pretty(pg_total_relation_size(c.oid))                       AS total,
       pg_size_pretty(pg_relation_size(c.oid))                             AS heap,
       pg_size_pretty(pg_indexes_size(c.oid))                              AS indexes,
       pg_size_pretty(CASE WHEN c.reltoastrelid <> 0
                           THEN pg_total_relation_size(c.reltoastrelid)
                           ELSE 0 END)                                     AS toast_raw_jsonb,
       round(100.0 * pg_indexes_size(c.oid)
             / NULLIF(pg_total_relation_size(c.oid), 0), 1)                AS idx_pct
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'public' AND c.relkind IN ('r', 'm')
 ORDER BY pg_total_relation_size(c.oid) DESC
 LIMIT 20;

-- 3. Candidate drops: every index over 100 MB, with its lifetime scan count.
--    Sorted so the biggest never-used ones are on top. `kind` says which are
--    the upsert probes (uq_/PK) that must stay regardless of idx_scan.
SELECT s.relname                                            AS table_name,
       s.indexrelname                                       AS index_name,
       pg_size_pretty(pg_relation_size(s.indexrelid))       AS size,
       s.idx_scan,
       CASE WHEN i.indisprimary THEN 'PRIMARY KEY'
            WHEN i.indisunique  THEN 'UNIQUE (ON CONFLICT probe)'
            ELSE 'plain' END                                AS kind,
       pg_get_indexdef(s.indexrelid)                        AS definition
  FROM pg_stat_user_indexes s
  JOIN pg_index i ON i.indexrelid = s.indexrelid
 WHERE s.schemaname = 'public'
   AND pg_relation_size(s.indexrelid) > 100 * 1024 * 1024
 ORDER BY (s.idx_scan = 0) DESC, pg_relation_size(s.indexrelid) DESC
 LIMIT 40;

-- 4. Structurally redundant: a plain index whose key columns are a leading
--    prefix of another index on the same table. The wider sibling answers
--    every query the narrow one can. This is idx_fi_balancete_cnpj vs
--    uq_fi_balancete from migration 22, generalised.
WITH ix AS (
  SELECT i.indrelid, i.indexrelid, c.relname AS index_name,
         i.indisunique, i.indisprimary,
         i.indkey::int2[] AS cols, array_length(i.indkey::int2[], 1) AS ncols,
         pg_relation_size(i.indexrelid) AS bytes
    FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
   WHERE n.nspname = 'public' AND i.indpred IS NULL AND i.indexprs IS NULL
)
SELECT t.relname                              AS table_name,
       a.index_name                           AS redundant_index,
       pg_size_pretty(a.bytes)                AS size,
       b.index_name                           AS covered_by,
       s.idx_scan                             AS redundant_idx_scan
  FROM ix a
  JOIN ix b ON b.indrelid = a.indrelid AND b.indexrelid <> a.indexrelid
           AND b.ncols > a.ncols
           AND b.cols[1:a.ncols] = a.cols
  JOIN pg_class t ON t.oid = a.indrelid
  JOIN pg_stat_user_indexes s ON s.indexrelid = a.indexrelid
 WHERE NOT a.indisunique AND NOT a.indisprimary
 ORDER BY a.bytes DESC
 LIMIT 20;

-- 5. Bloat: dead tuples and vacuum recency on the 15 largest tables.
--    n_tup_upd counts every ON CONFLICT DO UPDATE, including ones that
--    changed nothing — each is a new tuple version and a dead one behind it.
SELECT s.relname,
       pg_size_pretty(pg_relation_size(s.relid))            AS heap,
       s.n_live_tup, s.n_dead_tup,
       round(100.0 * s.n_dead_tup
             / NULLIF(s.n_live_tup + s.n_dead_tup, 0), 1)   AS dead_pct,
       s.n_tup_ins, s.n_tup_upd,
       round(1.0 * s.n_tup_upd / NULLIF(s.n_tup_ins, 0), 2) AS updates_per_insert,
       s.last_autovacuum::timestamp(0), s.last_autoanalyze::timestamp(0)
  FROM pg_stat_user_tables s
 WHERE s.schemaname = 'public'
 ORDER BY pg_relation_size(s.relid) DESC
 LIMIT 15;
