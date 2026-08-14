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
  correct regardless; the tables simply deepen as more data lands. That caveat is
  now stated ON the page as well as here — a reader looking at a two-class summary
  needs to know it is a coverage artefact, not a two-class industry.

  SECTION ORDER leads with the finding (the class summary and the rankings) and
  puts the methodology after them, because the basis note is what a reader
  consults once they have a number in front of them.
-->

```sql class_summary
select * from supabase.class_summary
```

```sql ranking_by_class
select * from supabase.ranking_by_class
```

# Fund Performance

> Who beat their peers, ranked **within** each asset class over the trailing
> window. The ranking is never cross-class: a fund is compared only against funds
> measured on the same basis.
>
> What this page does **not** support: a claim that one asset class out-performed
> another. FI is measured on quota return, FII on compounded dividend yield, and
> FIDC / FIAGRO / FIP on net-asset growth — which conflates subscriptions and
> redemptions with performance and is not a return at all. The basis travels with
> every row so the mix is always visible. A single fund's trajectory through time
> is on [Fund Explorer](/fund); the rates these returns should be judged against
> are on [Macro Context](/macro).

---

## Asset-Class Summary

> One row per class that has enough history to rank. **Coverage caveat:** fund
> history is currently 2026-only (FI daily, FII Q1, FIP), FIDC and FIAGRO are
> empty, and where `cvm_fund_registry` has not landed, FI funds fall into the
> coarse `Other FI` class. A short class list here is a measure of ingested
> history, not of the industry — check [Pipeline Ops](/ops) before reading it as
> a market fact.
>
> `Avg` and `Best` are per class and on that class's own basis, so the columns
> must not be compared down the page.

<DataTable data={class_summary}>
  <Column id=asset_class title="Asset Class"/>
  <Column id=return_basis title="Basis"/>
  <Column id=funds_ranked title="Funds Ranked" fmt=num0/>
  <Column id=avg_perf_num2 title="Avg Performance (%)" fmt=num2/>
  <Column id=best_num2 title="Best Performance (%)" fmt=num2/>
</DataTable>

---

## Top 10 per Asset Class — Trailing Window

> The ranking itself, grouped by class. `Obs` is the number of monthly
> observations behind each figure: a fund ranked on two observations is not
> comparable to one ranked on twelve, and no minimum has been imposed to hide
> that — the count is shown instead.

<DataTable data={ranking_by_class} rows=20 groupBy=asset_class>
  <Column id=rank_in_class title="#" fmt=num0/>
  <Column id=fund title="Fund"/>
  <Column id=entity_type title="Entity"/>
  <Column id=performance_num2 title="Performance (%)" fmt=num2/>
  <Column id=return_basis title="Basis"/>
  <Column id=n_obs title="Obs" fmt=num0/>
  <Column id=aum_mm title="Net Assets (R$mm)" fmt=num1/>
</DataTable>

---

## How Performance Is Measured

Performance is ranked **within** each asset class on a basis appropriate to that
class, and the basis travels with every row so numbers are never mixed across
classes:

| Asset class                              | Basis            | Meaning                                                                         |
| ---------------------------------------- | ---------------- | ------------------------------------------------------------------------------- |
| FI (Fixed Income / Equity / Multimarket) | `quota_return`   | last/first `vl_quota` − 1 (a true NAV return)                                   |
| FII (Real Estate)                        | `dividend_yield` | compounded monthly dividend yield                                               |
| FIDC / FIAGRO / FIP                      | `pl_growth`      | last/first net assets − 1 — **growth, not a clean return** (it conflates flows) |

Default window is the trailing 12 months; pass a calendar year to
`fund_performance_ranking(asset_class, start, end, …)` for "who beat their peers in
that year".

ETFs are excluded from every table above. They are carved out of `dim_fund` and
`fact_fund_monthly` upstream and are evaluated separately on
[the ETF page](/etf) — where, post-CVM-175, the NAV history a return would need is
largely missing.

---

## Horizontal Drill-Down

For a single fund's trajectory over time — per-period return and cumulative
return on its class basis — call:

```text
select * from fund_performance_series('<cnpj>', '2019-01-01', current_date);
```

It returns `period, return_basis, level_value, period_return, cumulative_return`
for that fund: the time-series companion to the cross-sectional ranking above.
The same function already powers the rebased-return chart for the largest funds
on [Fund Explorer](/fund).
