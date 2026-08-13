-- Focus (Expectativas de Mercado) consensus and dispersion, monthly, 24 months.
--
-- Long format: one row per (month, indicador). The month spine is CROSS JOINed
-- to the literal indicator list ingested for the Anuais endpoint
-- (EXPECTATIVAS_INDICATORS in src/pipeline/bacen_pipeline.py), so the source is
-- a fixed 24 x 4 = 96 rows and can never collapse to zero and break the build.
--
-- HORIZON IS PINNED, and it has to be. BACEN publishes, on every survey date,
-- one forecast per horizon: a median IPCA for 2026, another for 2027, another
-- for 2028. Plotting them together draws a line that jumps between a one-year
-- and a five-year forecast and calls it "the consensus". This query therefore
-- takes, for each survey month, the forecast for the CURRENT CALENDAR YEAR
-- (horizon = the four-digit year), which is the series that is comparable over
-- time and the one people mean by "the Focus number".
--
-- horizon only exists as a column from migration 16; before it, the unique key
-- collapsed every horizon into one arbitrary survivor (the backfill log shows
-- "collapsed 10000 -> 313 rows"). Rows ingested before that migration have
-- horizon backfilled from raw->>'DataReferencia'.
--
-- Month value = the LAST survey date in the month (DISTINCT ON), so the number
-- shown is one real Focus publication, not a blend of several.
with spine as (
  select generate_series(
           date_trunc('month', current_date) - interval '23 months',
           date_trunc('month', current_date),
           interval '1 month'
         )::date as period
),
indicators (indicador) as (
  values ('IPCA'), ('IGP-M'), ('PIB Total'), ('Selic')
),
monthly as (
  select distinct on (indicador, date_trunc('month', reference_date))
    indicador,
    date_trunc('month', reference_date)::date as period,
    reference_date,
    horizon,
    median,
    mean_val,
    std_dev
  from bacen_expectativas
  where endpoint_name = 'ExpectativasMercadoAnuais'
    and reference_date >= (date_trunc('month', current_date) - interval '23 months')::date
    -- the forecast for the year the survey was taken in
    and horizon = to_char(reference_date, 'YYYY')
  order by indicador, date_trunc('month', reference_date), reference_date desc
)
select
  sp.period,
  i.indicador,
  m.reference_date as survey_date,
  m.horizon,
  m.median         as median_val,
  m.mean_val,
  m.std_dev
from spine sp
cross join indicators i
left join monthly m
  on m.period = sp.period
 and m.indicador = i.indicador
order by sp.period, i.indicador
