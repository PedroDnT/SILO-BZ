-- Capital structure of the largest FIDCs at the latest reported period.
--
-- Reuses fidc_subordination_trend() (src/store/analytical/09_analytical_functions.sql)
-- rather than re-implementing its senior-detection rule. That function is
-- per-fund by signature, so it is called through a LATERAL over a bounded set
-- of 12 funds — the largest by PL that actually have tranche filings for the
-- period. Twelve indexed single-CNPJ calls, not a universe scan.
--
-- UNIT CAVEAT: the function's subordination_ratio is computed from qt_cota —
-- QUOTA COUNTS, not quota value. It is a structural headcount ratio, and only
-- equals a value-weighted subordination level when senior and subordinated
-- quotas carry the same unit price. It is reported as-is and labelled as a
-- quota ratio on the page; converting it to a value ratio would be an
-- assumption the source does not support.
--
-- ZERO-ROW SAFETY: one-row `row_guard` LEFT JOINed with ON TRUE, so an empty
-- cvm_fidc_tranche still yields a row.
with latest as (
  select max(period) as period from cvm_fidc_tranche
),
top_funds as (
  -- l.period is carried through so the LATERAL call below takes a plain column
  -- reference as its bounds rather than a scalar subquery.
  select m.cnpj, m.vl_patrim_liq, m.vl_inadimpl, l.period as latest_period
  from cvm_fidc_mensal m
  join latest l on m.period = l.period
  where m.vl_patrim_liq > 0
    and exists (
      select 1 from cvm_fidc_tranche t
      where t.cnpj = m.cnpj and t.period = l.period
    )
  order by m.vl_patrim_liq desc nulls last
  limit 12
),
structure as (
  select
    f.cnpj,
    f.vl_patrim_liq,
    f.vl_inadimpl,
    st.period,
    st.n_senior_series,
    st.n_subordinada_series,
    st.qt_senior,
    st.qt_subordinada,
    st.subordination_ratio
  from top_funds f
  cross join lateral fidc_subordination_trend(
    f.cnpj,
    f.latest_period,
    f.latest_period
  ) st
),
row_guard as (
  select 1 as one
)
select
  coalesce(r.fund_name, s.cnpj)                              as fund_name,
  s.cnpj,
  s.period,
  s.vl_patrim_liq / 1e6                                      as pl_mm,
  s.n_senior_series,
  s.n_subordinada_series,
  s.qt_senior / 1e6                                          as qt_senior_mm,
  s.qt_subordinada / 1e6                                     as qt_subordinada_mm,
  -- RPC already NULLs ratios outside [0,1]; clamp again so a stale function
  -- definition cannot paint thousands of percent on the page.
  case
    when s.subordination_ratio between 0 and 1
      then round(100.0 * s.subordination_ratio, 1)
  end                                                        as subordination_pct,
  round(100.0 * s.vl_inadimpl / nullif(s.vl_patrim_liq, 0), 1) as inadimpl_pct
from row_guard g
left join structure s on true
left join cvm_fund_registry r
  on r.cnpj = s.cnpj and r.entity_type = 'fidc'
order by s.vl_patrim_liq desc nulls last
