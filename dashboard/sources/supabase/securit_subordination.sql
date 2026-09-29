-- Subordination structure of the live securitisation book, by tranche class.
--
-- COLUMN AVAILABILITY (verified against the parser, not assumed):
--   * `classe` and `indice_subordinacao_minimo` ARE populated —
--     src/parsers/field_maps/securit_serie.py maps Classe and
--     Indice_Subordinacao_Minimo.
--   * `nivel_subordinacao` is NOT. src/store/schema.sql adds the column
--     (ALTER TABLE cvm_securit_serie … ADD COLUMN IF NOT EXISTS
--     nivel_subordinacao TEXT) but no FIELD_MAP entry writes it, so it is
--     always NULL today. It is still counted below as `n_with_nivel` so the
--     gap is visible on the page instead of being quietly hidden.
--
-- indice_subordinacao_minimo is reported as-is. CVM does not document whether
-- it is a fraction or a percentage and the two conventions appear across
-- filings, so it is NOT rescaled into a "%" here — that would be a guess.
--
-- ZERO-ROW SAFETY: one-row `row_guard` LEFT JOINed to the grouped aggregate.
with snapshot as (
  -- A series is (instrument_type, codigo_identificacao, numero_serie). The
  -- securitizer is not part of it: certificates move between securitizers
  -- (318 CRI codes, 2019-2026), and keying on cnpj_securit would count a moved
  -- series twice, once with the stale last filing of the old securitizer.
  -- classe, id only make the pick deterministic when one series number
  -- carries several rows in a month (migration 52 keeps them all).
  select distinct on (
      s.instrument_type, s.codigo_identificacao, s.numero_serie
    )
    s.classe,
    s.nivel_subordinacao,
    s.situacao,
    s.valor_certificados,
    s.indice_subordinacao_minimo
  from cvm_securit_serie s
  where s.data_referencia is not null
  order by
    s.instrument_type,
    s.codigo_identificacao,
    s.numero_serie,
    s.data_referencia desc,
    s.classe,
    s.id
),
agg as (
  select
    coalesce(nullif(trim(classe), ''), 'Classe não informada')      as classe,
    count(*)                                                        as n_series,
    sum(valor_certificados) / 1e9                                   as value_bn,
    count(*) filter (where indice_subordinacao_minimo is not null)  as n_with_idx,
    round(avg(indice_subordinacao_minimo), 4)                       as idx_subord_min_avg,
    round(
      (percentile_cont(0.5) within group (order by indice_subordinacao_minimo))::numeric,
      4
    )                                                               as idx_subord_min_median,
    count(*) filter (where nivel_subordinacao is not null)          as n_with_nivel,
    count(*) filter (where situacao = 'Inadimplente')                as n_inadimplente
  from snapshot
  group by coalesce(nullif(trim(classe), ''), 'Classe não informada')
),
row_guard as (
  select 1 as one
)
select
  a.classe,
  a.n_series,
  a.value_bn,
  a.n_with_idx,
  a.idx_subord_min_avg,
  a.idx_subord_min_median,
  a.n_with_nivel,
  round(100.0 * a.n_inadimplente / nullif(a.n_series, 0), 1) as inadimplente_num1
from row_guard g
left join agg a on true
order by a.value_bn desc nulls last
limit 20
