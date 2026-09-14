-- Subordination structure over 24 months for the single largest FIDC that has
-- tranche filings, again via fidc_subordination_trend()
-- (src/store/analytical/09_analytical_functions.sql).
--
-- One fund, not the universe, because the function is per-CNPJ by signature and
-- a subordination ratio is only meaningful within one capital structure —
-- averaging it across funds of different sizes would produce a number that
-- describes no actual deal.
--
-- Same qt_cota caveat as fidc_subordination_top.sql: the ratio is a quota-count
-- ratio, not a value-weighted one.
--
-- ZERO-ROW SAFETY: generate_series over 24 months drives the rows; the fund's
-- series is LEFT JOINed onto it, so months it did not file (or an entirely
-- empty cvm_fidc_tranche) come back NULL instead of no-row.
with anchor as (
  -- SPINE END: the last month the tranche filings have actually reached,
  -- capped at FIDC's completeness bound. That bound (mv_period_completeness)
  -- is measured on cvm_fidc_mensal, not on cvm_fidc_tranche, so the cap alone
  -- left the trailing months on the axis, empty — and this chart is ONE fund,
  -- so a single missed filing empties the point. least() ignores a NULL max().
  select least(
           date_trunc('month', latest_complete_period('fidc')),
           date_trunc('month', max(period))
         )::date as p_end
  from cvm_fidc_tranche
),
months as (
  select generate_series(
           date_trunc('month', a.p_end) - interval '23 months',
           date_trunc('month', a.p_end),
           interval '1 month'
         )::date as period
  from anchor a
),
latest as (
  -- never anchor "latest" on a partially-filed month: the same bound as the spine
  select max(t.period) as period
  from cvm_fidc_tranche t
  cross join anchor a
  where t.period < (date_trunc('month', a.p_end) + interval '1 month')::date
),
biggest as (
  select m.cnpj
  from cvm_fidc_mensal m
  join latest l on m.period = l.period
  where m.vl_patrim_liq > 0
    and exists (
      select 1 from cvm_fidc_tranche t
      where t.cnpj = m.cnpj and t.period = l.period
    )
  order by m.vl_patrim_liq desc nulls last
  limit 1
),
series as (
  select
    b.cnpj,
    date_trunc('month', st.period)::date as period,
    st.n_senior_series,
    st.n_subordinada_series,
    st.qt_senior,
    st.qt_subordinada,
    st.subordination_ratio
  from biggest b
  cross join anchor a
  cross join lateral fidc_subordination_trend(
    b.cnpj,
    (date_trunc('month', a.p_end) - interval '23 months')::date,
    (date_trunc('month', a.p_end) + interval '1 month' - interval '1 day')::date
  ) st
)
select
  m.period,
  coalesce(r.fund_name, s.cnpj)           as fund_name,
  s.cnpj,
  s.n_senior_series,
  s.n_subordinada_series,
  s.qt_senior / 1e6                       as qt_senior_mm,
  s.qt_subordinada / 1e6                  as qt_subordinada_mm,
  case
    when s.subordination_ratio between 0 and 1
      then round(100.0 * s.subordination_ratio, 1)
  end                                     as subordination_num1
from months m
left join series s on s.period = m.period
left join cvm_fund_registry r
  on r.cnpj = s.cnpj and r.entity_type = 'fidc'
order by m.period
