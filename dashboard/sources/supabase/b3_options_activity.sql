-- Monthly B3 equity-option activity: premium volume, series traded, call/put
-- split. Full history from 2019-01.
--
-- tpmerc '070' is the call board and '080' the put board; COTAHIST "volume" on
-- an option row is PREMIUM traded (price x quantity), not notional exercised —
-- exercises print on their own boards ('012'/'013') and are excluded here.
--
-- No latest_complete_period() clamp: session prints are complete by
-- construction, so the bound is the tape's own max(trade_date).
--
-- ZERO-ROW SAFETY: generate_series month spine drives the rows, aggregates are
-- LEFT JOINed — an empty table yields a spine of NULL months, never the 0-row
-- source whose 0-byte parquet kills the Evidence build.
with bounds as (
  select coalesce(
           (select date_trunc('month', max(trade_date)) from b3_cotahist),
           date '2019-01-01'
         ) as month_end
),
spine as (
  select generate_series(
           date '2019-01-01',
           b.month_end,
           interval '1 month'
         )::date as period
  from bounds b
),
agg as (
  select
    date_trunc('month', trade_date)::date                       as period,
    sum(volume) / 1e9                                           as option_volume_bn,
    sum(volume) filter (where tpmerc = '070') / 1e9             as call_volume_bn,
    sum(volume) filter (where tpmerc = '080') / 1e9             as put_volume_bn,
    count(distinct codneg)                                      as n_series,
    count(distinct codneg) filter (where tpmerc = '070')        as n_call_series,
    count(distinct codneg) filter (where tpmerc = '080')        as n_put_series
  from b3_cotahist
  where tpmerc in ('070', '080')
  group by date_trunc('month', trade_date)
)
select
  sp.period,
  a.option_volume_bn,
  a.call_volume_bn,
  a.put_volume_bn,
  a.n_series,
  a.n_call_series,
  a.n_put_series
from spine sp
left join agg a on a.period = sp.period
order by sp.period
