-- Headline counters for the /securit page.
--
-- ZERO-ROW SAFETY: the outer SELECT is a bare aggregate with no GROUP BY, so
-- Postgres returns exactly one row even when `snapshot` (and cvm_securit_serie
-- behind it) is completely empty. Every measure then comes back 0 or NULL
-- rather than the query returning nothing and Evidence writing a 0-byte
-- parquet.
--
-- Grain: one row per series (instrument_type, codigo_identificacao,
-- numero_serie), taking that series' most recent filing in the live window
-- (the snapshot CTE, #434). cvm_securit_serie is a monthly re-statement of the
-- whole live book, so summing it raw would multiply-count every series by the
-- number of months it has been reported.
with per_period as (
  select period, count(*) as n,
         lag(count(*)) over (order by period) as prev_n
  from fact_security_monthly
  group by period
),
as_of as (
  -- AS-OF MONTH: the rule securit_issuance_trend.sql and
  -- distressed_securities() (09) use, the newest ENDED period holding at least
  -- half the previous period's rows. COALESCE falls back to the last ended
  -- month when nothing qualifies (an empty fact).
  select coalesce(
           (select period
              from per_period
             where period <= (date_trunc('month', current_date) - interval '1 month')::date
               and (prev_n is null or n >= 0.5 * prev_n)
             order by period desc
             limit 1),
           (date_trunc('month', current_date) - interval '1 month')::date
         ) as p_end
),
snapshot as (
  -- LIVE SERIES (#434): a series is live when its latest filing falls in the
  -- as-of month or the month before; filings after the as-of month are
  -- ignored. This used to be every series' latest filing EVER, which kept the
  -- series that stopped filing (matured or redeemed): 10,855 series against
  -- 6,862 live at 2026-07, R$427.8 bn against R$376.8 bn. Two months, not
  -- the as-of month alone, because that month can be only half filed: with
  -- 2026-07 at 55%, "filed in 2026-07" showed 3,763 series and R$201.0 bn,
  -- the window 6,824 and R$372.5 bn.
  -- A series is (instrument_type, codigo_identificacao, numero_serie). The
  -- securitizer is not part of it: certificates move between securitizers
  -- (318 CRI codes, 2019-2026), and keying on cnpj_securit would count a moved
  -- series twice, once with the stale last filing of the old securitizer.
  -- classe, id only make the pick deterministic when one series number
  -- carries several rows in a month (migration 52 keeps them all).
  select distinct on (
      s.instrument_type, s.codigo_identificacao, s.numero_serie
    )
    s.instrument_type,
    s.cnpj_securit,
    s.codigo_identificacao,
    s.situacao,
    s.valor_certificados,
    s.data_vencimento,
    s.data_referencia
  from cvm_securit_serie s
  cross join as_of a
  where s.data_referencia >= (a.p_end - interval '1 month')::date
    and s.data_referencia <  (a.p_end + interval '1 month')::date
  order by
    s.instrument_type,
    s.codigo_identificacao,
    s.numero_serie,
    s.data_referencia desc,
    s.classe,
    s.id
)
select
  count(*)                                                       as n_series,
  count(distinct cnpj_securit)                                   as n_securitizadoras,
  sum(valor_certificados) / 1e9                                  as outstanding_bn,
  -- Situacao as filed: Adimplente, Em atraso, or empty (every CRI row
  -- through 2022-06). 'Inadimplente' never occurs (#430). The share is of
  -- series that filed a status: an empty one is unknown, not current.
  count(*) filter (where situacao = 'Em atraso')                 as n_em_atraso,
  count(*) filter (where situacao is null)                       as n_sem_status,
  round(
    100.0 * count(*) filter (where situacao = 'Em atraso')
    / nullif(count(*) filter (where situacao is not null), 0), 1
  )                                                              as em_atraso_num1,
  -- Series already past their maturity date but not yet marked closed: these
  -- fall outside the forward maturity ladder, so surface them separately
  -- instead of silently dropping them.
  count(*) filter (
    where data_vencimento is not null
      and data_vencimento < current_date
      and coalesce(situacao, '') not in ('Vencido', 'Cancelado', 'Liquidado', 'Encerrado')
  )                                                              as n_past_maturity,
  count(*) filter (where data_vencimento is null)                as n_sem_vencimento,
  (select p_end from as_of)                                      as as_of_period
from snapshot
