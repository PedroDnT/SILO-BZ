---
title: Dormant Funds
---

<!--
  The screen is defined ONCE, as fraud_screen_dormant_funds() and
  fraud_screen_dormant_trend() in src/store/analytical/15_fraud_screens.sql, so
  this page, the analytical layer and any API caller share a single definition.
  Every dormant_* source passes the same lookback (3) — change it in the
  functions' callers together or the tiles and the tables will disagree.

  THRESHOLDS ARE ARGUMENTS, not findings, and they are stated on the page:
    fraud_screen_dormant_funds(3)         3 consecutive complete months
    fraud_screen_dormant_trend(3, 36)     the same, at every month-end for 36

  WHY THIS IS NOT /suspicious's "zombie growth": that screen is a FIDC credit
  pattern (delinquency > 5% with inflows still arriving). This page is about
  open-ended funds through which NOTHING moves. The market calls both "zombies";
  the site does not, because they are opposite conditions — one is growing on
  bad credit, the other is not moving at all.

  SOURCES ALL READ fact_fund_monthly, not the daily tape: the monthly matview
  already carries captc_mes / resg_mes / nr_cotst per fund-month, so the screen
  costs seconds at build time. The daily-grain measurement that motivated the
  page is health diagnostic 16 (scripts/health_diagnostics/).

  ZERO-ROW SAFETY: the two tile sources are no-GROUP-BY aggregates; the trend
  is a month spine; the three list sources are slot spines filtered here in
  DuckDB. A 0-row source writes a 0-byte parquet and kills the whole build.
-->

```sql headline
select * from supabase.dormant_headline
```

```sql trend
select * from supabase.dormant_trend
```

```sql shells
select * from supabase.dormant_shells
where cnpj is not null
```

```sql parked_top
select * from supabase.dormant_parked_top
where cnpj is not null
```

```sql by_admin
select * from supabase.dormant_by_admin
where admin_name is not null
```

```sql admin_coverage
select * from supabase.dormant_admin_coverage
```

# Dormant Funds

> Open-ended funds that file every month and through which **nothing moves**:
> zero subscriptions, zero redemptions, for three consecutive complete months.
> Two populations hide inside that description, and the quotaholder count tells
> them apart.
>
> **Empty shells** have no investor at all — a registered, filing vehicle holding
> nobody's money, a structure someone has already paid to stand up and is keeping
> ready. **Parked capital** has investors but no money in or out: the
> exclusive-fund and closed-structure profile, and also capital that has simply
> stopped. Neither is wrongdoing. Both are worth counting, because a fund that
> exists without doing anything is invisible to every metric built on flows.
>
> This is a different condition from the FIDC **zombie growth** screen on
> [Suspicious Deal Screens](/suspicious), which flags funds still _taking_ money
> against a deteriorating book. The market calls both "zombies"; they are
> opposites.

---

## The Definition, Stated

> A fund is on this page when, over the **3 complete months** ending at
> <Value data={headline} column=window_to/> (from
> <Value data={headline} column=window_from/>):
>
> - it filed in **every** month of the window — a fund that filed once and went
>   silent is _not filing_, which [Pipeline Ops](/ops) owns, not this page;
> - its reported subscriptions **and** redemptions sum to **exactly zero** — not
>   "small";
> - its flows and quotaholder count were **reported** in every month. A month with
>   an unreported flow is unknown, and unknown disqualifies the fund rather than
>   being counted as zero.
>
> `max_investors = 0` across the window makes it an **empty shell**; anything
> above zero, **parked capital**. FI only: the monthly fact table carries flows
> for the open-ended family alone, and "subscription" is not the same act in a
> closed-end listed vehicle. Three months is a **floor** — a longer window would
> raise the bar, not lower it.

<BigValue data={headline} value=empty_shells label="Empty Shells" fmt=num0/>
<BigValue data={headline} value=parked_capital label="Parked-Capital Funds" fmt=num0/>
<BigValue data={headline} value=parked_pl_bn label="Net Assets Standing Still (R$bn)" fmt=num1/>
<BigValue data={headline} value=parked_share_num1 label="Share of FI Classes Filing (%)" fmt=num1/>
<BigValue data={headline} value=funds_filing label="FI Classes Filing" fmt=num0/>
<BigValue data={headline} value=listed_companies label="Listed Companies, for Scale" fmt=num0/>

> **For scale** is the count of registered companhias abertas not marked
> cancelled — the honest denominator for "empresas na bolsa". It is not a ticker
> count: one issuer can carry several tickers, and the cash tape also lists ETFs,
> BDRs and FIIs.

---

## Thirty-Six Months of Stillness

> The same screen evaluated at every month-end, each looking back three months.
> A month the industry has not fully published yet is absent, not carried
> forward. Watch the parked-capital line against the FI net-flow chart on
> [FI Industry](/fi): capital stops moving _before_ it leaves.

<LineChart
  data={trend}
  x=period
  y=parked_capital
  yAxisTitle="Funds with Zero Flow, Investors Present"
  title="Parked-Capital Funds — Last 36 Months"
/>

<LineChart
  data={trend}
  x=period
  y=empty_shells
  yAxisTitle="Funds with Zero Flow, Zero Investors"
  title="Empty Shells — Last 36 Months"
/>

<AreaChart
  data={trend}
  x=period
  y=parked_pl_bn
  yAxisTitle="Net Assets (R$bn)"
  title="Net Assets Sitting in Parked-Capital Funds"
/>

---

## Where the Money Is Standing Still

> The largest parked-capital funds by net assets at the window's last month.
> Quotaholders is the maximum across the window. Names come from the CVM
> registry and fall back to the CNPJ where the registry has none.

<DataTable data={parked_top} rows=25>
  <Column id=fund_name title="Fund"/>
  <Column id=admin_name title="Administrator"/>
  <Column id=max_investors title="Quotaholders" fmt=num0/>
  <Column id=last_pl_mm title="Net Assets (R$mm)" fmt=num1/>
</DataTable>

---

## By Administrator

<BigValue data={admin_coverage} value=hits label="Screen Hits" fmt=num0/>
<BigValue data={admin_coverage} value=hits_with_admin label="…with a Registry Administrator" fmt=num0/>
<BigValue data={admin_coverage} value=hits_without_admin label="…with None" fmt=num0/>

> **Coverage first.** `admin_name` comes from CVM's cadastral file and is
> sparsely populated. The ranking below covers only the hits the registry names;
> the tile says how many it cannot. A short list means a sparse registry, not
> few administrators.

<BarChart
  data={by_admin}
  x=admin_name
  y=parked_pl_bn
  swapXY=true
  yAxisTitle="Parked Net Assets (R$bn)"
  title="Parked Capital by Administrator — Top 20"
/>

<DataTable data={by_admin} rows=20>
  <Column id=admin_name title="Administrator"/>
  <Column id=parked_funds title="Parked-Capital Funds" fmt=num0/>
  <Column id=empty_shells title="Empty Shells" fmt=num0/>
  <Column id=parked_pl_bn title="Parked Net Assets (R$bn)" fmt=num2/>
</DataTable>

---

## The Empty Shells

> Every fund that filed all three months with zero flow and **no quotaholder**.
> Ordered by whatever net assets the filing still reports — most read zero. The
> headline tile carries the true total; this table shows up to 100.

<DataTable data={shells} rows=100>
  <Column id=fund_name title="Fund"/>
  <Column id=cnpj title="CNPJ"/>
  <Column id=admin_name title="Administrator"/>
  <Column id=last_pl_mm title="Net Assets (R$mm)" fmt=num2/>
</DataTable>

---

> **An empty table means no fund matched the definition at the latest complete
> month** — not that the screen failed to run. If the tiles read zero across the
> board, check that the FI monthly slice actually landed on
> [Pipeline Ops](/ops) before concluding every fund in Brazil is busy.
