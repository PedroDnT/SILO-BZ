-- Shape of the tracked universe: fund count and net assets per conformed asset
-- class (dim_fund_category), using each fund's most recent monthly observation.
--
-- asset_class is the conformed bucket that lets the five CVM families sit on one
-- axis; FI funds fall into the coarse 'Other FI' class until cvm_fund_registry
-- populates tp_fundo, so an oversized 'Other FI' bar means the registry is thin,
-- not that the funds are unclassifiable.
--
-- ZERO-ROW SAFETY: a GROUP BY over an empty dim_fund would return no rows at all
-- (dim_fund is smoke-checked at apply time, but a stale/never-refreshed matview
-- would still slip through), so the whole aggregate hangs off a one-row VALUES
-- spine + LEFT JOIN LATERAL. Verified against an emptied warehouse: 1 row, not 0.
select
  x.asset_class         as asset_class,
  x.entity_type         as entity_type,
  x.n_funds             as n_funds,
  x.n_funds_reporting   as n_funds_reporting,
  x.aum_bn              as aum_bn,
  x.investor_positions  as investor_positions,
  x.latest_period       as latest_period
from (values (1)) as g(one)
left join lateral (
  with latest as (
    select distinct on (f.cnpj, f.entity_type)
      f.cnpj          as cnpj,
      f.entity_type   as entity_type,
      f.period        as period,
      f.vl_patrim_liq as vl_patrim_liq,
      f.nr_cotst      as nr_cotst
    from fact_fund_monthly f
    order by f.cnpj, f.entity_type, f.period desc
  )
  select
    coalesce(c.asset_class, 'Unclassified')     as asset_class,
    d.entity_type                               as entity_type,
    count(*)                                    as n_funds,
    count(l.cnpj)                               as n_funds_reporting,
    sum(l.vl_patrim_liq) / 1e9                  as aum_bn,
    sum(l.nr_cotst)                             as investor_positions,
    max(l.period)                               as latest_period
  from dim_fund d
  left join dim_fund_category c
    on c.cnpj = d.cnpj and c.entity_type = d.entity_type
  left join latest l
    on l.cnpj = d.cnpj and l.entity_type = d.entity_type
  group by coalesce(c.asset_class, 'Unclassified'), d.entity_type
) x on true
order by x.aum_bn desc nulls last, x.n_funds desc nulls last
