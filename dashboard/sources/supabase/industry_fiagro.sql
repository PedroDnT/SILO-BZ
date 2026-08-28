-- FIAGRO (agribusiness) monthly reporting, straight from cvm_fiagro_mensal.
--
-- Read at source rather than through fact_fund_monthly so FIAGRO is visible by
-- name — including its delinquency column (vl_inadimpl), which FIAGRO shares
-- with FIDC and which no aggregate view exposes for it.
--
-- Month spine drives the rows (fixed 24); the aggregate LATERAL always returns
-- exactly one row, so an empty cvm_fiagro_mensal produces blank months rather
-- than a 0-row source — the zero-byte parquet that kills an Evidence build.
--
-- COVERAGE: the CVM FIAGRO monthly file only starts in 2025-05, so months
-- before that are legitimately empty, not a pipeline failure.
--
-- inadimpl_num1 = delinquent value / net assets, in percent, computed here.
with bounds as (
  -- BOTH edges are clamped to reality. The end is fiagro's completeness bound
  -- (mv_period_completeness) so a partially-filed month is not served. The
  -- START is the first month CVM actually published for the family: the file
  -- begins 2025-05, so a bare 24-month window rendered ~14 leading months of
  -- structural emptiness that read as "FIAGRO collapsed to zero" rather than
  -- "FIAGRO did not exist here yet". greatest() keeps the shorter of the two,
  -- and the spine still drives the row count, so this cannot produce a 0-row
  -- source (the zero-byte-parquet build killer).
  select
    date_trunc('month', latest_complete_period('fiagro'))::date as p_end,
    greatest(
      (date_trunc('month', latest_complete_period('fiagro')) - interval '23 months')::date,
      coalesce(
        (select date_trunc('month', min(period))::date from cvm_fiagro_mensal),
        (date_trunc('month', latest_complete_period('fiagro')) - interval '23 months')::date
      )
    ) as p_start
),
spine as (
  select generate_series(b.p_start, b.p_end, interval '1 month')::date as period
  from bounds b
)
select
  sp.period,
  f.n_funds,
  f.pl_bn,
  f.inadimpl_mm,
  f.inadimpl_num1,
  f.cotistas
from spine sp
left join lateral (
  select
    count(distinct g.cnpj)                                                        as n_funds,
    sum(g.vl_patrim_liq) / 1e9                                                    as pl_bn,
    sum(g.vl_inadimpl)   / 1e6                                                    as inadimpl_mm,
    round(100.0 * sum(g.vl_inadimpl) / nullif(sum(g.vl_patrim_liq), 0), 2)        as inadimpl_num1,
    sum(g.nr_cotst)                                                               as cotistas
  from cvm_fiagro_mensal g
  where g.period = sp.period
    and g.cnpj is not null
) f on true
order by sp.period
