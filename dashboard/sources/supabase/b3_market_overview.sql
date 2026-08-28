-- Headline strip for /markets: the latest B3 session in one row.
--
-- B3 COTAHIST is session data — every row is a print that actually happened on
-- the exchange, so there is no "partially filed month" and no
-- latest_complete_period() clamp here (that clamp exists for CVM filings, which
-- trickle in). The tape's own max(trade_date) is the honest bound.
--
-- ZERO-ROW SAFETY: every value is an aggregate (or a scalar subselect of one),
-- and aggregates over an empty table still return exactly one row — NULLs, not
-- zero rows — so this source can never write the 0-byte parquet that kills the
-- whole Evidence build.
with latest as (
  select max(trade_date) as trade_date from b3_cotahist
)
select
  l.trade_date                                              as latest_session,
  (select count(distinct c.codneg)
     from b3_cotahist c, latest l2
    where c.trade_date = l2.trade_date
      and c.tpmerc = '010')                                 as cash_instruments,
  (select sum(c.volume) / 1e9
     from b3_cotahist c, latest l2
    where c.trade_date = l2.trade_date)                     as session_volume_bn,
  (select count(distinct c.codneg)
     from b3_cotahist c, latest l2
    where c.trade_date = l2.trade_date
      and c.tpmerc in ('070', '080'))                       as option_series
from latest l
