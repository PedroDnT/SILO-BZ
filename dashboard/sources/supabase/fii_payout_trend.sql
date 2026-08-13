-- FII sector payout trend, 24 months: income to be distributed
-- (rendimentos_distribuir, from the ativo_passivo subtype) against total assets
-- (vl_ativo) and net assets, plus how many funds actually reported each field.
--
-- The n_funds_* columns are load-bearing: a payout total that drops because
-- fewer funds filed is a coverage artefact, not a market event, and the reader
-- can see which one it is.
--
-- ZERO-ROW SAFETY: 24-month generate_series spine drives the result; the monthly
-- aggregate is LEFT JOINed on, so the source always returns 24 rows.
with anchor as (
  select coalesce(
           max(period),
           date_trunc('month', current_date)::date
         ) as p_end
  from cvm_fii_mensal
),
months as (
  select generate_series(
           date_trunc('month', a.p_end) - interval '23 months',
           date_trunc('month', a.p_end),
           interval '1 month'
         )::date as period
  from anchor a
),
per_fund as (
  select
    m.period                                                                   as period,
    m.cnpj                                                                     as cnpj,
    max(m.vl_ativo) filter (where m.doc_subtype = 'ativo_passivo')             as vl_ativo,
    max(m.rendimentos_distribuir) filter (where m.doc_subtype = 'ativo_passivo')
                                                                               as rendimentos,
    coalesce(
      max(m.vl_patrim_liq) filter (where m.doc_subtype = 'complemento'),
      max(m.vl_patrim_liq) filter (where m.doc_subtype = 'geral')
    )                                                                          as pl,
    coalesce(
      max(m.cotas_emitidas) filter (where m.doc_subtype = 'complemento'),
      max(m.cotas_emitidas) filter (where m.doc_subtype = 'geral')
    )                                                                          as cotas_emitidas
  from cvm_fii_mensal m
  cross join anchor a
  where m.period between (date_trunc('month', a.p_end) - interval '23 months')::date
                     and a.p_end
    and m.cnpj is not null
  group by m.period, m.cnpj
),
agg as (
  select
    period                                                as period,
    sum(rendimentos)                                      as payout,
    sum(vl_ativo)                                         as assets,
    sum(pl)                                               as pl,
    count(*)                                              as n_funds,
    count(*) filter (where rendimentos is not null)       as n_funds_payout,
    count(*) filter (where vl_ativo is not null)          as n_funds_assets,
    count(*) filter (where cotas_emitidas is not null)    as n_funds_cotas
  from per_fund
  group by period
)
select
  m.period                                                as period,
  a.payout / 1e6                                          as payout_mm,
  a.assets / 1e9                                          as assets_bn,
  a.pl / 1e9                                              as pl_bn,
  round(100.0 * a.payout / nullif(a.pl, 0), 2)            as payout_pct_of_pl,
  a.n_funds                                               as n_funds,
  a.n_funds_payout                                        as n_funds_payout,
  a.n_funds_assets                                        as n_funds_assets,
  a.n_funds_cotas                                         as n_funds_cotas
from months m
left join agg a on a.period = m.period
order by m.period
