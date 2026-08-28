---
title: Brazilian Fund Industry Data
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

```sql fund_headline
select * from supabase.fund_headline
```

```sql ops_health
select * from supabase.ops_health
```

```sql aum_by_entity
select * from supabase.aum_by_entity
```

```sql fidc_delinquency
select * from supabase.fidc_delinquency
```

```sql row_counts
select * from supabase.row_counts
```

# Brazilian Fund Industry Data

> A public-data record of the Brazilian fund industry — net assets, flows,
> delinquency, tranche structure and payout behaviour — assembled from CVM and
> BACEN open data and refreshed daily. It is built for checking claims against
> filings, not for choosing investments: there is no advice, no rating and no
> recommendation anywhere on this site.
>
> Everything shown is what the filings say. Where a field has not been published,
> not been ingested, or is ambiguous in the source, the page says so and leaves
> the cell blank rather than filling it with an estimate.

<BigValue data={fund_headline} value=funds_tracked label="Funds Tracked" fmt=num0/>
<BigValue data={fund_headline} value=aum_bn label="Net Assets (R$bn)" fmt=num0/>
<BigValue data={fund_headline} value=investor_positions label="Quotaholder Positions" fmt=num0/>
<BigValue data={ops_health} value=rows_7d label="Rows Ingested (7d)" fmt=num0/>
<BigValue data={ops_health} value=hours_since_last_run label="Hours Since Last Ingest" fmt=num1/>

> Net assets are each fund's most recent reported `vl_patrim_liq`, summed — so
> the total is latest-available per fund, not an as-of-one-date figure. Quotaholder
> positions are summed `nr_cotst` and count **positions, not people**: one investor
> in three funds counts three times, and FIDC and FIP report no holder count at
> all. If **Hours Since Last Ingest** is much above 30, the daily cron has stopped
> and every number on the site is older than it looks — check
> [Pipeline Ops](/ops).

---

## Start Here

Three questions the data can answer, and where each is answered:

- **How big is the industry, and who controls it?** → [Industry Structure](/industry)
  for size, concentration and formation; [Managers](/managers) for the
  administrator and gestor league tables.
- **Is any particular fund in trouble?** → [Fund Explorer](/fund) to find it and
  follow its net assets, flows and return; [Performance](/performance) to see how
  it ranked against its own asset class.
- **Where is credit deteriorating?** → [FIDC Credit Monitor](/fidc) for
  receivables funds, [Securitization](/securit) for CRI/CRA certificates, and
  [Suspicious Deal Screens](/suspicious) for the specific patterns worth a second
  look.

---

## Industry Net Assets by Family — 12 Months

> The five CVM fund families stacked. FI dominates by an order of magnitude, so
> the other four are readable only as the thin bands at the top; the same series
> over 36 months, split out per family, is on [Industry Structure](/industry).
>
> FIP files **yearly** and is mapped to 31-Dec of its reporting year, so it
> contributes to one month and is absent from the other eleven. That is a filing
> grain, not a collapse in private-equity assets.

<AreaChart
  data={aum_by_entity}
  x=period
  y=aum_bn
  series=entity_type
  type=stacked
  yAxisTitle="Net Assets (R$bn)"
  title="Net Assets by Fund Family — Last 12 Months"
/>

---

## FIDC Sector Delinquency — 12 Months

> Overdue receivables as a share of FIDC net assets, across every FIDC that filed
> both an aging table and a monthly report. This is the single most load-bearing
> risk series on the site: it is the asset side of the receivables-fund industry
> marking itself.
>
> It is a **sector aggregate and hides everything about distribution** — a stable
> line is consistent with a handful of funds deteriorating badly while the rest
> improve. The 24-month series, the aging buckets behind it, and the fund-level
> ranking are on [the FIDC Credit Monitor](/fidc).

<LineChart
  data={fidc_delinquency}
  x=period
  y=delinquency_rate_num1
  yAxisTitle="Delinquency (%)"
  title="FIDC Sector Delinquency Rate"
/>

---

## Pages

### Industry-wide

| Page                            | What it answers                                                                                                                   | Watch out for                                                                                      |
| ------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| [Industry Structure](/industry) | Size, concentration (HHI and top-N share), fund formation, investor base, composition by asset class, plus FIP and FIAGRO by name | Families are measured at their **own** latest period; FIP's grain is yearly                        |
| [Managers](/managers)           | Administrator and gestor league tables by net assets and by net flow                                                              | Built on registry names, which are **sparsely populated** — the page publishes the size of the gap |
| [Fund Explorer](/fund)          | The searchable universe, then per-fund net assets, quota, return and flow                                                         | Only the largest funds carry per-fund time series; the site is static                              |
| [Performance](/performance)     | Who beat their peers, ranked **within** each asset class                                                                          | The return basis differs per class and is never mixed                                              |

### By asset class

| Page                         | What it answers                                                                                               | Watch out for                                                                                   |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| [FI Industry](/fi)           | Open-ended funds: daily flows, quotaholder base, investor mix, portfolio allocation, largest funds            | CDA allocation is a **directional mix, not a market-value census**                              |
| [FIDC Credit Monitor](/fidc) | Receivables funds: delinquency, both aging bands, tranche promised-vs-realised, subordination, tranche flows  | Raw CVM performance percentages carry extreme outliers — aggregates are medians                 |
| [FII Market](/fii)           | Real-estate funds: net assets, dividend-yield distribution, payout coverage, individual properties            | Property detail is partial by construction; the coverage tiles say how partial                  |
| [Securitization](/securit)   | CRI / CRA / OTS certificates: outstanding value, maturity wall, payment waterfall, ratings, distressed series | These are **not funds**; "reported value" is stock outstanding, not new issuance                |
| [ETF Market](/etf)           | Listed ETFs by provider, segment and tracked index, plus a scraped market snapshot                            | ETFs are carved out of the fund universe; NAV/return history is largely **absent post-CVM-175** |

### Context and scrutiny

| Page                                   | What it answers                                                                                | Watch out for                                                                           |
| -------------------------------------- | ---------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| [Macro Context](/macro)                | SELIC, CDI, inflation, PTAX and the BACEN Focus consensus                                      | Units are BACEN's and are **not converted** — % a.a. and % a.d. sit side by side        |
| [B3 Markets](/markets)                 | Exchange session prints from the COTAHIST tape: volume by board and instrument type, options   | Quotes are **unadjusted** and some papers quote per lot (`fator_cotacao` ≠ 1)           |
| [Suspicious Deal Screens](/suspicious) | Four forensic patterns: zombie growth, evergreen aging, overdue certificates, captive vehicles | Screens produce **signals, not findings** — every hit needs primary-source verification |
| [Pipeline Ops](/ops)                   | Whether the ingest ran, whether it succeeded, and whether the data actually landed             | A recent `ok` over a stale table is the disagreement worth catching                     |

---

## What Is in the Warehouse

> Row counts for the four largest ingested tables — a crude but honest measure of
> depth. Per-table freshness, per-entity ingest status and the full audit log are
> on [Pipeline Ops](/ops).
>
> **≈** — these are Postgres planner estimates (`pg_class.reltuples`), not exact
> counts. The daily ingest runs `ANALYZE` after every upsert, so they track the
> true count within ~1%; an exact `count(*)` here means a full scan of tens of
> millions of rows on every site build.

<DataTable data={row_counts}>
  <Column id=dataset title="Dataset"/>
  <Column id=rows_est title="Rows (≈)" fmt=num0/>
</DataTable>

---

## How to Read This Dashboard

**Units live in the column title.** Scaling happens in SQL, so a column headed
`(R$mm)` is already in millions and a column headed `(%)` is already a percentage.
Where CVM publishes a field whose scale it does not document — several `PR_` and
`índice` fields do exactly this — the column is labelled **source units** and is
shown unconverted. Read those as rankings, not as percentages.

**Blank is not zero.** A blank cell or a gap in a line means the figure was not
published, not filed, or not yet ingested. Zero means the filing said zero. No
value on this site is carried forward, interpolated or imputed.

**Publication lag is structural.** CVM publishes its monthly datasets one to two
months in arrears, so the newest month or two are legitimately thin. FIP files
yearly, FIAGRO's monthly file begins only in 2025-05, and post-CVM-175 share-class
splits break the CNPJ join that ETF NAV history depended on. None of these are
pipeline failures, and each is flagged where it bites.

**Coverage differs per field.** Registry names, investor splits, property detail
and securitisation statement lines are each ingested to a different depth. Every
page that depends on a partial field states its coverage before it draws a chart
from it, so a thin table can be told apart from a thin market.

**Terminology.** "Net assets" throughout is CVM's `vl_patrim_liq` (patrimônio
líquido) — the figure loosely called AUM elsewhere. "Quotaholders" is `nr_cotst`,
a count of positions in a fund rather than of distinct people.
