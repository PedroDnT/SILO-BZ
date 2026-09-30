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
years as (
  select generate_series(
           extract(year from current_date)::int,
           extract(year from current_date)::int + 14
         ) as maturity_year
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
  -- Latest reported snapshot per series (same de-duplication as
  -- securit_overview.sql — the source table re-states the whole book monthly).
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
    s.valor_certificados,
    s.data_vencimento,
    s.situacao
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
