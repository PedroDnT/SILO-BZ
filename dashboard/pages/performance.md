---
title: Fund Performance
---

<!--
  Per-asset-class performance on two axes, powered by the RPC functions in
  src/store/analytical/17_performance_analysis.sql (ETFs excluded — they are on
  /etf). Only return-like measures are displayed:
    FI = quota return · FII = compounded dividend yield.
  FIDC/FIAGRO/FIP net-asset growth is excluded because subscriptions,
  redemptions and capital calls make it a size change, not performance.

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

```sql fund_perf_series
select * from supabase.fund_perf_series
```

# Fund Performance

> Who beat their peers, ranked **within** each asset class over the trailing
> window. The ranking is never cross-class: a fund is compared only against funds
> measured on the same basis.
>
> What this page does **not** support: a claim that one asset class out-performed
> another. FI is measured on quota return while FII is measured on compounded
> dividend yield. FIDC, FIAGRO and FIP are absent: their filings expose net
> assets but no return series, and net-asset growth is dominated by flows and
> capital calls. A single fund's trajectory through time is on
> [Fund Explorer](/fund); the rates these returns should be judged against are
> on [Macro Context](/macro).

---

## Asset-Class Summary

> One row per class that has enough history to rank. Monthly fund history covers
> 2019–present, and returns are per-class bases: FI quota return, FII compounded
> dividend yield, FIDC/FIAGRO/FIP PL growth (the last is a size change, not a
> return, and is kept off these tables).
>
> `Avg` and `Best` are per class and on that class's own basis, so the columns
> must not be compared down the page. Classes with no defensible return measure
> are omitted rather than displaying economically meaningless PL growth.

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

## Cumulative Return Through Time — Largest Funds

> The time-series companion to the cross-sectional ranking above: rebased
> cumulative return for the six largest FI/FII funds, from
> `fund_performance_series()` (the same `fund_perf_series` source that powers
> [Fund Explorer](/fund)). No per-**class** return series function exists —
> aggregating returns across funds would require a weighting choice the data
> does not justify — so this chart is per fund, on each fund's own class basis:
> FI quota return, FII compounded dividend yield. Lines are comparable in shape,
> not strictly in basis.

<LineChart
  data={fund_perf_series}
  x=period
  y=cum_return_num2
  series=fund
  yAxisTitle="Cumulative Return (%)"
  title="Rebased Cumulative Return — Six Largest FI/FII Funds"
/>

---

## How Performance Is Measured

Performance is ranked **within** each asset class on a basis appropriate to that
class, and the basis travels with every row so numbers are never mixed across
classes:

| Asset class                              | Basis            | Meaning                                       |
| ---------------------------------------- | ---------------- | --------------------------------------------- |
| FI (Fixed Income / Equity / Multimarket) | `quota_return`   | last/first `vl_quota` − 1 (a true NAV return) |
| FII (Real Estate)                        | `dividend_yield` | compounded monthly dividend yield             |

FIDC, FIAGRO and FIP are deliberately absent. Their available `vl_patrim_liq`
series measures the size of the vehicle after subscriptions, redemptions and
capital calls; using `last / first − 1` produced million-percent figures that
were mathematically valid size changes but economically invalid returns.

Default window is the trailing 12 months; pass a calendar year to
`fund_performance_ranking(asset_class, start, end, …)` for "who beat their peers in
that year".

ETFs are excluded from every table above. They are carved out of `dim_fund` and
`fact_fund_monthly` upstream and are evaluated separately on
[the ETF page](/etf) — where, post-CVM-175, the NAV history a return would need is
largely missing.

---

## Horizontal Drill-Down

For a single fund's trajectory over time — net assets, quota, flows, and
per-period and cumulative return on its class basis — use the charts on
[Fund Explorer](/fund), which draw the same `fund_performance_series()` data
fund by fund.
