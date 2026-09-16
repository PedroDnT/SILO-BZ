-- POSIÇÕES SHORT POR SETOR — the sector bar.
--
-- short_brl_equities, not short_brl: the unclassified bucket is almost entirely
-- ETFs and BDRs, which B3 assigns no sector, and including them would make
-- "Não classificado" the largest bar on a chart about single-name risk.
-- Sectors are B3's own top-level labels with its spelling variants merged (see
-- dim_ticker_float) — no ticker is moved between sectors.
--
-- ZERO-ROW SAFETY: this source is empty until the first daily run lands, and a
-- zero-row source writes the 0-byte parquet that kills the whole Evidence build
-- (same guard as b3_top_volume.sql / delinquency_trend.sql). That window is not
-- hypothetical here — B3 keeps no archive, so on a fresh deploy these tables are
-- empty until the cron has run once. Hence the union-all sentinel row.
with rows_ as (
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
)
select * from rows_
union all
select null::text, null::bigint, null::numeric, null::numeric
where not exists (select 1 from rows_)
