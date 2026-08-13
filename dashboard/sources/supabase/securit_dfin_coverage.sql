-- Filing COVERAGE ONLY for cvm_securit_dfin (securitizadora financial
-- statements). Deliberately not a financial analysis.
--
-- cvm_securit_dfin has no parsed measures to chart: schema.sql gives it
-- (instrument_type, period_year, cnpj_securit, raw JSONB) and
-- src/parsers/field_maps/securit_dfin.py maps exactly one field, cnpj_securit —
-- "All other fields fall through to residual `raw` until the schema is
-- extended." Charting a balance sheet from here would mean inventing one, so
-- this source counts filings and nothing else.
--
-- instrument_type values are 'dfin_cra' / 'dfin_cri' — these come straight from
-- the doc_type and are NOT rewritten by _DOC_TO_INSTRUMENT (which only covers
-- the classe/fluxo doc types), unlike cvm_securit_serie.
--
-- ZERO-ROW SAFETY: generate_series over the filing years drives the rows
-- (dfin_cri starts 2018, dfin_cra 2019 per src/fetchers/cvm_config.py); the
-- aggregate is LEFT JOINed, so an unfetched year reports NULL.
with years as (
  select generate_series(2018, extract(year from current_date)::int) as period_year
),
agg as (
  select
    period_year,
    count(*) filter (where instrument_type = 'dfin_cra')               as n_cra,
    count(*) filter (where instrument_type = 'dfin_cri')               as n_cri,
    count(*) filter (where instrument_type not in ('dfin_cra', 'dfin_cri')) as n_outros,
    count(distinct cnpj_securit)                                       as n_securitizadoras
  from cvm_securit_dfin
  group by period_year
)
select
  y.period_year::text as period_year,
  a.n_cra,
  a.n_cri,
  a.n_outros,
  a.n_securitizadoras
from years y
left join agg a on a.period_year = y.period_year
order by y.period_year
