-- Securitisation payment waterfall, aggregated across the whole book, monthly.
--
-- Reads cvm_securit_fluxo, whose columns map 1:1 onto the CVM cash-flow CSV
-- (see src/parsers/field_maps/securit_fluxo.py): receivables collected in, then
-- paid out down the priority ladder — expenses, senior, mezzanine, junior.
--
-- ZERO-ROW SAFETY: a generate_series of the last 24 months drives the rows and
-- the aggregate is LEFT JOINed, so a month with no filings yields NULLs instead
-- of removing the row.
--
-- The outflow columns are NOT negated: they are reported as positive amounts
-- paid, matching the source. cobertura_num1 is the share of the month's
-- receivables consumed by all payments — above 100 means the structure paid out
-- more than it collected that month.
with months as (
  select generate_series(
           -- last ENDED month: securit is outside fund completeness; the
           -- in-progress month of a monthly filing is partial by construction
           date_trunc('month', current_date - interval '23 months'),
           date_trunc('month', current_date) - interval '1 month',
           interval '1 month'
         )::date as period
),
agg as (
  select
    date_trunc('month', f.data_referencia)::date          as period,
    sum(f.recebimentos_direitos_creditorios) / 1e6        as recebimentos_mm,
    sum(f.pagamentos_classe_senior) / 1e6                 as pgt_senior_mm,
    sum(f.pagamentos_mezanino) / 1e6                      as pgt_mezanino_mm,
    sum(f.pagamentos_junior) / 1e6                        as pgt_junior_mm,
    sum(f.pagamentos_despesas) / 1e6                      as pgt_despesas_mm,
    sum(f.variacao_liquida_caixa) / 1e6                   as variacao_caixa_mm,
    count(distinct f.cnpj_securit)                        as n_securitizadoras,
    count(*)                                              as n_filings,
    -- FILTERed so a month where every payment column is NULL reports NULL,
    -- not a fabricated "R$0 paid". coalesce inside the sum only fills gaps
    -- between the four legs of a row that did report something.
    sum(
      coalesce(f.pagamentos_classe_senior, 0)
      + coalesce(f.pagamentos_mezanino, 0)
      + coalesce(f.pagamentos_junior, 0)
      + coalesce(f.pagamentos_despesas, 0)
    ) filter (
      where f.pagamentos_classe_senior is not null
         or f.pagamentos_mezanino is not null
         or f.pagamentos_junior is not null
         or f.pagamentos_despesas is not null
    ) / 1e6                                               as pgt_total_mm,
    sum(f.recebimentos_direitos_creditorios)              as recebimentos_raw,
    sum(
      coalesce(f.pagamentos_classe_senior, 0)
      + coalesce(f.pagamentos_mezanino, 0)
      + coalesce(f.pagamentos_junior, 0)
      + coalesce(f.pagamentos_despesas, 0)
    ) filter (
      where f.pagamentos_classe_senior is not null
         or f.pagamentos_mezanino is not null
         or f.pagamentos_junior is not null
         or f.pagamentos_despesas is not null
    )                                                     as pgt_total_raw
  from cvm_securit_fluxo f
  where f.data_referencia >= (date_trunc('month', current_date) - interval '23 months')::date
  group by date_trunc('month', f.data_referencia)::date
)
select
  m.period,
  a.recebimentos_mm,
  a.pgt_senior_mm,
  a.pgt_mezanino_mm,
  a.pgt_junior_mm,
  a.pgt_despesas_mm,
  a.pgt_total_mm,
  a.variacao_caixa_mm,
  a.n_securitizadoras,
  a.n_filings,
  round(100.0 * a.pgt_total_raw / nullif(a.recebimentos_raw, 0), 1) as cobertura_num1
from months m
left join agg a on a.period = m.period
order by m.period
