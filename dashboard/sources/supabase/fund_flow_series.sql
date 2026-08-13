-- Subscription / redemption flow for the six largest FI funds, via
-- fund_flow_trend(). Restricted to FI on purpose: captc_mes / resg_mes exist only
-- on the FI branch of fact_fund_monthly (they are summed from cvm_fi_diario), so
-- asking for flows on a FIDC or FII fund would return an all-NULL line that looks
-- like "no flows" instead of "not published".
--
-- redemption_pressure is resg_mes / net assets — the share of the fund redeemed
-- in the month.
--
-- ZERO-ROW SAFETY: 36-month generate_series spine drives the output; the flow
-- series is LEFT JOINed on.
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
top_funds as (
  select
    s.cnpj                        as cnpj,
    coalesce(s.fund_name, s.cnpj) as fund
  from search_funds('', 'fi', 6) s
),
series as (
  select
    t.fund                    as fund,
    f.cnpj                    as cnpj,
    f.period                  as period,
    f.captc_mes               as captc_mes,
    f.resg_mes                as resg_mes,
    f.net_flow                as net_flow,
    f.cumulative_net_flow     as cumulative_net_flow,
    f.redemption_pressure     as redemption_pressure
  from top_funds t
  cross join anchor a
  cross join lateral fund_flow_trend(
    t.cnpj,
    (date_trunc('month', a.p_end) - interval '35 months')::date,
    a.p_end
  ) f
)
select
  m.period                                        as period,
  x.fund                                          as fund,
  x.captc_mes / 1e6                               as inflow_mm,
  x.resg_mes / 1e6                                as outflow_mm,
  x.net_flow / 1e6                                as net_flow_mm,
  x.cumulative_net_flow / 1e9                     as cum_net_flow_bn,
  round(100.0 * x.redemption_pressure, 2)         as redemption_pressure_pct
from months m
left join series x on x.period = m.period
order by m.period, x.fund
