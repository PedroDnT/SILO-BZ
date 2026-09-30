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
with anchor as (
  -- SPINE END. Securitizadoras are outside fact_fund_monthly, so no
  -- coverage-based completeness exists for them. The rule is the last ENDED
  -- month that has a filing: never the in-progress month (partial by
  -- construction for a monthly filing) and never a month the filings have not
  -- reached yet — the axis would run past the data. least() ignores a NULL
  -- max() on an empty table, so this falls back to the last ended month.
  select least(
           date_trunc('month', current_date) - interval '1 month',
           date_trunc('month', max(data_referencia))
         )::date as p_end
  from cvm_securit_serie
),
months as (
  select generate_series(
           date_trunc('month', a.p_end) - interval '35 months',
           date_trunc('month', a.p_end),
           interval '1 month'
         )::date as period
  from anchor a
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
    t.n_em_atraso,
    t.n_sem_status
  from anchor a
  cross join lateral security_issuance_trend(
         null::text,
         (date_trunc('month', a.p_end) - interval '35 months')::date,
         (date_trunc('month', a.p_end) + interval '1 month' - interval '1 day')::date
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
    sum(n_em_atraso)                                     as n_em_atraso,
    sum(n_sem_status)                                    as n_sem_status,
    -- A status nobody classifies yet: 0 while CVM files only Adimplente and
    -- Em atraso. Non-zero is how a new value shows up instead of hiding the
    -- way 'Inadimplente' did (#430).
    sum(n_series - n_adimplente - n_em_atraso - n_sem_status) as n_outro_status
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
  a.n_em_atraso,
  a.n_sem_status,
  a.n_outro_status,
  -- Of series that filed a status: an empty status is unknown, not current.
  round(100.0 * a.n_em_atraso / nullif(a.n_series - a.n_sem_status, 0), 1) as em_atraso_num1
from months m
left join agg a on a.period = m.period
order by m.period
