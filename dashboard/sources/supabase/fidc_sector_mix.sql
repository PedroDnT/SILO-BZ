-- Receivables by sector across every FIDC at the latest complete period, from
-- informe tab II (cvm_fidc_setor, migration 38).
--
-- Tab II is a hierarchy: eleven lettered sectors A..K, some with numbered
-- members (C1..C3, D1..D4, F1..F8, H1..H2, I1..I4). This source sums the
-- LETTERED level only, so nothing is counted twice; the numbered detail is
-- served by api.fidc_portfolio per fund. `share_num1` is the sector's share
-- of the summed lettered lines, not of TOTAL: a fund can file a TOTAL that
-- differs from the sum of its lines, and dividing by TOTAL would present that
-- gap as a phantom sector.
--
-- ZERO-ROW SAFETY: structural, as in fidc_aging_profile — `totals` is a bare
-- aggregate (one row even over an empty table) unnested against the eleven
-- fixed sector labels, so the axis is always present and an empty table
-- yields eleven rows of NULL measures.
--
-- Completeness clamp: bare max(period) lands on a partially-filed trailing
-- month; latest_complete_period keeps FIDC's month-end convention.
with latest as (
  select max(period) as period
    from cvm_fidc_setor
   where period <= latest_complete_period('fidc')
),
totals as (
  select
    sum(s.vl_a_indust)        as a,
    sum(s.vl_b_imobil)        as b,
    sum(s.vl_c_comerc)        as c,
    sum(s.vl_d_serv)          as d,
    sum(s.vl_e_agroneg)       as e,
    sum(s.vl_f_financ)        as f,
    sum(s.vl_g_credito)       as g,
    sum(s.vl_h_factor)        as h,
    sum(s.vl_i_setor_publico) as i,
    sum(s.vl_j_judicial)      as j,
    sum(s.vl_k_marca)         as k,
    count(distinct s.cnpj)    as n_funds,
    max(s.period)             as period
  from cvm_fidc_setor s
  join latest l on s.period = l.period
),
sectors as (
  select
    t.period,
    t.n_funds,
    v.code,
    v.sector,
    v.value,
    coalesce(t.a,0)+coalesce(t.b,0)+coalesce(t.c,0)+coalesce(t.d,0)+coalesce(t.e,0)
      +coalesce(t.f,0)+coalesce(t.g,0)+coalesce(t.h,0)+coalesce(t.i,0)
      +coalesce(t.j,0)+coalesce(t.k,0) as graded_total
  from totals t
  cross join lateral unnest(
    array['A','B','C','D','E','F','G','H','I','J','K'],
    array['A Industrial', 'B Imobiliário', 'C Comercial', 'D Serviços', 'E Agronegócio',
          'F Financeiro', 'G Crédito', 'H Factoring', 'I Setor público', 'J Judicial', 'K Marcas'],
    array[t.a, t.b, t.c, t.d, t.e, t.f, t.g, t.h, t.i, t.j, t.k]
  ) as v(code, sector, value)
)
select
  code,
  sector,
  period,
  n_funds,
  value / 1e9 as value_bn,
  round(100.0 * value / nullif(graded_total, 0), 1) as share_num1
from sectors
order by value desc nulls last
