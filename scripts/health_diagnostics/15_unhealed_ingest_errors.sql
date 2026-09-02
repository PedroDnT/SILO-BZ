-- INGEST BACKLOG: unhealed error slices, including the ones health no longer fails on
--
-- Check 1 in health.yml counts unhealed error slices, but since #174 it only
-- FAILS on slices the daily run would retry: undated ones, current-year yearly
-- ones, and monthly periods inside CVM_DAILY_LOOKBACK_MONTHS. That change is
-- right — daily_update never probes 2005, so a 26-hour alarm on a 2005 slice is
-- a red light only a backfill can clear, and the watchdog's remedy (re-run
-- daily) is a no-op for it.
--
-- But the run now prints "0 (of 7 error rows)" and says nothing about the 7.
-- A backlog that cannot fail the gate and cannot be seen either is the same
-- shape as the failures this repo keeps finding: present, queryable, silently
-- ignored. This file is the view of it. It is read-only and reads one small
-- table (cvm_ingest_log), so it costs nothing to keep in every diagnostics run.
--
-- "Unhealed" is defined exactly as check 1 defines it: an 'error' row for a
-- slice with no later 'ok' or 'skipped' row for the same
-- (entity, doc_type, period_year, period_month). IS NOT DISTINCT FROM is
-- required — NULL period keys must match each other.
--
-- Reading it:
--   1. rollup — what to re-dispatch, and how much of it the gate can see.
--      `in_daily_window` rows are the ones check 1 fails on; `historical` rows
--      are backfill work that will sit here until someone dispatches it.
--   2. detail — the historical backlog, latest attempt per slice. The error
--      text says whether it is a source truth (a block CVM never published),
--      a transport fault (CVMHostUnreachable — just re-dispatch), or a real
--      defect.
--   3. reconciliation — the same numbers over check 1's own 26h window, so the
--      "N (of M error rows)" line in the health log can be explained rather
--      than guessed at.
--
-- An empty result for block 1 means there is no ingest backlog at all.
--
-- The `3 * INTERVAL '1 month'` below is DAILY_LOOKBACK_MONTHS - 1, matching
-- health.yml's own expression. psql -f takes no variables here, so the constant
-- is literal; tests/test_health_workflow.py asserts it against the workflow's
-- env so the two cannot drift into disagreeing about what "the daily window" is.

-- 1. Rollup: what is outstanding, and how much of it the gate can see.
WITH unhealed AS (
    SELECT DISTINCT ON (e.entity, e.doc_type, e.period_year, e.period_month)
           e.entity, e.doc_type, e.period_year, e.period_month,
           e.started_at, e.error_msg,
           (
                 e.period_year IS NULL
              OR (e.period_month IS NULL
                  AND e.period_year = EXTRACT(YEAR FROM CURRENT_DATE)::int)
              OR (e.period_month IS NOT NULL
                  AND make_date(e.period_year, e.period_month, 1)
                      >= (date_trunc('month', CURRENT_DATE)
                          - 3 * INTERVAL '1 month')::date)
           ) AS in_daily_window
      FROM cvm_ingest_log e
     WHERE e.status = 'error'
       AND NOT EXISTS (
             SELECT 1 FROM cvm_ingest_log s
              WHERE s.status IN ('ok', 'skipped')
                AND s.entity       IS NOT DISTINCT FROM e.entity
                AND s.doc_type     IS NOT DISTINCT FROM e.doc_type
                AND s.period_year  IS NOT DISTINCT FROM e.period_year
                AND s.period_month IS NOT DISTINCT FROM e.period_month
                AND s.started_at   > e.started_at)
     ORDER BY e.entity, e.doc_type, e.period_year, e.period_month,
              e.started_at DESC
)
SELECT entity, doc_type,
       count(*)                                    AS unhealed_slices,
       count(*) FILTER (WHERE in_daily_window)     AS in_daily_window,
       count(*) FILTER (WHERE NOT in_daily_window) AS historical,
       min(period_year)                            AS first_year,
       max(period_year)                            AS last_year,
       max(started_at)                             AS latest_attempt
  FROM unhealed
 GROUP BY entity, doc_type
 ORDER BY unhealed_slices DESC, entity, doc_type;

-- 2. Detail: the historical backlog the gate no longer fails on.
--    One row per slice (its latest attempt), newest first.
WITH unhealed AS (
    SELECT DISTINCT ON (e.entity, e.doc_type, e.period_year, e.period_month)
           e.entity, e.doc_type, e.period_year, e.period_month,
           e.started_at, e.error_msg,
           (
                 e.period_year IS NULL
              OR (e.period_month IS NULL
                  AND e.period_year = EXTRACT(YEAR FROM CURRENT_DATE)::int)
              OR (e.period_month IS NOT NULL
                  AND make_date(e.period_year, e.period_month, 1)
                      >= (date_trunc('month', CURRENT_DATE)
                          - 3 * INTERVAL '1 month')::date)
           ) AS in_daily_window
      FROM cvm_ingest_log e
     WHERE e.status = 'error'
       AND NOT EXISTS (
             SELECT 1 FROM cvm_ingest_log s
              WHERE s.status IN ('ok', 'skipped')
                AND s.entity       IS NOT DISTINCT FROM e.entity
                AND s.doc_type     IS NOT DISTINCT FROM e.doc_type
                AND s.period_year  IS NOT DISTINCT FROM e.period_year
                AND s.period_month IS NOT DISTINCT FROM e.period_month
                AND s.started_at   > e.started_at)
     ORDER BY e.entity, e.doc_type, e.period_year, e.period_month,
              e.started_at DESC
)
SELECT started_at, entity, doc_type, period_year, period_month,
       left(coalesce(error_msg, ''), 160) AS error
  FROM unhealed
 WHERE NOT in_daily_window
 ORDER BY started_at DESC
 LIMIT 60;

-- 3. Reconciliation with check 1's own window: the health log prints
--    "unhealed ingest errors (26h, daily window): N (of M error rows)".
--    M is every error row started in 26h; N is the unhealed subset the gate
--    fails on. This block shows both, plus the middle term the log omits —
--    unhealed slices in 26h that the daily-window filter excluded.
SELECT
    (SELECT count(*) FROM cvm_ingest_log
      WHERE status = 'error'
        AND started_at > now() - interval '26 hours')          AS error_rows_26h,
    (SELECT count(*) FROM (
        SELECT DISTINCT e.entity, e.doc_type, e.period_year, e.period_month
          FROM cvm_ingest_log e
         WHERE e.status = 'error'
           AND e.started_at > now() - interval '26 hours'
           AND NOT EXISTS (
                 SELECT 1 FROM cvm_ingest_log s
                  WHERE s.status IN ('ok', 'skipped')
                    AND s.entity       IS NOT DISTINCT FROM e.entity
                    AND s.doc_type     IS NOT DISTINCT FROM e.doc_type
                    AND s.period_year  IS NOT DISTINCT FROM e.period_year
                    AND s.period_month IS NOT DISTINCT FROM e.period_month
                    AND s.started_at   > e.started_at)
     ) u)                                                      AS unhealed_slices_26h,
    (SELECT count(*) FROM (
        SELECT DISTINCT e.entity, e.doc_type, e.period_year, e.period_month
          FROM cvm_ingest_log e
         WHERE e.status = 'error'
           AND e.started_at > now() - interval '26 hours'
           AND NOT EXISTS (
                 SELECT 1 FROM cvm_ingest_log s
                  WHERE s.status IN ('ok', 'skipped')
                    AND s.entity       IS NOT DISTINCT FROM e.entity
                    AND s.doc_type     IS NOT DISTINCT FROM e.doc_type
                    AND s.period_year  IS NOT DISTINCT FROM e.period_year
                    AND s.period_month IS NOT DISTINCT FROM e.period_month
                    AND s.started_at   > e.started_at)
           AND NOT (
                 e.period_year IS NULL
              OR (e.period_month IS NULL
                  AND e.period_year = EXTRACT(YEAR FROM CURRENT_DATE)::int)
              OR (e.period_month IS NOT NULL
                  AND make_date(e.period_year, e.period_month, 1)
                      >= (date_trunc('month', CURRENT_DATE)
                          - 3 * INTERVAL '1 month')::date))
     ) u)                                                      AS excluded_as_historical;
