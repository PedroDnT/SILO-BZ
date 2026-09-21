-- Coverage of every SGS series the pipeline is configured to ingest.
--
-- The driver is the literal series list from SGS_SERIES in
-- src/pipeline/bacen_pipeline.py (the ten policy / price / FX series plus the
-- 25 extra codes of INFLATION_SERIES), so the source always returns exactly
-- 35 rows and a series that has never been ingested shows up as an explicit
-- blank line rather than silently disappearing (or emptying the parquet and
-- killing the build). Nothing is filled in for a missing series.
-- tests/test_inflation_contract.py pins the inflation codes here to the
-- pipeline's list.
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
    (4380,  'PIB',          'R$ million, monthly, current prices'),
    -- the IPCA set (INFLATION_SERIES); group codes 1640..1643 are
    -- Comunicação / Saúde / Despesas pessoais / Educação — measured, not IBGE's order
    (13522, 'IPCA_12M',                  '% accumulated 12 months'),
    (7478,  'IPCA15',                    '% change in month'),
    (4466,  'IPCA_CORE_MS',              '% change in month'),
    (11426, 'IPCA_CORE_MA',              '% change in month'),
    (11427, 'IPCA_CORE_EX0',             '% change in month'),
    (16121, 'IPCA_CORE_EX2',             '% change in month'),
    (16122, 'IPCA_CORE_DP',              '% change in month'),
    (4449,  'IPCA_MONITORADOS',          '% change in month'),
    (11428, 'IPCA_LIVRES',               '% change in month'),
    (4447,  'IPCA_COMERCIALIZAVEIS',     '% change in month'),
    (4448,  'IPCA_NAO_COMERCIALIZAVEIS', '% change in month'),
    (10841, 'IPCA_NAO_DURAVEIS',         '% change in month'),
    (10842, 'IPCA_SEMI_DURAVEIS',        '% change in month'),
    (10843, 'IPCA_DURAVEIS',             '% change in month'),
    (10844, 'IPCA_SERVICOS',             '% change in month'),
    (21379, 'IPCA_DIFUSAO',              '% of items rising'),
    (1635,  'IPCA_G_ALIMENTACAO',        '% change in month'),
    (1636,  'IPCA_G_HABITACAO',          '% change in month'),
    (1637,  'IPCA_G_ARTIGOS_RESIDENCIA', '% change in month'),
    (1638,  'IPCA_G_VESTUARIO',          '% change in month'),
    (1639,  'IPCA_G_TRANSPORTES',        '% change in month'),
    (1640,  'IPCA_G_COMUNICACAO',        '% change in month'),
    (1641,  'IPCA_G_SAUDE',              '% change in month'),
    (1642,  'IPCA_G_DESPESAS_PESSOAIS',  '% change in month'),
    (1643,  'IPCA_G_EDUCACAO',           '% change in month')
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
