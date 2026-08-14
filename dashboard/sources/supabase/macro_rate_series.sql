-- Monthly view of the policy / inflation SGS series, last 60 months.
--
-- Driven from a generate_series month spine and LEFT JOINed to the data, so the
-- row count is a fixed 60 whatever bacen_sgs holds — the zero-row parquet that
-- kills an Evidence build cannot happen here. Months with no observation come
-- back NULL, which is what absent data should look like.
--
-- One observation per (series, month): the LAST reading in the month
-- (DISTINCT ON ... ORDER BY reference_date DESC), not an average — these are
-- levels (SELIC target, daily CDI) and monthly-change indices, and averaging
-- either would invent a number BACEN never published.
--
-- Units, unconverted: SELIC meta % a.a. · SELIC diária and CDI % a.d. ·
-- IPCA / IGP-M / INPC / poupança % change in the month.
with spine as (
  select generate_series(
           date_trunc('month', current_date) - interval '59 months',
           date_trunc('month', current_date),
           interval '1 month'
         )::date as period
),
monthly as (
  select distinct on (series_code, date_trunc('month', reference_date))
    series_code,
    date_trunc('month', reference_date)::date as period,
    value
  from bacen_sgs
  where reference_date >= (date_trunc('month', current_date) - interval '59 months')::date
  order by series_code, date_trunc('month', reference_date), reference_date desc
)
select
  sp.period,
  max(m.value) filter (where m.series_code = 432) as selic_meta_num2,
  max(m.value) filter (where m.series_code = 11)  as selic_diaria_num2,
  max(m.value) filter (where m.series_code = 12)  as cdi_num2,
  max(m.value) filter (where m.series_code = 433) as ipca_mes_num2,
  max(m.value) filter (where m.series_code = 189) as igpm_mes_num2,
  max(m.value) filter (where m.series_code = 188) as inpc_mes_num2,
  max(m.value) filter (where m.series_code = 25)  as poupanca_mes_num2
from spine sp
left join monthly m on m.period = sp.period
group by sp.period
order by sp.period
