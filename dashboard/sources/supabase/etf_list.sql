select
  ticker,
  fund_name,
  provider,
  segment,
  underlying_index,
  case when is_active then 'Active' else 'Cancelled' end as status
from cvm_etf_registry
order by provider, ticker
