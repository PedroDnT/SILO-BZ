-- /rates: the global backdrop, WEEKLY (last observation of each series in the
-- week), from mkt_series, each straight from its primary publisher:
--   UST_PAR_2Y, UST_PAR_10Y  U.S. Treasury par yields, % a.a. (us_treasury)
--   BRENT_SPOT_FOB           Brent spot, USD per barrel (eia; EIA publishes
--                            weekly, so the latest weeks can lag the others)
--   OFR_FSI                  OFR Financial Stress Index (ofr; positive = stress
--                            above average; published about two business days
--                            late)
-- The series run on different calendars, so each is taken at its own last
-- observation in the week. VIX is held but not shown: Cboe requires a signed
-- licence to publish it, and the OFR index is the stress gauge used instead.
--
-- ZERO-ROW SAFETY: a generate_series week spine from 2007-01-01 drives the row
-- count; the series are LEFT JOINed on, so an empty table yields NULLs.
with spine as (
  select generate_series(
           date '2007-01-01',
           date_trunc('week', current_date)::date,
           interval '1 week'
         )::date as week
),
weekly as (
  select distinct on (series_id, date_trunc('week', observation_date))
    series_id,
    date_trunc('week', observation_date)::date as week,
    value
  from mkt_series
  where series_id in ('UST_PAR_2Y', 'UST_PAR_10Y', 'BRENT_SPOT_FOB', 'OFR_FSI')
  order by series_id, date_trunc('week', observation_date), observation_date desc
)
select
  s.week,
  max(w.value) filter (where w.series_id = 'UST_PAR_2Y')      as ust_2y_num2,
  max(w.value) filter (where w.series_id = 'UST_PAR_10Y')     as ust_10y_num2,
  max(w.value) filter (where w.series_id = 'BRENT_SPOT_FOB')  as brent_usd_num2,
  max(w.value) filter (where w.series_id = 'OFR_FSI')         as ofr_fsi_num2
from spine s
left join weekly w on w.week = s.week
group by s.week
order by s.week
