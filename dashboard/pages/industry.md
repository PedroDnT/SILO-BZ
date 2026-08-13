---
title: Industry Structure
---

<!--
  The shape of the Brazilian fund industry as a whole: size, concentration,
  formation, investor base, and the composition by conformed asset class.

  Every number on this page comes from an analytical RPC that already existed and
  had no caller:
    industry_aum_trend()          09_analytical_functions.sql
    market_concentration()        09_analytical_functions.sql
    new_funds_per_period()        09_analytical_functions.sql
    quotaholder_trend()           09_analytical_functions.sql
    asset_class_performance()     14_ranking_functions.sql
    quotaholder_trend_by_class()  14_ranking_functions.sql
  The last two run over dim_fund_category (13_dim_classification.sql), which
  conforms five heterogeneous CVM families onto one asset_class axis.

  FIP AND FIAGRO ARE READ AT SOURCE. Both are otherwise only visible as an
  anonymous slice of an aggregate, so each gets its own section built directly
  on cvm_fip_periodic and cvm_fiagro_mensal — including FIAGRO's vl_inadimpl,
  which no aggregate view exposes for it.

  GRAIN WARNINGS, none of them smoothed over:
    * FIP reports YEARLY (inf_trimestral to 2023, inf_quadrimestral from 2024)
      and fact_fund_monthly maps it to 31-DEC of the reporting year — a date in
      the FUTURE for most of the calendar year. Anything that resolves "the
      latest period" as max(period) therefore lands on a FIP-only date. That is
      why the class snapshot uses each class's OWN latest period (and prints it).
    * captc_mes / resg_mes exist for FI only, so "net flow" is an FI number.
    * nr_cotst is absent for FIDC and FIP entirely.
    * pct_yield_mes is populated for FII only, so median yield is blank for every
      other class by construction — it is NOT a cross-class return comparison.
    * CVM publishes monthly datasets 1-2 months in arrears; the newest month or
      two are legitimately thin, not broken.

  ZERO-ROW RULE: every source is driven from a generate_series spine or a literal
  driver list with the RPC LEFT JOINed on, so none can return zero rows — which
  would write a zero-byte parquet and kill the Evidence build. Absent data
  renders blank.
-->

```sql industry_aum_trend
select * from supabase.industry_aum_trend
```

```sql industry_concentration
select * from supabase.industry_concentration
```

```sql industry_new_funds
select * from supabase.industry_new_funds
```

```sql industry_quotaholders
select * from supabase.industry_quotaholders
```

```sql industry_asset_class
select * from supabase.industry_asset_class
```

```sql industry_class_latest
select * from supabase.industry_class_latest
```

```sql industry_quotaholder_by_class
select * from supabase.industry_quotaholder_by_class
```

```sql industry_fip
select * from supabase.industry_fip
```

```sql industry_fiagro
select * from supabase.industry_fiagro
```

# Industry Structure

> How big the industry is, how concentrated, how fast it forms new vehicles, and
> who owns it — across all five CVM fund families, with FIP and FIAGRO shown by
> name rather than buried in an aggregate.

---

## Industry AUM by Fund Family

> Net assets summed per family per month. FIP contributes only in the month its
> yearly filing maps to (December), so its line is a step, not a trend.

<AreaChart
data={industry_aum_trend}
x=period
y={['fi_aum_bn','fidc_aum_bn','fii_aum_bn','fiagro_aum_bn','fip_aum_bn']}
yAxisTitle="AUM (R$ bn)"
title="Industry AUM by Family — Last 36 Months"
/>

---

## FI Net Flow

> Subscriptions minus redemptions. `captc_mes` and `resg_mes` are FI-only columns
> in `fact_fund_monthly`, so this is the open-ended fund industry alone — the
> other families report no flow at all and are omitted rather than shown as zero.

<LineChart
data={industry_aum_trend}
x=period
y=fi_net_flow_bn
yAxisTitle="Net flow (R$ bn)"
title="FI Net Flow per Month"
/>

---

## Concentration

> HHI on the 0–10,000 scale (sum of squared AUM shares × 10,000) plus top-N share
> of AUM, each family measured at **its own latest reported period** — shown in
> the Period column, because FIP's yearly grain means the families are not all
> as-of the same date.
>
> As a rule of thumb an HHI above 2,500 is a concentrated market; below 1,500 is
> not. All five families are listed even when a family has no data.

<DataTable data={industry_concentration}>
  <Column id=family title="Fund Family"/>
  <Column id=period title="Period"/>
  <Column id=n_funds title="Funds" fmt=num0/>
  <Column id=hhi title="HHI (0–10,000)" fmt=num0/>
  <Column id=top5_pct title="Top 5 Share (%)" fmt=num1/>
  <Column id=top10_pct title="Top 10 Share (%)" fmt=num1/>
  <Column id=top20_pct title="Top 20 Share (%)" fmt=num1/>
</DataTable>

---

## Fund Formation

> Count of funds whose **first appearance in CVM's data** falls in each month.
> That is a proxy for launch, not a registration date: a fund that existed before
> the ingested history begins looks new in the first month of coverage, so read
> the left edge of the series with care.

<BarChart
data={industry_new_funds}
x=period
y={['fi_new','fidc_new','fii_new','fiagro_new','fip_new']}
type=stacked
yAxisTitle="New funds"
title="First-Reported Funds per Month"
/>

---

## Investor Base

> Total quotaholders (`nr_cotst`). **FIDC and FIP report no quotaholder count at
> all** in CVM's files, so the total is a total of what exists — not an
> industry-wide investor count. Counts are in millions.

<LineChart
data={industry_quotaholders}
x=period
y={['fi_cotistas_mm','fii_cotistas_mm','fiagro_cotistas_mm']}
yAxisTitle="Quotaholders (millions)"
title="Quotaholders by Family — Last 36 Months"
/>

---

## Composition by Asset Class

> `dim_fund_category` conforms the five families onto one axis: FI splits into
> Fixed Income / Equity / Multimarket / Other FI on the registry's `tp_fundo`
> label, and each other family maps whole (FIDC → Structured Credit, FII → Real
> Estate, FIAGRO → Agribusiness, FIP → Private Equity). Funds whose registry row
> has not been ingested fall into **Other FI**, so that bucket is a coverage
> artefact as much as a category.

<AreaChart
data={industry_asset_class}
x=period
y=aum_bn
series=asset_class
yAxisTitle="AUM (R$ bn)"
title="AUM by Conformed Asset Class — Last 24 Months"
/>

---

## Asset Class Snapshot

> Each class at **its own latest period** — the Period column says which, and the
> rows are therefore not necessarily as-of the same date. Median yield is blank
> outside Real Estate because `pct_yield_mes` is an FII-only field.

<DataTable data={industry_class_latest} rows=9>
  <Column id=asset_class title="Asset Class"/>
  <Column id=period title="Period"/>
  <Column id=n_funds title="Funds" fmt=num0/>
  <Column id=aum_bn title="AUM (R$ bn)" fmt=num1/>
  <Column id=net_flow_bn title="Net Flow (R$ bn)" fmt=num2/>
  <Column id=cotistas_mm title="Quotaholders (mm)" fmt=num2/>
  <Column id=median_yield_pct title="Median Yield (%)" fmt=num2/>
</DataTable>

---

## Investor Growth by Asset Class

> Average quotaholders per fund — retail reach per vehicle rather than raw
> headcount. Structured Credit and Private Equity are blank throughout because
> their source files carry no quotaholder count.

<LineChart
data={industry_quotaholder_by_class}
x=period
y=avg_cotistas_per_fund
series=asset_class
yAxisTitle="Avg quotaholders per fund"
title="Average Quotaholders per Fund by Class"
/>

---

## FIP — Private Equity (yearly grain)

> Read directly from `cvm_fip_periodic`, whose natural key is
> `(cnpj, doc_type, period_year)`. CVM changed the filing from **inf_trimestral**
> (through 2023) to **inf_quadrimestral** (2024 onward) — the Doc Types column
> shows which applied in each year.
>
> `Funds w/ PL` is the honest denominator: a FIP can file without a net-assets
> figure, and those funds are counted as filers but contribute nothing to the AUM
> column.

<BarChart
data={industry_fip}
x=period_year
y=total_pl_bn
yAxisTitle="Net assets (R$ bn)"
title="FIP Net Assets by Reporting Year"
/>

<DataTable data={industry_fip} rows=10>
  <Column id=period_year title="Year" fmt=num0/>
  <Column id=doc_types title="Doc Types"/>
  <Column id=n_funds title="Funds Filing" fmt=num0/>
  <Column id=n_funds_with_pl title="Funds w/ PL" fmt=num0/>
  <Column id=total_pl_bn title="Net Assets (R$ bn)" fmt=num1/>
  <Column id=n_reports title="Reports" fmt=num0/>
</DataTable>

---

## FIAGRO — Agribusiness (monthly grain)

> Read directly from `cvm_fiagro_mensal`, including `vl_inadimpl` — FIAGRO
> carries a delinquency figure like FIDC does, and no aggregate view exposes it.
>
> **Coverage:** CVM's FIAGRO monthly file only begins **2025-05**. Earlier months
> are empty because the dataset did not exist, not because the pipeline failed.

<LineChart
data={industry_fiagro}
x=period
y=pl_bn
yAxisTitle="Net assets (R$ bn)"
title="FIAGRO Net Assets per Month"
/>

<DataTable data={industry_fiagro} rows=12>
  <Column id=period title="Month"/>
  <Column id=n_funds title="Funds" fmt=num0/>
  <Column id=pl_bn title="Net Assets (R$ bn)" fmt=num2/>
  <Column id=inadimpl_mm title="Delinquent (R$ mm)" fmt=num1/>
  <Column id=inadimpl_pct title="Delinquency (%)" fmt=num2/>
  <Column id=cotistas title="Quotaholders" fmt=num0/>
</DataTable>

> Who administers and manages these funds is on [Managers](/managers); whether
> the underlying slices actually landed is on [Pipeline Ops](/ops).
