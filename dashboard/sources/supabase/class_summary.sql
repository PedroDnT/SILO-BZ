select
  asset_class,
  count(*)                                          as funds_ranked,
  round(avg(total_performance) * 100, 2)            as avg_perf_pct,
  round(max(total_performance) * 100, 2)            as best_pct,
  min(return_basis)                                 as return_basis
from fund_performance_ranking(null, null, null, null, null, 2)
group by asset_class
order by funds_ranked desc
