-- Coverage of every SGS series the pipeline is configured to ingest.
--
-- The driver is the literal series list from SGS_SERIES in
-- src/pipeline/bacen_pipeline.py, so the source always returns exactly 10 rows
-- and a series that has never been ingested shows up as an explicit blank line
-- rather than silently disappearing (or emptying the parquet and killing the
-- build). Nothing is filled in for a missing series.
--
-- Units are BACEN's, unconverted — they differ per series, which is exactly why
-- the unit travels with the row.
with configured (series_code, series_name, unit) as (
  values
    (432,   'SELIC_META',   '% a.a. (policy target)'),
    (11,    'SELIC_DIARIA', '% a.d.'),
    (12,    'CDI',          '% a.d.'),
    (433,   'IPCA',         '% change in month'),
    (189,   'IGPM',         '% change in month'),
    (188,   'INPC',         '% change in month'),
    (25,    'POUPANCA',     '% change in month'),
    (1,     'USDBRL',       'BRL per USD'),
    (21619, 'EURBRL',       'BRL per EUR'),
    (4380,  'PIB',          'R$ million, monthly, current prices')
)
select
  c.series_code,
  c.series_name,
  c.unit,
  s.n_obs,
  s.first_obs,
  s.last_obs,
  s.last_value,
  (current_date - s.last_obs) as days_stale
from configured c
left join lateral (
  select
    count(*)              as n_obs,
    min(b.reference_date) as first_obs,
    max(b.reference_date) as last_obs,
    (select v.value
       from bacen_sgs v
      where v.series_code = c.series_code
      order by v.reference_date desc
      limit 1)            as last_value
  from bacen_sgs b
  where b.series_code = c.series_code
) s on true
order by c.series_code
