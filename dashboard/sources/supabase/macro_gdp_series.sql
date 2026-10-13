-- GDP, monthly: BACEN SGS 4380 ("PIB mensal - Valores correntes"), last 60
-- months.
--
-- Units are BACEN's and NOT converted: R$ million, current prices — nominal,
-- so inflation is inside every change, and not seasonally adjusted, so
-- adjacent months are not a growth rate. Nothing is chained or rebased.
--
-- A generate_series month spine LEFT JOINed to the data: a fixed 60 rows
-- whatever bacen_sgs holds, never the zero-row parquet that breaks the build.
-- One observation per month, the LAST reading in it (a monthly series, one
-- reading each; DISTINCT ON keeps the construction of macro_rate_series).
--
-- SPINE END (dashboard/README.md, "Spine rule"): BACEN publishes 4380 a month
-- or two late, so p_end = least(last ended month, last month with a value);
-- least() ignores a NULL max(), so an empty table falls back to the last
-- ended month.
with anchor as (
  select least(
           (date_trunc('month', current_date) - interval '1 month')::date,
           (select max(date_trunc('month', reference_date))::date
              from bacen_sgs
             where series_code = 4380
               and value is not null)
         ) as p_end
),
spine as (
  select generate_series(
           (select p_end from anchor) - interval '59 months',
           (select p_end from anchor),
           interval '1 month'
         )::date as period
),
monthly as (
  select distinct on (date_trunc('month', reference_date))
    date_trunc('month', reference_date)::date as period,
    value
  from bacen_sgs
  where series_code = 4380
    and reference_date >= ((select p_end from anchor) - interval '59 months')::date
    and reference_date <  ((select p_end from anchor) + interval '1 month')::date
  order by date_trunc('month', reference_date), reference_date desc
)
select
  sp.period,
  m.value as gdp_num0
from spine sp
left join monthly m on m.period = sp.period
order by sp.period
