-- /fi headline tiles: the FI industry at its most recent reported month.
--
-- ZERO-ROW SAFETY: `latest` is an aggregate without GROUP BY, so it is always
-- exactly one row (COALESCE covers the no-data case), and fact_fund_monthly is
-- LEFT JOINed onto it. If the FI slice were ever empty this still returns one
-- row of NULLs instead of an empty parquet (see etf_market.sql for the same
-- pattern and the build failure it prevents).
with latest as (
  select coalesce(
           max(period),
           date_trunc('month', current_date)::date
         ) as period
  from fact_fund_monthly
  where entity_type = 'fi'
)
select
  l.period                                     as latest_period,
  count(f.cnpj)                                as n_funds,
  sum(f.vl_patrim_liq) / 1e9                   as aum_bn,
  sum(f.nr_cotst)                              as investors,
  sum(f.captc_mes - f.resg_mes) / 1e9          as net_flow_bn,
  sum(f.captc_mes) / 1e9                       as inflow_bn,
  sum(f.resg_mes) / 1e9                        as outflow_bn
from latest l
left join fact_fund_monthly f
  on f.entity_type = 'fi'
 and f.period = l.period
group by l.period
