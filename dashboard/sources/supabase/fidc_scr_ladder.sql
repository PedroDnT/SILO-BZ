-- Receivables by BACEN SCR grade at the latest complete period with tab X
-- data (cvm_fidc_scr, migration 38): the same book graded two ways — by the
-- DEBTOR's rating and by the OPERATION's rating. AA is the best grade, H the
-- worst; H is the bucket a provisioning rule treats as ~100% loss.
--
-- tab X exists from 2023-10 only. `latest` reads the newest complete period
-- that HAS scr rows, so the section never shows an older month as empty.
--
-- ZERO-ROW SAFETY: structural (bare aggregate × fixed grade axis), as in
-- fidc_aging_profile: nine rows always, NULL measures over an empty table.
with latest as (
  select max(period) as period
    from cvm_fidc_scr
   where period <= latest_complete_period('fidc')
),
totals as (
  select
    sum(r.vl_devedor_aa) as d_aa, sum(r.vl_devedor_a) as d_a, sum(r.vl_devedor_b) as d_b,
    sum(r.vl_devedor_c)  as d_c,  sum(r.vl_devedor_d) as d_d, sum(r.vl_devedor_e) as d_e,
    sum(r.vl_devedor_f)  as d_f,  sum(r.vl_devedor_g) as d_g, sum(r.vl_devedor_h) as d_h,
    sum(r.vl_oper_aa)    as o_aa, sum(r.vl_oper_a)    as o_a, sum(r.vl_oper_b)    as o_b,
    sum(r.vl_oper_c)     as o_c,  sum(r.vl_oper_d)    as o_d, sum(r.vl_oper_e)    as o_e,
    sum(r.vl_oper_f)     as o_f,  sum(r.vl_oper_g)    as o_g, sum(r.vl_oper_h)    as o_h,
    count(distinct r.cnpj) as n_funds,
    max(r.period)          as period
  from cvm_fidc_scr r
  join latest l on r.period = l.period
),
grades as (
  select
    t.period,
    t.n_funds,
    v.grade,
    v.by_debtor,
    v.by_operation,
    coalesce(t.d_aa,0)+coalesce(t.d_a,0)+coalesce(t.d_b,0)+coalesce(t.d_c,0)+coalesce(t.d_d,0)
      +coalesce(t.d_e,0)+coalesce(t.d_f,0)+coalesce(t.d_g,0)+coalesce(t.d_h,0) as debtor_total
  from totals t
  cross join lateral unnest(
    array['1 AA', '2 A', '3 B', '4 C', '5 D', '6 E', '7 F', '8 G', '9 H'],
    array[t.d_aa, t.d_a, t.d_b, t.d_c, t.d_d, t.d_e, t.d_f, t.d_g, t.d_h],
    array[t.o_aa, t.o_a, t.o_b, t.o_c, t.o_d, t.o_e, t.o_f, t.o_g, t.o_h]
  ) as v(grade, by_debtor, by_operation)
)
select
  grade,
  period,
  n_funds,
  by_debtor / 1e9    as by_debtor_bn,
  by_operation / 1e9 as by_operation_bn,
  round(100.0 * by_debtor / nullif(debtor_total, 0), 1) as debtor_share_num1
from grades
order by grade
