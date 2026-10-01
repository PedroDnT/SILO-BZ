-- /etf: the Brazilian fixed income ETFs (cvm_etf_registry.segment =
-- 'fixed_income_br'), one row each, with the index family they belong to and
-- the published figures that exist for them.
--
-- FAMILY is mapped here from the registry's free-text index name, nothing else:
--   IMA-B / IMA-B 5 / IMA-B 5+   the ANBIMA IPCA-linked Treasury indices by name
--   NTN-B maturity               a single NTN-B or Tesouro IPCA+ maturity year
--   Prefixado (IRF-M, pré)       IRF-M, pré-fixado and DI-futures rate indices
--   Selic / LFT                  Tesouro Selic and LFT indices
--   Credit (debentures, LF)      debentures, letras financeiras, iBoxx credit
--   Other IPCA-linked / Other    the rest, named as published
-- The page shows the index name next to the family, so the mapping is checkable.
--
-- NUMBERS, each from its own source and with its own date:
--   nav        CVM net assets: cvm_etf_registry.vl_patrim_liq, else
--              cvm_fund_registry.vl_patrim_liq (same rule as etf_market.sql),
--              dated by its own dt_patrim_liq.
--   price      the etfsbrasil snapshot (etf_market_latest), dated by its
--              snapshot_date: the previous session's B3 close (matched the
--              COTAHIST close to the cent for BOVA11, IVVB11, SMAL11, GOLD11,
--              HASH11 and DIVO11 on 2026-09-25). Present for all 46.
-- Not shown: the snapshot's cotistas holds a year (2024 to 2026) for every
-- ETF, not a holder count, and its return, volatility and Sharpe fields are
-- empty, so none of them are used.
-- No B3 tape column: none of these tickers appear in b3_cotahist, because
-- B3's COTAHIST file itself omits them (raw COTAHIST_D29092026: 14,966 records,
-- none of the 46, while equity ETFs such as BOVA11 are present; the parser
-- filters no board). Where B3 publishes their prints is not identified.
--
-- ZERO-ROW SAFETY: a one-row driver LEFT JOINs the ETF list, so an empty
-- segment yields one NULL row, never a 0-row source. NAV and the snapshot are
-- LEFT JOINed, so gaps read as blanks.
with fi as (
  select
    r.ticker,
    case
      when r.underlying_index ilike 'IMA-B 5+%'                    then 'IMA-B 5+'
      when r.underlying_index ~* '^IMA-B ?5 P2'                    then 'IMA-B 5'
      when r.underlying_index = 'IMA-B'                            then 'IMA-B'
      when r.underlying_index ~* '^NTN-B 20[0-9]{2}$'
        or r.underlying_index ~* 'Tesouro IPCA 20[0-9]{2}$'        then 'NTN-B maturity'
      when r.underlying_index ~* 'IRF-M|Pré|Taxas Juros'           then 'Prefixado (IRF-M, pré)'
      when r.underlying_index ~* 'Selic & IPCA'                    then 'Other'
      when r.underlying_index ~* 'Selic|LFT'                       then 'Selic / LFT'
      when r.underlying_index ~* 'Debêntures|Letra|iBoxx'          then 'Credit (debentures, LF)'
      when r.underlying_index ~* 'IPCA|DAP'                        then 'Other IPCA-linked'
      else 'Other'
    end                                                   as family,
    r.underlying_index                                    as index_name,
    r.provider                                            as brand,
    coalesce(r.vl_patrim_liq, fr.vl_patrim_liq) / 1e6     as nav_mm,
    case when r.vl_patrim_liq is not null then r.dt_patrim_liq
         else fr.dt_patrim_liq end                        as nav_date,
    m.price                                               as price,
    m.snapshot_date
  from cvm_etf_registry r
  left join cvm_fund_registry fr on fr.cnpj = r.cnpj
  left join etf_market_latest m on m.ticker = r.ticker
  where r.segment = 'fixed_income_br'
)
select fi.*
from (select 1) as one
left join fi on true
order by fi.nav_mm desc nulls last, fi.ticker
