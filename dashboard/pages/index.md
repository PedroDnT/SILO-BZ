---
title: iliquid — Brazilian Fund Analytics
---

```sql aum_by_entity
select
  entity_type,
  period,
  sum(vl_patrim_liq) / 1e9 as aum_bn
from fact_fund_monthly
where period >= current_date - interval '12 months'
group by entity_type, period
order by period desc, aum_bn desc
```

```sql fidc_delinquency
select
  a.period,
  round(100.0 * sum(a.vl_total_inad) / nullif(sum(m.vl_patrim_liq), 0), 2) as delinquency_rate_pct
from cvm_fidc_aging a
join cvm_fidc_mensal m using (cnpj, period)
where a.period >= current_date - interval '12 months'
group by a.period
order by a.period desc
```

```sql row_counts
select 'FI diário'     as dataset, count(*) as rows from cvm_fi_diario
union all
select 'FIDC mensal',   count(*) from cvm_fidc_mensal
union all
select 'FII mensal',    count(*) from cvm_fii_mensal
union all
select 'SECURIT série', count(*) from cvm_securit_serie
```

# Brazilian Fund Analytics

> CVM + BACEN data. Updated daily via GitHub Actions.

<BigValue data={row_counts} value=rows label=dataset fmt=num0/>

---

## AUM by Fund Type — Last 12 Months

<BarChart
  data={aum_by_entity}
  x=period
  y=aum_bn
  series=entity_type
  type=stacked
  yAxisTitle="AUM (R$ bn)"
  title="Total AUM by Entity Type"
/>

---

## FIDC Sector Delinquency Rate

<LineChart
  data={fidc_delinquency}
  x=period
  y=delinquency_rate_pct
  yAxisTitle="Delinquency Rate (%)"
  title="FIDC Sector-Wide Delinquency"
/>

---

## Explore

- [FIDC Credit Monitor](/fidc) — Aging buckets, tranche performance, red flags
- [FII Market](/fii) — Real estate funds: yield, AUM, dividend trends
- [CRA/CRI Issuance](/securit) — Fixed-income securitisation market
- [Suspicious Deals](/suspicious) — Forensic screens: zombie growth, evergreen aging
- [Fund Lookup](/fund) — Search any fund by name or CNPJ
