-- How much of the short book can be expressed as a % of FREE FLOAT at all.
--
-- This exists so the page cannot quietly imply that every row on it is
-- comparable. index_free_float is the metric the market quotes;
-- shares_outstanding is a different, larger denominator; a NULL basis means B3
-- published neither for that ticker.
--
-- ZERO-ROW SAFETY: this source is empty until the first daily run lands, and a
-- zero-row source writes the 0-byte parquet that kills the whole Evidence build
-- (same guard as b3_top_volume.sql / delinquency_trend.sql). That window is not
-- hypothetical here — B3 keeps no archive, so on a fresh deploy these tables are
-- empty until the cron has run once. Hence the union-all sentinel row.
with rows_ as (
  select
    coalesce(s.float_basis, 'sem denominador') as float_basis,
    count(*)                                   as tickers,
    sum(s.short_brl)                           as short_brl
  from fact_short_interest_daily s
  where s.trade_date = (select max(trade_date) from fact_short_interest_daily)
  group by coalesce(s.float_basis, 'sem denominador')
  order by sum(s.short_brl) desc
)
select * from rows_
union all
select null::text, null::bigint, null::numeric
where not exists (select 1 from rows_)
