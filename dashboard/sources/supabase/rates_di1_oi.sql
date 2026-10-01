-- /rates: DI1 futures open interest and settlement rate by maturity, latest
-- session, from b3_futures_settlement (B3 daily settlement report; DI1 only,
-- from 2018-01-02).
--
-- For DI1 the settlement_rate column is the rate (% a.a., 252 business days)
-- and settlement_price the PU. maturity_month is decoded from the ticker's
-- month letter (F G H J K M N Q U V X Z = Jan..Dec) and two-digit year; the
-- contract expires on that month's first business day.
--
-- ZERO-ROW SAFETY: a one-row driver LEFT JOINs the session, so an empty table
-- yields one NULL row, never a 0-row source.
with last_session as (
  select max(trade_date) as d from b3_futures_settlement
),
latest as (
  select
    f.trade_date,
    f.ticker,
    make_date(
      2000 + substr(f.ticker, 5, 2)::int,
      strpos('FGHJKMNQUVXZ', substr(f.ticker, 4, 1)),
      1
    )                    as maturity_month,
    f.open_interest,
    f.settlement_rate,
    f.contracts
  from b3_futures_settlement f
  join last_session s on f.trade_date = s.d
  where f.ticker ~ '^DI1[FGHJKMNQUVXZ][0-9]{2}$'
)
select
  l.trade_date,
  l.ticker,
  l.maturity_month,
  l.open_interest,
  l.settlement_rate as settlement_rate_num2,
  l.contracts
from (select 1) as one
left join latest l on true
order by l.maturity_month
