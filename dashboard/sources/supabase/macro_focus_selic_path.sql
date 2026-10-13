-- The Focus SELIC path: from ONE survey (the latest the pipeline holds for
-- ExpectativasMercadoAnuais / Selic), the median forecast of the year-end
-- SELIC for the survey's year and the four after it. A forward path, all from
-- the same survey date, so no vintages are mixed.
--
-- Why the Anuais endpoint and not the per-COPOM-meeting one:
-- ExpectativasMercadoSelic carries its meeting in "Reuniao", not in
-- "DataReferencia", so its stored horizon is NULL and only one meeting
-- survives per survey date. A meeting-by-meeting path cannot be drawn from
-- what is stored; the year-end path can.
--
-- Driver: integer offsets 0..4 from the survey's year, LEFT JOINed on the
-- horizon, so the source is a fixed 5 rows (blank where BACEN published no
-- horizon, or when nothing has landed), never a zero-row parquet.
--
-- Units: % a.a., the year-end SELIC target as BACEN publishes the median.
-- horizon_year is text (a year): it carries no numeric fmt on the page.
with survey as (
  select max(reference_date) as survey_date
  from bacen_expectativas
  where endpoint_name = 'ExpectativasMercadoAnuais'
    and indicador = 'Selic'
),
path as (
  select
    o.n,
    s.survey_date,
    (extract(year from s.survey_date)::int + o.n)::text as horizon_year
  from generate_series(0, 4) as o(n)
  cross join survey s
)
select
  p.horizon_year,
  p.survey_date,
  b.median   as median_num2,
  b.mean_val as mean_num2,
  b.std_dev  as std_dev_num2
from path p
left join bacen_expectativas b
       on b.endpoint_name = 'ExpectativasMercadoAnuais'
      and b.indicador = 'Selic'
      and b.reference_date = p.survey_date
      and b.horizon = p.horizon_year
order by p.n
