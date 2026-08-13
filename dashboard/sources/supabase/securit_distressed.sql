-- Distressed CRI/CRA/OTS series at the latest reported period.
--
-- Reuses distressed_securities() (src/store/analytical/09_analytical_functions.sql),
-- which already resolves the reference period (COALESCE(as_of_period,
-- MAX(period) FROM fact_security_monthly)) and owns the definition of
-- "distressed" — situacao_mes IN ('Inadimplente', 'Em atraso', 'Cancelado').
-- Both arguments are passed as explicit NULL casts so the untyped literals
-- resolve unambiguously.
--
-- ZERO-ROW SAFETY: `row_guard` is a one-row CTE and the (already LIMITed)
-- function result is LEFT JOINed with ON TRUE. A clean book — genuinely no
-- distressed series — yields one all-NULL row, which the page renders as an
-- empty table rather than killing the build.
with distressed as (
  select
    d.cnpj_securit,
    d.codigo_identificacao,
    d.instrument_type,
    d.period,
    d.situacao_mes,
    d.numero_serie,
    d.data_vencimento,
    d.valor_certificados,
    d.rentabilidade_mes,
    d.recebimentos_mes,
    d.pgt_senior_mes,
    d.pgt_junior_mes
  from distressed_securities(null::text, null::date) d
  order by d.valor_certificados desc nulls last
  limit 30
),
row_guard as (
  select 1 as one
)
select
  case
    when d.instrument_type like 'cra%' or d.instrument_type like '%cra' then 'CRA'
    when d.instrument_type like 'cri%' or d.instrument_type like '%cri' then 'CRI'
    when d.instrument_type like 'ots%' or d.instrument_type like '%ots' then 'OTS'
    else d.instrument_type
  end                              as instrument,
  d.cnpj_securit,
  d.codigo_identificacao,
  d.numero_serie,
  d.period,
  d.situacao_mes,
  d.data_vencimento,
  d.valor_certificados / 1e6       as value_mm,
  d.recebimentos_mes / 1e6         as recebimentos_mm,
  d.pgt_senior_mes / 1e6           as pgt_senior_mm,
  d.pgt_junior_mes / 1e6           as pgt_junior_mm
from row_guard g
left join distressed d on true
order by d.valor_certificados desc nulls last
