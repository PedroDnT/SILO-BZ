-- Debtor concentration of the largest FIDC books at the latest complete
-- period: the rank-1 exposure and the sum of the filed top-25 ranks from
-- informe tab VIII (cvm_fidc_sacado), against the receivables total from tab
-- II (cvm_fidc_setor). Both tabs are members of one monthly informe, so the
-- join on (cnpj, period) is the fund's own filing, not a cross-source match.
--
-- The debtors are ANONYMIZED in the source: CVM publishes (rank, value) and
-- nothing else, so this table can say how concentrated a book is and never
-- in whom. `seq` is CVM's rank as filed and is not recomputed here — the
-- rank-1 row is read, not the max. top25 sums whatever ranks the fund filed
-- (1..n, n <= 25); nothing is imputed for ranks it did not file.
--
-- Floor: receivables >= R$10mm, so a R$50k book with one debtor does not
-- head the table. The floor is printed on the page.
--
-- ZERO-ROW SAFETY: one-row `row_guard` LEFT JOINed with ON TRUE, as in
-- fidc_subordination_top.
with latest as (
  select max(period) as period
    from cvm_fidc_sacado
   where period <= latest_complete_period('fidc')
),
ranks as (
  select
    k.cnpj,
    k.period,
    max(k.valor) filter (where k.seq = 1) as top1,
    sum(k.valor)                          as top25,
    count(*)                              as n_ranks
  from cvm_fidc_sacado k
  join latest l on k.period = l.period
  group by k.cnpj, k.period
),
book as (
  select
    r.cnpj,
    r.period,
    r.top1,
    r.top25,
    r.n_ranks,
    s.vl_carteira as receivables,
    m.vl_patrim_liq
  from ranks r
  join cvm_fidc_setor s on s.cnpj = r.cnpj and s.period = r.period
  left join cvm_fidc_mensal m on m.cnpj = r.cnpj and m.period = r.period
  where s.vl_carteira >= 1e7
    and r.top1 is not null
),
row_guard as (
  select 1 as one
)
select
  coalesce(f.fund_name, b.cnpj)                                as fund_name,
  b.cnpj,
  b.period,
  b.receivables / 1e6                                          as receivables_mm,
  b.vl_patrim_liq / 1e6                                        as pl_mm,
  b.top1 / 1e6                                                 as top1_mm,
  b.top25 / 1e6                                                as top25_mm,
  b.n_ranks,
  round(100.0 * b.top1  / nullif(b.receivables, 0), 1)         as top1_num1,
  round(100.0 * b.top25 / nullif(b.receivables, 0), 1)         as top25_num1
from row_guard g
left join book b on true
left join cvm_fund_registry f
  on f.cnpj = b.cnpj and f.entity_type = 'fidc'
order by top1_num1 desc nulls last, b.receivables desc nulls last
limit 20
