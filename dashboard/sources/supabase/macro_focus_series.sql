-- Focus (Expectativas de Mercado) consensus and dispersion, monthly, 24 months.
--
-- Long format: one row per (month, indicador). The month spine is CROSS JOINed
-- to the literal indicator list ingested for the Anuais endpoint
-- (EXPECTATIVAS_INDICATORS in src/pipeline/bacen_pipeline.py), so the source is
-- a fixed 24 x 4 = 96 rows and can never collapse to zero and break the build.
--
-- Month value = the LAST survey date in the month (DISTINCT ON), so the number
-- shown is one real Focus publication, not a blend of several.
--
-- CAVEAT, load-bearing: bacen_expectativas is keyed UNIQUE on
-- (endpoint_name, indicador, reference_date). The Focus API returns one row per
-- forecast HORIZON per survey date, so only one horizon survives per survey
-- date — the one written last. Treat the level as indicative of the consensus
-- and read survey_date as the vintage; the horizon that actually landed is kept
-- in raw->>'DataReferencia' and is surfaced on the "latest" table.
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
    median,
    mean_val,
    std_dev
  from bacen_expectativas
  where endpoint_name = 'ExpectativasMercadoAnuais'
    and reference_date >= (date_trunc('month', current_date) - interval '23 months')::date
  order by indicador, date_trunc('month', reference_date), reference_date desc
)
select
  sp.period,
  i.indicador,
  m.reference_date as survey_date,
  m.median         as median_val,
  m.mean_val,
  m.std_dev
from spine sp
cross join indicators i
left join monthly m
  on m.period = sp.period
 and m.indicador = i.indicador
order by sp.period, i.indicador
