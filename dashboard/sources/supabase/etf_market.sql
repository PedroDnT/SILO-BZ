-- Driven from cvm_etf_registry (not etf_market_latest) so this source always
-- yields rows.
--
-- etf_market_latest is FROM etf_market_snapshot LEFT JOIN cvm_etf_registry, and
-- etf_market_snapshot stays empty until the APIFY_TOKEN-gated etfsbrasil scrape
-- runs — so the view returns 0 rows on a token-less deploy. Evidence writes a
-- zero-byte file for a 0-row source, and the build then dies reading it back:
--
--     Invalid Input Error: File 'supabase_etf_market.parquet' too small to be a
--     Parquet file
--
-- Flipping the join direction keeps the ETF universe (the registry is populated
-- by its own backfill job) as the row driver and leaves every market column
-- NULL until a snapshot exists. Absent data reads as absent — never as a guess —
-- and the section fills in on its own once the scrape lands.
--
-- WHERE EACH COLUMN COMES FROM. Every market column used to come from the
-- scrape alone, so the whole table read NULL on a token-less deploy even though
-- CVM and B3 publish most of it. Now each column falls back to published data
-- and the scrape is only an override:
--
--   manager   registry gestor, else            CVM. THE FUND MANAGER. All 187
--             cvm_fund_registry.gestor_name    ETF CNPJs are in
--                                              cvm_fund_registry, but the
--                                              cad_fi enrichment behind
--                                              cvm_etf_registry.gestor filled
--                                              only 16, and the registry itself
--                                              carried a manager for just 20 —
--                                              because registro_classe.csv
--                                              publishes no Gestor column and
--                                              its upsert was blanking the one
--                                              registro_fundo had just written
--                                              (same CNPJ, same key). Fixed in
--                                              the ingest, not here; replaying
--                                              both real CVM files puts 185 of
--                                              187 ETFs on a named manager.
--                                          `provider` next to it is a curated
--                                          brand label from the seed CSV
--                                          ("XP Asset (Trend)") and the index
--                                          name often carries a DIFFERENT
--                                          firm — Bloomberg indexes an XP
--                                          fund. Index ≠ manager; they are
--                                          separate columns and separately
--                                          titled on the page.
--   nav       etf registry vl_patrim_liq,  CVM's published PL, with its own
--             else fund registry           as-of date. The ETF-registry column
--             (scrape m.nav overrides)     is filled for 16 funds; the fund
--                                          registry now carries
--                                          Patrimonio_Liquido for all 187,
--                                          straight from registro_fundo /
--                                          registro_classe (migration 28).
--                                          nav_date tracks whichever source
--                                          supplied the figure — a PL is a
--                                          measurement on a day, and the day
--                                          travels with it.
--   price     last B3 close (unit price)   b3_cotahist via the typed view:
--                                          preco_fechamento / fator_cotacao,
--                                          both published. This is the EXCHANGE
--                                          price of the quota and is a
--                                          different fact from NAV — an ETF
--                                          trades at a premium or discount to
--                                          its quota value, so both are shown
--                                          and never blended.
--   premium   (price - nav_per_quota)      Left NULL: CVM publishes fund-level
--                                          PL but not quota count here, so a
--                                          per-quota NAV cannot be derived
--                                          without guessing. Shown only when
--                                          the scrape supplies both.
--   taxa_adm  registry taxa_adm            CVM cad_fi administration fee.
--   cotistas  scrape only                  CVM's ETF file does not carry the
--                                          quotaholder count; blank is honest.
with last_px as (
  -- One row per ETF ticker: its most recent cash-market print. Restricted to
  -- tickers in the registry, so this is a bounded lookup, not a tape scan.
  select distinct on (v.codneg)
    v.codneg                                          as ticker,
    v.preco_fechamento / nullif(v.fator_cotacao, 0)   as close_unit,
    v.trade_date                                      as close_date
  from vw_b3_instrument_typed v
  where v.tpmerc = '010'
    and v.codneg in (select ticker from cvm_etf_registry)
    and v.trade_date > (select max(trade_date) from b3_cotahist) - 30
  order by v.codneg, v.trade_date desc, v.codbdi
)
select
  r.ticker,
  coalesce(m.fund_name, r.fund_name)      as fund_name,
  coalesce(r.gestor, fr.gestor_name)      as manager,
  coalesce(r.admin, fr.admin_name)        as administrator,
  r.provider                              as brand,
  r.underlying_index                      as index_name,
  r.segment,
  coalesce(m.price, p.close_unit)                          as price,
  coalesce(m.nav, r.vl_patrim_liq, fr.vl_patrim_liq)       as nav,
  m.cotistas,
  coalesce(m.taxa_adm_pct, r.taxa_adm)    as taxa_adm_num2,
  m.ret_12m_pct                           as ret_12m_num2,
  -- As-of is per source: a price from B3 and a PL from CVM are as of different
  -- days, and pretending otherwise is the kind of quiet lie this repo bans.
  p.close_date                            as price_date,
  -- Paired with the coalesce above, arm for arm, so nav_date always names the
  -- day the shown NAV was measured rather than the freshest date on the row.
  case
    when m.nav is not null            then m.snapshot_date
    when r.vl_patrim_liq is not null  then r.dt_patrim_liq
    else                                   fr.dt_patrim_liq
  end                                     as nav_date
from cvm_etf_registry r
-- Published CVM fund registry: carries gestor_name / admin_name / net assets
-- for every ETF CNPJ (187/187 join), which the cad_fi enrichment does not.
left join cvm_fund_registry fr on fr.cnpj = r.cnpj
left join etf_market_latest m on m.ticker = r.ticker
left join last_px p on p.ticker = r.ticker
-- Sort by the NAV actually displayed, so the biggest fund is top of the table
-- whichever source supplied its figure.
order by coalesce(m.nav, r.vl_patrim_liq, fr.vl_patrim_liq) desc nulls last, r.ticker
