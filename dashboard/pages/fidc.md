---
title: FIDC Credit Monitor
---

```sql delinquency_trend
select
  a.period,
  round(100.0 * sum(a.vl_total_inad) / nullif(sum(m.vl_patrim_liq), 0), 2) as delinquency_rate_pct,
  sum(a.vl_total_inad) / 1e6 as total_inad_mm,
  count(distinct a.cnpj) as n_funds
from cvm_fidc_aging a
join cvm_fidc_mensal m using (cnpj, period)
where a.period >= current_date - interval '24 months'
group by a.period
order by a.period
```

```sql aging_buckets
select
  period,
  sum(vl_inad_30)         / 1e6 as inad_30d,
  sum(vl_inad_60)         / 1e6 as inad_60d,
  sum(vl_inad_90)         / 1e6 as inad_90d,
  sum(vl_inad_180)        / 1e6 as inad_180d,
  sum(vl_inad_360)        / 1e6 as inad_360d,
  sum(vl_inad_maior_1080) / 1e6 as inad_over1080d
from cvm_fidc_aging
where period >= current_date - interval '12 months'
group by period
order by period
```

```sql top_delinquent
select
  a.cnpj,
  coalesce(r.fund_name, a.cnpj) as fund_name,
  a.period,
  round(100.0 * a.vl_total_inad / nullif(m.vl_patrim_liq, 0), 1) as delinquency_pct,
  a.vl_total_inad / 1e6 as inad_mm,
  m.vl_patrim_liq / 1e6 as pl_mm
from cvm_fidc_aging a
join cvm_fidc_mensal m using (cnpj, period)
left join cvm_fund_registry r on r.cnpj = a.cnpj and r.entity_type = 'fidc'
where a.period = (select max(period) from cvm_fidc_aging)
  and m.vl_patrim_liq > 1e6
order by delinquency_pct desc nulls last
limit 20
```

```sql high_delinq_growing
select
  a.cnpj,
  coalesce(r.fund_name, a.cnpj) as fund_name,
  a.period,
  m.vl_patrim_liq / 1e6 as pl_mm,
  round(100.0 * a.vl_total_inad / nullif(m.vl_patrim_liq, 0), 1) as inad_pct
from cvm_fidc_aging a
join cvm_fidc_mensal m using (cnpj, period)
left join cvm_fund_registry r on r.cnpj = a.cnpj and r.entity_type = 'fidc'
where a.period = (select max(period) from cvm_fidc_aging)
  and m.vl_patrim_liq > 1e6
  and 100.0 * a.vl_total_inad / nullif(m.vl_patrim_liq, 0) > 5
order by pl_mm desc nulls last
limit 15
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
