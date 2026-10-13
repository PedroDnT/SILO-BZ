-- The Focus monthly IPCA path: from ONE survey (the latest the pipeline holds
-- for ExpectativaMercadoMensais / IPCA), the median forecast for each month
-- ahead. A forward path, not a history: the x-axis is the month the forecast
-- is ABOUT (horizon), all from the same survey date, so no vintages are mixed.
--
-- NOTE the singular "Expectativa": that is BACEN's resource name and the
-- endpoint_name the pipeline stores (see macro_focus_latest.sql).
--
-- Driver: integer offsets 0..24 from the survey's first published horizon —
-- 25 horizons, the window Focus publishes (the month just ended if IBGE had
-- not printed it by the survey date, else the survey's own month, through 24
-- months on) — LEFT JOINed on the horizon key, so the source is a fixed 25
-- rows: a horizon BACEN did not publish shows blank, and an empty table gives
-- 25 blank rows, never a zero-row parquet. Offsets are integers, so no spine
-- stops in the open month.
--
-- Units: % change in the month, as BACEN publishes the median; not annualised
-- or chained.
with survey as (
  select max(reference_date) as survey_date
  from bacen_expectativas
  where endpoint_name = 'ExpectativaMercadoMensais'
    and indicador = 'IPCA'
),
first_horizon as (
  -- Where this survey's window starts: the month just ended while IBGE has not
  -- printed it, the survey's own month once it has. Read from the survey's
  -- rows; the fallback only applies when nothing is stored (one row always).
  select coalesce(
           min(to_date(b.horizon, 'MM/YYYY')),
           (date_trunc('month', s.survey_date) - interval '1 month')::date
         ) as h0
  from survey s
  left join bacen_expectativas b
         on b.endpoint_name = 'ExpectativaMercadoMensais'
        and b.indicador = 'IPCA'
        and b.reference_date = s.survey_date
        and b.horizon ~ '^\d{2}/\d{4}$'
  group by s.survey_date
),
path as (
  select
    o.n,
    s.survey_date,
    (f.h0 + make_interval(months => o.n))::date as horizon_month
  from generate_series(0, 24) as o(n)
  cross join survey s
  cross join first_horizon f
)
select
  p.horizon_month,
  p.survey_date,
  b.horizon,
  b.median   as median_num2,
  b.mean_val as mean_num2,
  b.std_dev  as std_dev_num2
from path p
left join bacen_expectativas b
       on b.endpoint_name = 'ExpectativaMercadoMensais'
      and b.indicador = 'IPCA'
      and b.reference_date = p.survey_date
      and b.horizon = to_char(p.horizon_month, 'MM/YYYY')
order by p.n
