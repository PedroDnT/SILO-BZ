-- The 20 most recent ingest runs, newest first, with their error text.
--
-- A generate_series(1, 20) slot spine drives the rows and the log is LEFT JOINed
-- onto it, so this source is always exactly 20 rows: on a fresh or wiped
-- database the slots simply come back blank instead of the source returning
-- nothing, writing a zero-byte parquet, and killing the Evidence build. Blank
-- rows at the bottom mean the log holds fewer than 20 runs.
--
-- row_number() is evaluated before ORDER BY / LIMIT in Postgres, so slots 1..20
-- are exactly the 20 newest runs.
--
-- duration_s is NULL while a run is still 'running' (finished_at unset) — that
-- is the tell for a job that died without writing its terminal status.
-- error_msg is truncated to 200 chars; the full text stays in the table.
with recent as (
  select
    row_number() over (order by started_at desc) as slot,
    entity,
    doc_type,
    period_year,
    period_month,
    status,
    rows_upserted,
    started_at,
    round(extract(epoch from (finished_at - started_at))::numeric, 1) as duration_s,
    error_msg
  from cvm_ingest_log
  order by started_at desc
  limit 20
),
slots as (
  select generate_series(1, 20) as slot
)
select
  s.slot,
  r.entity,
  r.doc_type,
  r.period_year,
  r.period_month,
  r.status,
  r.rows_upserted,
  r.duration_s,
  r.started_at,
  left(r.error_msg, 200) as error_msg
from slots s
left join recent r on r.slot = s.slot
order by s.slot
