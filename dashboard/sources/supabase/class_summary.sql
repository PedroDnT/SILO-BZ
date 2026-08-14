select
  asset_class,
  count(*)                                          as funds_ranked,
  round(avg(total_performance) * 100, 2)            as avg_perf_num2,
  round(max(total_performance) * 100, 2)            as best_num2,
  min(return_basis)                                 as return_basis
from fund_performance_ranking(null, null, null, null, null, 2)
group by asset_class
order by funds_ranked desc
