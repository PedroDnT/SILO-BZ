-- Top 15 tickers by standard-lot volume over the last 90 calendar days of tape.
--
-- "Last 90 days" is relative to max(trade_date) of the table, NOT current_date:
-- if the ingest stalls, this table shows the last window the tape actually
-- covers instead of silently shrinking to nothing. Prices are UNADJUSTED
-- COTAHIST closes — no split/dividend adjustment, and papers with
-- fator_cotacao != 1 quote per lot, not per share.
--
-- instrument_type / share_class come from vw_b3_instrument_typed at the
-- ticker's latest session (CODBDI/ESPECI can drift across the window).
--
-- ZERO-ROW SAFETY: a ranked top-N over an empty table is zero rows, and a
-- zero-row source writes the 0-byte parquet that kills the whole Evidence
-- build — hence the union-all fallback (same guard as delinquency_trend.sql).
with agg as (
  select
    codneg,
    sum(volume) / 1e9                                          as volume_bn,
    round(sum(negocios)::numeric
          / nullif(count(distinct trade_date), 0), 0)          as avg_daily_trades,
    (array_agg(preco_fechamento order by trade_date desc))[1]  as last_close,
    (array_agg(instrument_type  order by trade_date desc))[1]  as instrument_type,
    (array_agg(share_class      order by trade_date desc))[1]  as share_class
  from vw_b3_instrument_typed
  where tpmerc = '010'
    and trade_date > (select max(trade_date) from b3_cotahist) - interval '90 days'
  group by codneg
  order by sum(volume) desc nulls last
  limit 15
)
select codneg, instrument_type, share_class, volume_bn, avg_daily_trades, last_close
from agg
union all
select null::text, null::text, null::text, null::numeric, null::numeric, null::numeric
where not exists (select 1 from agg)
order by volume_bn desc nulls last
