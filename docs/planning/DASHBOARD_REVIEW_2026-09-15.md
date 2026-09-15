# Dashboard review — 2026-09-15

Page-by-page review of the live site (`https://silo-bz.vercel.app`, build of `main`
@ #213's dashboard code, data from the 06:00 UTC ingest), captured full-page with
headless Chromium after scrolling so Evidence's lazily rendered charts hydrate.
Each page: what it shows, findings tagged **wrong** / **unclear** / **stale** /
**fine**, and the fix with its cost. The systemic items and the two double-counting defects are fixed in the PR
this document ships with; everything else is listed for the owner to pick.

## Systemic (every page)

| # | Finding | Tag | Fix |
| --- | --- | --- | --- |
| S1 | Every page shows its title **twice**: Evidence renders the frontmatter `title` as an H1 above the page's own `# H1`. | wrong | `hide_title: true` beside `title:` on all 15 pages (this PR). |
| S2 | Every `<BigValue>` tile shows the **column name** as its title ("Aum Bn", "Admin Coverage Num1", "Selic Meta Num2", "Built At Utc") because the pages pass `label=`, which is not a BigValue prop; the prop is `title=`. 69 tiles. | wrong | `label=` → `title=` on every BigValue (this PR). |
| S3 | Wide `DataTable`s whose first column is a fund name (`/performance` Top 10, `/fi` Largest FI Funds, `/fii` Top 25, `/fidc` Most Delinquent / Subordination, `/suspicious`, `/dormant`) render **only the name column** in the visible width — the numbers are off to the right and the reader sees a list of names with no figures. | unclear | Per table: put the numeric columns before the name, or `<Column id=fund_name wrap=true>` / a `maxWidth`. Page-markdown only; ~10 tables. Owner to pick the convention. |
| S4 | `fact_fund_monthly` keeps each family's **raw period convention** (FI first-of-month, FIDC month-end, FIP 31-Dec). Any chart that groups on the raw `period` gets two x-points per month and draws a sawtooth to zero. Seen on `/` and `/industry`; the spine sources already normalise with `date_trunc('month', …)`. | wrong | `aum_by_entity.sql` normalised (this PR). `/industry` "Net Assets by Family — ex-FI absolute" (`industry_aum_trend` second chart) shows the same FIDC spikes — check whether that chart reads a raw-period column. |

## Per page

### `/` — Brazilian Fund Industry Data
- Shows: six tiles, net assets by family (12 mo, stacked area), FIDC sector delinquency (12 mo), page index, row counts, reading guide.
- **wrong** — "Net Assets by Fund Family — Last 12 Months" is a sawtooth (S4). Fixed in this PR.
- **fine** — delinquency line, tiles (after S2), the reading guide.

### `/industry` — Industry Structure
- **wrong** — "Average Quotaholders per Fund by Class": every line **collapses toward zero at the last month**. Source `industry_quotaholder_by_class.sql` ends at `latest_complete_period('fi')`, so the month is "complete" for FI filings, but `quotaholder_trend_by_class()` divides by funds *with data* in that month and the class attribution (`dim_fund_category`) or `nr_cotst` evidently lags a month. Check: run `quotaholder_trend_by_class(<p_end-1 month>, <p_end>)` and compare `n_funds_with_data` between the two months; if the last month is a fraction of the previous, end the spine one month earlier for this chart (or require `n_funds_with_data ≥ 50 % of the prior month`). SQL-only.
- **wrong** — "Net Assets by Family — 36 Months (ex-FI absolute)": FIDC band spikes (S4 pattern). Check the second query in `industry_aum_trend.sql`.
- **fine** — share-of-total area, concentration table, asset-class composition (ends Jul, complete bands), FI net flow bars, fund formation, FIP yearly bars, FIAGRO line and table.

### `/managers` — Managers
- **fine** — coverage disclosure first, both league tables, flow table, universes. Only S2 (tiles) applies.

### `/fund` — Fund Explorer
- **wrong** — "Quotaholder Count by Fund": one fund's line **oscillates between ~100k and ~0 every other month**. Either `nr_cotst` is null in alternate months and the chart draws null as zero (then `handleMissing=gap` on the LineChart, or a `where nr_cotst is not null` in `fund_nav_series.sql`), or the daily file carries the count only on some month-ends (then the source should take the month's last non-null). Check the fund's rows in `fact_fund_monthly` first.
- **wrong** — "Cumulative Return, Rebased" shows the same +250 % / −50 % fund as `/performance` (shared `fund_perf_series`); the guard proposed there fixes both.
- **unclear** — S3 on the four tables (names and month only in view).
- **fine** — search box, universe by asset class (bars + table with "Latest Month" per family), profile cards, net assets by fund, monthly net flow, redemption pressure.

### `/performance` — Fund Performance
- **wrong** — "Asset-Class Summary" Other FI: *Best Performance 1,070,760.11 %* and the rebased-return chart has one fund at +250 % then −50 %: `last / first − 1` on `vl_quota` across a quota split, amortisation or a re-based series. The basis is right for a NAV return but needs a guard: exclude a fund's window when any single-month quota move exceeds a threshold (e.g. |r| > 50 %) or when `vl_quota` is discontinuous, and say so in the note. Analytical-function change (`fund_performance_ranking` / `_series`), plus a page note.
- **unclear** — S3 (Top 10 table shows names only); Real Estate *Avg 0.02 / Best 10.19* are dividend-yield percentages with no unit in the column header.
- **fine** — the "How Performance Is Measured" section is exactly the honesty the page needs.

### `/fi` — FI Industry
- **wrong** — "FI Investor Base by Class" has a one-month spike where one class jumps and falls back (Feb 2026), and "FI Book by Asset Type" drops to zero for one month (Apr 2026): a month with a partial CDA / PERFIL filing drawn as a value. Stacked charts need every band; the spine rule says a month is drawn only if every band has a value. Sources `fi_investor_mix.sql`, `fi_allocation.sql`: skip months whose row count is below the neighbours' (or below `latest_complete_period('fi')`-style completeness for `cvm_fi_perfil` / `cvm_fi_cda`, which have none). SQL-only, but needs a rule.
- **unclear** — the page tile says *Latest Period 2026-08-01* and the Investor Mix tile *Latest Period 2026-08-31* for the same month: two period conventions side by side (S4's cousin). Normalise the displayed period to first-of-month in `fi_perfil_coverage.sql`.
- **unclear** — S3 on "Largest FI Funds".
- **fine** — net assets, monthly net flow, daily flow (120 d, ends at the last session), cumulative flow, quotaholder positions, retail share, concentration screen.

### `/fidc` — FIDC Credit Monitor
- **unclear** — "Subscriptions vs Redemptions by Month" and "Net Tranche Flow" are dominated by a single month's spike; either a real one-off (a large FIDC's issuance) or a duplicated tranche-flow row. Check the month's top contributors in `cvm_fidc_tranche_flows`; if real, a note; if duplicated, the `fidc_tranche_flows.sql` grouping.
- **unclear** — S3 on Most Delinquent, Tranches Missing Target, Subordination tables.
- **fine** — sector delinquency (24 mo), aging buckets, performing vs delinquent, remaining-term area, promised-vs-realised bars, median tranche performance, subordinated share.

### `/fii` — FII Market
- **wrong** — "FII Monthly Dividend Yield Distribution": y-axis to **2,500 %**. `yield_distribution.sql` and `top_fii_yield.sql` multiplied `pct_dividend_yield_mes` by 100, but CVM publishes the field already in percent (the API's `yield` metric says "as published"). Median FII yield is ~1 %/month; the chart showed ~150. Fixed in this PR (both sources).
- **unclear** — "Rows Single Asset Over 50pct: 0" tile — a zero that may be a real answer or an unpopulated `pr_*` field; the note says CVM leaves it blank for a minority. Confirm with a count of non-null `pr_*` before showing the tile.
- **unclear** — S3 on Top 25.
- **fine** — FII vs FIAGRO, income declared, payout share, filing-coverage table, property explorer.

### `/securit` — Securitization
- **wrong** — "Receivables Collected vs Total Paid Out": the last point **drops to zero** (a partly filed newest month). `securit_waterfall.sql` ends at `max(data_referencia)`, which the spine round set because securit has no completeness model. Options: end one month before `max(data_referencia)` unconditionally, or end at the last month whose row count is ≥ 50 % of the prior month's. Owner's call; SQL-only.
- **fine** — outstanding value by family, inadimplente share (flat 0 — real), maturity wall (forward ladder, allowlisted), payments by priority, ratings, subordination, distressed series, DFIN filings per year.

### `/etf` — ETF Market
- **fine** — brand/segment bars, index table, universe, exchange volume / tickers / median close from the tape (no cliffs), snapshot tiles and table. Nothing to change beyond S2.

### `/macro` — Macro Context
- **wrong** — Bid-ask table: the `ARS` row shows *Latest Quote 1970-01-01* with 0 observations — a null date rendered as the epoch. `macro_fx_latest.sql`: emit the date as `null` (or text) for series with no rows rather than letting the max() null through a date format.
- **fine** — SELIC target, SELIC diária vs CDI, inflation monthly changes, PTAX, Focus median and dispersion (24 mo), latest Focus per endpoint, SGS inventory.

### `/markets` — B3 Markets
- **fine** — every chart ends at the last complete month (Aug) with no cliff: monthly volume standard vs odd lot, distinct tickers, volume by instrument type, ETF vs FII quota volume, option premium, option series. Most-traded table shows all columns. Only S2 (tiles).

### `/suspicious` — Suspicious Deal Screens
- **wrong** — "Overdue Securitisation Series": the **same row thirty times** (`BRECOACRA1C2`, 2016-08-15, 374.0, across 3 pages). `cvm_securit_serie` holds one row per series *per monthly filing* (`data_referencia` is in the key), and `fraud_screen_overdue_securit()` screened every filing instead of each series' newest one — which also meant a series whose latest filing says *Liquidado* still appeared from an older *Adimplente* row. Fixed in this PR (`15_fraud_screens.sql`: `DISTINCT ON` the series key by newest `data_referencia`, then screen). Verified on the ephemeral Postgres: three filings of one CRA whose newest is Liquidado → not returned; two filings of a CRI still Adimplente → one row.
- **unclear** — S3 on the three fund tables (names only in view).
- **fine** — thresholds stated per screen; the "signals, not findings" framing; the empty-table note.

### `/dormant` — Dormant Funds
- **fine** — definition stated first with the window dates, three 36-month series (no cliffs), parked capital by administrator, coverage tiles. S2 (tiles), S3 (the two fund tables).

### `/ops` — Pipeline Ops
- **wrong** — "Funds Reporting per Month by Family": the FI line **collapses to ~0 at the last month**. This is the page where lag is *supposed* to be visible, but a cliff to zero reads as an outage, not as "August is partly filed". Either end each family's line at its `latest_complete_period` and print the partial month's count in the freshness table beside it, or draw the last month as a hollow marker. `ops_coverage.sql` + a note; owner's call.
- **unclear** — "Table Freshness": `cvm_fip_periodic` *Days Stale −107* — the yearly row is keyed 31-Dec of the current year, so the staleness is negative. Show "yearly (2026-12-31)" for period-year tables instead of a negative number. `ops_table_freshness.sql`.
- **fine** — health strip, rows per day, run status per day, freshness per entity, status breakdown, most recent runs.

## What this PR fixes

S1, S2, S4 (home chart), the FII yield scaling and the duplicated overdue-securit
rows. All but the last are under `dashboard/`, so it builds one preview; the
production rebuild after merge is the verification: `/` shows one H1 and a smooth
stacked area; `/managers` tiles read "Registry Rows w/ Administrator (%)"; `/fii`
yield distribution reads in single-digit percent; `/suspicious` lists each overdue
series once (after the nightly analytical apply re-creates the function).

## Not in this PR (owner to pick)

S3 (table layout convention), the `/industry` quotaholder cliff and ex-FI spikes, the
`/performance` return guard, the `/fi` partial-month bands and period label, the
`/securit` newest-month rule, the `/macro` epoch date, the `/fii` zero tile, the
`/fidc` spike check, the `/ops` last-month cliff and negative staleness.
