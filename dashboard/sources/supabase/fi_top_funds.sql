-- The 25 largest FI funds at the latest reported month, via fund_ranking().
--
-- fund_ranking() intentionally returns no fund_name (see
-- src/store/analytical/09_analytical_functions.sql), so dim_fund is joined here
-- for the label; where cvm_fund_registry has not populated a name yet the CNPJ is
-- shown instead of inventing one.
--
-- ZERO-ROW SAFETY: one-row VALUES spine + LEFT JOIN LATERAL, so an FI slice with
-- no data returns a single all-NULL row rather than an empty parquet.
select
  x.rank_pos     as rank_pos,
  x.cnpj         as cnpj,
  x.fund_name    as fund_name,
  x.period       as period,
  x.aum_bn       as aum_bn,
  x.investors    as investors,
  x.net_flow_mm  as net_flow_mm,
  x.quota        as quota
from (values (1)) as g(one)
left join lateral (
  select
    r.rank_pos                          as rank_pos,
    r.cnpj                              as cnpj,
    coalesce(d.fund_name, r.cnpj)       as fund_name,
    r.period                            as period,
    r.metric_value / 1e9                as aum_bn,
    f.nr_cotst                          as investors,
    (f.captc_mes - f.resg_mes) / 1e6    as net_flow_mm,
    f.vl_quota                          as quota
  from fund_ranking('fi', 'aum', null, 25) r
  left join dim_fund d
    on d.cnpj = r.cnpj and d.entity_type = 'fi'
  left join fact_fund_monthly f
    on f.cnpj = r.cnpj and f.entity_type = 'fi' and f.period = r.period
) x on true
order by x.rank_pos nulls last
