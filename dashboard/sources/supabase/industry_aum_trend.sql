-- Industry AUM and FI net flow by fund family, monthly, last 36 months.
--
-- Calls the industry_aum_trend() RPC (src/store/analytical/09_analytical_functions.sql)
-- and pivots it onto a generate_series month spine. The spine is the row driver
-- and the function output is LEFT JOINed, so the shape is a fixed 36 rows even
-- on an empty fact_fund_monthly — a 0-row source writes a zero-byte parquet and
-- takes the whole Evidence build down with it.
--
-- FIP reports yearly and lands on 31-Dec in fact_fund_monthly, hence the join on
-- date_trunc('month', ...) rather than on the raw period.
--
-- net_flow only exists for FI: captc_mes/resg_mes are FI-only columns in
-- fact_fund_monthly, so the other families are left out of the flow column
-- rather than shown as zero.
with spine as (
  select generate_series(
           date_trunc('month', current_date) - interval '35 months',
           date_trunc('month', current_date),
           interval '1 month'
         )::date as period
),
t as (
  select *
  from industry_aum_trend(
    null,
    (date_trunc('month', current_date) - interval '35 months')::date,
    current_date
  )
)
select
  sp.period,
  sum(t.total_aum) filter (where t.entity_type = 'fi')     / 1e9 as fi_aum_bn,
  sum(t.total_aum) filter (where t.entity_type = 'fidc')   / 1e9 as fidc_aum_bn,
  sum(t.total_aum) filter (where t.entity_type = 'fii')    / 1e9 as fii_aum_bn,
  sum(t.total_aum) filter (where t.entity_type = 'fiagro') / 1e9 as fiagro_aum_bn,
  sum(t.total_aum) filter (where t.entity_type = 'fip')    / 1e9 as fip_aum_bn,
  sum(t.total_aum)                                         / 1e9 as total_aum_bn,
  sum(t.n_funds)                                                 as n_funds,
  sum(t.net_flow) filter (where t.entity_type = 'fi')      / 1e9 as fi_net_flow_bn
from spine sp
left join t on date_trunc('month', t.period)::date = sp.period
group by sp.period
order by sp.period
