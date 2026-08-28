-- Investor base (nr_cotst) by fund family, monthly, last 36 months.
--
-- Wraps quotaholder_trend() (src/store/analytical/09_analytical_functions.sql)
-- and pivots it onto a month spine that drives the row count (fixed 36), so an
-- empty fact_fund_monthly gives NULL columns rather than a 0-row source — which
-- would write a zero-byte parquet and break the build.
--
-- COVERAGE: nr_cotst is only carried for FI (from cvm_fi_diario), FII
-- (complemento) and FIAGRO. FIDC and FIP report no quotaholder count at all, so
-- they are absent by construction and the total is a total of what exists — not
-- an industry-wide investor count.
--
-- Counts are divided by 1e6 here; the unit lives in the column title.
with spine as (
  select generate_series(
           date_trunc('month', latest_complete_period(null)) - interval '35 months',
           date_trunc('month', latest_complete_period(null)),
           interval '1 month'
         )::date as period
),
t as (
  select *
  from quotaholder_trend(
    null,
    (date_trunc('month', latest_complete_period(null)) - interval '35 months')::date,
    current_date
  )
  -- per-family completeness clamp (see mv_period_completeness)
  where period <= latest_complete_period(entity_type)
)
select
  sp.period,
  sum(t.total_cotistas) filter (where t.entity_type = 'fi')     / 1e6 as fi_cotistas_mm,
  sum(t.total_cotistas) filter (where t.entity_type = 'fii')    / 1e6 as fii_cotistas_mm,
  sum(t.total_cotistas) filter (where t.entity_type = 'fiagro') / 1e6 as fiagro_cotistas_mm,
  sum(t.total_cotistas)                                         / 1e6 as total_cotistas_mm,
  sum(t.n_funds_with_data)                                            as n_funds_with_data
from spine sp
left join t on date_trunc('month', t.period)::date = sp.period
group by sp.period
order by sp.period
