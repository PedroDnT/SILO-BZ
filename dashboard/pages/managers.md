---
title: Managers
---

<!--
  Administrator and gestor league tables, from the two ranking RPCs and the two
  dimension views that had no caller:
    administrator_rankings(p_period, p_metric, p_limit)   14_ranking_functions.sql
    gestor_rankings(p_period, p_metric, p_limit)          14_ranking_functions.sql
    dim_administrator / dim_gestor                        13_dim_classification.sql

  ALL FOUR READ cvm_fund_registry.admin_name / gestor_name, added by migration 11
  and lifted from CVM's cadastral CSVs at ingest. Nothing derives, infers or
  back-fills a name: a fund whose cadastral row has not been ingested has no
  administrator and no gestor here, and is therefore absent from every table on
  this page. The coverage strip at the top of the page is the measured size of
  that gap, published rather than hidden, and the tables show the gap as blank
  rows rather than inventing a "Unknown" or "Other" bucket.

  ZERO-ROW RULE — this page is the reason the rule matters. Both ranking
  functions INNER JOIN the registry and drop every unnamed fund, so on a database
  whose registry has no names they return NOTHING. A 0-row source makes Evidence
  write a zero-byte parquet and the build dies with "Invalid Input Error: File
  ... too small to be a Parquet file". Every source here is therefore driven by a
  generate_series SLOT spine (1..N) with the ranking LEFT JOINed onto it: fixed
  row count, blank slots when there is no name. Structural, not cosmetic.

  PERIOD CHOICE, load-bearing: passing NULL for p_period makes the functions
  resolve max(period) over fact_fund_monthly — and FIP is stored at 31-DEC of its
  reporting year, a date in the FUTURE for most of the year. NULL therefore pins
  the ranking to a FIP-only period, in which no fund carries a registry name, and
  returns nothing. Every ranking here passes the latest MONTHLY period explicitly
  (max(period) excluding FIP).

  OTHER CAVEATS:
    * The ranking tables pin every house to ONE period. The dim_ universe tables
      sum each fund's MOST RECENT observation instead, so their net assets are
      latest-available per fund and will not tie out with the ranking tables.
      They are different questions, not a discrepancy.
    * net_flow is FI-only (captc_mes / resg_mes exist for FI alone).
    * total_inadimpl is FIDC/FIAGRO-only.
    * Administrator and gestor are different roles and one house often appears in
      both tables; they must not be summed together.
-->

```sql mgr_coverage
select * from supabase.mgr_coverage
```

```sql mgr_admin_rankings
select * from supabase.mgr_admin_rankings
```

```sql mgr_gestor_rankings
select * from supabase.mgr_gestor_rankings
```

```sql mgr_admin_flow
select * from supabase.mgr_admin_flow
```

```sql mgr_admin_universe
select * from supabase.mgr_admin_universe
```

```sql mgr_gestor_universe
select * from supabase.mgr_gestor_universe
```

# Managers

> A handful of houses administer most of the industry's net assets, and the
> gestor side is more concentrated still. **Administrator** is the fund's legal
> and registry manager; **gestor** makes the investment decisions. One house can
> be both, so the two tables must never be added together.
>
> The load-bearing limit is on the next screen: these are league tables of the
> **named subset** of the industry, not of the industry. The coverage percentages
> below say how large that subset is, and nothing here is estimated to close the
> gap. Industry-wide concentration measured without needing names is on
> [Industry Structure](/industry).

<BigValue data={mgr_coverage} value=admin_coverage_pct label="Registry Rows w/ Administrator (%)" fmt=num1/>
<BigValue data={mgr_coverage} value=gestor_coverage_pct label="Registry Rows w/ Gestor (%)" fmt=num1/>
<BigValue data={mgr_coverage} value=n_administrators label="Administrators Named" fmt=num0/>
<BigValue data={mgr_coverage} value=n_gestores label="Gestores Named" fmt=num0/>
<BigValue data={mgr_coverage} value=ranking_period label="Ranking Period"/>

---

## Name Coverage — Read This First

> `admin_name` and `gestor_name` come straight from CVM's cadastral files
> (`cvm_fund_registry`, migration 11). **They are sparsely populated**, and every
> table on this page is built on them, so each table covers only the named slice
> of the industry — the percentages above say how large that slice is.
>
> Nothing here is estimated, imputed or bucketed into an "unknown" catch-all. A
> fund with no name in the registry is simply not ranked, and a rank with no name
> behind it renders as a **blank row**, which is what missing data honestly looks
> like. If the two percentages above are low, treat these league tables as a
> ranking of the named subset, not of the market. Coverage improves only when the
> cadastral ingest runs — its status is on [Pipeline Ops](/ops) under the `cad`
> doc types.

<DataTable data={mgr_coverage}>
  <Column id=registry_rows title="Registry Rows" fmt=num0/>
  <Column id=rows_with_admin title="With Administrator" fmt=num0/>
  <Column id=rows_with_gestor title="With Gestor" fmt=num0/>
  <Column id=admin_coverage_pct title="Admin Coverage (%)" fmt=num1/>
  <Column id=gestor_coverage_pct title="Gestor Coverage (%)" fmt=num1/>
  <Column id=funds_in_universe title="Funds in Universe" fmt=num0/>
  <Column id=ranking_period title="Ranking Period"/>
</DataTable>

---

## Top Administrators by Net Assets

> Ranked at the latest monthly period. Every fund the administrator has reporting
> **in that month** is counted; a family whose newest filing is older is not
> carried forward, so an administrator concentrated in a lagging family will look
> smaller here than it is.

<BarChart
  data={mgr_admin_rankings}
  x=admin_name
  y=aum_bn
  swapXY=true
  yAxisTitle="Net Assets (R$bn)"
  title="Administrators by Net Assets"
/>

<DataTable data={mgr_admin_rankings} rows=20>
  <Column id=slot title="#" fmt=num0/>
  <Column id=admin_name title="Administrator"/>
  <Column id=n_funds title="Funds" fmt=num0/>
  <Column id=aum_bn title="Net Assets (R$bn)" fmt=num2/>
  <Column id=net_flow_bn title="Net Flow (R$bn)" fmt=num2/>
  <Column id=inadimpl_mm title="Delinquent (R$mm)" fmt=num1/>
  <Column id=avg_yield_pct title="Avg Yield (%)" fmt=num2/>
  <Column id=period title="Period"/>
</DataTable>

---

## Top Gestores by Net Assets

> The investment-decision side of the same universe, on the same period and the
> same coverage caveat. A house appearing in both tables is playing two roles, not
> holding the assets twice.

<BarChart
  data={mgr_gestor_rankings}
  x=gestor_name
  y=aum_bn
  swapXY=true
  yAxisTitle="Net Assets (R$bn)"
  title="Gestores by Net Assets"
/>

<DataTable data={mgr_gestor_rankings} rows=20>
  <Column id=slot title="#" fmt=num0/>
  <Column id=gestor_name title="Gestor"/>
  <Column id=n_funds title="Funds" fmt=num0/>
  <Column id=aum_bn title="Net Assets (R$bn)" fmt=num2/>
  <Column id=net_flow_bn title="Net Flow (R$bn)" fmt=num2/>
  <Column id=inadimpl_mm title="Delinquent (R$mm)" fmt=num1/>
  <Column id=avg_yield_pct title="Avg Yield (%)" fmt=num2/>
  <Column id=period title="Period"/>
</DataTable>

---

## Administrators by Net Flow

> Who gathered and who lost money in the month, rather than who is simply large.
> Ranked descending, so **outflows sit at the bottom of the table**.
>
> Net flow is an FI-only measure — `captc_mes` and `resg_mes` exist for FI alone —
> so an administrator whose book is entirely FII, FIDC or FIP shows blank here,
> meaning "not reported", not "flat".

<DataTable data={mgr_admin_flow} rows=15>
  <Column id=slot title="#" fmt=num0/>
  <Column id=admin_name title="Administrator"/>
  <Column id=n_funds title="Funds" fmt=num0/>
  <Column id=net_flow_bn title="Net Flow (R$bn)" fmt=num2/>
  <Column id=aum_bn title="Net Assets (R$bn)" fmt=num2/>
  <Column id=flow_over_aum_pct title="Flow / Net Assets (%)" fmt=num2/>
  <Column id=period title="Period"/>
</DataTable>

---

## Administrator Universe

> From `dim_administrator`, ranked by **number of mandates**. This view sums each
> fund's most recent observation, so its net assets are latest-available per fund
> and are a different (and staler) number from the ranking table above, which pins
> every house to one period. The two are not meant to reconcile.
>
> `Active` counts `cvm_fund_registry.is_active`, derived from CVM's own status
> field; a fund with no status recorded is not counted as active.

<DataTable data={mgr_admin_universe} rows=20>
  <Column id=slot title="#" fmt=num0/>
  <Column id=admin_name title="Administrator"/>
  <Column id=admin_cnpj title="CNPJ"/>
  <Column id=n_funds title="Funds" fmt=num0/>
  <Column id=n_active_funds title="Active" fmt=num0/>
  <Column id=aum_bn title="Net Assets, Latest per Fund (R$bn)" fmt=num2/>
</DataTable>

---

## Gestor Universe

> From `dim_gestor`, same construction and the same latest-per-fund caveat.
> `gestor_id` is a **CPF** when the gestor is a natural person and a **CNPJ** when
> it is a firm — carried straight from the cadastral file, unreformatted, for
> drill-through. Individual funds behind any of these mandates can be looked up on
> [Fund Explorer](/fund).

<DataTable data={mgr_gestor_universe} rows=20>
  <Column id=slot title="#" fmt=num0/>
  <Column id=gestor_name title="Gestor"/>
  <Column id=gestor_id title="CPF / CNPJ"/>
  <Column id=n_funds title="Funds" fmt=num0/>
  <Column id=n_active_funds title="Active" fmt=num0/>
  <Column id=aum_bn title="Net Assets, Latest per Fund (R$bn)" fmt=num2/>
</DataTable>
