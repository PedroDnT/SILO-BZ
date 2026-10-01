-- /etf: exchange prints of the Brazilian fixed income ETFs, one row per
-- ticker and session, from b3_trade_consolidated (B3's
-- TradeInformationConsolidatedFile, migration 57). These ETFs trade in B3's
-- segment FORWARD, which the COTAHIST tape omits, so this is their only
-- exchange record. History starts at B3's retention edge (2025-06-10 when
-- checked) once the backfill runs; the daily run adds each new session.
--
-- As published: last_price is the session's last trade; notional_brl is the
-- traded value in R$ as this file reports it, which B3 computes differently
-- from COTAHIST's volume, so it is not comparable with the equity ETF volume
-- chart above. The source has no opening price. Only files marked Final are
-- stored (the ingest's rule).
--
-- Restricted to the tickers cvm_etf_registry labels fixed_income_br; the
-- index family comes from etf_fixed_income on the page.
--
-- ZERO-ROW SAFETY: a one-row driver LEFT JOINs the prints, so an empty table
-- yields one NULL row, never a 0-row source.
with prints as (
  select
    t.trade_date,
    t.ticker,
    t.last_price,
    t.notional_brl / 1e6   as notional_mm,
    t.trade_count,
    t.quantity
  from b3_trade_consolidated t
  where t.ticker in (
    select ticker from cvm_etf_registry where segment = 'fixed_income_br'
  )
)
select p.*
from (select 1) as one
left join prints p on true
order by p.trade_date, p.ticker
