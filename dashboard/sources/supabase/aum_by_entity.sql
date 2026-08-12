select
  entity_type,
  period,
  sum(vl_patrim_liq) / 1e9 as aum_bn
from fact_fund_monthly
where period >= current_date - interval '12 months'
group by entity_type, period
order by period desc, aum_bn desc
