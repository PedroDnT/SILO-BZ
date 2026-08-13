-- Maturity wall: outstanding certificate value bucketed by maturity year.
--
-- Deliberately NOT security_maturity_ladder(): that function reads dim_security,
-- which does not carry valor_certificados, and its own body hardcodes
-- `NULL::NUMERIC AS total_value` (see the comment at
-- src/store/analytical/09_analytical_functions.sql). A wall with no value on it
-- is not a wall, so the amounts are taken from cvm_securit_serie directly.
--
-- ZERO-ROW SAFETY: generate_series over the next 15 calendar years drives the
-- rows; the aggregate is LEFT JOINed. Empty years report NULL, never no-row.
--
-- Series with no data_vencimento, or already past maturity, fall outside this
-- forward ladder on purpose — they are counted in securit_overview.sql
-- (n_sem_vencimento / n_past_maturity) so the excluded tail stays visible.
with years as (
  select generate_series(
           extract(year from current_date)::int,
           extract(year from current_date)::int + 14
         ) as maturity_year
),
snapshot as (
  -- Latest reported snapshot per series (same de-duplication as
  -- securit_overview.sql — the source table re-states the whole book monthly).
  select distinct on (
      s.instrument_type, s.cnpj_securit, s.codigo_identificacao, s.numero_serie
    )
    s.instrument_type,
    s.valor_certificados,
    s.data_vencimento,
    s.situacao
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
    extract(year from data_vencimento)::int as maturity_year,
    count(*)                                as n_series,
    sum(valor_certificados) / 1e9           as value_bn,
    sum(valor_certificados) filter (
      where instrument_type like 'cri%' or instrument_type like '%cri'
    ) / 1e9                                 as cri_bn,
    sum(valor_certificados) filter (
      where instrument_type like 'cra%' or instrument_type like '%cra'
    ) / 1e9                                 as cra_bn,
    sum(valor_certificados) filter (
      where instrument_type like 'ots%' or instrument_type like '%ots'
    ) / 1e9                                 as ots_bn
  from snapshot
  where data_vencimento is not null
  group by extract(year from data_vencimento)::int
)
select
  y.maturity_year::text as maturity_year,
  a.n_series,
  a.value_bn,
  a.cri_bn,
  a.cra_bn,
  a.ots_bn
from years y
left join agg a on a.maturity_year = y.maturity_year
order by y.maturity_year
