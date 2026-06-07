---
title: Fund Performance
---

<!--
  Per-asset-class performance on two axes, powered by the RPC functions in
  src/store/analytical/17_performance_analysis.sql (ETFs excluded — they are on
  /etf). Return basis is per class and is shown as a column, never conflated:
    FI = quota return · FII = compounded dividend yield · FIDC/FIAGRO/FIP = PL growth.

  COVERAGE: fund history is currently 2026 only (FI daily + FII Q1 + FIP),
  FIDC/FIAGRO are empty, and cvm_fund_registry is empty so FI funds fall into the
  coarse 'Other FI' class until the registry/backfill runs. The functions are
  correct regardless; the tables simply deepen as more data lands.
-->

```sql ranking_by_class
select
  asset_class,
  rank_in_class,
  entity_type,
  coalesce(fund_name, cnpj)            as fund,
  return_basis,
  round(total_performance * 100, 2)    as performance_pct,
  n_obs,
  round(aum_end / 1e6, 1)              as aum_mm
from fund_performance_ranking(null, null, null, null, 10, 2)
order by asset_class, rank_in_class
```

```sql class_summary
select
  asset_class,
  count(*)                                          as funds_ranked,
  round(avg(total_performance) * 100, 2)            as avg_perf_pct,
  round(max(total_performance) * 100, 2)            as best_pct,
  min(return_basis)                                 as return_basis
from fund_performance_ranking(null, null, null, null, 1000, 2)
group by asset_class
order by funds_ranked desc
```

# Fund Performance

> **Vertical** (who beat their peers) and **horizontal** (how a fund moved over
> time) analysis, per asset class. ETFs are evaluated separately on
> [the ETF page](/etf).

## How "performance" is measured

Performance is ranked **within** each asset class on a basis appropriate to that
class — and the basis travels with every row so numbers are never mixed across
classes:

| Asset class | Basis | Meaning |
| --- | --- | --- |
| FI (Fixed Income / Equity / Multimarket) | `quota_return` | last/first `vl_quota` − 1 (a true NAV return) |
| FII (Real Estate) | `dividend_yield` | compounded monthly dividend yield |
| FIDC / FIAGRO / FIP | `pl_growth` | last/first net-assets − 1 — **growth, not a clean return** (it conflates flows) |

Default window is the trailing 12 months; pass a calendar year to
`fund_performance_ranking(asset_class, start, end, …)` for "who beat their peers in
that year".

---

## Asset-Class Summary

<DataTable data={class_summary}>
  <Column id=asset_class title="Asset Class"/>
  <Column id=return_basis title="Basis"/>
  <Column id=funds_ranked title="Funds" fmt=num0/>
  <Column id=avg_perf_pct title="Avg %" fmt=num2/>
  <Column id=best_pct title="Best %" fmt=num2/>
</DataTable>

---

## Top 10 per Asset Class — Trailing Window

<DataTable data={ranking_by_class} rows=20 groupBy=asset_class>
  <Column id=rank_in_class title="#" fmt=num0/>
  <Column id=fund title="Fund"/>
  <Column id=entity_type title="Type"/>
  <Column id=performance_pct title="Performance %" fmt=num2/>
  <Column id=return_basis title="Basis"/>
  <Column id=n_obs title="Obs" fmt=num0/>
  <Column id=aum_mm title="AUM (R$mm)" fmt=num1/>
</DataTable>

---

## Horizontal drill-down

For a single fund's trajectory over time — per-period return and cumulative
return on its class basis — call:

```text
select * from fund_performance_series('<cnpj>', '2019-01-01', current_date);
```

It returns `period, return_basis, level_value, period_return, cumulative_return`
for that fund, the time-series companion to the cross-sectional ranking above.
