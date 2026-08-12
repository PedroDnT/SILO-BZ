select
  entity_type,
  period,
  sum(vl_patrim_liq) / 1e9 as aum_bn,
  count(distinct cnpj) as n_funds
from fact_fund_monthly
where entity_type in ('fii', 'fiagro')
  and period >= current_date - interval '24 months'
group by entity_type, period
order by period, entity_type
