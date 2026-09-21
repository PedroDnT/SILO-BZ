-- The IPCA set on a monthly spine: headline, BACEN's own 12-month
-- accumulation, IPCA-15, the five BCB cores, monitored vs free prices and the
-- diffusion index. Last 36 months.
--
-- Same construction as macro_rate_series.sql: a generate_series month spine
-- LEFT JOINed to the data, so the row count is a fixed 36 whatever bacen_sgs
-- holds — no zero-row parquet. One observation per (series, month): the LAST
-- reading in the month (these are monthly indices, one reading each; DISTINCT
-- ON keeps the construction identical to the rate series).
--
-- Units, unconverted: every column is the % change in the month AS BACEN
-- PUBLISHES IT, except ipca_12m_num2 (BACEN's 12-month accumulation, code
-- 13522 — BACEN's number, not chained here) and difusao_num2 (the share of
-- items that rose, %). Nothing is annualised, chained or rebased on this page;
-- the chained acc_12m lives in api.inflation, where it is labelled derived.
--
-- Codes are the same list as INFLATION_SERIES in src/pipeline/bacen_pipeline.py
-- and api.inflation_registry() in 19_api_contract.sql;
-- tests/test_inflation_contract.py pins them together.
with spine as (
  -- SPINE END: the last ENDED month. IPCA publishes month M around the 10th
  -- of M+1, so the last ended month is usually still empty; macro.md clamps
  -- each chart to its own last non-null month.
  select generate_series(
           date_trunc('month', current_date) - interval '36 months',
           date_trunc('month', current_date) - interval '1 month',
           interval '1 month'
         )::date as period
),
monthly as (
  select distinct on (series_code, date_trunc('month', reference_date))
    series_code,
    date_trunc('month', reference_date)::date as period,
    value
  from bacen_sgs
  where series_code in (433, 13522, 7478, 4466, 11426, 11427, 16121, 16122, 4449, 11428, 21379)
    and reference_date >= (date_trunc('month', current_date) - interval '36 months')::date
    and reference_date <  date_trunc('month', current_date)::date
  order by series_code, date_trunc('month', reference_date), reference_date desc
)
select
  sp.period,
  max(m.value) filter (where m.series_code = 433)   as ipca_mes_num2,
  max(m.value) filter (where m.series_code = 13522) as ipca_12m_num2,
  max(m.value) filter (where m.series_code = 7478)  as ipca15_mes_num2,
  max(m.value) filter (where m.series_code = 4466)  as core_ms_num2,
  max(m.value) filter (where m.series_code = 11426) as core_ma_num2,
  max(m.value) filter (where m.series_code = 11427) as core_ex0_num2,
  max(m.value) filter (where m.series_code = 16121) as core_ex2_num2,
  max(m.value) filter (where m.series_code = 16122) as core_dp_num2,
  max(m.value) filter (where m.series_code = 4449)  as monitorados_num2,
  max(m.value) filter (where m.series_code = 11428) as livres_num2,
  max(m.value) filter (where m.series_code = 21379) as difusao_num2
from spine sp
left join monthly m on m.period = sp.period
group by sp.period
order by sp.period
