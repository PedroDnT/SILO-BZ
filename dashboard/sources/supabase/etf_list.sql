-- Registry listing. `manager` is CVM's published gestor (cad_fi); `brand` is the
-- curated seed label ("XP Asset (Trend)") and `index_name` is the index the fund
-- tracks. These are three DIFFERENT things and the page titles them separately:
-- an index published by Bloomberg does not make Bloomberg the manager.
-- manager falls back to cvm_fund_registry.gestor_name: all 197 ETF CNPJs are
-- in that published registry, while the cad_fi enrichment on
-- cvm_etf_registry.gestor reached only 16 of them (measured 2026-08-28).
select
  e.ticker,
  e.fund_name,
  coalesce(e.gestor, fr.gestor_name)  as manager,
  e.provider                          as brand,
  e.segment,
  e.underlying_index                  as index_name,
  case when e.is_active then 'Active' else 'Cancelled' end as status
from cvm_etf_registry e
left join cvm_fund_registry fr on fr.cnpj = e.cnpj
order by coalesce(e.gestor, fr.gestor_name, e.provider), e.ticker
