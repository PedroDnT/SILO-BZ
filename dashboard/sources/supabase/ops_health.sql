-- One-line pipeline health summary from the cvm_ingest_log audit table.
--
-- Every ingest run writes exactly one cvm_ingest_log row (started 'running',
-- finished 'ok' / 'error' / 'skipped'), so this table is the only place that
-- knows whether the nightly job actually ran. 'skipped' is a deliberate,
-- non-alarming status: a monthly slice CVM has not published yet 404s and is
-- logged skipped, not error (src/pipeline/cvm_pipeline.py::_log_finish).
--
-- stuck_running counts rows that started more than 6 hours ago and never
-- reached a terminal status — the signature of a process that died mid-run.
--
-- Aggregates with no GROUP BY, so exactly one row always comes back even on a
-- completely empty log; a 0-row source writes a zero-byte parquet and breaks the
-- Evidence build.
select
  count(*)                                                                              as log_rows_total,
  count(*) filter (where started_at >= now() - interval '24 hours')                     as runs_24h,
  count(*) filter (where started_at >= now() - interval '7 days')                       as runs_7d,
  count(*) filter (where started_at >= now() - interval '7 days' and status = 'ok')     as ok_7d,
  count(*) filter (where started_at >= now() - interval '7 days' and status = 'error')  as errors_7d,
  count(*) filter (where started_at >= now() - interval '7 days' and status = 'skipped') as skipped_7d,
  count(*) filter (where status = 'running' and started_at < now() - interval '6 hours') as stuck_running,
  sum(rows_upserted) filter (where started_at >= now() - interval '24 hours')           as rows_24h,
  sum(rows_upserted) filter (where started_at >= now() - interval '7 days')             as rows_7d,
  max(started_at)                                                                        as last_run_at,
  round(extract(epoch from (now() - max(started_at)))::numeric / 3600.0, 1)                       as hours_since_last_run,
  count(distinct entity)                                                                 as entities_seen
from cvm_ingest_log
