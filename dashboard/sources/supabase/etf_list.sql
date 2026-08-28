-- Registry listing. `manager` is CVM's published gestor (cad_fi); `brand` is the
-- curated seed label ("XP Asset (Trend)") and `index_name` is the index the fund
-- tracks. These are three DIFFERENT things and the page titles them separately:
-- an index published by Bloomberg does not make Bloomberg the manager.
select
  ticker,
  fund_name,
  gestor            as manager,
  provider          as brand,
  segment,
  underlying_index  as index_name,
  case when is_active then 'Active' else 'Cancelled' end as status
from cvm_etf_registry
order by coalesce(gestor, provider), ticker
