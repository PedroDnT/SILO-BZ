---
title: Brazilian Public Financial Data
hide_title: true
---

<!--
  Entry point: what the site covers, two orienting numbers, routing. Shows a shorter
  window (12 months) than /industry and /fidc. fund_headline.latest_period is NOT
  shown: FIP is stored at 31-Dec of its reporting year, a future date most of the year.
-->

```sql build_stamp
select * from supabase.build_stamp
```

```sql fund_headline
select * from supabase.fund_headline
```

```sql ops_health
select * from supabase.ops_health
```

```sql aum_by_entity
select * from supabase.aum_by_entity
```

```sql fip_latest
select * from supabase.fip_latest
```

```sql fidc_delinquency
select * from supabase.fidc_delinquency
```

```sql row_counts
select * from supabase.row_counts
```

```sql rates_1y
select * from supabase.rates_breakeven_latest where tenor_label = '1y'
```

# Brazilian Public Financial Data

> A public-data record of Brazilian **funds**, **listed companies** and the **B3
> market**, from CVM, BACEN and B3 open data, rebuilt after each daily ingest. It
> checks claims against filings and gives no advice. Unpublished or ambiguous fields
> are left **blank, never estimated**.

<BigValue data={fund_headline} value=funds_tracked title="Funds Tracked" fmt=num0/>
<BigValue data={fund_headline} value=aum_bn title="Net Assets (R$bn)" fmt=num0/>
<BigValue data={fund_headline} value=investor_positions title="Quotaholder Positions" fmt=num0/>
<BigValue data={ops_health} value=rows_7d title="Rows Ingested (7d)" fmt=num0/>
<BigValue data={ops_health} value=hours_since_last_run title="Hours Since Last Ingest" fmt=num1/>
<BigValue data={build_stamp} value=built_at_utc title="Snapshot Built"/>

> - **Net assets**: each fund's latest `vl_patrim_liq`, summed (latest per fund, not one date).
> - **Quotaholder positions**: summed `nr_cotst`. Positions, not people. FIDC and FIP report no holder count.
> - **Hours Since Last Ingest** much above 30 means the daily cron stopped; see [Pipeline Ops](/ops).
> - **Snapshot Built**: nothing here is newer than this stamp.

<BigValue data={rates_1y} value=real_num2 title="1y Real Yield (% a.a.)" fmt=num2/>
<BigValue data={rates_1y} value=breakeven_num2 title="1y Breakeven Inflation (%)" fmt=num2/>
<BigValue data={rates_1y} value=trade_date title="Curve Session"/>

> B3's real (DPL) curve at the 1-year vertex and the inflation it implies against the nominal (PRE) curve. Method on [Rates and Curves](/rates).

---

## Start Here

**Funds**

- **How big is the industry, and who controls it?** → [Industry Structure](/industry);
  [Managers](/managers) for the administrator and gestor league tables.
- **Is any particular fund in trouble?** → [Fund Explorer](/fund) for its net assets,
  flows and return; [Performance](/performance) for its rank within its asset class.
- **Where is credit deteriorating?** → [FIDC Credit Monitor](/fidc),
  [Securitization](/securit) for CRI/CRA, [Suspicious Deal Screens](/suspicious).
- **Which funds exist but do nothing?** → [Dormant Funds](/dormant): vehicles filing
  every month with zero flow: empty shells, and parked capital that stopped moving.

**Markets and macro**

- **What is the exchange actually doing?** → [B3 Markets](/markets) for session volume
  by board and instrument type.
- **What do real yields and implied inflation look like?** → [Rates and Curves](/rates)
  for B3's nominal and real curves, breakeven inflation since 2008 and DI1 open interest.
- **Who is short, and what does it cost to borrow?** → [Short Monitor](/short): short
  interest, % of free float, days to cover and borrow rates.
- **Who is buying and selling?** → [Follow the Money](/flows) for net flow by investor
  type; [Macro Context](/macro) for SELIC, CDI, inflation and the Focus consensus.

Listed-company financials (ITR/DFP statements, margins, ROE, the IPE event feed) live on
the companion CIA Aberta site, and every number on both is queryable through the
[API](https://octo-98895abd.mintlify.site/).

---

## Industry Net Assets by Family, 12 Months

> CVM **monthly** fund families, stacked; the stack ends at the last month **every** family has fully filed (CVM, monthly, 1 to 2 months lag). FIP files **yearly** and is excluded; its latest year-end is in the tiles below. Per-family 36 months on [Industry Structure](/industry).

<AreaChart
  data={aum_by_entity}
  x=period
  y=aum_bn
  series=entity_type
  type=stacked
  yAxisTitle="Net Assets (R$bn)"
  title="Net Assets by Monthly Fund Family — Last 12 Months"
/>

<BigValue data={fip_latest} value=aum_bn title="FIP Net Assets, Latest Year-End (R$bn)" fmt=num0/>
<BigValue data={fip_latest} value=period title="FIP Filing Year-End"/>
<BigValue data={fip_latest} value=n_funds title="FIP Vehicles Filing" fmt=num0/>

---

## FIDC Sector Delinquency, 12 Months

> Overdue receivables as a share of FIDC net assets (CVM, monthly, 1 to 2 months lag). A **sector aggregate that hides distribution**: a flat line can hide a few funds deteriorating badly. Detail on [the FIDC Credit Monitor](/fidc).

<LineChart
  data={fidc_delinquency}
  x=period
  y=delinquency_rate_num1
  yAxisTitle="Delinquency (%)"
  title="FIDC Sector Delinquency Rate"
/>

---

## Pages

In sidebar order.

### Industry and backdrop

| Page                            | What it answers                                                                                                                   | Watch out for                                                                                      |
| ------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| [Industry Structure](/industry) | Size, concentration (HHI and top-N share), fund formation, investor base, composition by asset class, plus FIP and FIAGRO by name | Families are measured at their **own** latest period; FIP's grain is yearly                        |
| [Macro Context](/macro)         | SELIC, CDI, inflation, PTAX and the BACEN Focus consensus                                                                         | Units are BACEN's and are **not converted** — % a.a. and % a.d. sit side by side                   |
| [Rates and Curves](/rates)      | B3 nominal (PRE) and real (DPL) curves, breakeven inflation since 2008 vs the Focus survey, DI1 open interest, NTN-B held by funds, global backdrop | Breakeven is **derived** at B3's fixed vertices and includes any risk premium; the long end is extrapolated by B3 |
| [B3 Markets](/markets)          | Exchange session prints from the COTAHIST tape: volume by board and instrument type, options                                      | Quotes are **unadjusted** and some papers quote per lot (`fator_cotacao` ≠ 1)                      |
| [Short Monitor](/short)         | Securities lending: short interest by ticker, % of free float, days to cover, borrow rates, sector concentration                  | History starts when SILO began capturing — B3 keeps ~21 business days and **cannot be backfilled** |
| [Follow the Money](/flows)      | Net flow by investor type (foreign, institutional, retail) and B3 cash-market ADTV                                                | Flow is **derived** from B3's month-to-date snapshots and lags **T+2**; there is no YTD column     |

### By asset class

| Page                         | What it answers                                                                                               | Watch out for                                                                                   |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| [FI Industry](/fi)           | Open-ended funds: daily flows, quotaholder base, investor mix, portfolio allocation, largest funds            | CDA allocation is a **directional mix, not a market-value census**                              |
| [FIDC Credit Monitor](/fidc) | Receivables funds: delinquency and its drivers, both aging bands, tranche promised-vs-realised, subordination | Raw CVM performance percentages carry extreme outliers — aggregates are medians                 |
| [FII Market](/fii)           | Real-estate funds: net assets, dividend-yield distribution, payout coverage, individual properties            | Property detail is partial by construction; the coverage tiles say how partial                  |
| [Securitization](/securit)   | CRI / CRA / OTS certificates: outstanding value, maturity wall, payment waterfall, ratings, distressed series | These are **not funds**; "reported value" is stock outstanding, not new issuance                |
| [ETF Market](/etf)           | Listed ETFs by provider, segment and tracked index, plus a scraped market snapshot                            | ETFs are carved out of the fund universe; NAV/return history is largely **absent post-CVM-175** |

### Houses, funds, rankings and screens

| Page                                   | What it answers                                                                                 | Watch out for                                                                                      |
| -------------------------------------- | ----------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| [Managers](/managers)                  | Administrator and gestor league tables by net assets and by net flow                            | Built on registry names, which are **sparsely populated** — the page publishes the size of the gap |
| [Fund Explorer](/fund)                 | The searchable universe, then per-fund net assets, quota, return and flow                       | Only the largest funds carry per-fund time series; the site is static                              |
| [Fund Holdings](/holdings)             | What funds hold: the largest stock positions by ticker, debentures by issuer, same-group holdings | Ends at the last month nearly all funds have filed; debenture issuers are B3 codes, not names     |
| [Performance](/performance)            | Who beat their peers, ranked **within** each asset class                                        | The return basis differs per class and is never mixed                                              |
| [Suspicious Deal Screens](/suspicious) | Four forensic patterns: zombie growth, evergreen aging, overdue certificates, captive vehicles  | Screens produce **signals, not findings** — every hit needs primary-source verification            |
| [Dormant Funds](/dormant)              | FI classes with zero subscriptions and redemptions for 3 months: empty shells vs parked capital | Three months is a **floor**; NULL flows disqualify rather than count as zero; FI only              |

### Operations

| Page                 | What it answers                                                                    | Watch out for                                                       |
| -------------------- | ---------------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| [Pipeline Ops](/ops) | Whether the ingest ran, whether it succeeded, and whether the data actually landed | A recent `ok` over a stale table is the disagreement worth catching |

---

## What Is in the Warehouse

> Row counts for the largest tables; freshness is on [Pipeline Ops](/ops). **≈** marks Postgres planner estimates (`pg_class.reltuples`, within ~1% after the daily `ANALYZE`).

<DataTable data={row_counts}>
  <Column id=dataset title="Dataset"/>
  <Column id=rows_est title="Rows (≈)" fmt=num0/>
</DataTable>

---

## How to Read This Dashboard

**Units** are in the column title; scaling happens in SQL. A column labelled **source units** is unconverted: read it as a ranking, not a percentage.

**Blank is not zero.** Blank means not published, not filed or not yet ingested; nothing is carried forward or imputed.

**Publication lag is structural.** CVM publishes monthly data 1 to 2 months in arrears; FIP files yearly, FIAGRO's file begins 2025-05, and post-CVM-175 share-class splits break the CNPJ join ETF NAV history depended on. None are pipeline failures. Each page states coverage before charting a partial field.

**Terminology.** "Net assets" is `vl_patrim_liq`; "quotaholders" is `nr_cotst`, positions not people.

---

## Want to know more?

**[What Silo serves](https://claude.ai/code/artifact/10fa2f4d-ce1f-48b1-aa31-064cdb0cb1dd)**: a plain-language walkthrough of what the warehouse does and does not claim.

**[API docs](https://octo-98895abd.mintlify.site/)**: every number here is queryable, free and anonymous.

**[Sign in](/signin.html)**: a GitHub account raises query ceilings (3 → 50 ids per call).
