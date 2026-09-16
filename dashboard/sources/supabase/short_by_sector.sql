-- POSIÇÕES SHORT POR SETOR — the sector bar.
--
-- short_brl_equities, not short_brl: the unclassified bucket is almost entirely
-- ETFs and BDRs, which B3 assigns no sector, and including them would make
-- "Não classificado" the largest bar on a chart about single-name risk.
-- Sectors are B3's own top-level labels with its spelling variants merged (see
-- dim_ticker_float) — no ticker is moved between sectors.
select
  v.b3_sector as sector,
  v.tickers,
  v.short_brl_equities as short_brl,
  v.short_qty
from vw_short_by_sector v
where v.trade_date = (select max(trade_date) from vw_short_by_sector)
  and v.b3_sector <> 'Não classificado'
  and v.short_brl_equities > 0
order by v.short_brl_equities desc
