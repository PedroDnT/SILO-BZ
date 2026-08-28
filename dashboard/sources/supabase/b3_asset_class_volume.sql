-- Monthly standard-lot cash volume split by instrument type, with the ETF and
-- FII share of the fund-quota bucket called out.
--
-- READS THE MATVIEW, NOT THE TAPE (migration 30) — see b3_monthly_volume.sql.
-- This source alone took 8 minutes on the production build that failed on
-- 2026-08-28.
--
-- Two grains, deliberately, because COUNT(DISTINCT ...) does not re-aggregate:
--   grain='type'    — volume and n_tickers per instrument_type, counted at that
--                     grain rather than summed from subtypes (summing would
--                     double-count any ticker that appeared under more than one
--                     subtype across the month)
--   grain='subtype' — the etf/fii volume split inside fund_quota
--
-- The literal type list drives the row count with the aggregate LEFT JOINed, so
-- a type absent from a month reads NULL rather than dropping out of the chart.
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
types (instrument_type) as (
  values ('equity'), ('bdr'), ('unit'), ('fund_quota'), ('cash_security')
),
by_type as (
  select period, instrument_type, volume / 1e9 as volume_bn, n_tickers
  from mv_b3_monthly_activity
  where grain = 'type'
    and tpmerc = '010'
),
by_subtype as (
  select
    period,
    instrument_type,
    sum(volume) filter (where instrument_subtype = 'etf') / 1e9 as etf_volume_bn,
    sum(volume) filter (where instrument_subtype = 'fii') / 1e9 as fii_volume_bn
  from mv_b3_monthly_activity
  where grain = 'subtype'
    and tpmerc = '010'
  group by period, instrument_type
)
select
  sp.period,
  t.instrument_type,
  a.volume_bn,
  a.n_tickers,
  s.etf_volume_bn,
  s.fii_volume_bn
from spine sp
cross join types t
left join by_type a
  on a.period = sp.period and a.instrument_type = t.instrument_type
left join by_subtype s
  on s.period = sp.period and s.instrument_type = t.instrument_type
order by sp.period, t.instrument_type
