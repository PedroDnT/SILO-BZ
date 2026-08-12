---
title: FIDC Credit Monitor
---

```sql delinquency_trend
select * from supabase.delinquency_trend
```

```sql aging_buckets
select * from supabase.aging_buckets
```

```sql top_delinquent
select * from supabase.top_delinquent
```

```sql high_delinq_growing
select * from supabase.high_delinq_growing
```

# FIDC Credit Monitor

Receivables funds: delinquency trends, aging buckets, and forensic red flags.

---

## Sector Delinquency — 24 Months

<LineChart
  data={delinquency_trend}
  x=period
  y=delinquency_rate_pct
  yAxisTitle="Delinquency Rate (%)"
  title="FIDC Sector Delinquency Rate"
/>

<DataTable data={delinquency_trend} rows=6>
  <Column id=period title="Period"/>
  <Column id=n_funds title="Funds" fmt=num0/>
  <Column id=total_inad_mm title="Total Inad (R$mm)" fmt=num1/>
  <Column id=delinquency_rate_pct title="Delinq Rate %" fmt=num2/>
</DataTable>

---

## Delinquency by Aging Bucket — Last 12 Months (R$ mm)

<AreaChart
  data={aging_buckets}
  x=period
  y={['inad_30d','inad_60d','inad_90d','inad_180d','inad_360d','inad_over1080d']}
  type=stacked
  yAxisTitle="R$ mm"
  title="Delinquency by Aging Bucket"
/>

---

## Top 20 Most Delinquent FIDCs (Latest Period)

<DataTable data={top_delinquent} rows=20>
  <Column id=fund_name title="Fund"/>
  <Column id=pl_mm title="AUM (R$mm)" fmt=num1/>
  <Column id=inad_mm title="Inad (R$mm)" fmt=num1/>
  <Column id=delinquency_pct title="Delinquency %" fmt=num1/>
</DataTable>

---

## 🚨 Funds with Delinquency > 5% and AUM > R$1mm

<DataTable data={high_delinq_growing}>
  <Column id=fund_name title="Fund"/>
  <Column id=period title="Period"/>
  <Column id=pl_mm title="AUM (R$mm)" fmt=num1/>
  <Column id=inad_pct title="Delinq %" fmt=num1/>
</DataTable>
