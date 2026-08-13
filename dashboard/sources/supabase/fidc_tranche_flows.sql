-- Tranche-level capital flows across the FIDC universe, monthly.
--
-- cvm_fidc_tranche_flows is CVM tab_X_4: one row per (cnpj, period,
-- classe_serie, tp_oper), with tp_oper carrying the operation type
-- (TAB_X_TP_OPER). Captação/resgate are matched on the CAPT/RESG substrings —
-- the same convention fidc_flow_vs_delinquency() uses in
-- src/store/analytical/10_analytical_functions_advanced.sql — so the two agree.
-- Anything matching neither is surfaced as `outros_mm` instead of being dropped.
--
-- Both legs are reported as positive amounts, as filed; net_flow_mm carries the
-- sign. net_flow_mm is NULL (not 0) when neither leg reported for the month, so
-- "no filing" never renders as "flat".
--
-- ZERO-ROW SAFETY: generate_series over the last 24 months drives the rows and
-- the aggregate is LEFT JOINed.
with months as (
  select generate_series(
           date_trunc('month', current_date - interval '23 months'),
           date_trunc('month', current_date),
           interval '1 month'
         )::date as period
),
agg as (
  select
    date_trunc('month', f.period)::date as period,
    sum(f.vl_total) filter (where upper(f.tp_oper) like '%CAPT%') / 1e6 as captacao_mm,
    sum(f.vl_total) filter (where upper(f.tp_oper) like '%RESG%') / 1e6 as resgate_mm,
    sum(f.vl_total) filter (
      where upper(coalesce(f.tp_oper, '')) not like '%CAPT%'
        and upper(coalesce(f.tp_oper, '')) not like '%RESG%'
    ) / 1e6                                                            as outros_mm,
    count(distinct f.cnpj)                                             as n_funds,
    count(*)                                                           as n_rows
  from cvm_fidc_tranche_flows f
  where f.period >= (date_trunc('month', current_date) - interval '23 months')::date
  group by date_trunc('month', f.period)::date
)
select
  m.period,
  a.captacao_mm,
  a.resgate_mm,
  a.outros_mm,
  a.n_funds,
  a.n_rows,
  case
    when a.captacao_mm is null and a.resgate_mm is null then null
    else coalesce(a.captacao_mm, 0) - coalesce(a.resgate_mm, 0)
  end as net_flow_mm
from months m
left join agg a on a.period = m.period
order by m.period
