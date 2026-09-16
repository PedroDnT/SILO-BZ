-- MAIORES POSIÇÕES SHORT — top 20 by short interest as a share of the float.
--
-- index_free_float ONLY. b3_index_portfolio carries a real free float for the
-- ~150 index names; everything else falls back to shares outstanding, which is
-- a bigger denominator and therefore NOT the same metric. Mixing the two in one
-- ranking would put shares-outstanding names artificially low and read as if
-- they were lightly shorted. The tail is not lost — it is on the table below
-- this one, labelled with its own basis.
--
-- Equities only (SHARES/UNIT): an index ETF's "short %" against its own float
-- is a creation/redemption artefact, not a directional bet.
--
-- ZERO-ROW SAFETY: this source is empty until the first daily run lands, and a
-- zero-row source writes the 0-byte parquet that kills the whole Evidence build
-- (same guard as b3_top_volume.sql / delinquency_trend.sql). That window is not
-- hypothetical here — B3 keeps no archive, so on a fresh deploy these tables are
-- empty until the cron has run once. Hence the union-all sentinel row.
with rows_ as (
  select
    row_number() over (order by s.pct_float desc) as rank,
    s.codneg                                      as ticker,
    s.asset_name,
    s.b3_sector_top                               as sector,
    s.pct_float,
    s.short_brl,
    s.days_to_cover,
    s.taxa_tomador_pct as taxa_tomador_aa
  from fact_short_interest_daily s
  where s.trade_date = (select max(trade_date) from fact_short_interest_daily)
    and s.float_basis = 'index_free_float'
    and s.pct_float is not null
    and s.categoria in ('SHARES', 'UNIT')
  order by s.pct_float desc
  limit 20
)
select * from rows_
union all
select null::bigint, null::text, null::text, null::text, null::numeric, null::numeric, null::numeric, null::numeric
where not exists (select 1 from rows_)
