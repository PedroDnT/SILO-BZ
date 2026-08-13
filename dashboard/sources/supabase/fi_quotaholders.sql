-- FI quotaholder base over 36 months, via quotaholder_trend('fi', …).
-- This is the headcount from cvm_fi_diario (nr_cotst), independent of the
-- PERFIL_MENSAL class split — so it is the reliable "how many investors" series
-- even when the perfil breakdown is unmapped.
--
-- ZERO-ROW SAFETY: generate_series month spine drives the result; the function
-- output is LEFT JOINed on, so 36 rows always.
with anchor as (
  select coalesce(
           max(period),
           date_trunc('month', current_date)::date
         ) as p_end
  from fact_fund_monthly
  where entity_type = 'fi'
),
months as (
  select generate_series(
           date_trunc('month', a.p_end) - interval '35 months',
           date_trunc('month', a.p_end),
           interval '1 month'
         )::date as period
  from anchor a
),
qt as (
  select t.period, t.total_cotistas, t.avg_cotistas_per_fund, t.n_funds_with_data
  from anchor a
  cross join lateral quotaholder_trend(
    'fi',
    (date_trunc('month', a.p_end) - interval '35 months')::date,
    a.p_end
  ) t
)
select
  m.period                          as period,
  q.total_cotistas / 1e6            as investors_mm,
  q.avg_cotistas_per_fund           as avg_investors_per_fund,
  q.n_funds_with_data               as n_funds
from months m
left join qt q on q.period = m.period
order by m.period
