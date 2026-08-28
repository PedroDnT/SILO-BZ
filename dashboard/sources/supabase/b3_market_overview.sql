-- Headline strip for /markets: the latest B3 session in one row.
--
-- B3 COTAHIST is session data, so "latest" is the newest trade_date on the
-- tape, not a clamped period.
--
-- PARTITION PRUNING, which is why this reads the matview at all. The query only
-- ever wants one session, but `trade_date = (SELECT max(trade_date) ...)` gives
-- the planner no constant to prune on, so it reached into every yearly
-- partition of b3_cotahist — 4.4 minutes on the production build that failed on
-- 2026-08-28.
--
-- mv_b3_monthly_activity's newest period is the first day of the newest month
-- present on the tape, so every session we could possibly want is >= it. Using
-- it as a lower bound on both the max() and the aggregates leaves the planner a
-- real predicate on the partition key and confines the work to one partition,
-- without changing which session is selected: the true max is inside that
-- bound by construction.
--
-- If the matview is empty (fresh database) the bound falls back to a date
-- before the tape starts, which is the old full-scan behaviour — correct, just
-- slow, and only until the first refresh.
with lower_bound as (
  select coalesce(
           (select max(period) from mv_b3_monthly_activity),
           date '1900-01-01'
         ) as from_date
),
latest as (
  select max(c.trade_date) as trade_date
  from b3_cotahist c, lower_bound lb
  where c.trade_date >= lb.from_date
)
select
  l.trade_date                                              as latest_session,
  (select count(distinct c.codneg)
     from b3_cotahist c, latest l2, lower_bound lb
    where c.trade_date = l2.trade_date
      and c.trade_date >= lb.from_date
      and c.tpmerc = '010')                                 as cash_instruments,
  (select sum(c.volume) / 1e9
     from b3_cotahist c, latest l2, lower_bound lb
    where c.trade_date = l2.trade_date
      and c.trade_date >= lb.from_date)                     as session_volume_bn,
  (select count(distinct c.codneg)
     from b3_cotahist c, latest l2, lower_bound lb
    where c.trade_date = l2.trade_date
      and c.trade_date >= lb.from_date
      and c.tpmerc in ('070', '080'))                       as option_series
from latest l
