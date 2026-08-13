-- Searchable explorer: the 400 largest funds across every entity type.
--
-- Evidence builds to a static site, so there is no server to answer a per-fund
-- query at view time. The explorer is therefore a bounded, pre-materialised slice
-- (top 400 by latest net assets) that the DataTable searches client-side, rather
-- than a parameterised drill-down.
--
-- search_funds('', null, 400) is the existing discovery RPC: an empty query
-- matches every fund and the function already orders by latest net assets. Names
-- come from cvm_fund_registry via dim_fund; when the registry has not populated
-- one, the CNPJ is shown instead of inventing a label.
--
-- ZERO-ROW SAFETY: one-row VALUES spine + LEFT JOIN LATERAL, so an empty fund
-- universe returns a single all-NULL row rather than an empty parquet.
select
  x.fund_name     as fund_name,
  x.cnpj          as cnpj,
  x.entity_type   as entity_type,
  x.asset_class   as asset_class,
  x.aum_mm        as aum_mm,
  x.investors     as investors,
  x.latest_period as latest_period,
  x.first_period  as first_period,
  x.last_period   as last_period,
  x.months_report as months_report
from (values (1)) as g(one)
left join lateral (
  select
    coalesce(s.fund_name, s.cnpj)   as fund_name,
    s.cnpj                          as cnpj,
    s.entity_type                   as entity_type,
    c.asset_class                   as asset_class,
    s.latest_aum / 1e6              as aum_mm,
    l.nr_cotst                      as investors,
    l.period                        as latest_period,
    s.first_period                  as first_period,
    s.last_period                   as last_period,
    d.n_reports                     as months_report
  from search_funds('', null, 400) s
  left join dim_fund d
    on d.cnpj = s.cnpj and d.entity_type = s.entity_type
  left join dim_fund_category c
    on c.cnpj = s.cnpj and c.entity_type = s.entity_type
  left join lateral (
    select f.period as period, f.nr_cotst as nr_cotst
    from fact_fund_monthly f
    where f.cnpj = s.cnpj and f.entity_type = s.entity_type
    order by f.period desc
    limit 1
  ) l on true
) x on true
order by x.aum_mm desc nulls last, x.fund_name
