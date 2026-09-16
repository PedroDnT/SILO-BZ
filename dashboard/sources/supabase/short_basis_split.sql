-- How much of the short book can be expressed as a % of FREE FLOAT at all.
--
-- This exists so the page cannot quietly imply that every row on it is
-- comparable. index_free_float is the metric the market quotes;
-- shares_outstanding is a different, larger denominator; a NULL basis means B3
-- published neither for that ticker.
select
  coalesce(s.float_basis, 'sem denominador') as float_basis,
  count(*)                                   as tickers,
  sum(s.short_brl)                           as short_brl
from fact_short_interest_daily s
where s.trade_date = (select max(trade_date) from fact_short_interest_daily)
group by coalesce(s.float_basis, 'sem denominador')
order by sum(s.short_brl) desc
