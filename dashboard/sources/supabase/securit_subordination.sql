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
    s.classe,
    s.nivel_subordinacao,
    s.situacao,
    s.valor_certificados,
    s.indice_subordinacao_minimo
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
    count(*) filter (where situacao = 'Em atraso')                   as n_em_atraso,
    count(*) filter (where situacao is null)                         as n_sem_status
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
  -- Of series that filed a status (securit_overview.sql says why).
  round(100.0 * a.n_em_atraso / nullif(a.n_series - a.n_sem_status, 0), 1) as em_atraso_num1
from row_guard g
left join agg a on true
order by a.value_bn desc nulls last
limit 20
