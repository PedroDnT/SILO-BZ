---
title: Fund Explorer
---

<!--
  A fund-level explorer over the whole tracked universe (FI / FIDC / FIAGRO /
  FII / FIP; ETFs are carved out of dim_fund and live on /etf).

  WHY THIS IS AN EXPLORER AND NOT A DRILL-DOWN: Evidence builds to a fully static
  site — there is no server at view time to answer "now show me fund X". So the
  page pre-materialises a bounded slice (the 400 largest funds) that the DataTable
  searches client-side, and reserves the per-CNPJ RPCs (fund_profile,
  fund_nav_series, fund_performance_series, fund_flow_trend — all of which require
  a cnpj argument) for a SMALL driver set of the largest funds. Running them over
  every fund would blow up both the query and the parquet.

  Names come from cvm_fund_registry via dim_fund. Where the registry has not
  populated a name, the CNPJ is displayed — never a synthesised label.

  Every source query is driven by a generate_series spine, a one-row VALUES
  spine, or a no-GROUP-BY aggregate, so none of them can return zero rows (a
  0-row source writes a 0-byte parquet and kills the Evidence build).
-->

```sql fund_headline
select * from supabase.fund_headline
```

```sql fund_entity_mix
select * from supabase.fund_entity_mix
```

```sql fund_explorer
select * from supabase.fund_explorer
```

```sql fund_profiles
select * from supabase.fund_profiles
```

```sql fund_nav_series
select * from supabase.fund_nav_series
```

```sql fund_perf_series
select * from supabase.fund_perf_series
```

```sql fund_flow_series
select * from supabase.fund_flow_series
```

# Fund Explorer

> Search the tracked fund universe, then follow the largest funds through time —
> net assets, quota, rebased return and monthly flow. Rankings by asset class live
> on [Performance](/performance); the FI industry aggregate lives on [FI](/fi).

<BigValue data={fund_headline} value=funds_tracked label="Funds Tracked" fmt=num0/>
<BigValue data={fund_headline} value=aum_bn label="Net Assets, Latest Obs. (R$ bn)" fmt=num0/>
<BigValue data={fund_headline} value=investor_positions label="Quotaholder Positions" fmt=num0/>
<BigValue data={fund_headline} value=funds_reporting_latest label="Reporting in Latest Month" fmt=num0/>
<BigValue data={fund_headline} value=funds_with_name label="Funds with a Registry Name" fmt=num0/>

> "Funds with a registry name" is the honest read on labelling: every other fund
> below is identified by CNPJ because `cvm_fund_registry` has not published a name
> for it yet.

---

## Universe by Asset Class

<BarChart
  data={fund_entity_mix}
  x=asset_class
  y=aum_bn
  series=entity_type
  type=stacked
  swapXY=true
  yAxisTitle="Net Assets (R$ bn)"
  title="Net Assets by Conformed Asset Class"
/>

<DataTable data={fund_entity_mix} rows=12>
  <Column id=asset_class title="Asset Class"/>
  <Column id=entity_type title="Entity"/>
  <Column id=n_funds title="Funds" fmt=num0/>
  <Column id=n_funds_reporting title="With an Observation" fmt=num0/>
  <Column id=aum_bn title="Net Assets (R$ bn)" fmt=num1/>
  <Column id=investor_positions title="Quotaholders" fmt=num0/>
  <Column id=latest_period title="Latest Month"/>
</DataTable>

---

## Search the Universe

> The 400 largest funds by latest reported net assets, from
> `search_funds('', null, 400)`. Type a name, a CNPJ fragment, or an entity type
> in the search box. A fund whose `latest_aum` is blank has a registry entry but
> no monthly observation in `fact_fund_monthly` — an absence, not a zero.

<DataTable data={fund_explorer} rows=20 search=true>
  <Column id=fund_name title="Fund"/>
  <Column id=cnpj title="CNPJ"/>
  <Column id=entity_type title="Entity"/>
  <Column id=asset_class title="Asset Class"/>
  <Column id=aum_mm title="Net Assets (R$ mm)" fmt=num0/>
  <Column id=investors title="Quotaholders" fmt=num0/>
  <Column id=latest_period title="Latest Month"/>
  <Column id=first_period title="First Report"/>
  <Column id=months_report title="Months Reported" fmt=num0/>
</DataTable>

---

## Profile Cards — 12 Largest Funds

> One `fund_profile(cnpj)` call per fund. **Share of peak** is the fund's latest
> net assets against its own historical peak: well under 100% means it has been
> redeemed or paid out, not that it under-performed. `is_active` is CVM-reported
> reporting recency (a report within 90 days), not a solvency judgement.

<DataTable data={fund_profiles} rows=12>
  <Column id=fund_name title="Fund"/>
  <Column id=entity_type title="Entity"/>
  <Column id=latest_aum_mm title="Latest Net Assets (R$ mm)" fmt=num0/>
  <Column id=peak_aum_mm title="Peak Net Assets (R$ mm)" fmt=num0/>
  <Column id=pct_of_peak title="Share of Peak (%)" fmt=num1/>
  <Column id=months_reported title="Months Reported" fmt=num0/>
  <Column id=first_period title="First Report"/>
  <Column id=last_period title="Last Report"/>
  <Column id=is_active title="Active"/>
  <Column id=status title="Registry Status"/>
</DataTable>

---

## Net Assets Through Time — Six Largest Funds

> `fund_nav_series(cnpj, …)` over 36 months. Months a fund did not report are
> gaps in the line rather than carried-forward values.

<LineChart
  data={fund_nav_series}
  x=period
  y=aum_bn
  series=fund
  yAxisTitle="Net Assets (R$ bn)"
  title="Net Assets by Fund"
/>

<LineChart
  data={fund_nav_series}
  x=period
  y=investors
  series=fund
  yAxisTitle="Quotaholders"
  title="Quotaholder Count by Fund"
/>

> Quota value (`vl_quota`) is published on the FI daily file only, so it is blank
> for FIDC / FIAGRO / FII / FIP rows in the table below. Use the rebased return
> chart in the next section to compare funds of different quota scales.

<DataTable data={fund_nav_series} rows=12>
  <Column id=period title="Month"/>
  <Column id=fund title="Fund"/>
  <Column id=entity_type title="Entity"/>
  <Column id=aum_bn title="Net Assets (R$ bn)" fmt=num2/>
  <Column id=quota title="Quota Value (R$)" fmt='#,##0.00'/>
  <Column id=investors title="Quotaholders" fmt=num0/>
</DataTable>

---

## Rebased Return — Six Largest Funds

> `fund_performance_series(cnpj, …)`, rebased to the start of the window. The
> **basis differs by family and is shown as a column** — FI is a true quota
> return, FII is compounded dividend yield, and everything else is PL growth,
> which conflates flows with performance. Lines on different bases are not
> directly comparable; that is a property of the source data, not of the chart.

<LineChart
  data={fund_perf_series}
  x=period
  y=cum_return_pct
  series=fund
  yAxisTitle="Cumulative Return (%)"
  title="Cumulative Return, Rebased to Window Start"
/>

<DataTable data={fund_perf_series} rows=12>
  <Column id=period title="Month"/>
  <Column id=fund title="Fund"/>
  <Column id=asset_class title="Asset Class"/>
  <Column id=return_basis title="Basis"/>
  <Column id=period_return_pct title="Month Return (%)" fmt=num2/>
  <Column id=cum_return_pct title="Cumulative (%)" fmt=num2/>
</DataTable>

---

## Flow Trend — Six Largest FI Funds

> `fund_flow_trend(cnpj, …)`. Restricted to FI on purpose: subscriptions and
> redemptions are summed from `cvm_fi_diario` and exist only on the FI branch of
> `fact_fund_monthly`, so charting them for other families would show an empty
> line that reads as "no flows" instead of "not published".

<BarChart
  data={fund_flow_series}
  x=period
  y=net_flow_mm
  series=fund
  type=grouped
  yAxisTitle="Net Flow (R$ mm)"
  title="Monthly Net Flow by Fund"
/>

<LineChart
  data={fund_flow_series}
  x=period
  y=redemption_pressure_pct
  series=fund
  yAxisTitle="Redemptions / Net Assets (%)"
  title="Monthly Redemption Pressure"
/>

<DataTable data={fund_flow_series} rows=12>
  <Column id=period title="Month"/>
  <Column id=fund title="Fund"/>
  <Column id=inflow_mm title="Subscriptions (R$ mm)" fmt=num1/>
  <Column id=outflow_mm title="Redemptions (R$ mm)" fmt=num1/>
  <Column id=net_flow_mm title="Net (R$ mm)" fmt=num1/>
  <Column id=cum_net_flow_bn title="Cumulative Net (R$ bn)" fmt=num2/>
  <Column id=redemption_pressure_pct title="Redemption Pressure (%)" fmt=num2/>
</DataTable>
