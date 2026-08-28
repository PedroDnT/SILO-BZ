-- Monthly ETF activity on the standard-lot cash board: median close, traded
-- volume, and how many distinct ETF tickers printed.
--
-- READS THE MATVIEW, NOT THE TAPE (migration 30) — see b3_monthly_volume.sql.
--
-- median_close is precomputed at this exact grain, because a median cannot be
-- re-aggregated: there is no way to combine per-subtype medians into a correct
-- one, so the matview computes percentile_cont at the grain that is served.
--
-- The subtype grain is the ETF one: instrument_subtype = 'etf' under
-- instrument_type = 'fund_quota'. That subtype now survives B3's late-2019
-- board-code change because vw_b3_instrument_typed falls back to
-- mv_b3_isin_subtype — which is what closed the 2019-08 volume gap.
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
agg as (
  select
    period,
    median_close,
    volume / 1e9 as volume_bn,
    n_tickers    as n_etf_tickers
  from mv_b3_monthly_activity
  where grain = 'subtype'
    and tpmerc = '010'
    and instrument_subtype = 'etf'
)
select
  sp.period,
  round(a.median_close::numeric, 2) as median_close,
  a.volume_bn,
  a.n_etf_tickers
from spine sp
left join agg a on a.period = sp.period
order by sp.period
