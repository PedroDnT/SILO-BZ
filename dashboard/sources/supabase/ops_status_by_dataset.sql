-- Run outcomes per (entity, doc_type) over the last 30 days, via the
-- ingest_log_summary() RPC (src/store/analytical/09_analytical_functions.sql).
--
-- The literal entity list is the row driver — these are the entity labels the
-- pipeline actually writes to cvm_ingest_log (src/pipeline/cvm_pipeline.py and
-- anbima_pipeline.py), NOT the API dispatch keys, which differ (the log
-- records e.g. doc_type 'inf_diario' where dispatch calls it 'diario'). With
-- LEFT JOIN LATERAL, an entity that produced no runs at all still comes back as
-- one row with NULL counts, so the source can never be empty — a 0-row source
-- writes a zero-byte parquet and takes the whole Evidence build down.
--
-- ingest_log_summary only counts 'ok' and 'error', so 'skipped' is added here
-- from the log directly. skipped is expected, not a failure: it is how a
-- not-yet-published CVM month is recorded.
with entities (entity) as (
  values ('fi'), ('fidc'), ('fiagro'), ('fii'), ('fip'),
         ('securit'), ('etf'), ('cia_aberta'), ('anbima_etf'),
         ('b3'), ('bacen')
)
select
  e.entity,
  s.doc_type,
  s.n_runs,
  s.n_ok,
  s.n_error,
  round(100.0 * s.n_ok / nullif(s.n_runs, 0), 1) as ok_num1,
  (select count(*)
     from cvm_ingest_log g
    where g.entity = e.entity
      and g.doc_type = s.doc_type
      and g.status = 'skipped'
      and g.started_at >= current_date - 30)       as n_skipped,
  s.total_rows,
  s.last_run,
  left(s.last_error_msg, 160)                      as last_error_msg
from entities e
left join lateral (
  select *
  from ingest_log_summary((current_date - 30)::date, current_date) f
  where f.entity = e.entity
) s on true
order by coalesce(s.n_error, 0) desc, e.entity, s.doc_type
