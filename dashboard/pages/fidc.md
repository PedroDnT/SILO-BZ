---
title: FIDC Credit Monitor
---

<!--
  FIDC = receivables funds. Two grains matter and this page shows both:

    ASSET SIDE  — cvm_fidc_aging (CVM tab_VI). Twenty columns, in two bands of
      ten: vl_prazo_* (band A, days REMAINING to maturity — still performing)
      and vl_inad_* (band B, days ALREADY overdue). The dashboard originally read
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
      level only when senior and subordinated quotas share a unit price. This
      is also why, by count, subordination genuinely clusters near 100% for
      many funds even after the fix below: subordinated/junior quotas are
      typically issued in far larger quantity at a far lower unit price than
      senior quotas, so a headcount ratio overstates them relative to a
      value-weighted one.
    * fidc_subordination_trend()'s senior/subordinated split previously used a
      PREFIX match (classe_serie ILIKE 'Senior%'), which missed every
      CVM-175-era (2025+) filing — those are labelled "Subclasse Senior ..." /
      "Classe Sênior ...", not a bare "Senior ...". Verified against a live CVM
      file: 0 of ~10,700 rows matched. Fixed to a substring match. The prefix
      bug is also what zeroed "Senior Quotas" and, combined with dirty
      TAB_X_QT_COTA outliers in some historical months (raw values up to
      6.9e13 per schema.sql), produced subordination readings over 1000%; the
      ratio is now excluded (NULL, not fabricated) for any month where it
      would fall outside the valid [0%, 100%] range.
    * pr_desemp_esperado ("promised" performance) is genuinely 0.00 for roughly
      half of all tranche filings in the raw CVM data, spread across senior,
      mezanino, and subordinated series alike (verified against a live CVM
      file) — most likely tranches with no fixed target rather than a
      residual/floating return. A universe median landing at or near 0% is
      real, not a parsing bug.
    * Delinquency figures above 100% (a fund's overdue book exceeding its own
      net assets) are real and expected for severely distressed funds, not
      capped — that is the signal this page exists to surface. The *chart*
      showing ~210% for a table that reads 1.1% was not that: Evidence treats
      a column named `*_pct` as a 0–1 fraction and multiplies by 100. SQL
      already stores percentage points. Columns are named `*_num1` so the
      chart and the table share a scale.
    * FIDC ingestion has historically lagged (CVM publication delay); months with
      no filing render blank rather than zero.

  SECTION ORDER runs asset side (how bad, who, and in which buckets) before
  liability side (who absorbs it) — the deterioration is the finding and the
  capital structure is the consequence.

  DE-DUPLICATED: this page previously carried a "Delinquency > 5% and AUM >
  R$1mm" table (source high_delinq_growing.sql) that is the same screen as
  fraud_screen_zombie_growth on /suspicious — same latest period, same 5%
  threshold, same R$1mm floor, same columns. It has been dropped in favour of a
  link, so the screen has ONE definition on the site. high_delinq_growing.sql now
  has no caller and is a deletion candidate for the source owner.
-->

```sql delinquency_trend
select * from supabase.delinquency_trend
```

```sql top_delinquent
select * from supabase.top_delinquent
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

> Receivables funds are where credit deterioration shows up first and in the most
> detail: FIDCs file both an aging table for the loans they hold and a tranche
> table for the investors who bear the losses. This page reads the asset side
> first — the sector rate, the funds behind it, and which buckets the balance sits
> in — then the liability side that absorbs it.
>
> The sector rate is an aggregate and **says nothing about distribution**: it can
> sit flat while individual books fail. Every promised-versus-realised figure here
> is a **median**, because CVM's raw percentage fields carry outliers up to 1.6e8
> that would own any average, and the subordination ratios are built from **quota
> counts, not value**. Screens that flag specific patterns are on
> [Suspicious Deal Screens](/suspicious); the securitised-certificate market that
> buys similar receivables is on [Securitization](/securit).

---

## Sector Delinquency — 24 Months

> Overdue receivables as a share of net assets, across FIDCs that filed both an
> aging table and a monthly report. FIAGRO files a comparable `vl_inadimpl` figure
> and is charted on [Industry Structure](/industry).

<LineChart
  data={delinquency_trend}
  x=period
  y=delinquency_rate_num1
  yAxisTitle="Delinquency (%)"
  title="FIDC Sector Delinquency Rate"
/>

<DataTable data={delinquency_trend} rows=6>
  <Column id=period title="Period"/>
  <Column id=n_funds title="Funds" fmt=num0/>
  <Column id=total_inad_mm title="Total Delinquent (R$mm)" fmt=num1/>
  <Column id=delinquency_rate_num1 title="Delinquency (%)" fmt=num1/>
</DataTable>

---

## Most Delinquent FIDCs — Latest Period

> The twenty worst rates among funds with more than R$1mm in net assets, at the
> newest period the aging table covers. Ranked by rate, so small books with a bad
> ratio sort above large books with a moderate one — read the net-assets column
> alongside the rate. Funds where the pattern is not just a level but a persistent
> one are screened on [Suspicious Deal Screens](/suspicious).

<DataTable data={top_delinquent} rows=20>
  <Column id=fund_name title="Fund"/>
  <Column id=period title="Period"/>
  <Column id=pl_mm title="Net Assets (R$mm)" fmt=num1/>
  <Column id=inad_mm title="Delinquent (R$mm)" fmt=num1/>
  <Column id=delinquency_num1 title="Delinquency (%)" fmt=num1/>
</DataTable>

---

## Delinquency by Aging Bucket — 12 Months

> The overdue band (`vl_inad_*`) split by how long each balance has been past due.
> Weight moving rightward — out of the 30d bucket and into 360d and beyond — is
> deterioration that a flat headline rate hides, because a receivable that ages
> without being written off keeps the rate constant while the recovery prospect
> falls.

<AreaChart
data={aging_buckets}
x=period
y={['inad_30d','inad_60d','inad_90d','inad_180d','inad_360d','inad_over1080d']}
type=stacked
yAxisTitle="R$mm"
  title="Delinquency by Aging Bucket (R$mm)"
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
  y={['performing_mm', 'delinquent_mm']}
  type=grouped
  swapXY=true
  xAxisTitle="R$mm"
  title="Performing vs Delinquent Receivables by Bucket (R$mm)"
/>

<DataTable data={fidc_aging_profile} rows=10>
  <Column id=bucket title="Bucket"/>
  <Column id=performing_mm title="Performing (R$mm)" fmt=num1/>
  <Column id=delinquent_mm title="Delinquent (R$mm)" fmt=num1/>
  <Column id=delinquent_num1 title="Delinquent Share of Bucket (%)" fmt=num1/>
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
yAxisTitle="R$mm"
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
yAxisTitle="% (Median)"
title="Promised vs Realised Performance by Tranche Class"
/>

<DataTable data={fidc_tranche_performance} rows=6>
  <Column id=tranche_class title="Tranche Class"/>
  <Column id=n_tranches title="Tranches" fmt=num0/>
  <Column id=n_funds title="Funds" fmt=num0/>
  <Column id=desemp_esperado_median title="Promised (%, median)" fmt=num2/>
  <Column id=desemp_real_median title="Realised (%, median)" fmt=num2/>
  <Column id=gap_median title="Gap (pp, median)" fmt=num2/>
  <Column id=n_comparable title="Comparable" fmt=num0/>
  <Column id=underperforming_num1 title="Underperforming (%)" fmt=num1/>
</DataTable>

> The same two medians over 24 months, and the share of comparable tranches
> falling short, are below. A widening gap alongside a rising share is a sector
> promising more than the underlying book delivers.

<LineChart
data={fidc_tranche_trend}
x=period
y={['esperado_median','real_median']}
yAxisTitle="% (Median)"
title="Universe Median: Promised vs Realised Tranche Performance"
/>

<LineChart
  data={fidc_tranche_trend}
  x=period
  y=underperforming_num1
  yAxisTitle="% of Comparable Tranches"
  title="Share of Tranches Below Their Promised Performance"
/>

---

## Tranches Missing Their Target — Largest Funds

> Individual series where realised fell short of promised at the latest period,
> ordered by fund size rather than by gap. Sorting by worst gap would rank the
> dirtiest surviving numbers first; sorting by net assets ranks the ones that
> matter. `Rows Excluded` reports how many latest-period tranche filings fell
> outside the plausibility band (|value| ≤ 1000%) applied for display — the
> filter's cost is on screen, and nothing was rescaled to fit.

<DataTable data={fidc_tranche_underperformers} rows=15 search=true>
  <Column id=fund_name title="Fund"/>
  <Column id=classe_serie title="Series (as filed)"/>
  <Column id=pl_mm title="Net Assets (R$mm)" fmt=num1/>
  <Column id=desemp_esperado title="Promised (%)" fmt=num2/>
  <Column id=desemp_real title="Realised (%)" fmt=num2/>
  <Column id=gap title="Gap (pp)" fmt=num2/>
  <Column id=rentab_mes title="Return in Month (%)" fmt=num2/>
  <Column id=inadimpl_num1 title="Fund Delinquency (%)" fmt=num1/>
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
  <Column id=pl_mm title="Net Assets (R$mm)" fmt=num1/>
  <Column id=n_senior_series title="Senior Series" fmt=num0/>
  <Column id=n_subordinada_series title="Subordinated Series" fmt=num0/>
  <Column id=qt_senior_mm title="Senior Quotas (mm)" fmt=num2/>
  <Column id=qt_subordinada_mm title="Subord. Quotas (mm)" fmt=num2/>
  <Column id=subordination_num1 title="Subordination, of Quotas (%)" fmt=num1/>
  <Column id=inadimpl_num1 title="Delinquency (%)" fmt=num1/>
</DataTable>

> One fund tracked for 24 months below. A subordination ratio only means something
> inside a single capital structure, so averaging it across funds of different
> sizes would describe no actual deal. A ratio falling while delinquency rises is
> the combination worth investigating: the cushion thinning as it is needed most.

<LineChart
  data={fidc_subordination_trend}
  x=period
  y=subordination_num1
  yAxisTitle="% of Quotas"
  title="Subordinated Share of Quotas — Largest FIDC"
  fmt=num1
/>

<DataTable data={fidc_subordination_trend} rows=6>
  <Column id=period title="Period"/>
  <Column id=fund_name title="Fund"/>
  <Column id=n_senior_series title="Senior Series" fmt=num0/>
  <Column id=n_subordinada_series title="Subordinated Series" fmt=num0/>
  <Column id=qt_senior_mm title="Senior Quotas (mm)" fmt=num2/>
  <Column id=qt_subordinada_mm title="Subord. Quotas (mm)" fmt=num2/>
  <Column id=subordination_num1 title="Subordination, of Quotas (%)" fmt=num1/>
</DataTable>

---

## Tranche Flows — Captação vs Resgate

> Money into and out of FIDC tranches, from `cvm_fidc_tranche_flows` (tab X_4).
> Both legs are plotted as filed, positive; `Net Flow` carries the sign. A month
> with no filing is blank, never zero — "no data" and "no flow" are different
> facts. Rising subscriptions into a book whose delinquency is also rising is the
> pattern the zombie-growth screen on [Suspicious Deal Screens](/suspicious)
> isolates fund by fund.

<BarChart
data={fidc_tranche_flows}
x=period
y={['captacao_mm','resgate_mm']}
type=grouped
yAxisTitle="R$mm"
  title="Subscriptions vs Redemptions by Month (R$mm)"
/>

<LineChart
  data={fidc_tranche_flows}
  x=period
  y=net_flow_mm
  yAxisTitle="R$mm"
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

> The raw `tp_oper` values behind that split are below. Captação and resgate are
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
