---
title: FIDC Credit Monitor
---

<!--
  FIDC = receivables funds. Two grains matter and this page now shows both:

    ASSET SIDE  — cvm_fidc_aging (CVM tab_VI). Twenty columns, in two bands of
      ten: vl_prazo_* (band A, days REMAINING to maturity — still performing)
      and vl_inad_* (band B, days ALREADY overdue). Until now the dashboard read
      only band B. Band A has been ingested since the dataset was wired
      (src/parsers/field_maps/fidc_aging.py maps all ten) and is what a
      delinquency rate cannot tell you — a book whose performing balance sits in
      the 720d+ buckets is carrying duration risk that simply has not come due.

    LIABILITY SIDE — cvm_fidc_tranche (tabs X_2/X_3/X_6) and
      cvm_fidc_tranche_flows (tab X_4): who holds which slice, what each slice
      was promised versus what it earned, and money in versus money out per
      series.

  DATA CAVEATS, none of them papered over:
    * pr_desemp_esperado / pr_desemp_real / vl_rentab_mes are raw CVM percentage
      fields and schema.sql states outright that they contain garbage outliers
      (observed up to 1.6e8). Every aggregate here is a MEDIAN, not a mean, so
      one dirty filing cannot move it, and no arbitrary cut-off is needed. The
      one place a band IS applied — the per-tranche table — prints the count of
      rows the band removed.
    * subordination_ratio from fidc_subordination_trend() is built from qt_cota,
      i.e. QUOTA COUNTS, not value. It equals a value-weighted subordination
      level only when senior and subordinated quotas share a unit price.
    * FIDC ingestion has historically lagged (CVM publication delay); months with
      no filing render blank rather than zero.
-->

```sql delinquency_trend
select * from supabase.delinquency_trend
```

```sql aging_buckets
select * from supabase.aging_buckets
```

```sql fidc_aging_profile
select * from supabase.fidc_aging_profile
```

```sql fidc_performing_aging
select * from supabase.fidc_performing_aging
```

```sql top_delinquent
select * from supabase.top_delinquent
```

```sql high_delinq_growing
select * from supabase.high_delinq_growing
```

```sql fidc_tranche_performance
select * from supabase.fidc_tranche_performance
```

```sql fidc_tranche_trend
select * from supabase.fidc_tranche_trend
```

```sql fidc_tranche_underperformers
select * from supabase.fidc_tranche_underperformers
```

```sql fidc_subordination_top
select * from supabase.fidc_subordination_top
```

```sql fidc_subordination_trend
select * from supabase.fidc_subordination_trend
```

```sql fidc_tranche_flows
select * from supabase.fidc_tranche_flows
```

```sql fidc_flows_by_oper
select * from supabase.fidc_flows_by_oper
```

# FIDC Credit Monitor

Receivables funds: delinquency trends, aging buckets, tranche structure, and forensic red flags.

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

## Performing vs Delinquent — Both Bands, Latest Period

> The full tab*VI form on one axis: `vl_prazo*_`(performing, bucketed by days
**to** maturity) against`vl*inad*_` (delinquent, bucketed by days **past**
> due). The ten buckets are a property of the CVM form, so they are always
> present — an empty bar is a bucket with nothing in it, not a missing bucket.

<BarChart
data={fidc_aging_profile}
x=bucket
y={['performing_mm','delinquent_mm']}
type=grouped
yAxisTitle="R$ mm"
title="Performing vs Delinquent Receivables by Bucket (R$mm)"
/>

<DataTable data={fidc_aging_profile} rows=10>
  <Column id=bucket title="Bucket"/>
  <Column id=performing_mm title="Performing (R$mm)" fmt=num1/>
  <Column id=delinquent_mm title="Delinquent (R$mm)" fmt=num1/>
  <Column id=delinquent_pct title="Delinquent % of Bucket" fmt=num1/>
  <Column id=n_funds title="Funds" fmt=num0/>
</DataTable>

---

## Performing Receivables by Remaining Term — 12 Months

> The asset side's maturity profile: receivables that are **not** overdue, by
> days remaining. These ten columns have been ingested all along and were never
> shown. Weight drifting into `721-1080d` and `>1080d` is duration the book has
> taken on but has not yet had to collect.

<AreaChart
data={fidc_performing_aging}
x=period
y={['perf_30d','perf_60d','perf_90d','perf_120d','perf_150d','perf_180d','perf_360d','perf_720d','perf_1080d','perf_over1080d']}
type=stacked
yAxisTitle="R$ mm"
title="Performing Receivables by Remaining Term (R$mm)"
/>

<DataTable data={fidc_performing_aging} rows=6>
  <Column id=period title="Period"/>
  <Column id=perf_30d title="≤30d (R$mm)" fmt=num1/>
  <Column id=perf_90d title="61-90d (R$mm)" fmt=num1/>
  <Column id=perf_180d title="151-180d (R$mm)" fmt=num1/>
  <Column id=perf_360d title="181-360d (R$mm)" fmt=num1/>
  <Column id=perf_720d title="361-720d (R$mm)" fmt=num1/>
  <Column id=perf_over1080d title="Over 1080d (R$mm)" fmt=num1/>
  <Column id=inad_total_mm title="Total Delinquent (R$mm)" fmt=num1/>
  <Column id=n_funds title="Funds" fmt=num0/>
</DataTable>

---

## Tranche Performance — Promised vs Realised

> `pr_desemp_esperado` against `pr_desemp_real` at the latest period, folded into
> the four structural tranche classes (`classe_serie` is free text). **Medians,
> not means** — `schema.sql` warns these raw CVM percentage fields carry outliers
> up to 1.6e8, which would own any average. `Comparable` is the number of
> tranches that filed both figures and so could actually be compared.

<BarChart
data={fidc_tranche_performance}
x=tranche_class
y={['desemp_esperado_median','desemp_real_median']}
type=grouped
yAxisTitle="% (median)"
title="Promised vs Realised Performance by Tranche Class"
/>

<DataTable data={fidc_tranche_performance} rows=6>
  <Column id=tranche_class title="Tranche Class"/>
  <Column id=n_tranches title="Tranches" fmt=num0/>
  <Column id=n_funds title="Funds" fmt=num0/>
  <Column id=desemp_esperado_median title="Promised % (median)" fmt=num2/>
  <Column id=desemp_real_median title="Realised % (median)" fmt=num2/>
  <Column id=gap_median title="Gap pp (median)" fmt=num2/>
  <Column id=n_comparable title="Comparable" fmt=num0/>
  <Column id=underperforming_pct title="Underperforming %" fmt=num1/>
</DataTable>

---

## Promised vs Realised — 24 Months

<LineChart
data={fidc_tranche_trend}
x=period
y={['esperado_median','real_median']}
yAxisTitle="% (median)"
title="Universe Median: Promised vs Realised Tranche Performance"
/>

<LineChart
  data={fidc_tranche_trend}
  x=period
  y=underperforming_pct
  yAxisTitle="% of comparable tranches"
  title="Share of Tranches Below Their Promised Performance"
/>

---

## Tranches Missing Their Target — Largest Funds

> Individual series where realised fell short of promised at the latest period,
> ordered by fund size rather than by gap. Sorting by worst gap would rank the
> dirtiest surviving numbers first; sorting by AUM ranks the ones that matter.
> `Rows Excluded` reports how many latest-period tranche filings fell outside the
> plausibility band (|value| ≤ 1000%) applied for display — the filter's cost is
> on screen, and nothing was rescaled to fit.

<DataTable data={fidc_tranche_underperformers} rows=15 search=true>
  <Column id=fund_name title="Fund"/>
  <Column id=classe_serie title="Series (as filed)"/>
  <Column id=pl_mm title="AUM (R$mm)" fmt=num1/>
  <Column id=desemp_esperado title="Promised %" fmt=num2/>
  <Column id=desemp_real title="Realised %" fmt=num2/>
  <Column id=gap title="Gap pp" fmt=num2/>
  <Column id=rentab_mes title="Return in Month %" fmt=num2/>
  <Column id=inadimpl_pct title="Fund Delinq %" fmt=num1/>
  <Column id=n_excluded_outliers title="Rows Excluded by Band" fmt=num0/>
</DataTable>

---

## Subordination Structure — Largest FIDCs

> Senior versus subordinated quotas for the twelve largest FIDCs with tranche
> filings, from `fidc_subordination_trend()`. **This is a quota-count ratio, not
> a value-weighted one**: the function divides `qt_cota`, so it equals a true
> subordination level only where senior and subordinated quotas share a unit
> price. Read it as capital-structure shape, not as loss absorption in reais.

<DataTable data={fidc_subordination_top} rows=12>
  <Column id=fund_name title="Fund"/>
  <Column id=pl_mm title="AUM (R$mm)" fmt=num1/>
  <Column id=n_senior_series title="Senior Series" fmt=num0/>
  <Column id=n_subordinada_series title="Subordinated Series" fmt=num0/>
  <Column id=qt_senior_mm title="Senior Quotas (mm)" fmt=num2/>
  <Column id=qt_subordinada_mm title="Subord. Quotas (mm)" fmt=num2/>
  <Column id=subordination_pct title="Subordination % (of quotas)" fmt=num1/>
  <Column id=inadimpl_pct title="Delinq %" fmt=num1/>
</DataTable>

---

## Subordination Over Time — Largest FIDC

> One fund, tracked for 24 months. A subordination ratio only means something
> inside a single capital structure, so averaging it across funds of different
> sizes would describe no actual deal. A ratio falling while delinquency rises is
> the combination worth investigating: the cushion thinning as it is needed most.

<LineChart
  data={fidc_subordination_trend}
  x=period
  y=subordination_pct
  yAxisTitle="% of quotas"
  title="Subordinated Share of Quotas — Largest FIDC"
/>

<DataTable data={fidc_subordination_trend} rows=6>
  <Column id=period title="Period"/>
  <Column id=fund_name title="Fund"/>
  <Column id=n_senior_series title="Senior Series" fmt=num0/>
  <Column id=n_subordinada_series title="Subordinated Series" fmt=num0/>
  <Column id=qt_senior_mm title="Senior Quotas (mm)" fmt=num2/>
  <Column id=qt_subordinada_mm title="Subord. Quotas (mm)" fmt=num2/>
  <Column id=subordination_pct title="Subordination % (of quotas)" fmt=num1/>
</DataTable>

---

## Tranche Flows — Captação vs Resgate

> Money into and out of FIDC tranches, from `cvm_fidc_tranche_flows` (tab X_4).
> Both legs are plotted as filed, positive; `Net Flow` carries the sign. A month
> with no filing is blank, never zero — "no data" and "no flow" are different
> facts.

<BarChart
data={fidc_tranche_flows}
x=period
y={['captacao_mm','resgate_mm']}
type=grouped
yAxisTitle="R$ mm"
title="Subscriptions vs Redemptions by Month (R$mm)"
/>

<LineChart
  data={fidc_tranche_flows}
  x=period
  y=net_flow_mm
  yAxisTitle="R$ mm"
  title="Net Tranche Flow (R$mm)"
/>

<DataTable data={fidc_tranche_flows} rows=6>
  <Column id=period title="Period"/>
  <Column id=captacao_mm title="Captação (R$mm)" fmt=num1/>
  <Column id=resgate_mm title="Resgate (R$mm)" fmt=num1/>
  <Column id=net_flow_mm title="Net Flow (R$mm)" fmt=num1/>
  <Column id=outros_mm title="Unclassified (R$mm)" fmt=num1/>
  <Column id=n_funds title="Funds" fmt=num0/>
</DataTable>

---

## Operation Types as Filed — Latest Period

> The raw `tp_oper` values behind the split above. Captação and resgate are
> matched on the `CAPT` / `RESG` substrings — the same rule
> `fidc_flow_vs_delinquency()` uses — and CVM's vocabulary has drifted across
> years. Anything landing in `(não classificado)` is the signal that the rule has
> stopped catching everything, which is exactly why the raw values are printed
> instead of only the tidy two-way split.

<DataTable data={fidc_flows_by_oper} rows=10>
  <Column id=tp_oper title="tp_oper (as filed)"/>
  <Column id=leg title="Classified As"/>
  <Column id=vl_mm title="Volume (R$mm)" fmt=num1/>
  <Column id=n_funds title="Funds" fmt=num0/>
  <Column id=n_classes title="Series" fmt=num0/>
  <Column id=n_rows title="Rows" fmt=num0/>
</DataTable>

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
