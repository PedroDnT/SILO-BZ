---
title: Industry Structure
hide_title: true
sidebar_position: 1
---

<!--
  Size, concentration, formation, investor base and composition by asset class, from
  existing analytical RPCs (09 and 14) over dim_fund_category (13); FIP and FIAGRO are
  read at source (cvm_fip_periodic, cvm_fiagro_mensal).
  Grain: FIP is YEARLY, mapped to 31-DEC of the reporting year (a future date most of
  the year), so the class snapshot uses each class's OWN latest period. captc_mes and
  resg_mes are FI only; nr_cotst is absent for FIDC and FIP; pct_yield_mes is FII only.
  Zero-row rule: sources are a spine LEFT JOINed with the RPC, so none returns zero rows.
  Share chart: stacked100 breaks with a wide y list, so the SQL emits *_share_num1.
-->

```sql industry_aum_trend
select * from supabase.industry_aum_trend
```

```sql industry_concentration
select * from supabase.industry_concentration
```

```sql industry_asset_class
select * from supabase.industry_asset_class
```

```sql industry_class_latest
select * from supabase.industry_class_latest
```

```sql industry_new_funds
select * from supabase.industry_new_funds
```

```sql industry_quotaholders
select * from supabase.industry_quotaholders
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

> FI holds an order of magnitude more net assets than FIDC, FII, FIAGRO and FIP combined, and each family is concentrated in a few houses (CVM, monthly, 1 to 2 months lag). No cross-family return comparison is supported: net flow is FI only, quotaholders are absent for FIDC and FIP, and median yield is FII only. Houses: [Managers](/managers); landing: [Pipeline Ops](/ops).

---

## Industry Net Assets by Fund Family

> Net assets summed per family per month (CVM, monthly, 1 to 2 months lag). FIP lands only in December, so its line is a step. Two views, because FI fills a linear scale: share of total, and absolute with FI excluded.

> **The step at 2025-05 is FIAGRO entering the data, not the industry growing.** CVM's FIAGRO file begins May 2025 with **3 funds**, reaches 125 by September and 202 by December; per-family lines are unaffected.

<AreaChart
data={industry_aum_trend}
x=period
type=stacked
y={['fi_share_num1','fidc_share_num1','fii_share_num1','fiagro_share_num1','fip_share_num1']}
yAxisTitle="Share of Total Net Assets (%)"
title="Net Assets by Family — Last 36 Months (share of total)"
/>

<AreaChart
data={industry_aum_trend}
x=period
y={['fidc_aum_bn','fii_aum_bn','fiagro_aum_bn']}
yAxisTitle="Net Assets (R$bn)"
title="Net Assets by Family — Last 36 Months (ex-FI and ex-FIP, absolute)"
/>

> FIP is left off the absolute stack: its yearly filing would dwarf the other three in one month. Its yearly bars are below.

---

## Concentration

> HHI (0 to 10,000; sum of squared net-asset shares × 10,000) and top-N share, each family at **its own latest period** (Period column, since FIP is yearly). Rule of thumb: above 2,500 concentrated, below 1,500 not. All five families are listed even without data.

<DataTable data={industry_concentration}>
  <Column id=family title="Fund Family"/>
  <Column id=period title="Period"/>
  <Column id=n_funds title="Funds" fmt=num0/>
  <Column id=hhi title="HHI (0–10,000)" fmt=num0/>
  <Column id=top5_num1 title="Top 5 Share (%)" fmt=num1/>
  <Column id=top10_num1 title="Top 10 Share (%)" fmt=num1/>
  <Column id=top20_num1 title="Top 20 Share (%)" fmt=num1/>
</DataTable>

---

## Composition by Asset Class

> `dim_fund_category` conforms the five families onto one axis: FI splits by the registry's `tp_fundo`; FIDC is Structured Credit, FII Real Estate, FIAGRO Agribusiness, FIP Private Equity. Funds with no registry row fall into **Other FI**, a coverage artefact as much as a category (CVM, monthly, 1 to 2 months lag).

<AreaChart
  data={industry_asset_class}
  x=period
  y=aum_bn
  series=asset_class
  yAxisTitle="Net Assets (R$bn)"
  title="Net Assets by Conformed Asset Class — Last 24 Months"
/>

> Each class is at **its own latest period** (Period column). Median yield is blank outside Real Estate (`pct_yield_mes` is FII only), so it is **not** a cross-class return comparison. Rankings: [Performance](/performance).

<DataTable data={industry_class_latest} rows=9>
  <Column id=asset_class title="Asset Class"/>
  <Column id=period title="Period"/>
  <Column id=n_funds title="Funds" fmt=num0/>
  <Column id=aum_bn title="Net Assets (R$bn)" fmt=num2/>
  <Column id=net_flow_bn title="Net Flow (R$bn)" fmt=num2/>
  <Column id=cotistas_mm title="Quotaholders (mm)" fmt=num2/>
  <Column id=median_yield_num2 title="Median Yield (%)" fmt=num2/>
</DataTable>

---

## FI Net Flow

> Subscriptions minus redemptions (CVM, monthly, 1 to 2 months lag). `captc_mes` and `resg_mes` exist for FI only, so other families are omitted, not zero. Daily version: [FI Industry](/fi).

<BarChart
  data={industry_aum_trend}
  x=period
  y=fi_net_flow_bn
  yAxisTitle="Net Flow (R$bn)"
  title="FI Net Flow per Month"
/>

---

## Fund Formation

> Funds whose **first appearance in CVM's data** falls in each month (CVM, monthly): a proxy for launch, so the left edge of the series looks inflated.

<BarChart
data={industry_new_funds}
x=period
y={['fi_new', 'fidc_new', 'fii_new', 'fiagro_new']}
type=stacked
yAxisTitle="New Funds"
title="First-Reported Funds per Month — Monthly Filers"
/>

> **FIP is not on this chart:** it files yearly, so it stacked into a fake spike each January. See the FIP section below.

---

## Investor Base

> Total quotaholders (`nr_cotst`), in millions (CVM, monthly, 1 to 2 months lag). **FIDC and FIP report no quotaholder count**, so this totals what exists. It counts positions, not people.

<LineChart
data={industry_quotaholders}
x=period
y={['fi_cotistas_mm','fii_cotistas_mm','fiagro_cotistas_mm']}
yAxisTitle="Quotaholders (millions)"
title="Quotaholders by Family — Last 36 Months"
/>

> Average quotaholders per fund. Structured Credit, Private Equity and Agribusiness are blank because their files carry no count: measured 2026-08-28, `nr_cotst` is on 100% of FI rows, 99.9% of FII rows and **zero** FIDC, FIP or FIAGRO rows. Blank is CVM not publishing, never a failed load.

<LineChart
  data={industry_quotaholder_by_class}
  x=period
  y=avg_cotistas_per_fund
  series=asset_class
  yAxisTitle="Avg Quotaholders per Fund"
  title="Average Quotaholders per Fund by Class"
/>

---

## FIP: Private Equity (Yearly Grain)

> Read from `cvm_fip_periodic`, key `(cnpj, doc_type, period_year)` (CVM, yearly). The filing changed from **inf_trimestral** (through 2023) to **inf_quadrimestral** (2024 onward). `Funds w/ Net Assets` is the honest denominator: a FIP can file without a net-assets figure.

<BarChart
  data={industry_fip}
  x=period_year
  y=total_pl_bn
  yAxisTitle="Net Assets (R$bn)"
  title="FIP Net Assets by Reporting Year"
/>

<DataTable data={industry_fip} rows=10>
  <Column id=period_year title="Year"/>
  <Column id=doc_types title="Doc Types"/>
  <Column id=n_funds title="Funds Filing" fmt=num0/>
  <Column id=n_funds_with_pl title="Funds w/ Net Assets" fmt=num0/>
  <Column id=total_pl_bn title="Net Assets (R$bn)" fmt=num2/>
  <Column id=n_reports title="Reports" fmt=num0/>
</DataTable>

---

## FIAGRO: Agribusiness (Monthly Grain)

> Read from `cvm_fiagro_mensal` (CVM, monthly), including `vl_inadimpl`, which no aggregate exposes. Compare with [the FIDC Credit Monitor](/fidc). **Coverage:** the file begins **2025-05**; earlier months are empty because the dataset did not exist.

<LineChart
  data={industry_fiagro}
  x=period
  y=pl_bn
  yAxisTitle="Net Assets (R$bn)"
  title="FIAGRO Net Assets per Month"
/>

<DataTable data={industry_fiagro} rows=12>
  <Column id=period title="Month"/>
  <Column id=n_funds title="Funds" fmt=num0/>
  <Column id=pl_bn title="Net Assets (R$bn)" fmt=num2/>
  <Column id=inadimpl_mm title="Delinquent (R$mm)" fmt=num1/>
  <Column id=inadimpl_num1 title="Delinquency (%)" fmt=num1/>
  <Column id=cotistas title="Quotaholders" fmt=num0/>
</DataTable>
