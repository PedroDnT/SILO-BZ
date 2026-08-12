---
title: FII Market
---

```sql fii_vs_fiagro
select * from supabase.fii_vs_fiagro
```

```sql top_fii_yield
select * from supabase.top_fii_yield
```

```sql yield_distribution
select * from supabase.yield_distribution
```

# FII Market

Real estate investment funds: AUM, dividend yield, and investor trends.

---

## FII vs FIAGRO AUM

<BarChart
  data={fii_vs_fiagro}
  x=period
  y=aum_bn
  series=entity_type
  type=grouped
  yAxisTitle="AUM (R$ bn)"
  title="FII vs FIAGRO Total AUM"
/>

---

## Yield Distribution Across FIIs — p10 to p90

<LineChart
  data={yield_distribution}
  x=period
  y={['p10','p25','median','p75','p90']}
  yAxisTitle="Dividend Yield (%)"
  title="FII Monthly Dividend Yield Distribution"
/>

---

## Top 25 FIIs by Dividend Yield (AUM > R$50mm)

<DataTable data={top_fii_yield} rows=25>
  <Column id=fund_name title="Fund"/>
  <Column id=pl_mm title="AUM (R$mm)" fmt=num0/>
  <Column id=investors title="Investors" fmt=num0/>
  <Column id=dy_pct title="DY %" fmt=num2/>
  <Column id=return_pct title="Return %" fmt=num2/>
</DataTable>
