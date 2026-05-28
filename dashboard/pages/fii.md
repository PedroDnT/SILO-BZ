---
title: FII Market
---

```sql fii_vs_fiagro
select
  entity_type,
  period,
  sum(vl_patrim_liq) / 1e9 as aum_bn,
  avg(pct_dividend_yield_mes) * 100 as avg_dy_pct,
  count(distinct cnpj) as n_funds
from fact_fund_monthly
where entity_type in ('fii', 'fiagro')
  and period >= current_date - interval '24 months'
group by entity_type, period
order by period, entity_type
```

```sql top_fii_yield
select
  m.cnpj,
  coalesce(r.fund_name, m.cnpj) as fund_name,
  m.period,
  m.vl_patrim_liq / 1e6 as pl_mm,
  m.nr_cotst as investors,
  round(m.pct_dividend_yield_mes * 100, 2) as dy_pct,
  round(m.pct_rentab_patrimonial * 100, 2) as return_pct
from cvm_fii_mensal m
left join cvm_fund_registry r on r.cnpj = m.cnpj and r.entity_type = 'fii'
where m.doc_subtype = 'complemento'
  and m.period = (select max(period) from cvm_fii_mensal where doc_subtype = 'complemento')
  and m.vl_patrim_liq > 5e7
  and m.pct_dividend_yield_mes > 0
order by dy_pct desc nulls last
limit 25
```

```sql yield_distribution
select
  period,
  percentile_cont(0.10) within group (order by pct_dividend_yield_mes) * 100 as p10,
  percentile_cont(0.25) within group (order by pct_dividend_yield_mes) * 100 as p25,
  percentile_cont(0.50) within group (order by pct_dividend_yield_mes) * 100 as median,
  percentile_cont(0.75) within group (order by pct_dividend_yield_mes) * 100 as p75,
  percentile_cont(0.90) within group (order by pct_dividend_yield_mes) * 100 as p90
from cvm_fii_mensal
where doc_subtype = 'complemento'
  and pct_dividend_yield_mes > 0
  and period >= current_date - interval '12 months'
group by period
order by period
```

# FII Market

Real estate investment funds: AUM, dividend yield, and investor trends.

---

## FII vs FIAGRO — AUM & Yield

<BarChart
  data={fii_vs_fiagro}
  x=period
  y=aum_bn
  series=entity_type
  type=grouped
  yAxisTitle="AUM (R$ bn)"
  title="FII vs FIAGRO Total AUM"
/>

<LineChart
  data={fii_vs_fiagro}
  x=period
  y=avg_dy_pct
  series=entity_type
  yAxisTitle="Avg Dividend Yield (%)"
  title="Average Monthly Dividend Yield"
/>

---

## Yield Distribution Across FIIs (p10–p90)

<LineChart
  data={yield_distribution}
  x=period
  y={['p10','p25','median','p75','p90']}
  yAxisTitle="Dividend Yield (%)"
  title="FII Yield Distribution — Monthly"
/>

---

## Top 25 FIIs by Dividend Yield (Latest Period, AUM > R$50mm)

<DataTable data={top_fii_yield} rows=25>
  <Column id=fund_name title="Fund"/>
  <Column id=pl_mm title="AUM (R$mm)" fmt=num0/>
  <Column id=investors title="Investors" fmt=num0/>
  <Column id=dy_pct title="DY %" fmt=num2/>
  <Column id=return_pct title="Return %" fmt=num2/>
</DataTable>
