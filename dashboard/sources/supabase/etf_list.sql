-- Registry listing. `manager` is CVM's published gestor (cad_fi); `brand` is the
-- curated seed label ("XP Asset (Trend)") and `index_name` is the index the fund
-- tracks. These are three DIFFERENT things and the page titles them separately:
-- an index published by Bloomberg does not make Bloomberg the manager.
-- manager falls back to cvm_fund_registry.gestor_name: all 187 ETF CNPJs are in
-- that published registry, while the cad_fi enrichment on
-- cvm_etf_registry.gestor reached only 16 of them. The registry itself held a
-- manager for just 20 until the class-row upsert stopped blanking it — see
-- ingest_fund_registry_cvm175; 185 of 187 carry one on a replay of the real
-- CVM files.
--
-- Net assets follow etf_fixed_income.sql / etf_market.sql: CVM's
-- cvm_etf_registry.vl_patrim_liq, else cvm_fund_registry.vl_patrim_liq, each
-- dated by its own dt_patrim_liq. The size rank is over the ETFs that HAVE a
-- published figure, so a missing one is a blank, never ranked last. This
-- replaces the hand-made matview mv_etf_landscape (dropped in migration 58),
-- which ranked the same columns but was never refreshed.
with r as (
  select
    e.ticker,
    e.fund_name,
    coalesce(e.gestor, fr.gestor_name)  as manager,
    e.provider                          as brand,
    e.segment,
    e.underlying_index                  as index_name,
    case when e.is_active then 'Active' else 'Cancelled' end as status,
    coalesce(e.vl_patrim_liq, fr.vl_patrim_liq) / 1e6 as nav_mm,
    case when e.vl_patrim_liq is not null then e.dt_patrim_liq
         else fr.dt_patrim_liq end      as nav_date
  from cvm_etf_registry e
  left join cvm_fund_registry fr on fr.cnpj = e.cnpj
)
select
  r.*,
  case when r.nav_mm is not null
       then rank() over (order by r.nav_mm desc nulls last)
  end as size_rank
from r
order by r.nav_mm desc nulls last, r.ticker
