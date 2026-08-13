-- Credit-rating distribution across the live securitisation book.
--
-- classificacao_risco_atual is free text straight from the CVM classe CSV
-- (src/parsers/field_maps/securit_serie.py maps Classificacao_Risco_Atual with
-- no normalisation), so agencies, scales and "sem rating" spellings are mixed.
-- It is grouped verbatim rather than bucketed into a synthetic scale — mapping
-- e.g. "brAAA" and "AAA(bra)" onto one label would be an assumption, not data.
--
-- ZERO-ROW SAFETY: `row_guard` always yields exactly one row, and `agg` is
-- LEFT JOINed onto it with ON TRUE. When the book is empty the source still
-- emits a single all-NULL row instead of nothing.
with snapshot as (
  select distinct on (
      s.instrument_type, s.cnpj_securit, s.codigo_identificacao, s.numero_serie
    )
    s.situacao,
    s.valor_certificados,
    s.classificacao_risco_atual
  from cvm_securit_serie s
  where s.data_referencia is not null
  order by
    s.instrument_type,
    s.cnpj_securit,
    s.codigo_identificacao,
    s.numero_serie,
    s.data_referencia desc
),
agg as (
  select
    coalesce(nullif(trim(classificacao_risco_atual), ''), 'Sem rating informado') as rating,
    count(*)                                                       as n_series,
    sum(valor_certificados) / 1e9                                  as value_bn,
    count(*) filter (where situacao = 'Inadimplente')               as n_inadimplente
  from snapshot
  group by coalesce(nullif(trim(classificacao_risco_atual), ''), 'Sem rating informado')
),
row_guard as (
  select 1 as one
)
select
  a.rating,
  a.n_series,
  a.value_bn,
  a.n_inadimplente,
  round(100.0 * a.n_inadimplente / nullif(a.n_series, 0), 1) as inadimplente_pct
from row_guard g
left join agg a on true
order by a.n_series desc nulls last
limit 20
