-- /rates: the latest US Treasury par yield curve, from mkt_series (source
-- us_treasury, U.S. Department of the Treasury daily par yield curve, % a.a.
-- as published). Context for the Brazilian curves, not a comparison of like
-- with like: different currency, compounding and day count.
--
-- ZERO-ROW SAFETY: a literal tenor driver fixes the row count; the curve is
-- LEFT JOINed on, so an empty table yields NULLs, never a 0-row source.
with tenors (series_id, tenor_years) as (
  values ('UST_PAR_1M', 1 / 12.0), ('UST_PAR_2M', 2 / 12.0),
         ('UST_PAR_3M', 0.25), ('UST_PAR_4M', 4 / 12.0),
         ('UST_PAR_6M', 0.5), ('UST_PAR_1Y', 1), ('UST_PAR_2Y', 2),
         ('UST_PAR_3Y', 3), ('UST_PAR_5Y', 5), ('UST_PAR_7Y', 7),
         ('UST_PAR_10Y', 10), ('UST_PAR_20Y', 20), ('UST_PAR_30Y', 30)
),
last_day as (
  select max(observation_date) as d
  from mkt_series
  where source = 'us_treasury'
)
select
  t.series_id,
  round(t.tenor_years, 2)        as tenor_years,
  (select d from last_day)       as observation_date,
  m.value                        as ust_par_num2
from tenors t
left join mkt_series m
  on m.source = 'us_treasury'
 and m.series_id = t.series_id
 and m.observation_date = (select d from last_day)
order by t.tenor_years
