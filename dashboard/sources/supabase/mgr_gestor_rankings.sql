-- Top 20 gestores (portfolio managers) by AUM at the latest monthly period.
--
-- Same shape and the same structural guarantee as mgr_admin_rankings:
-- gestor_rankings() (src/store/analytical/14_ranking_functions.sql) drops every
-- fund whose cvm_fund_registry.gestor_name is NULL and can therefore return no
-- rows at all, which would write a zero-byte parquet and break the build. A
-- generate_series(1, 20) slot spine drives the rows and the ranking is LEFT
-- JOINed on, so the result is always 20 rows, with empty slots left honestly
-- blank rather than filled with a made-up name.
--
-- PERIOD CHOICE, load-bearing: a NULL period resolves to max(period) over
-- fact_fund_monthly, where FIP sits at 31-DEC of its reporting year — a future
-- date for most of the year, and a period in which no fund carries a registry
-- gestor name. The latest MONTHLY period (every family except FIP) is passed
-- explicitly instead.
--
-- Administrator and gestor are different roles: the administrator is the fund's
-- legal/registry manager, the gestor makes the investment decisions. One house
-- can appear in both tables, and often does.
with ranked as (
  select
    row_number() over (order by rank_pos, gestor_name) as slot,
    gestor_name,
    period,
    n_funds,
    total_aum,
    net_flow,
    avg_yield,
    total_inadimpl
  from gestor_rankings(
    (select max(period) from fact_fund_monthly where entity_type <> 'fip'),
    'aum',
    20
  )
),
slots as (
  select generate_series(1, 20) as slot
)
select
  s.slot,
  r.gestor_name,
  r.period,
  r.n_funds,
  r.total_aum      / 1e9 as aum_bn,
  r.net_flow       / 1e9 as net_flow_bn,
  r.total_inadimpl / 1e6 as inadimpl_mm,
  round(r.avg_yield, 2)  as avg_yield_pct
from slots s
left join ranked r on r.slot = s.slot
order by s.slot
