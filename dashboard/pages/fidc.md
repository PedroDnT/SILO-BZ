---
title: FIDC Credit Monitor
hide_title: true
sidebar_position: 8
---

<!--
  FIDC = receivables funds. ASSET SIDE: cvm_fidc_aging (tab_VI), twenty columns in two
  bands of ten: vl_prazo_* (days REMAINING, still performing) and vl_inad_* (days
  already overdue). LIABILITY SIDE: cvm_fidc_tranche (tabs X_2/X_3/X_6) and
  cvm_fidc_tranche_flows (X_4).
  Caveats:
  * pr_desemp_esperado / pr_desemp_real / vl_rentab_mes are raw CVM percentages with
    garbage outliers (up to 1.6e8, per schema.sql), so every aggregate is a MEDIAN; the
    one applied band (per-tranche table) prints the count of rows it removed.
  * subordination_ratio (fidc_subordination_trend()) is built from qt_cota, QUOTA
    COUNTS, not value; it equals a value-weighted level only when senior and
    subordinated quotas share a unit price. By count it clusters near 100% because
    subordinated quotas are issued in far larger quantity at a far lower unit price.
  * The senior/subordinated split uses a substring match: the old prefix match
    (classe_serie ILIKE 'Senior%') missed every CVM-175-era (2025+) filing
    ("Subclasse Senior ...", "Classe Sênior ..."; 0 of ~10,700 rows matched). Ratios
    outside [0%, 100%] (dirty TAB_X_QT_COTA, up to 6.9e13) are NULL, not fabricated.
  * pr_desemp_esperado is genuinely 0.00 for about half of tranche filings (verified
    against a live CVM file), so a universe median near 0% is real, not a parsing bug.
  * Delinquency above 100% is real and expected for distressed funds, not capped.
    Columns are named *_num1 because Evidence multiplies a `*_pct` column by 100.
  * Months with no filing render blank, not zero (CVM publication lag).
  * CONCENTRATION (migration 38): cvm_fidc_setor (sum one level, never parents with
    children), cvm_fidc_scr (tab X, 2023-10+), cvm_fidc_sacado (tab VIII, 25 largest
    debtors as ANONYMIZED ranks; ~2% of funds file a top-25 sum above their tab II
    total, shown as filed), cvm_fidc_cedente (tab I, named originators; PR_CEDENTE
    is dirty, ~9% of slots above 100, read only inside [0,100] with the count printed).
  Section order: asset side (how bad, who, which buckets) before liability side.
  The "Delinquency > 5% and AUM > R$1mm" table was dropped: it duplicated
  fraud_screen_zombie_growth on /suspicious, so that screen has ONE definition.
-->

-->

```sql delinquency_trend
select * from supabase.delinquency_trend
```

```sql top_delinquent
select * from supabase.top_delinquent
```

```sql fidc_drivers_summary
select * from supabase.fidc_drivers_summary
```

```sql fidc_drivers_consistent
select * from supabase.fidc_drivers_consistent
```

```sql fidc_drivers_masked
select * from supabase.fidc_drivers_masked
```

```sql fidc_drivers_denominator
select * from supabase.fidc_drivers_denominator
```

```sql fidc_drivers_all
select * from supabase.fidc_drivers_all
```

```sql fidc_stopped_reporting
select * from supabase.fidc_stopped_reporting
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

```sql fidc_sector_mix
select * from supabase.fidc_sector_mix
```

```sql fidc_scr_ladder
select * from supabase.fidc_scr_ladder
```

```sql fidc_concentration_top
select * from supabase.fidc_concentration_top
```

```sql fidc_cedentes_top
select * from supabase.fidc_cedentes_top
```

# FIDC Credit Monitor

> Asset side first (aging), then the liability side that absorbs it (tranches); CVM, monthly, 1 to 2 months lag. Carry three things: the sector rate **says nothing about distribution**; promised-versus-realised figures are **medians** (CVM's raw percentages carry outliers up to 1.6e8); subordination ratios use **quota counts, not value**. Screens: [Suspicious Deal Screens](/suspicious). Comparable receivables: [Securitization](/securit).

---

## Sector Delinquency: 24 Months

> Overdue receivables as a share of net assets, across FIDCs that filed both an aging table and a monthly report (CVM, monthly, 1 to 2 months lag). FIAGRO is on [Industry Structure](/industry).

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

## Most Delinquent FIDCs: Latest Period

> The twenty worst rates among funds above R$1mm net assets, at the newest period the aging table covers (CVM, monthly, 1 to 2 months lag). Ranked by rate, so read net assets alongside it. Persistent cases: [Suspicious Deal Screens](/suspicious).

<DataTable data={top_delinquent} rows=20>
  <Column id=fund_name title="Fund"/>
  <Column id=period title="Period"/>
  <Column id=pl_mm title="Net Assets (R$mm)" fmt=num1/>
  <Column id=inad_mm title="Delinquent (R$mm)" fmt=num1/>
  <Column id=delinquency_num1 title="Delinquency (%)" fmt=num1/>
</DataTable>

---

## Where Delinquency Worsened: and Why

> The rate is `overdue (R$) ÷ net assets (R$)`, so it also moves when net assets move. Each fund is scored on **both** over the last twelve complete months (CVM, monthly, 1 to 2 months lag), first observation against last. "Value moved" is **|Δ R$| ≥ R$1mm**, "rate moved" is **|Δ| ≥ 1 p.p.**; a fund needs **≥ 6 observations**, and tables keep funds with **≥ R$10mm** of latest net assets.

| Driver                    | What happened                     | Read it as                                                       |
| ------------------------- | --------------------------------- | ---------------------------------------------------------------- |
| **Consistent worsening**  | overdue R$ **up** and rate **up** | credit deteriorated: the cleanest signal                        |
| **Value up, rate masked** | overdue R$ up, rate flat or down  | net assets grew with it: real deterioration the rate hides       |
| **Denominator only**      | rate up, overdue R$ flat or down  | net assets shrank: amortisation or outflow, not new delinquency |
| Improvement / stable      | n/a                               | n/a                                                              |

<BigValue data={fidc_drivers_summary} value=n_active title="Funds Scored (≥ R$10mm)" fmt=num0/>
<BigValue data={fidc_drivers_summary} value=n_consistent title="Consistent Worsening" fmt=num0/>
<BigValue data={fidc_drivers_summary} value=n_masked title="Value Up, Rate Masked" fmt=num0/>
<BigValue data={fidc_drivers_summary} value=n_denominator title="Denominator Only" fmt=num0/>
<BigValue data={fidc_drivers_summary} value=consistent_delta_bn title="New Overdue, Consistent (R$bn)" fmt=num1/>
<BigValue data={fidc_drivers_summary} value=masked_delta_bn title="New Overdue, Masked (R$bn)" fmt=num1/>

<ScatterPlot
  data={fidc_drivers_all}
  x=delta_pp_num1
  y=delta_mm
  series=driver
  xAxisTitle="Δ delinquency rate (p.p.)"
  yAxisTitle="Δ overdue value (R$mm)"
  title="Every Scored FIDC — Δ Value vs Δ Rate, Coloured by Driver"
/>

### Consistent worsening: overdue value and rate both rose

> Ranked by the **R$ change**, the more robust of the two. A rate above 100 % means overdue receivables exceed the fund's own net assets.

<DataTable data={fidc_drivers_consistent} rows=25>
  <Column id=delta_mm title="Δ Overdue (R$mm)" fmt=num1/>
  <Column id=rate_start_num1 title="Rate Start (%)" fmt=num1/>
  <Column id=rate_end_num1 title="Rate End (%)" fmt=num1/>
  <Column id=delta_pp_num1 title="Δ Rate (pp)" fmt=num1/>
  <Column id=nav_end_mm title="Net Assets (R$mm)" fmt=num1/>
  <Column id=n_months title="Months" fmt=num0/>
  <Column id=fund_name title="Fund"/>
</DataTable>

### Real deterioration the rate hides

> Overdue value rose by at least R$1mm while the rate barely moved or fell, because net assets grew (new funding dilutes a rate).

<DataTable data={fidc_drivers_masked} rows=15>
  <Column id=delta_mm title="Δ Overdue (R$mm)" fmt=num1/>
  <Column id=delta_nav_mm title="Δ Net Assets (R$mm)" fmt=num1/>
  <Column id=rate_start_num1 title="Rate Start (%)" fmt=num1/>
  <Column id=rate_end_num1 title="Rate End (%)" fmt=num1/>
  <Column id=delta_pp_num1 title="Δ Rate (pp)" fmt=num1/>
  <Column id=fund_name title="Fund"/>
</DataTable>

### False positives: the rate rose only because net assets shrank

> Overdue value did not rise and the rate still climbed: contraction or amortisation, not new delinquency.

<DataTable data={fidc_drivers_denominator} rows=15>
  <Column id=delta_pp_num1 title="Δ Rate (pp)" fmt=num1/>
  <Column id=delta_mm title="Δ Overdue (R$mm)" fmt=num1/>
  <Column id=delta_nav_mm title="Δ Net Assets (R$mm)" fmt=num1/>
  <Column id=rate_end_num1 title="Rate End (%)" fmt=num1/>
  <Column id=fund_name title="Fund"/>
</DataTable>

### Stopped reporting

> A month not filed is **absent, never zero**, so a fund that quit drops out of every rate above rather than reading as clean. These filed at least six months of the window, then went two or more months quiet while the family kept filing.

<DataTable data={fidc_stopped_reporting} rows=25>
  <Column id=last_month title="Last Filing"/>
  <Column id=months_missing title="Months Missing" fmt=num0/>
  <Column id=nav_end_mm title="Last Net Assets (R$mm)" fmt=num1/>
  <Column id=rate_end_num1 title="Last Rate (%)" fmt=num1/>
  <Column id=fund_name title="Fund"/>
</DataTable>

### Every scored fund

<DataTable data={fidc_drivers_all} rows=20 search=true>
  <Column id=driver title="Driver"/>
  <Column id=delta_mm title="Δ Overdue (R$mm)" fmt=num1/>
  <Column id=delta_pp_num1 title="Δ Rate (pp)" fmt=num1/>
  <Column id=rate_end_num1 title="Rate End (%)" fmt=num1/>
  <Column id=nav_end_mm title="Net Assets (R$mm)" fmt=num1/>
  <Column id=n_months title="Months" fmt=num0/>
  <Column id=fund_name title="Fund"/>
</DataTable>

> **What this cannot tell you.** CVM's monthly FIDC file carries no portfolio composition (no sector, no debtor, no guarantee), so nothing here says _whose_ receivables went overdue or whether a subordinated tranche absorbs the loss first. `vl_inadimpl` is the **overdue** value, not a realised loss: no provisions or recovery, and a figure can sit unchanged for months then jump on a revaluation. Δ R$ is nominal. Filed only from **2025-01**.

---

## Delinquency by Aging Bucket: 12 Months

> The overdue band (`vl_inad_*`) by days past due (CVM, monthly, 1 to 2 months lag). Weight moving toward 360d and beyond is deterioration a flat headline rate hides.

<AreaChart
data={aging_buckets}
x=period
y={['inad_30d','inad_60d','inad_90d','inad_180d','inad_360d','inad_over1080d']}
type=stacked
yAxisTitle="R$mm"
  title="Delinquency by Aging Bucket (R$mm)"
/>

---

## Performing vs Delinquent: Both Bands, Latest Period

> Tab VI on one axis: `vl_prazo_*` (performing, days **to** maturity) against `vl_inad_*` (delinquent, days **past** due) (CVM, monthly, 1 to 2 months lag). The ten buckets are fixed by the form, so an empty bar is an empty bucket, not a missing one.

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

## Performing Receivables by Remaining Term: 12 Months

> Receivables that are **not** overdue, by days remaining (CVM, monthly, 1 to 2 months lag). Weight drifting into `721-1080d` and `>1080d` is duration not yet collected.

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

## What the Receivables Are: Sector Mix, Latest Period

> Tab II files receivables by sector, a **hierarchy** of eleven lettered sectors with numbered members; this chart sums the lettered level only, so nothing is counted twice (CVM, monthly, 1 to 2 months lag). The share is of the summed sector lines, **not of each fund's filed TOTAL**, which can differ and would show as a phantom sector. Numbered detail: `api.fidc_portfolio`.

<BarChart
  data={fidc_sector_mix}
  x=sector
  y=value_bn
  swapXY=true
  xAxisTitle="R$bn"
  title="Receivables by Sector, All FIDCs (R$bn)"
/>

<DataTable data={fidc_sector_mix} rows=11>
  <Column id=sector title="Sector (tab II)"/>
  <Column id=value_bn title="Receivables (R$bn)" fmt=num1/>
  <Column id=share_num1 title="Share of Sector Lines (%)" fmt=num1/>
  <Column id=n_funds title="Funds Filing" fmt=num0/>
</DataTable>

---

## How the Receivables Are Graded: SCR Ladder, Latest Period

> Tab X files the same receivables under BACEN SCR grades **AA..H** twice, by **debtor** and by **operation**: two views of one book, each summing to the graded total (CVM, monthly, 1 to 2 months lag). `H` is what a provisioning rule treats as near-total loss. **Tab X exists from 2023-10 only.**

<BarChart
data={fidc_scr_ladder}
x=grade
y={['by_debtor_bn', 'by_operation_bn']}
type=grouped
xAxisTitle="SCR grade"
yAxisTitle="R$bn"
  title="Receivables by SCR Grade — by Debtor vs by Operation (R$bn)"
/>

<DataTable data={fidc_scr_ladder} rows=9>
  <Column id=grade title="Grade"/>
  <Column id=by_debtor_bn title="By Debtor (R$bn)" fmt=num1/>
  <Column id=by_operation_bn title="By Operation (R$bn)" fmt=num1/>
  <Column id=debtor_share_num1 title="Share, by Debtor (%)" fmt=num1/>
</DataTable>

---

## Debtor Concentration: Books Most Exposed to One Sacado

> Tab VIII publishes each fund's **25 largest debtors as anonymized ranks**, a value per rank and nothing else, so this says _how concentrated_ a book is, never _in whom_ (CVM, monthly, 1 to 2 months lag). The ratio is the rank-1 value (and the sum of filed ranks) over the tab II receivables total of the same filing. **The two tabs do not share a base for every fund**: in 2026-07 rank-1 alone exceeded the total for 0.5% of funds, the top-25 sum for 1.9%. Shown as filed, **not capped**. `Ranks Filed` = 1 means a single debtor. Floor: receivables ≥ R$10mm.

<DataTable data={fidc_concentration_top} rows=20 search=true>
  <Column id=fund_name title="Fund"/>
  <Column id=receivables_mm title="Receivables (R$mm)" fmt=num1/>
  <Column id=pl_mm title="Net Assets (R$mm)" fmt=num1/>
  <Column id=top1_mm title="Largest Debtor (R$mm)" fmt=num1/>
  <Column id=top1_num1 title="Largest Debtor / Receivables (%)" fmt=num1/>
  <Column id=top25_num1 title="Top-25 / Receivables (%)" fmt=num1/>
  <Column id=n_ranks title="Ranks Filed" fmt=num0/>
</DataTable>

---

## Named Originators: Who Sells Receivables to the Most Funds

> Tab I is the one concentration table **with identities**: each fund names the nine largest cedentes of each block by CPF/CNPJ, checksum-verified at ingest (CVM, monthly, 1 to 2 months lag). Block A is receivables acquired _with_ retention of risks and benefits by the originator, block B _without_. This counts **funds per originator** and never adds shares across funds, since each share is a percent of one fund's block. Names appear only for listed companies, keyed by CNPJ. **The share field is dirty as filed**: 9% of slots exceed 100 (one reads 19,771); `Max Share` reads only 0 to 100, `Outlier Slots` counts the rest.

<DataTable data={fidc_cedentes_top} rows=20 search=true>
  <Column id=originator title="Originator (name if listed)"/>
  <Column id=cedente_id title="CPF/CNPJ"/>
  <Column id=tickers title="Tickers"/>
  <Column id=n_funds title="Funds Buying" fmt=num0/>
  <Column id=n_funds_block_a title="of which Block A" fmt=num0/>
  <Column id=n_rank1 title="Funds Where #1" fmt=num0/>
  <Column id=max_share_num1 title="Max Share of a Block (%)" fmt=num1/>
  <Column id=n_share_outliers title="Outlier Slots" fmt=num0/>
</DataTable>

---

## Tranche Performance: Promised vs Realised

> `pr_desemp_esperado` against `pr_desemp_real` at the latest period (CVM, monthly, 1 to 2 months lag), folded into four tranche classes (`classe_serie` is free text). **Medians, not means**: these raw percentages carry outliers up to 1.6e8. `Comparable` counts tranches that filed both figures.

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

> The same medians over 24 months, and the share of comparable tranches falling short.

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

## Tranches Missing Their Target: Largest Funds

> Series where realised fell short of promised at the latest period (CVM, monthly, 1 to 2 months lag), ordered by **fund size, not gap**, because the worst gap ranks the dirtiest numbers first. `Rows Excluded` counts filings outside the display band (|value| ≤ 1000%); nothing was rescaled.

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

## Subordination Structure: Largest FIDCs

> Senior versus subordinated quotas for the twelve largest FIDCs with tranche filings (CVM, monthly, 1 to 2 months lag). **A quota-count ratio, not value-weighted**: it divides `qt_cota`, so it matches a true subordination level only where senior and subordinated quotas share a unit price. Read it as capital-structure shape, not loss absorption in reais.

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

> One fund tracked for 24 months; the ratio only means something inside a single capital structure, so it is never averaged across funds. A falling ratio with rising delinquency is the combination worth investigating.

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

## Tranche Flows: Captação vs Resgate

> Money into and out of FIDC tranches (tab X_4; CVM, monthly, 1 to 2 months lag). Both legs are positive as filed; `Net Flow` carries the sign; a month with no filing is blank, never zero. Zombie-growth screen: [Suspicious Deal Screens](/suspicious).

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

> The raw `tp_oper` values behind that split, matched on the `CAPT` / `RESG` substrings; CVM's vocabulary has drifted. Anything in `(não classificado)` means the rule stopped catching everything.

<DataTable data={fidc_flows_by_oper} rows=10>
  <Column id=tp_oper title="tp_oper (as filed)"/>
  <Column id=leg title="Classified As"/>
  <Column id=vl_mm title="Volume (R$mm)" fmt=num1/>
  <Column id=n_funds title="Funds" fmt=num0/>
  <Column id=n_classes title="Series" fmt=num0/>
  <Column id=n_rows title="Rows" fmt=num0/>
</DataTable>
