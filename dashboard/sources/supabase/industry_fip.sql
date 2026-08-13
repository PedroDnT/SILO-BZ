-- FIP (private equity) reporting, per calendar year, straight from
-- cvm_fip_periodic.
--
-- FIP is the one family with a YEARLY grain: inf_trimestral up to 2023 and
-- inf_quadrimestral from 2024 (see the dispatch matrix in src/api/dispatch.py),
-- keyed UNIQUE on (cnpj, doc_type, period_year). It is read here directly rather
-- than through fact_fund_monthly, where it is mapped onto 31-Dec and disappears
-- into a monthly aggregate.
--
-- A year spine drives the rows (fixed, ~8) and an aggregate LATERAL — which
-- always returns exactly one row — supplies the numbers, so an empty
-- cvm_fip_periodic yields blank years instead of a 0-row source (the zero-byte
-- parquet that kills the build).
--
-- vl_patrim_liq is net assets as filed. Funds that filed without a PL figure are
-- counted in n_funds but contribute nothing to pl_bn — hence n_funds_with_pl.
with years as (
  select generate_series(2019, extract(year from current_date)::int) as period_year
)
select
  y.period_year,
  f.n_funds,
  f.n_funds_with_pl,
  f.total_pl_bn,
  f.doc_types,
  f.n_reports
from years y
left join lateral (
  select
    count(distinct p.cnpj)                                                as n_funds,
    count(distinct p.cnpj) filter (where p.vl_patrim_liq is not null)     as n_funds_with_pl,
    sum(p.vl_patrim_liq) / 1e9                                            as total_pl_bn,
    string_agg(distinct p.doc_type, ', ')                                 as doc_types,
    count(*)                                                              as n_reports
  from cvm_fip_periodic p
  where p.period_year = y.period_year
    and p.cnpj is not null
) f on true
order by y.period_year
