-- Monthly issuance / outstanding trend by instrument family, reusing the
-- existing security_issuance_trend() RPC (src/store/analytical/
-- 09_analytical_functions.sql) rather than re-deriving its logic here.
--
-- ZERO-ROW SAFETY: a generate_series of the last 36 calendar months is the row
-- driver; the function result is LEFT JOINed onto it. Months with no securit
-- data come back with NULL measures, so this source can never be empty.
--
-- instrument_type NOTE: src/pipeline/ingest_securit.py::_DOC_TO_INSTRUMENT
-- rewrites the doc_type into the *_mensal label before upsert, so the values
-- actually stored in cvm_securit_serie are 'cra_mensal' / 'cri_mensal' /
-- 'ots_mensal' — NOT the 'cra_classe' spelling that the dim_security comment
-- and yield_universe()'s default still mention. The prefix/suffix match below
-- classifies either spelling correctly.
with months as (
  select generate_series(
           date_trunc('month', current_date - interval '35 months'),
           date_trunc('month', current_date),
           interval '1 month'
         )::date as period
),
trend as (
  select
    t.period,
    case
      when t.instrument_type like 'cra%' or t.instrument_type like '%cra' then 'cra'
      when t.instrument_type like 'cri%' or t.instrument_type like '%cri' then 'cri'
      when t.instrument_type like 'ots%' or t.instrument_type like '%ots' then 'ots'
      else 'outros'
    end          as family,
    t.n_series,
    t.total_value,
    t.n_adimplente,
    t.n_inadimplente
  from security_issuance_trend(
         null::text,
         (date_trunc('month', current_date) - interval '35 months')::date,
         current_date
       ) t
),
agg as (
  select
    period,
    sum(total_value) filter (where family = 'cra') / 1e9 as cra_bn,
    sum(total_value) filter (where family = 'cri') / 1e9 as cri_bn,
    sum(total_value) filter (where family = 'ots') / 1e9 as ots_bn,
    sum(total_value) filter (where family = 'outros') / 1e9 as outros_bn,
    sum(n_series)                                        as n_series,
    sum(n_inadimplente)                                  as n_inadimplente
  from trend
  group by period
)
select
  m.period,
  a.cra_bn,
  a.cri_bn,
  a.ots_bn,
  a.outros_bn,
  a.n_series,
  a.n_inadimplente,
  round(100.0 * a.n_inadimplente / nullif(a.n_series, 0), 1) as inadimplente_num1
from months m
left join agg a on a.period = m.period
order by m.period
