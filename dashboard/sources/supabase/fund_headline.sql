-- /fund headline tiles: the whole tracked fund universe in one row.
--
-- Driven from dim_fund (the registry of every fund CNPJ across FI / FIDC /
-- FIAGRO / FII / FIP, ETFs carved out) with each fund's most recent monthly
-- observation LEFT JOINed on, so funds that have stopped reporting are still
-- counted — they simply carry NULL money columns.
--
-- ZERO-ROW SAFETY: aggregate without GROUP BY → exactly one row, always.
with latest as (
  select distinct on (f.cnpj, f.entity_type)
    f.cnpj          as cnpj,
    f.entity_type   as entity_type,
    f.period        as period,
    f.vl_patrim_liq as vl_patrim_liq,
    f.nr_cotst      as nr_cotst
  from fact_fund_monthly f
  order by f.cnpj, f.entity_type, f.period desc
),
max_period as (
  select max(period) as p from fact_fund_monthly
)
select
  count(*)                                                as funds_tracked,
  count(distinct d.entity_type)                           as entity_types,
  sum(l.vl_patrim_liq) / 1e9                              as aum_bn,
  sum(l.nr_cotst)                                         as investor_positions,
  max(l.period)                                           as latest_period,
  count(*) filter (
    where l.period = (select p from max_period)
  )                                                       as funds_reporting_latest,
  count(*) filter (where d.fund_name is not null)         as funds_with_name
from dim_fund d
left join latest l
  on l.cnpj = d.cnpj and l.entity_type = d.entity_type
