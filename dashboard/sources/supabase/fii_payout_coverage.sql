-- FII payout coverage, per fund, at the latest monthly period.
--
-- Pulls the three ingested cvm_fii_mensal subtypes that the dashboard has never
-- shown (only `complemento` was used until now):
--   ativo_passivo → vl_ativo (Total_Investido), rendimentos_distribuir
--   geral         → cotas_emitidas (Quantidade_Cotas_Emitidas)
--   complemento   → vl_patrim_liq, vl_patrimonial_cotas, cotas_emitidas,
--                   pct_dividend_yield_mes
-- Each field is read from the subtype that actually carries it (see
-- src/parsers/field_maps/fii_*.py), then coalesced only across subtypes that
-- publish the SAME field — never across different fields.
--
-- "Coverage" here is the payout against the fund's own book:
--   payout_pct_of_pl  = rendimentos_distribuir / net assets
--   payout_per_cota   = rendimentos_distribuir / quotas outstanding
--   payout_yield_pct  = payout_per_cota / book value per quota
-- A fund distributing well above what its book yields is paying out of capital
-- or of realised gains — the figures are shown, the interpretation is not
-- asserted.
--
-- ZERO-ROW SAFETY: one-row VALUES spine + LEFT JOIN LATERAL.
select
  x.fund_name         as fund_name,
  x.cnpj              as cnpj,
  x.period            as period,
  x.pl_mm             as pl_mm,
  x.vl_ativo_mm       as vl_ativo_mm,
  x.payout_mm         as payout_mm,
  x.payout_pct_of_pl  as payout_pct_of_pl,
  x.cotas_emitidas    as cotas_emitidas,
  x.vpc               as vpc,
  x.payout_per_cota   as payout_per_cota,
  x.payout_yield_pct  as payout_yield_pct,
  x.reported_dy_pct   as reported_dy_pct
from (values (1)) as g(one)
left join lateral (
  with anchor as (
    select coalesce(
             max(period),
             date_trunc('month', current_date)::date
           ) as p_end
    from cvm_fii_mensal
  ),
  base as (
    select
      m.cnpj                                                                   as cnpj,
      max(m.period)                                                            as period,
      max(m.vl_ativo) filter (where m.doc_subtype = 'ativo_passivo')           as vl_ativo,
      max(m.rendimentos_distribuir) filter (where m.doc_subtype = 'ativo_passivo')
                                                                               as rendimentos,
      coalesce(
        max(m.cotas_emitidas) filter (where m.doc_subtype = 'complemento'),
        max(m.cotas_emitidas) filter (where m.doc_subtype = 'geral')
      )                                                                        as cotas_emitidas,
      max(m.vl_patrimonial_cotas) filter (where m.doc_subtype = 'complemento')  as vpc,
      max(m.pct_dividend_yield_mes) filter (where m.doc_subtype = 'complemento') as dy,
      coalesce(
        max(m.vl_patrim_liq) filter (where m.doc_subtype = 'complemento'),
        max(m.vl_patrim_liq) filter (where m.doc_subtype = 'geral')
      )                                                                        as pl
    from cvm_fii_mensal m
    cross join anchor a
    where m.period = a.p_end
      and m.cnpj is not null
    group by m.cnpj
  )
  select
    coalesce(d.fund_name, b.cnpj)                                    as fund_name,
    b.cnpj                                                           as cnpj,
    b.period                                                         as period,
    b.pl / 1e6                                                       as pl_mm,
    b.vl_ativo / 1e6                                                 as vl_ativo_mm,
    b.rendimentos / 1e6                                              as payout_mm,
    round(100.0 * b.rendimentos / nullif(b.pl, 0), 2)                as payout_pct_of_pl,
    b.cotas_emitidas                                                 as cotas_emitidas,
    b.vpc                                                            as vpc,
    b.rendimentos / nullif(b.cotas_emitidas, 0)                      as payout_per_cota,
    round(100.0 * (b.rendimentos / nullif(b.cotas_emitidas, 0))
                / nullif(b.vpc, 0), 2)                               as payout_yield_pct,
    round(b.dy * 100, 2)                                             as reported_dy_pct
  from base b
  left join dim_fund d
    on d.cnpj = b.cnpj and d.entity_type = 'fii'
  order by b.rendimentos desc nulls last, b.pl desc nulls last
  limit 50
) x on true
order by x.payout_mm desc nulls last, x.pl_mm desc nulls last
