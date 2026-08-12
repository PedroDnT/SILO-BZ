select
  coalesce(underlying_index, '(unknown)') as underlying_index,
  count(*)                                as n_etfs
from cvm_etf_registry
group by underlying_index
order by n_etfs desc
limit 15
