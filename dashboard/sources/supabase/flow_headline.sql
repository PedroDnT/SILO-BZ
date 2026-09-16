-- Headline strip for /flows: latest reference date, its lag, and coverage depth.
--
-- publication_lag_days is shown because B3 publishes this table T+2 and a
-- reader comparing it to today's tape will otherwise think the feed has
-- stalled.
--
-- PARTITION PRUNING on the tape read, the same lesson b3_market_overview
-- documents: `max(trade_date) from b3_cotahist` with no predicate gives the
-- planner nothing to prune on and scans every yearly partition — 4.4 minutes
-- on the build that failed on 2026-08-28. mv_b3_monthly_activity's newest
-- period is the first day of the newest month on the tape, so every session
-- we could want is >= it; using it as a lower bound confines the work to one
-- partition without changing which session is selected. An empty matview
-- falls back to the old full-scan bound — correct, just slow, and only until
-- the first refresh.
with tape_bound as (
  select coalesce(
           (select max(period) from mv_b3_monthly_activity),
           date '1900-01-01'
         ) as from_date
),
latest as (
  select
    max(f.reference_date)                                 as reference_date,
    count(distinct f.reference_date)                      as sessions_held,
    min(f.reference_date)                                 as first_session
  from fact_investor_flow_daily f
  where f.net_brl_mil is not null
)
select
  l.reference_date,
  l.sessions_held,
  l.first_session,
  (select max(c.trade_date) from b3_cotahist c, tape_bound tb
    where c.trade_date >= tb.from_date) - l.reference_date      as publication_lag_days,
  (select sum(f.net_brl_mil / 1e6)
     from fact_investor_flow_daily f
    where f.reference_date = l.reference_date
      and f.investor_type = 'Investidor Estrangeiro')        as estrangeiro_last_day_bn
from latest l
