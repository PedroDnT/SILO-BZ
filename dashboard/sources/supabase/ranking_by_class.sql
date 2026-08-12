select
  asset_class,
  rank_in_class,
  entity_type,
  coalesce(fund_name, cnpj)            as fund,
  return_basis,
  round(total_performance * 100, 2)    as performance_pct,
  n_obs,
  round(aum_end / 1e6, 1)              as aum_mm
from fund_performance_ranking(null, null, null, null, 10, 2)
order by asset_class, rank_in_class
