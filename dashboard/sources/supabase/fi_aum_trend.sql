-- FI industry AUM + net flow, 36 months, from industry_aum_trend().
--
-- ZERO-ROW SAFETY: the row driver is a generate_series month spine anchored on
-- the latest FI period (or today when the fact table is empty), so this source
-- always emits 36 rows. Months the industry has not reported yet come back NULL
-- rather than shrinking the result to nothing.
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
trend as (
  select t.period, t.total_aum, t.n_funds, t.net_flow
  from anchor a
  cross join lateral industry_aum_trend(
    array['fi'],
    (date_trunc('month', a.p_end) - interval '35 months')::date,
    a.p_end
  ) t
)
select
  m.period                    as period,
  t.total_aum / 1e9           as aum_bn,
  t.n_funds                   as n_funds,
  t.net_flow / 1e9            as net_flow_bn
from months m
left join trend t on t.period = m.period
order by m.period
