-- STUCK 'running' ROWS: audit rows whose process died before the finish write
--
-- Check 1b in health.yml fails on daily-window slices stuck at 'running' for
-- more than MAX_RUNNING_AGE_HOURS with no later ok/skipped. This file is the
-- full view: every stuck row, any age, historical backfill slices included,
-- with how long it has sat, and whether a later attempt for the same slice
-- exists (and how that attempt ended). A row with a later 'ok' is healed
-- data-wise and only needs the sweep; a row with no later attempt is work.
--
-- Rows here come from three shapes: a GitHub job past timeout-minutes, a
-- runner lost mid-slice, or a process SIGKILLed — none of which reach the
-- pipeline's finish write (src/pipeline/ingest_log writes the error row on
-- cancellation, but nothing can write on SIGKILL). The 24 h sweep that flips
-- them to 'error' lives in backfill.yml's coverage inspection and runs only
-- when a backfill is dispatched.
--
-- Read-only; reads cvm_ingest_log alone.

SELECT e.started_at,
       round(extract(epoch from (now() - e.started_at)) / 3600.0, 1)  AS hours_running,
       e.entity,
       e.doc_type,
       e.period_year,
       e.period_month,
       (SELECT s.status
          FROM cvm_ingest_log s
         WHERE s.entity       IS NOT DISTINCT FROM e.entity
           AND s.doc_type     IS NOT DISTINCT FROM e.doc_type
           AND s.period_year  IS NOT DISTINCT FROM e.period_year
           AND s.period_month IS NOT DISTINCT FROM e.period_month
           AND s.started_at   > e.started_at
         ORDER BY s.started_at DESC
         LIMIT 1)                                                    AS later_attempt_status,
       CASE
         WHEN e.period_year IS NULL THEN 'undated'
         WHEN e.period_month IS NULL
              AND e.period_year = EXTRACT(YEAR FROM CURRENT_DATE)::int THEN 'current-year yearly'
         WHEN e.period_month IS NOT NULL
              AND make_date(e.period_year, e.period_month, 1)
                  >= (date_trunc('month', CURRENT_DATE) - 3 * INTERVAL '1 month')::date
              THEN 'daily window'
         ELSE 'historical'
       END                                                           AS scope
  FROM cvm_ingest_log e
 WHERE e.status = 'running'
   AND e.started_at < now() - interval '6 hours'
 ORDER BY e.started_at DESC
 LIMIT 100;
