-- Rows upserted and run outcomes per calendar day, last 30 days.
--
-- This is the chart that would have made a month-long silent outage visible on
-- day two: a day with no cron run has no cvm_ingest_log rows at all, and a
-- day-spine LEFT JOIN renders that as a hole in the series rather than dropping
-- the day from the axis.
--
-- The generate_series day spine drives the rows (fixed 30) and the aggregate
-- LATERAL always returns exactly one row, so an empty log yields 30 blank days
-- instead of a 0-row source — which writes a zero-byte parquet and kills the
-- build.
--
-- Days are bucketed on started_at in the database's own time zone. Statuses are
-- the pipeline's own: ok / error / skipped (a not-yet-published month) /
-- running (never finished).
with spine as (
  select generate_series(current_date - 29, current_date, interval '1 day')::date as day
)
select
  sp.day,
  l.n_runs,
  l.n_ok,
  l.n_error,
  l.n_skipped,
  l.n_running,
  l.rows_upserted
from spine sp
left join lateral (
  select
    count(*)                                          as n_runs,
    count(*) filter (where g.status = 'ok')           as n_ok,
    count(*) filter (where g.status = 'error')        as n_error,
    count(*) filter (where g.status = 'skipped')      as n_skipped,
    count(*) filter (where g.status = 'running')      as n_running,
    coalesce(sum(g.rows_upserted), 0)                 as rows_upserted
  from cvm_ingest_log g
  where g.started_at >= sp.day
    and g.started_at <  sp.day + 1
) l on true
order by sp.day
