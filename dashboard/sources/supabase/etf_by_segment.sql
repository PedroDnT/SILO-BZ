select
  coalesce(segment, '(unknown)') as segment,
  count(*)                       as n_etfs
from cvm_etf_registry
group by segment
order by n_etfs desc
