select
  count(*)                              as total_etfs,
  count(*) filter (where is_active)     as active_etfs,
  count(distinct provider)              as providers,
  count(distinct underlying_index)      as indices_tracked
from cvm_etf_registry
