-- Raw tp_oper breakdown of tranche flows at the latest reported period.
--
-- Shown verbatim rather than folded into "subscription / redemption": tp_oper
-- is free text from TAB_X_TP_OPER and CVM's vocabulary has drifted across
-- years. Printing the actual values is the only way to tell whether the
-- CAPT/RESG substring matching used elsewhere on this page is still catching
-- everything — a row landing in "(não classificado)" is the signal that it is
-- not.
--
-- ZERO-ROW SAFETY: one-row `row_guard` LEFT JOINed to the grouped aggregate.
with latest as (
  select max(period) as period from cvm_fidc_tranche_flows
),
agg as (
  select
    coalesce(nullif(trim(f.tp_oper), ''), '(não informado)') as tp_oper,
    case
      when upper(f.tp_oper) like '%CAPT%' then 'Captação'
      when upper(f.tp_oper) like '%RESG%' then 'Resgate'
      else '(não classificado)'
    end                                                      as leg,
    count(*)                                                 as n_rows,
    count(distinct f.cnpj)                                   as n_funds,
    count(distinct f.classe_serie)                           as n_classes,
    sum(f.vl_total) / 1e6                                    as vl_mm
  from cvm_fidc_tranche_flows f
  join latest l on f.period = l.period
  group by 1, 2
),
row_guard as (
  select 1 as one
)
select
  a.tp_oper,
  a.leg,
  a.n_funds,
  a.n_classes,
  a.n_rows,
  a.vl_mm
from row_guard g
left join agg a on true
order by a.vl_mm desc nulls last
limit 20
