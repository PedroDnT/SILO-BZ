select
  coalesce(provider, '(unknown)')   as provider,
  count(*)                          as n_etfs,
  count(*) filter (where is_active) as active
from cvm_etf_registry
group by provider
order by n_etfs desc
