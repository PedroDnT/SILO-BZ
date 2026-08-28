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
--
-- SHARE COLUMNS: Evidence AreaChart type=stacked100 rewrites each y column to
-- `{name}_pct` and then looks that name up in the dataset. That path errors
-- with "fi_aum_bn_pct is not a column" when y is a *list* of columns (wide
-- format) rather than one y + series= (long format) — verified on the live
-- /industry page after PR #81. Share-of-total is therefore computed here so
-- a regular stacked area of *_share_num1 is a 100% chart by construction.
--
-- Column names end in `_num1`, not `_pct`. Evidence treats the token after the
-- last underscore as a format tag: `_pct` means "this value is a 0–1 fraction"
-- and multiplies by 100 on every chart. These shares are already percentage
-- points (80 = 80%). `_num1` is the format this dashboard actually uses.
with spine as (
  -- Clamp to complete periods (mv_period_completeness): the trailing month is
  -- served only once its calendar month ended AND enough funds reported, so
  -- charts stop dipping toward zero on partially-filed data.
  select generate_series(
           date_trunc('month', latest_complete_period(null)) - interval '35 months',
           date_trunc('month', latest_complete_period(null)),
           interval '1 month'
         )::date as period
),
t as (
  select *
  from industry_aum_trend(
    null,
    (date_trunc('month', latest_complete_period(null)) - interval '35 months')::date,
    current_date
  )
  -- per-family clamp: each family truncates at its own completeness bound
  where period <= latest_complete_period(entity_type)
),
base as (
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
)
select
  period,
  fi_aum_bn,
  fidc_aum_bn,
  fii_aum_bn,
  fiagro_aum_bn,
  fip_aum_bn,
  total_aum_bn,
  n_funds,
  fi_net_flow_bn,
  round(100.0 * fi_aum_bn     / nullif(total_aum_bn, 0), 2) as fi_share_num1,
  round(100.0 * fidc_aum_bn   / nullif(total_aum_bn, 0), 2) as fidc_share_num1,
  round(100.0 * fii_aum_bn    / nullif(total_aum_bn, 0), 2) as fii_share_num1,
  round(100.0 * fiagro_aum_bn / nullif(total_aum_bn, 0), 2) as fiagro_share_num1,
  round(100.0 * fip_aum_bn    / nullif(total_aum_bn, 0), 2) as fip_share_num1
from base
order by period
