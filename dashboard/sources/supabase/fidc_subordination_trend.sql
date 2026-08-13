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
with months as (
  select generate_series(
           date_trunc('month', current_date - interval '23 months'),
           date_trunc('month', current_date),
           interval '1 month'
         )::date as period
),
latest as (
  select max(period) as period from cvm_fidc_tranche
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
  cross join lateral fidc_subordination_trend(
    b.cnpj,
    (date_trunc('month', current_date) - interval '23 months')::date,
    current_date
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
  end                                     as subordination_pct
from months m
left join series s on s.period = m.period
left join cvm_fund_registry r
  on r.cnpj = s.cnpj and r.entity_type = 'fidc'
order by m.period
