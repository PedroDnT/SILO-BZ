-- Most recent Focus row for every (endpoint, indicador) pair the pipeline
-- subscribes to, with the forecast horizon recovered from the raw payload.
--
-- The driver is the literal endpoint/indicator matrix from
-- EXPECTATIVAS_ENDPOINTS + EXPECTATIVAS_INDICATORS
-- (src/pipeline/bacen_pipeline.py). Fixed 8 rows; a pair that never ingested
-- shows blank rather than emptying the parquet and killing the build.
--
-- ExpectativasMercadoSelic is fetched with no indicator filter, so its driver
-- entry is NULL and matches whatever indicator BACEN stamped on the row.
-- horizon comes from raw->>'DataReferencia' — the reference period the forecast
-- is ABOUT, as opposed to survey_date, which is when it was collected.
with tracked (endpoint_name, indicador) as (
  values
    ('ExpectativasMercadoAnuais',          'IPCA'),
    ('ExpectativasMercadoAnuais',          'IGP-M'),
    ('ExpectativasMercadoAnuais',          'PIB Total'),
    ('ExpectativasMercadoAnuais',          'Selic'),
    ('ExpectativasMercadoMensais',         'IPCA'),
    ('ExpectativasMercadoMensais',         'IGP-M'),
    ('ExpectativasMercadoSelic',           null::text),
    ('ExpectativasMercadoInflacao12Meses', 'IPCA')
)
select
  t.endpoint_name,
  coalesce(e.indicador, t.indicador) as indicador,
  e.reference_date                   as survey_date,
  e.raw ->> 'DataReferencia'         as horizon,
  e.median                           as median_val,
  e.mean_val,
  e.std_dev,
  (current_date - e.reference_date)  as days_stale,
  n.n_obs
from tracked t
left join lateral (
  select b.indicador, b.reference_date, b.raw, b.median, b.mean_val, b.std_dev
  from bacen_expectativas b
  where b.endpoint_name = t.endpoint_name
    and (t.indicador is null or b.indicador = t.indicador)
  order by b.reference_date desc
  limit 1
) e on true
left join lateral (
  select count(*) as n_obs
  from bacen_expectativas b
  where b.endpoint_name = t.endpoint_name
    and (t.indicador is null or b.indicador = t.indicador)
) n on true
order by t.endpoint_name, t.indicador nulls last
