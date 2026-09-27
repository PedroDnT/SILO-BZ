# DUSTIN-BR: data sources for a Brazilian rates-regime model

The smallest set of market data SILO would need to support a research project
inspired by HSBC's DUSTIN framework: estimate, with probabilities, the direction
and regime of the Brazilian interest-rate curve about 21 trading days ahead,
from Brazilian rates, inflation, FX, global rates, a risk regime, sovereign risk,
commodities, momentum and realised volatility.

This document is Stage 1: what SILO already holds, what is missing, which
sources were tested and which were chosen. It was written **before** any
ingestion code. No model is built here.

Everything marked _measured_ was fetched from the stated URL on 2026-09-26/27
from a cloud container. Anything not measured is marked as an assumption or
as unverified. An unknown stays unknown.

---

## 1. What SILO already holds

Audited against `CLAUDE.md`, `README.md`, `docs/DATA_INVENTORY.md`,
`docs/planning/COMPETITIVE_GAPS.md`, `docs/planning/INSTRUMENTS.md`,
`src/pipeline/bacen_pipeline.py` (`SGS_SERIES`, `INFLATION_SERIES`,
`PTAX_CURRENCIES`, `EXPECTATIVAS_*`), `src/store/schema.sql`, the migrations,
`api.coverage()` and the ingest workflows.

| Need                          | Status        | Where                                                             | Notes                                                                                                                        |
| ----------------------------- | ------------- | ----------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| SELIC target                  | **existing**  | `bacen_sgs` 432, daily per calendar day                           | published **ahead** to the next Copom date (`api.coverage()` note), so a row dated in the future is not a future observation |
| SELIC effective / CDI         | **existing**  | `bacen_sgs` 11, 12                                                | % per business day, not annualised                                                                                           |
| IPCA and components           | **existing**  | `bacen_sgs` (26-code set), `ibge_ipca_item_monthly`               | monthly, dated the 1st of the reference month; IPCA from 1980 once the SGS history load has run                              |
| Inflation expectations        | **existing**  | `bacen_expectativas` (Focus)                                      | keyed on the survey date. **Not point-in-time as stored**, see §8                                                            |
| Selic expectations            | **existing**  | `bacen_expectativas` (`ExpectativasMercadoSelic`, annual `Selic`) | same caveat                                                                                                                  |
| USDBRL                        | **existing**  | `bacen_sgs` 1 and `bacen_ptax` (USD)                              | PTAX, the BCB fixing, not a market close                                                                                     |
| Other macro                   | **existing**  | IGP-M 189, INPC 188, monthly GDP 4380, EURBRL                     | none needed for the core set                                                                                                 |
| Brazilian equities            | **existing**  | `b3_cotahist` (cash tape, unadjusted)                             | stock prices only                                                                                                            |
| Ibovespa level                | **missing**   | none                                                              | COTAHIST carries no index levels; `b3_index_portfolio` has constituents only. Not needed for the core set (parking lot)      |
| DI1 futures per contract      | **missing**   | none                                                              | `INSTRUMENTS.md` Phase B, never built                                                                                        |
| B3 reference curve (DI x pré) | **missing**   | none                                                              | `INSTRUMENTS.md` Phase C, never built                                                                                        |
| US Treasury curve             | **missing**   | none                                                              |                                                                                                                              |
| VIX                           | **missing**   | none                                                              |                                                                                                                              |
| MOVE                          | **missing**   | none                                                              | proprietary, see §3.C                                                                                                        |
| Sovereign risk                | **missing**   | none                                                              | see §3.D                                                                                                                     |
| Commodities                   | **missing**   | none                                                              |                                                                                                                              |
| DI constant-maturity points   | **derivable** | from the B3 reference curve or DI1 contracts                      | research code, not stored                                                                                                    |
| Slopes, curvature             | **derivable** | from the constant-maturity points                                 | research code                                                                                                                |
| Momentum, realised vol, corr  | **derivable** | from any daily series above                                       | research code                                                                                                                |
| Breakeven inflation           | **derivable** | B3 `DIC` curve (DI x IPCA) from the same reference-rate file      | parking lot: one config value if wanted                                                                                      |
| Rates-volatility proxy        | **derivable** | realised vol of UST and DI yield changes                          | substitute for MOVE, §3.C                                                                                                    |

Two things found during the audit that shape the design:

- **`bacen_sgs.fetched_at` is not a publication time.** The upsert never sends
  it, so it keeps the first insert time. For history it is the backfill date.
  Point-in-time availability for history therefore has to come from each
  source's publication rule (§8), not from this column.
- **The `anon` revoke sweep is by table-name prefix** (`12_grants_and_rls.sql`:
  `cvm_|bacen_|ibge_|fnet_|b3_|anbima_|cia_|etf_|…`). A new landing table must
  use a covered prefix or extend the sweep, or it becomes readable through
  PostgREST.

---

## 2. What is missing

| Dataset                  | Priority | Why the model needs it                                              |
| ------------------------ | -------- | ------------------------------------------------------------------- |
| DI1 futures per contract | 1        | the target itself (curve level, slope, curvature) and its liquidity |
| US Treasury par curve    | 2        | global rates level and slope                                        |
| VIX                      | 3        | global risk regime                                                  |
| Sovereign-risk proxy     | 4        | Brazil's credit premium                                             |
| Commodities              | 5        | terms of trade, BRL and inflation pass-through                      |
| MOVE or substitute       | 6        | global rates volatility                                             |

---

## 3. Candidate sources, tested

Ranked by authority, depth, stability, reproducibility, machine access,
licensing and maintenance cost. "Selected" means ingested in Stage 2.

### A. DI1 futures and the DI curve

| Dataset          | Candidate source                                                                           | Official? | Frequency | Earliest history                            | Update lag                                    | Access                                             | Auth | Licence / access concerns                            | Reliability                                                                              | Selected?                     |
| ---------------- | ------------------------------------------------------------------------------------------ | --------- | --------- | ------------------------------------------- | --------------------------------------------- | -------------------------------------------------- | ---- | ---------------------------------------------------- | ---------------------------------------------------------------------------------------- | ----------------------------- |
| DI1 per contract | **B3 Price Report `BVBG.086.01`** (`pesquisapregao/download?filelist=PRyymmdd.zip`)        | yes       | session   | **2018-01-02** (_measured_)                 | same evening (_measured_: 18:37 to 20:31 BRT) | zip of zip of XML, 1 to 4 intraday versions        | none | public B3 file; SILO already republishes B3 COTAHIST | high                                                                                     | **yes**                       |
| DI curve         | **B3 reference rates, `TaxaSwap.txt`** (`pesquisapregao/download?filelist=TSyymmdd.ex_`)   | yes       | session   | **2008-01-02** (_measured_; older untested) | same evening                                  | zip → self-extracting exe → zip → fixed-width text | none | same                                                 | high; format unchanged 2008 to 2026 (_measured_: 72-char rows)                           | **yes** (curves `PRE`, `DOC`) |
| DI1 per contract | BDI table `ConsolidatedTradesDerivatives` (`arquivos.b3.com.br/bdi`)                       | yes       | session   | D-21 only (catalog `limitDate`)             | same day                                      | CSV export (the `b3_bdi_fetcher` contract)         | none | same                                                 | high, but no history                                                                     | no (redundant with PR)        |
| DI1 settlement   | legacy "Ajustes do pregão" page (`www2.bmf.com.br/…/lum-ajustes-do-pregao-ptBR.asp`)       | yes       | session   | was long                                    | n/a                                           | HTML                                               | none | n/a                                                  | **dead**: B3 moved it to the BDI on 2025-12-10 (B3's own notice); _measured_: empty body | no                            |
| DI1 OHLC/OI      | legacy "Sistema Pregão" bulletin (`www2.bmf.com.br/…/SistemaPregao1.asp`)                  | yes       | session   | was long                                    | n/a                                           | HTML                                               | none | n/a                                                  | **dead**: _measured_ timeout, then `SQL Server does not exist`                           | no                            |
| DI curve         | legacy "Taxas referenciais" page (`www2.bmf.com.br/…/lum-taxas-referenciais-bmf-ptBR.asp`) | yes       | session   | was long                                    | n/a                                           | HTML                                               | none | n/a                                                  | **dead**: same database error                                                            | no                            |
| DI swap tenors   | BCB SGS swap DI x pré series                                                               | BCB copy  | daily     | 1999                                        | n/a                                           | SGS REST                                           | none | none                                                 | **stopped**: series 7806 ends 2019-09-30 (_measured_)                                    | no                            |
| DI1              | Bloomberg / LSEG / B3 UP2DATA                                                              | vendor    | tick      | long                                        | real time                                     | terminal / paid feed                               | paid | licensed                                             | high                                                                                     | no (not free)                 |

**What the two B3 files give, measured on 2026-09-25:**

- The **Price Report** has, per DI1 contract (`DI1F27` …): `TradQty` (number
  of trades), `FinInstrmQty` (contracts traded), `NtlFinVol` (BRL notional),
  `OpnIntrst` (open interest), `FrstPric` / `MinPric` / `MaxPric` /
  `TradAvrgPric` / `LastPric` (**quoted as rates**, % a.a.),
  `BestBidPric` / `BestAskPric`, `AdjstdQt` (settlement **PU**) and
  `AdjstdQtTax` (settlement **rate**), the previous settlement pair,
  `AdjstdQtStin`, `VartnPts`, `AdjstdValCtrct`, and the daily limits. 45 DI1
  contracts that day, 38 on 2018-01-02. A contract that did not trade has no
  prices and no `TradDtls`, but still has settlement and open interest. The
  zip held four XML versions (18:37, 19:04, 19:22, 20:31); DI1 values were
  identical in all four. Every PR date from 2008 to 2017 that was tried
  (2008-01-02 through 2017-12-28) returned a 22-byte empty zip.
- The **reference-rate file** has one row per (curve, vertex): curve code,
  calendar days, business days, rate × 10⁷, and whether the vertex is fixed
  (`F`) or moving (`M`). 54 curves in 2008, 116 in 2026. The `PRE` curve
  (DI x pré, 252-business-day basis) had 114 vertices on 2008-01-02 and 286
  on 2026-09-25, out to 5,580 and 12,379 calendar days. `(curve, trade date,
calendar days)` is unique in every file tried.
- **`PRE` carries a moving vertex at every DI1 maturity, equal to that
  contract's settlement rate.** Checked on 2026-09-25: DI1F27 (13.55),
  DI1J27 (13.545), DI1F29 (13.814), DI1F32 (13.98) and DI1F37 (13.97). The
  business days implied by each contract's PU and rate
  (`PU = 100000 / (1 + r)^(du/252)`) land exactly on a `PRE` vertex with the
  same rate. Each vertex's calendar days give its maturity as
  `trade_date + calendar_days`, with no holiday calendar needed.

**Consequence.** B3's own `PRE` curve gives one consistent, official
construction from 2008 to today, anchored on DI1 settlement rates. The
per-contract Price Report adds OHLC, volume, open interest and trade counts
from 2018. **No splice is needed**: constant-maturity points come from the
same `PRE` file in every year, and the 2018+ contract data serves liquidity
features and cross-checks.

**Settlement rate, not price.** DI1 is quoted and settled in rate terms; the PU
is a function of the rate and the business-day count. Research code uses
`AdjstdQtTax` (Price Report) and the `PRE` rate (reference file) directly.
PU is stored as published but never used to infer a rate.

**Naming conventions** (B3 contract specification, not re-derived): root `DI1`,
month letter F G H J K M N Q U V X Z = Jan to Dec, two-digit year. Maturity is
the first business day of the contract month. The ticker is stored as the
natural key and never decomposed at ingest (the `INSTRUMENTS.md` rule). The
ingest keeps outright contracts only (`^DI1[FGHJKMNQUVXZ][0-9]{2}$`); strategy
and spread tickers are dropped and counted.

### B. US Treasury rates

| Dataset       | Candidate source                                                                                                                                    | Official? | Frequency    | Earliest                         | Update lag      | Access              | Auth | Licence                        | Reliability                                                                | Selected?           |
| ------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- | --------- | ------------ | -------------------------------- | --------------- | ------------------- | ---- | ------------------------------ | -------------------------------------------------------------------------- | ------------------- |
| UST par curve | **U.S. Treasury, Daily Treasury Par Yield Curve Rates** (`home.treasury.gov/…/daily-treasury-rates.csv/<year>/all?type=daily_treasury_yield_curve`) | yes       | business day | 1990 (Treasury); 2008 _measured_ | same US evening | one CSV per year    | none | US government work             | high; columns change over time (_measured_: 2026 adds `1.5 Month`, `4 Mo`) | **yes**             |
| DGS2/5/10/30  | FRED (Board of Governors H.15)                                                                                                                      | copy      | business day | 1962                             | next day        | CSV / API (API key) | key  | H.15 copies Treasury's numbers | not reachable from this container (_measured_: HTTP/2 error, empty reply)  | no (secondary copy) |
| UST           | Yahoo Finance `^TNX`                                                                                                                                | no        | —            | —                                | —               | scrape              | —    | ToS                            | —                                                                          | no                  |

The Treasury file is the primary source. All tenors are stored as published
(1 Mo to 30 Yr); the model reads 2Y, 5Y, 10Y and 30Y. Two known regime notes:
Treasury changed its curve methodology to monotone convex in December 2021,
and the 30-year was not published from February 2002 to February 2006
(before this sample).

### C. VIX and MOVE

| Dataset | Candidate source                                                                | Official? | Frequency    | Earliest                | Update lag | Access                      | Auth | Licence                                                                | Reliability | Selected?                      |
| ------- | ------------------------------------------------------------------------------- | --------- | ------------ | ----------------------- | ---------- | --------------------------- | ---- | ---------------------------------------------------------------------- | ----------- | ------------------------------ |
| VIX     | **Cboe `VIX_History.csv`** (`cdn.cboe.com/api/global/us_indices/daily_prices/`) | yes       | business day | 1990-01-02 (_measured_) | same day   | one CSV, OHLC               | none | Cboe states **no redistribution terms** on the page, only a disclaimer | high        | **yes**, stored **not served** |
| VIX     | FRED `VIXCLS`                                                                   | copy      | business day | 1990                    | next day   | CSV / API                   | key  | FRED marks it Cboe copyright                                           | copy        | no                             |
| MOVE    | ICE BofA MOVE Index                                                             | yes (ICE) | business day | 1988                    | same day   | ICE Data Indices, terminals | paid | **proprietary**                                                        | high        | **no**                         |
| MOVE    | Yahoo `^MOVE`                                                                   | no        | —            | —                       | —          | scrape                      | —    | republication of licensed data                                         | —           | **no**                         |

**MOVE is not ingested.** No public source carries it under terms that permit
automated ingestion. The substitute is **derived, not ingested**:

- **global rates vol**: 21- and 63-day realised volatility of daily changes in
  the UST 10Y par yield, in bp;
- **local rates vol**: the same on DI 1Y and 2Y constant-maturity rates.

Economic motivation: MOVE is the implied volatility of Treasury options, the
market price of rates uncertainty. Realised yield volatility measures the same
object after the fact. **What is lost**: forward-looking information and the
volatility risk premium; realised vol reacts only after moves happen, so it
lags regime changes that implied vol anticipates. The column is named
`rates_vol_proxy` so nobody mistakes it for MOVE.

### D. Brazil sovereign credit risk

| Dataset                          | Candidate source                                                                  | Official?   | Frequency    | Earliest                | Update lag   | Access             | Auth | Licence          | Reliability                                                                                 | Selected?                    |
| -------------------------------- | --------------------------------------------------------------------------------- | ----------- | ------------ | ----------------------- | ------------ | ------------------ | ---- | ---------------- | ------------------------------------------------------------------------------------------- | ---------------------------- |
| Brazil 5Y CDS                    | IHS Markit (S&P Global), ICE, via Bloomberg / LSEG                                | vendor      | daily        | ~2001                   | same day     | terminals          | paid | **proprietary**  | high                                                                                        | **no**                       |
| EMBI+ Brazil spread              | J.P. Morgan, republished by IPEA (`ipeadata` series `JPM366_EMBI366`)             | vendor copy | business day | 1994-04-29 (_measured_) | —            | OData JSON         | none | J.P. Morgan data | **stopped 2024-07-30** (_measured_: last observation; 145 rows in 2024, ~255 a year before) | **no**                       |
| Onshore USD rate (cupom cambial) | **B3 reference curve `DOC`** (DI x dólar, clean coupon), same `TaxaSwap.txt` file | yes         | session      | 2008-01-02 (_measured_) | same evening | same file as `PRE` | none | public B3 file   | high                                                                                        | **yes** (as the proxy input) |

**No free equivalent of CDS exists that we could verify.** The proxy is the
**onshore dollar premium**: B3's `DOC` curve (the onshore US-dollar interest
rate implied by DI and dollar futures) minus the UST yield of the same tenor.
It is a covered-interest-parity deviation: the extra dollar yield a lender
demands to hold dollars **inside Brazil**. Measured at 1 year it sits around
150 bp in 2008, 2017 and 2026 (DOC 360 days vs UST 1Y), which is the right
order of magnitude.

**What is lost relative to CDS**: the proxy mixes default risk with
convertibility and transfer risk, onshore dollar liquidity, and hedging
demand from exporters and banks. It can move on FX-flow shocks that are not
credit events. It has no standard 5-year point with CDS-like liquidity; the
long end of `DOC` is thin. Rate conventions differ: `DOC` is quoted by B3 as a
linear rate on a 360-day basis (**to verify** against B3's methodology before
modelling; the builder converts explicitly and says so), UST par yields are
semi-annual bond-equivalent. Call it `brazil_sovereign_risk_proxy`, never
"CDS".

EMBI+ via IPEA would be a useful one-off check of the proxy over 2008 to
2024-07, but a series that stopped is not worth an ingest (parking lot).

### E. Commodities

| Dataset               | Candidate source                                                       | Official?    | Frequency    | Earliest                      | Update lag                                                                                                     | Access                      | Auth                                              | Licence                | Reliability                                                                   | Selected?                             |
| --------------------- | ---------------------------------------------------------------------- | ------------ | ------------ | ----------------------------- | -------------------------------------------------------------------------------------------------------------- | --------------------------- | ------------------------------------------------- | ---------------------- | ----------------------------------------------------------------------------- | ------------------------------------- |
| Brent spot            | **EIA, Europe Brent Spot Price FOB (`RBRTE`)**, API v2                 | yes (US gov) | business day | 1987-05-20 (_measured_)       | **weekly**: released Wednesdays, data through the previous day (_measured_: release 9/23/2026, next 9/30/2026) | JSON API                    | API key (a public `DEMO_KEY` works, rate-limited) | US government work     | high                                                                          | **yes**                               |
| WTI spot              | EIA `RWTC`                                                             | yes          | business day | 1986                          | weekly                                                                                                         | same                        | same                                              | same                   | high                                                                          | no (redundant with Brent for Brazil)  |
| Broad commodity index | **BCB IC-Br** (SGS 27574 total, 27575 agro, 27576 metal, 27577 energy) | yes          | **monthly**  | 2008-01 at least (_measured_) | early next month (press reports a mid-week release; exact day **unverified**)                                  | SGS REST (existing fetcher) | none                                              | public                 | high                                                                          | **yes** (optional feature)            |
| Iron ore              | World Bank Pink Sheet (`CMO-Historical-Data-Monthly.xlsx`)             | yes          | monthly      | 1960                          | early next month                                                                                               | XLSX                        | none                                              | CC BY 4.0 (World Bank) | URL changes every release (_measured_: the link tried was a Dec-2025 edition) | no (IC-Br metal covers it for Brazil) |
| S&P GSCI, BCOM, CRB   | S&P, Bloomberg, LSEG                                                   | vendor       | daily        | long                          | same day                                                                                                       | terminals                   | paid                                              | proprietary            | high                                                                          | no                                    |

**The smallest defensible set is Brent (daily) plus IC-Br (monthly).** Brent is
the global energy price and the reference for Petrobras pricing, so it drives
Brazilian inflation and the fiscal outlook. IC-Br is the BCB's own index of
commodity prices **in reais** weighted for Brazil: about two thirds
agricultural, the rest energy and metals (iron ore dominates metals). It
captures the terms-of-trade channel that matters for BRL and for inflation
pass-through, which no single daily price does. It is monthly and lagged, so
it is an OPTIONAL regime feature, not a daily driver. No daily broad index is
freely available.

---

## 4. Selected sources

| Dataset                           | Source                                 | Stored in                     | Grain                           | Served via `api`? |
| --------------------------------- | -------------------------------------- | ----------------------------- | ------------------------------- | ----------------- |
| DI1 per contract                  | B3 Price Report `BVBG.086.01`          | `b3_futures_settlement` (new) | session × ticker                | no                |
| DI x pré curve, onshore USD curve | B3 `TaxaSwap.txt`, curves `PRE`, `DOC` | `b3_reference_rate` (new)     | session × curve × calendar days | no                |
| UST par curve                     | U.S. Treasury CSV                      | `mkt_series` (new)            | US business day × tenor         | no                |
| VIX OHLC                          | Cboe CSV                               | `mkt_series`                  | US business day × field         | no (licence)      |
| Brent spot                        | EIA API v2                             | `mkt_series`                  | business day                    | no                |
| IC-Br (4 series)                  | BCB SGS 27574 to 27577                 | `bacen_sgs` (existing)        | month                           | no                |

**Nothing new is served through schema `api` in this change.** Serving is a
separate decision: VIX's licence is unclear, and every new endpoint drags a
catalog entry, OpenAPI and the MCP contract with it. The landing tables are
covered by the `anon` revoke sweep. The research builder reads them with the
operator's database connection.

## 5. Rejected sources, and why

| Source                                         | Why rejected                                                                        |
| ---------------------------------------------- | ----------------------------------------------------------------------------------- |
| www2.bmf.com.br pages (ajustes, pregão, taxas) | retired by B3 on 2025-12-10; answer with database errors                            |
| BCB SGS swap DI x pré series                   | stopped in 2019                                                                     |
| BDI `ConsolidatedTradesDerivatives`            | 21-business-day retention; the Price Report carries the same fields with history    |
| FRED                                           | a secondary copy of Treasury, Cboe and EIA; primary sources exist; unreachable here |
| Yahoo Finance (`^TNX`, `^MOVE`, `^VIX`)        | not authoritative, republishes licensed data, ToS                                   |
| CDS (Markit, ICE), MOVE (ICE), GSCI, BCOM      | proprietary                                                                         |
| EMBI+ via IPEA                                 | stopped 2024-07-30                                                                  |
| World Bank Pink Sheet                          | monthly, URL changes per release; IC-Br metals covers iron ore for Brazil           |
| WTI                                            | redundant with Brent for this purpose                                               |

---

## 6. Historical coverage

| Series                                 | Class             | Starts                                      | Notes                                         |
| -------------------------------------- | ----------------- | ------------------------------------------- | --------------------------------------------- |
| DI constant-maturity 1Y/2Y/3Y/5Y (PRE) | **CORE**          | 2008-01-02                                  | from B3 `PRE`; older files untested           |
| DI slope, curvature                    | **CORE**          | 2008-01-02                                  | derived                                       |
| USDBRL (PTAX, SGS 1)                   | **CORE**          | before 2008 (existing)                      |                                               |
| UST 2Y/5Y/10Y/30Y                      | **CORE**          | 1990 (loaded from 2008)                     |                                               |
| VIX                                    | **CORE**          | 1990 (loaded from 2008)                     |                                               |
| Brent                                  | **CORE**          | 1987 (loaded from 2008)                     | weekly publication lag, §8                    |
| Sovereign proxy (DOC minus UST)        | **CORE**          | 2008-01-02                                  | derived                                       |
| Rates-vol proxy                        | **CORE**          | 2008 + 63 sessions                          | derived                                       |
| SELIC target                           | **CORE**          | before 2008 (existing)                      |                                               |
| IPCA                                   | **CORE**          | 1980 (existing, after the SGS history load) | monthly, lagged                               |
| IC-Br                                  | **OPTIONAL**      | 2008-01 at least                            | monthly, lagged                               |
| Focus expectations                     | **OPTIONAL**      | depends on the stored history               | needs the §8 lag; history may need a re-fetch |
| DI1 volume, open interest, trades      | **LATE-STARTING** | 2018-01-02                                  | Price Report history limit                    |
| DI1 per-contract OHLC                  | **LATE-STARTING** | 2018-01-02                                  | same                                          |

**Earliest date for a consistent CORE matrix: 2008-01-02**, subject to the
backfills in §10 actually landing. Rolling features consume their own
warm-up: 63-session features are first defined in early April 2008, and the
builder leaves them NULL until then rather than shortening the sample.

---

## 7. Licensing and access

- **B3** files are public downloads; SILO already republishes B3's COTAHIST.
  No login, cookie or token (_measured_). The Price Report is large: 12 MB zip,
  135 MB XML per version on 2026-09-25, so the backfill is bound by download
  and parse time, not rows.
- **U.S. Treasury** and **EIA**: US government works, public domain. EIA's API
  wants a key; a free one goes in the `EIA_API_KEY` secret. Without it the
  ingest uses EIA's public `DEMO_KEY`, which is rate-limited and logged as such.
- **Cboe**: the history page gives the file and a disclaimer, and no licence
  terms. Stored for research; **not served** until someone confirms
  redistribution terms with Cboe.
- **BCB SGS**: public, already ingested.

## 8. Point-in-time integrity

The builder produces one row per Brazilian session `t`: every value in it must
have been **public by the end of day t (Brasília)**. Each source gets an
explicit availability rule. Where the rule is an assumption, it is marked and
chosen to be conservative (later, never earlier).

| Series         | Observation date                           | Published                                                                                                    | Revised?                                | Rule used by the builder                                                                                          |
| -------------- | ------------------------------------------ | ------------------------------------------------------------------------------------------------------------ | --------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| DI (PRE, PR)   | B3 session                                 | same evening (_measured_ 18:37 to 20:31 BRT)                                                                 | settlement is final                     | available at t                                                                                                    |
| DOC            | B3 session                                 | same evening                                                                                                 | final                                   | available at t                                                                                                    |
| USDBRL (SGS 1) | business day                               | PTAX closes ~13:00 BRT                                                                                       | final                                   | available at t                                                                                                    |
| UST            | US business day                            | US evening, before 23:00 BRT                                                                                 | rare corrections (logged by the ingest) | as-of join: last UST date ≤ t                                                                                     |
| VIX            | US business day                            | US close                                                                                                     | final                                   | as-of join: last date ≤ t                                                                                         |
| Brent (EIA)    | business day                               | **weekly**, Wednesdays, through the previous day (_measured_)                                                | occasional revisions (logged)           | available the day after the **first Wednesday strictly after** the observation date (a Wednesday price waits a full week; the extra day absorbs holiday-shifted releases) |
| SELIC target   | calendar day, dated when in force          | ahead of time                                                                                                | no                                      | value dated t                                                                                                     |
| IPCA           | month M, dated the 1st                     | IBGE releases around the 10th of M+1                                                                         | no                                      | **assumption**: available from the 15th of M+1                                                                    |
| IC-Br          | month M, dated the 1st                     | early M+1 (exact day unverified)                                                                             | **unknown**                             | **assumption**: available from the 15th of M+1                                                                    |
| Focus          | survey day D (the stored `reference_date`) | **the Monday after D's week** (_measured_: on Sunday 2026-09-27 the newest daily value was dated 2026-09-18) | vintage not kept                        | available from the **Tuesday after D's week** (one day of buffer for holiday Mondays)                             |

Rules the builder enforces:

1. **Observation date and publication date are separate columns.** Every
   feature is joined on its `available_date`, never on its observation date.
2. **No blind forward fill.** An as-of join carries the last available value
   forward only within a staleness limit per source (5 sessions for daily
   series, 10 for Brent, 45 for monthly series); past it the feature is NULL
   and the gap is counted.
3. **No revised macro as point-in-time.** IPCA is not revised by IBGE. IC-Br
   revisions are unknown; until measured, IC-Br is OPTIONAL. SILO keeps no
   Focus vintages; a Focus value fetched later than its publication week may
   differ from what was public, which the coverage note already says.
4. **Contract data never leaks forward.** Constant-maturity points on day t
   use only the `PRE` vertices published for day t. No future listing, no
   future maturity and no later settlement is ever read.

---

## 9. Proposed schema

Following `DATA_MODELING.md`: grain first, long facts, natural keys straight
from source, named UNIQUE constraints, `ON CONFLICT DO UPDATE`.

```sql
-- B3 Price Report, one row per (session, outright futures ticker).
b3_futures_settlement (
    trade_date DATE, ticker TEXT,              -- UNIQUE (trade_date, ticker)
    instrument_id BIGINT,                      -- B3's own id, as published
    trades INT, contracts BIGINT, notional_brl NUMERIC, open_interest BIGINT,
    open_px, low_px, high_px, avg_px, close_px, best_bid, best_ask NUMERIC,  -- DI1: rates
    settlement_price NUMERIC, settlement_rate NUMERIC, settlement_status TEXT,
    prev_settlement_price NUMERIC, prev_settlement_rate NUMERIC, prev_settlement_status TEXT,
    variation_points NUMERIC, settlement_value_per_contract NUMERIC,
    report_created_at TIMESTAMP,               -- the XML's CreDtAndTm, local time as printed
    raw JSONB)

-- B3 reference rates (TaxaSwap), one row per (session, curve, vertex).
b3_reference_rate (
    trade_date DATE, curve TEXT, calendar_days INT,   -- UNIQUE (curve, trade_date, calendar_days)
    business_days INT, rate NUMERIC, vertex_type CHAR(1), vertex_code TEXT, curve_desc TEXT)

-- Non-Brazilian daily market series, long.
mkt_series (
    source TEXT, series_id TEXT, observation_date DATE,  -- UNIQUE (source, series_id, observation_date)
    value NUMERIC, unit TEXT,
    first_seen_at TIMESTAMPTZ DEFAULT now())             -- never sent by the upsert: SILO's own first sighting
```

DI futures get their own fact because a generic series table would lose the
contract grain (a ticker has open interest, settlement and a maturity; a
"series" does not). The reference curve is 2-D (date × tenor), so it is kept
out of any 1-D series table too (`INSTRUMENTS.md`: a curve is not a panel id).
`mkt_series` takes a new source as rows, not a migration. `mkt_` is added to
the revoke sweep. IC-Br stays in `bacen_sgs` as held-not-served series
(outside `SGS_SERIES`, so `api.macro_series`' registry is unchanged).

Row volumes: ~150 DI1 rows a day from 2018 (~0.1 M); `PRE` + `DOC` about 230
to 660 rows a day from 2008 (~2.5 M); `mkt_series` ~20 rows a day (~0.1 M).

## 10. Implementation plan

**Stage 2, ingestion** (in priority order, each with offline fixture tests):

1. `src/fetchers/b3_pesquisapregao_fetcher.py`: one downloader for `PR` and
   `TS` files. An empty zip is "not published" (logged `skipped`), not an error.
2. `src/parsers/b3_price_report.py` (streaming XML, the latest version in the
   zip, DI1 outright tickers, typed + `raw`) and
   `src/parsers/b3_taxa_swap.py` (fixed-width, strict layout check).
3. `src/fetchers/global_market_fetcher.py` + `src/parsers/global_market.py`:
   Treasury CSV (unknown column header raises), Cboe CSV, EIA API v2.
4. IC-Br: `RESEARCH_SGS_SERIES` in `bacen_pipeline.py`, fetched with the
   rest of SGS.
5. Migration 48 + `schema.sql`; `mkt_` in the revoke sweep.
6. `src/pipeline/market_pipeline.py` (`MarketIngestor`): `daily_update()`
   (last 7 calendar days of B3 files, current year of Treasury, trailing
   window of Cboe and EIA) and `backfill(source, start, end)`; one audit row
   per slice, revisions to stored values counted on the audit row.
7. Wiring: its own step in `daily_ingest.yml`, after the analytical layer
   (the FNET pattern: foreign hosts must not block the core run), and a
   `market_backfill.yml` dispatch (one year per job, `supabase-ingest`
   concurrency group).

**Data-quality checks** (in parsers and the ingest):

- duplicates: the natural key is unique within a file; a duplicate raises;
- impossible values: PU ≤ 0, rates outside (−5, 100) %, business days >
  calendar days, VIX ≤ 0, Brent ≤ 0 or > 1000 → row dropped and counted;
- schema changes: an unknown Treasury column, a TaxaSwap row that is not 72
  characters, a Price Report without `TradDt` → raise;
- dates: every row's date must equal the file's session date;
- missing sessions: DI and curve sessions are reconciled against the B3
  sessions `b3_cotahist` already holds (a research-builder check);
- stale observations: the builder's staleness limits (§8);
- outages: fetch failures raise and write an `error` audit row;
- contract transitions: the builder never assumes a fixed set of listed
  contracts; it interpolates from whatever vertices exist on day t.

**Stage 3, research dataset** (`research_examples/dustin_br/`): a builder that
reads the tables above, applies §8's availability rules, interpolates
constant-maturity DI rates from `PRE` (flat-forward in business days on a
252-day basis, B3's own convention for DI), and emits one row per B3 session
with the raw levels, derived rates, 5/21/63-session momentum, 21/63-session
realised volatility and 21/63-session correlations, plus an `available_date`
audit per source. Tests: interpolation reproduces a vertex exactly, no value
is used before its availability date, no fill beyond the staleness limits,
and `PRE` at each DI1 maturity equals the contract's settlement rate.

**Operator steps after merge** (a merge deploys nothing to the database):
dispatch `market_backfill.yml` for `ts` 2008 onward, `pr` 2018 onward,
`treasury`, `cboe`, `eia` from 2008; then
`run_backfill --bacen-only --bacen-sources sgs --bacen-start 2008-01-01` for
IC-Br.

## Parking lot

- Serve DI1 and the `PRE` curve through `api` (`future_curve`, `curve`,
  `INSTRUMENTS.md` Phases B and C).
- `DIC` (DI x IPCA) for breakeven inflation: one entry in the curve list.
- Validate the `DOC` proxy against EMBI+ over 2008 to 2024-07, once, offline.
- Try `TaxaSwap` files before 2008.
- Ibovespa level, if the equity channel is added.
- Cboe redistribution terms, before VIX is ever served.
