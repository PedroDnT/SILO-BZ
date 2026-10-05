-- pct_dividend_yield_mes is CVM's Percentual_Dividend_Yield_Mes stored AS PUBLISHED,
-- i.e. already a percent (the API's `yield` metric documents it the same way).
-- An earlier version multiplied by 100 and the p90 line read ~2,000 %.
--
-- The month is the latest COMPLETE one, not the latest filed one: on 2026-10-04
-- the newest month held 8 early filings, none with a yield, so max(period)
-- returned 0 rows and the zero-byte parquet failed the production build.
-- least() keeps a cold database (no complete month yet) on max(period). The
-- anchor is MATERIALIZED so the clamp runs once, not once per fact row
-- (tests/test_dashboard_source_plans.py).
with anchor as materialized (
  select least(
           latest_complete_period('fii'),
           (select max(period) from vw_fii_mensal_latest where doc_subtype = 'complemento')
         ) as p
)
select
  m.cnpj,
  coalesce(r.fund_name, m.cnpj) as fund_name,
  m.period,
  m.vl_patrim_liq / 1e6 as pl_mm,
  m.nr_cotst as investors,
  round(m.pct_dividend_yield_mes, 2) as dy_num2,
  round(m.pct_rentab_patrimonial * 100, 2) as return_num2
from vw_fii_mensal_latest m
cross join anchor a
left join cvm_fund_registry r on r.cnpj = m.cnpj and r.entity_type = 'fii'
where m.doc_subtype = 'complemento'
  and m.period = a.p
  and m.vl_patrim_liq > 5e7
  and m.pct_dividend_yield_mes > 0
order by dy_num2 desc nulls last
limit 25
