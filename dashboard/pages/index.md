---
title: Brazilian Public Financial Data
hide_title: true
---

<!--
  ENTRY POINT. This page has three jobs and nothing else:
    1. say what the site covers and what it does not,
    2. give the two numbers that orient a first-time reader (how big the
       industry is, and whether its worst-behaved corner is deteriorating),
    3. route to the right page.

  It deliberately shows a SHORTER window than the pages it links to — 12 months
  of AUM and 12 months of FIDC delinquency, against 36 and 24 on /industry and
  /fidc — so it reads as an entry point rather than a duplicate of them.

  Sources used here are index-only (aum_by_entity, fidc_delinquency, row_counts)
  plus two shared headline sources (fund_headline from /fund, ops_health from
  /ops) so the tile strip and the freshness signal are the same numbers those
  pages report, never a second computation of them.

  fund_headline.latest_period is deliberately NOT shown: it resolves to
  max(period) over fact_fund_monthly, and FIP is stored at 31-Dec of its
  reporting year — a date in the future for most of the calendar year. A "latest
  month" tile built on it would be wrong for eleven months of twelve.
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

# Brazilian Public Financial Data

> A public-data record of Brazilian **funds**, **listed companies** and the **B3
> market** — net assets, flows, delinquency, tranche structure, payout behaviour,
> filed financials, short interest and investor flow — from CVM, BACEN and B3 open
> data, ingested and republished unattended every morning. Built for checking
> claims against filings, not for choosing investments: no advice, no rating, no
> recommendation.
>
> Everything shown is what the filings say. Unpublished, uningested or ambiguous
> fields are left **blank, never estimated** — the same rule the API enforces for
> the agents that query it, which is why a question this warehouse cannot answer
> returns nothing rather than a plausible number.

<BigValue data={fund_headline} value=funds_tracked title="Funds Tracked" fmt=num0/>
<BigValue data={fund_headline} value=aum_bn title="Net Assets (R$bn)" fmt=num0/>
<BigValue data={fund_headline} value=investor_positions title="Quotaholder Positions" fmt=num0/>
<BigValue data={ops_health} value=rows_7d title="Rows Ingested (7d)" fmt=num0/>
<BigValue data={ops_health} value=hours_since_last_run title="Hours Since Last Ingest" fmt=num1/>
<BigValue data={build_stamp} value=built_at_utc title="Snapshot Built"/>

> - **Net assets** — each fund's most recent `vl_patrim_liq`, summed. Latest-available
>   per fund, not an as-of-one-date figure.
> - **Quotaholder positions** — summed `nr_cotst`. **Positions, not people**: one
>   investor in three funds counts three times. FIDC and FIP report no holder count.
> - **Hours Since Last Ingest** much above 30 means the daily cron has stopped —
>   check [Pipeline Ops](/ops).
> - **Snapshot Built** — this site is a build-time snapshot, rebuilt after each
>   successful ingest. Nothing here is newer than that stamp.

---

## Start Here

**Funds**

- **How big is the industry, and who controls it?** → [Industry Structure](/industry);
  [Managers](/managers) for the administrator and gestor league tables.
- **Is any particular fund in trouble?** → [Fund Explorer](/fund) for its net assets,
  flows and return; [Performance](/performance) for its rank within its asset class.
- **Where is credit deteriorating?** → [FIDC Credit Monitor](/fidc),
  [Securitization](/securit) for CRI/CRA, [Suspicious Deal Screens](/suspicious).
- **Which funds exist but do nothing?** → [Dormant Funds](/dormant) — vehicles filing
  every month with zero flow: empty shells, and parked capital that stopped moving.

**Markets and macro**

- **What is the exchange actually doing?** → [B3 Markets](/markets) for session volume
  by board and instrument type.
- **Who is short, and what does it cost to borrow?** → [Short Monitor](/short) — short
  interest, % of free float, days to cover and borrow rates.
- **Who is buying and selling?** → [Follow the Money](/flows) for net flow by investor
  type; [Macro Context](/macro) for SELIC, CDI, inflation and the Focus consensus.

Listed-company financials (ITR/DFP statements, margins, ROE, the IPE event feed) live on
the companion CIA Aberta site, and every number on both is queryable through the
[API](https://octo-98895abd.mintlify.site/).

---

## Industry Net Assets by Family — 12 Months

> The four **monthly** CVM fund families stacked. FI dominates by an order of
> magnitude, so the others read as thin bands at the top — the 36-month series
> split per family is on [Industry Structure](/industry). The stack ends at the
> last month **every** family has fully filed.
>
> FIP is excluded: it files **yearly** and would appear as one December band
> larger than FIDC, FII and FIAGRO together. Its latest year-end is the tile below.

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

## FIDC Sector Delinquency — 12 Months

> Overdue receivables as a share of FIDC net assets, across every FIDC filing both
> an aging table and a monthly report — the asset side of the receivables-fund
> industry marking itself.
>
> It is a **sector aggregate and hides distribution**: a stable line is consistent
> with a handful of funds deteriorating badly while the rest improve. The 24-month
> series, the aging buckets and the fund-level ranking are on [the FIDC Credit
> Monitor](/fidc).

<LineChart
  data={fidc_delinquency}
  x=period
  y=delinquency_rate_num1
  yAxisTitle="Delinquency (%)"
  title="FIDC Sector Delinquency Rate"
/>

---

## Pages

In sidebar order: industry and backdrop, then one page per asset class, then the
granular views, then the pipeline.

### Industry and backdrop

| Page                            | What it answers                                                                                                                   | Watch out for                                                                                      |
| ------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| [Industry Structure](/industry) | Size, concentration (HHI and top-N share), fund formation, investor base, composition by asset class, plus FIP and FIAGRO by name | Families are measured at their **own** latest period; FIP's grain is yearly                        |
| [Macro Context](/macro)         | SELIC, CDI, inflation, PTAX and the BACEN Focus consensus                                                                         | Units are BACEN's and are **not converted** — % a.a. and % a.d. sit side by side                   |
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
| [Performance](/performance)            | Who beat their peers, ranked **within** each asset class                                        | The return basis differs per class and is never mixed                                              |
| [Suspicious Deal Screens](/suspicious) | Four forensic patterns: zombie growth, evergreen aging, overdue certificates, captive vehicles  | Screens produce **signals, not findings** — every hit needs primary-source verification            |
| [Dormant Funds](/dormant)              | FI classes with zero subscriptions and redemptions for 3 months: empty shells vs parked capital | Three months is a **floor**; NULL flows disqualify rather than count as zero; FI only              |

### Operations

| Page                 | What it answers                                                                    | Watch out for                                                       |
| -------------------- | ---------------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| [Pipeline Ops](/ops) | Whether the ingest ran, whether it succeeded, and whether the data actually landed | A recent `ok` over a stale table is the disagreement worth catching |

---

## What Is in the Warehouse

> Row counts for the four largest ingested tables. Per-table freshness and the
> full audit log are on [Pipeline Ops](/ops).
>
> **≈** — Postgres planner estimates (`pg_class.reltuples`), within ~1% of the
> true count since the daily ingest runs `ANALYZE`. An exact `count(*)` would
> full-scan tens of millions of rows on every build.

<DataTable data={row_counts}>
  <Column id=dataset title="Dataset"/>
  <Column id=rows_est title="Rows (≈)" fmt=num0/>
</DataTable>

---

## How to Read This Dashboard

**Units live in the column title.** Scaling happens in SQL: `(R$mm)` is already
millions, `(%)` is already a percentage. Where CVM publishes a field whose scale it
does not document, the column is labelled **source units** and shown unconverted —
read those as rankings, not percentages.

**Blank is not zero.** Blank means not published, not filed, or not yet ingested.
Zero means the filing said zero. Nothing is carried forward, interpolated or imputed.

**Publication lag is structural.** CVM publishes monthly data one to two months in
arrears, so the newest month or two are legitimately thin. FIP files yearly, FIAGRO's
file begins 2025-05, and post-CVM-175 share-class splits break the CNPJ join ETF NAV
history depended on. None are pipeline failures; each is flagged where it bites.

**Coverage differs per field.** Registry names, investor splits, property detail and
securitisation lines are ingested to different depths. Every page states its coverage
before charting a partial field, so a thin table can be told from a thin market.

**Terminology.** "Net assets" is CVM's `vl_patrim_liq` — loosely called AUM elsewhere.
"Quotaholders" is `nr_cotst`, a count of positions rather than of distinct people.

---

## Want to know more?

**[What Silo serves](https://claude.ai/code/artifact/10fa2f4d-ce1f-48b1-aa31-064cdb0cb1dd)** — a plain-language walkthrough of what this
is and what the warehouse does and does not claim. Start here if you are not already
deep in Brazilian fund filings.

**[API docs](https://octo-98895abd.mintlify.site/)** — every number on this site is
queryable. Free and anonymous to read.

**[Sign in](/signin.html)** — a GitHub account raises the query ceilings (3 → 50 ids
per call, and a longer time budget). Nothing on this page requires it.
