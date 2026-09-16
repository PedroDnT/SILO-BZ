-- Total short balance per session, for the trend line.
--
-- Deliberately short: this series starts the day SILO began capturing, because
-- B3 publishes only a ~21-business-day window and keeps no archive. The page
-- says so next to the chart rather than letting a two-week line imply a
-- two-week story.
select
  s.trade_date,
  sum(s.short_brl)                                                  as short_brl,
  sum(s.short_brl) filter (where s.categoria in ('SHARES','UNIT'))  as short_brl_equities,
  count(*) filter (where s.categoria in ('SHARES','UNIT'))          as tickers
from fact_short_interest_daily s
group by s.trade_date
order by s.trade_date
