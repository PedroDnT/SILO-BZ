select
  m.cnpj,
  coalesce(r.fund_name, m.cnpj) as fund_name,
  m.period,
  m.vl_patrim_liq / 1e6 as pl_mm,
  m.nr_cotst as investors,
  round(m.pct_dividend_yield_mes * 100, 2) as dy_num2,
  round(m.pct_rentab_patrimonial * 100, 2) as return_num2
from cvm_fii_mensal m
left join cvm_fund_registry r on r.cnpj = m.cnpj and r.entity_type = 'fii'
where m.doc_subtype = 'complemento'
  and m.period = (select max(period) from cvm_fii_mensal where doc_subtype = 'complemento')
  and m.vl_patrim_liq > 5e7
  and m.pct_dividend_yield_mes > 0
order by dy_num2 desc nulls last
limit 25
