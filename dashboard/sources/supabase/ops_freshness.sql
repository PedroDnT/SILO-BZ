-- Freshness: the latest SUCCESSFUL slice per entity, and what happened last.
--
-- The operator question this answers is "when did each dataset last actually
-- land", which only 'ok' rows can answer — a run that 404s is logged 'skipped'
-- and a run that fails is logged 'error', and neither means data arrived. So
-- last_ok_at is computed from status = 'ok' alone, and the most recent attempt
-- of any status is shown beside it: last_status = 'error' with an old
-- last_ok_at is the exact shape of a silent outage.
--
-- Literal entity list drives the rows (fixed 9 — the labels the pipeline writes
-- to cvm_ingest_log), each LEFT JOIN LATERAL yields at most one row and keeps
-- the outer row when it yields none, so the source is never empty. A 0-row
-- source writes a zero-byte parquet and breaks the Evidence build.
--
-- Sorted worst-first with coalesce so an entity that has NEVER succeeded sorts
-- above one that succeeded a long time ago, instead of falling to the bottom as
-- a NULL.
with entities (entity) as (
  values ('fi'), ('fidc'), ('fiagro'), ('fii'), ('fip'),
         ('securit'), ('etf'), ('cia_aberta'), ('anbima_etf'),
         ('b3'), ('bacen')
)
select
  e.entity,
  ok.doc_type       as last_ok_doc_type,
  ok.period_year    as last_ok_year,
  ok.period_month   as last_ok_month,
  ok.rows_upserted  as last_ok_rows,
  ok.finished_at    as last_ok_at,
  round(extract(epoch from (now() - ok.finished_at))::numeric / 86400.0, 1) as days_since_ok,
  att.started_at    as last_attempt_at,
  att.status        as last_attempt_status,
  c.n_ok_30d,
  c.n_error_30d
from entities e
left join lateral (
  select g.doc_type, g.period_year, g.period_month, g.rows_upserted, g.finished_at
  from cvm_ingest_log g
  where g.entity = e.entity
    and g.status = 'ok'
    and g.finished_at is not null
  order by g.finished_at desc
  limit 1
) ok on true
left join lateral (
  select g.started_at, g.status
  from cvm_ingest_log g
  where g.entity = e.entity
  order by g.started_at desc
  limit 1
) att on true
left join lateral (
  select
    count(*) filter (where g.status = 'ok')    as n_ok_30d,
    count(*) filter (where g.status = 'error') as n_error_30d
  from cvm_ingest_log g
  where g.entity = e.entity
    and g.started_at >= current_date - 30
) c on true
order by coalesce(round(extract(epoch from (now() - ok.finished_at))::numeric / 86400.0, 1), 99999) desc
