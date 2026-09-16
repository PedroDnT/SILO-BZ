-- Total short balance per session, for the trend line.
--
-- Deliberately short: this series starts the day SILO began capturing, because
-- B3 publishes only a ~21-business-day window and keeps no archive. The page
-- says so next to the chart rather than letting a two-week line imply a
-- two-week story.
--
-- ZERO-ROW SAFETY: this source is empty until the first daily run lands, and a
-- zero-row source writes the 0-byte parquet that kills the whole Evidence build
-- (same guard as b3_top_volume.sql / delinquency_trend.sql). That window is not
-- hypothetical here — B3 keeps no archive, so on a fresh deploy these tables are
-- empty until the cron has run once. Hence the union-all sentinel row.
with rows_ as (
  select
    s.trade_date,
    sum(s.short_brl)                                                  as short_brl,
    sum(s.short_brl) filter (where s.categoria in ('SHARES','UNIT'))  as short_brl_equities,
    count(*) filter (where s.categoria in ('SHARES','UNIT'))          as tickers
  from fact_short_interest_daily s
  group by s.trade_date
  order by s.trade_date
)
select * from rows_
union all
select null::date, null::numeric, null::numeric, null::bigint
where not exists (select 1 from rows_)
