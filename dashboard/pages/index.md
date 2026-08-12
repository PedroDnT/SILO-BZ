---
title: iliquid — Brazilian Fund Analytics
---

```sql aum_by_entity
select * from supabase.aum_by_entity
```

```sql fidc_delinquency
select * from supabase.fidc_delinquency
```

```sql row_counts
select * from supabase.row_counts
```

# Brazilian Fund Analytics

> CVM + BACEN public data. Updated daily.

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

- [Fund Performance](/performance) — Who beat their peers, per asset class (horizontal + vertical)
- [ETF Market](/etf) — Listed ETFs, evaluated separately from the fund industry
- [FIDC Credit Monitor](/fidc) — Aging buckets, tranche performance, red flags
- [FII Market](/fii) — Real estate funds: yield, AUM, dividend trends
- [Suspicious Deals](/suspicious) — Forensic screens: zombie growth, evergreen aging
