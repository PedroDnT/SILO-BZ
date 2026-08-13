-- Headline counters for the /securit page.
--
-- ZERO-ROW SAFETY: the outer SELECT is a bare aggregate with no GROUP BY, so
-- Postgres returns exactly one row even when `snapshot` (and cvm_securit_serie
-- behind it) is completely empty. Every measure then comes back 0 or NULL
-- rather than the query returning nothing and Evidence writing a 0-byte
-- parquet.
--
-- Grain: one row per series (instrument_type, cnpj_securit,
-- codigo_identificacao, numero_serie), taking that series' most recent
-- data_referencia snapshot. cvm_securit_serie is a monthly re-statement of the
-- whole live book, so summing it raw would multiply-count every series by the
-- number of months it has been reported.
with snapshot as (
  select distinct on (
      s.instrument_type, s.cnpj_securit, s.codigo_identificacao, s.numero_serie
    )
    s.instrument_type,
    s.cnpj_securit,
    s.codigo_identificacao,
    s.situacao,
    s.valor_certificados,
    s.data_vencimento,
    s.data_referencia
  from cvm_securit_serie s
  where s.data_referencia is not null
  order by
    s.instrument_type,
    s.cnpj_securit,
    s.codigo_identificacao,
    s.numero_serie,
    s.data_referencia desc
)
select
  count(*)                                                       as n_series,
  count(distinct cnpj_securit)                                   as n_securitizadoras,
  sum(valor_certificados) / 1e9                                  as outstanding_bn,
  count(*) filter (where situacao = 'Inadimplente')              as n_inadimplente,
  round(
    100.0 * count(*) filter (where situacao = 'Inadimplente')
    / nullif(count(*), 0), 1
  )                                                              as inadimplente_pct,
  -- Series already past their maturity date but not yet marked closed: these
  -- fall outside the forward maturity ladder, so surface them separately
  -- instead of silently dropping them.
  count(*) filter (
    where data_vencimento is not null
      and data_vencimento < current_date
      and coalesce(situacao, '') not in ('Vencido', 'Cancelado', 'Liquidado', 'Encerrado')
  )                                                              as n_past_maturity,
  count(*) filter (where data_vencimento is null)                as n_sem_vencimento,
  max(data_referencia)                                           as last_reference
from snapshot
