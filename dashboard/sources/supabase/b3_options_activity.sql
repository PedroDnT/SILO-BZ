-- Monthly B3 equity-option activity: premium volume, series traded, call/put
-- split. tpmerc '070' is calls, '080' is puts.
--
-- READS THE MATVIEW, NOT THE TAPE (migration 30). See b3_monthly_volume.sql for
-- why: five sources aggregating the full 2019-2026 tape on every build is what
-- pushed the production dashboard build past Vercel's 45-minute ceiling on
-- 2026-08-28.
--
-- n_series uses the grain='segment' row rather than adding the call and put
-- rows. A call series and a put series do carry different codneg, so the sum
-- would happen to agree — but that is a fact about B3's ticker naming, not
-- something a count should depend on. The segment grain counts distinct series
-- across both boards directly.
--
-- ZERO-ROW SAFETY: the month spine drives the row count; the aggregate is
-- LEFT JOINed on, so an empty matview yields NULLs, never a 0-row source.
with bounds as (
  select coalesce(
           (select max(period) from mv_b3_monthly_activity),
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
by_board as (
  select
    period,
    sum(volume)                                  / 1e9 as option_volume_bn,
    sum(volume) filter (where tpmerc = '070')    / 1e9 as call_volume_bn,
    sum(volume) filter (where tpmerc = '080')    / 1e9 as put_volume_bn,
    max(n_tickers) filter (where tpmerc = '070')       as n_call_series,
    max(n_tickers) filter (where tpmerc = '080')       as n_put_series
  from mv_b3_monthly_activity
  where grain = 'tpmerc'
    and tpmerc in ('070', '080')
  group by period
),
by_segment as (
  select period, n_tickers as n_series
  from mv_b3_monthly_activity
  where grain = 'segment'
    and market_segment = 'option'
)
select
  sp.period,
  b.option_volume_bn,
  b.call_volume_bn,
  b.put_volume_bn,
  s.n_series,
  b.n_call_series,
  b.n_put_series
from spine sp
left join by_board   b on b.period = sp.period
left join by_segment s on s.period = sp.period
order by sp.period
