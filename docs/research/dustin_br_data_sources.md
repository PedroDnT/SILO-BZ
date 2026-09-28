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

### Updates after Stage 1 (2026-09-27)

Findings that changed a Stage 1 recommendation. The sections below are
updated in place; this list says what moved and why.

- **VIX is not ingested: Cboe licenses it.** Cboe's Use of Content policy
  (<https://www.cboe.com/use-of-content/>): "In order to use any Cboe logo,
  data, photo/image or other content contained in Cboe websites (collectively
  "Cboe Content"), you must receive approval in advance from Cboe" and "You
  are not approved to use Cboe Content until a license agreement has been
  signed by both you and Cboe." The Stage 1 check read only the history page,
  which states no terms. SILO ingests nothing that needs a licence, so the VIX
  code is gated on `CBOE_VIX_LICENSED=1` (set only once a licence is signed)
  and the risk-regime input is the **OFR Financial Stress Index** (§3.C).
- **B3 extrapolates `PRE` past the last DI1 maturity** (Manual de Curvas v21
  §2.1): the long vertices extend the last forward rate; they are not prices.
  The builder finds where that straight tail starts and leaves tenors beyond
  it NULL (§3.A).
- **`DOC` is linear on 360 days** (Manual de Curvas v21 §4.5). Confirmed; the
  builder's conversion is B3's own (§3.D).
- **Breakeven inflation comes from `DPL`, not `DIC`.** `DIC` is a dirty IPCA
  coupon from a poll of informants; `DPL` is the clean coupon from DAP futures
  (NTN-B fallback), B3's own basis for implied inflation (§3.A).
- **The sovereign proxy was checked against EMBI+** over 2008 to 2024-07. It
  follows EMBI+ over quarters, not in level across years. It is now OPTIONAL,
  to be read in changes (§3.D).
- **`TaxaSwap` before 2008**: the same 72-character layout, with `PRE` and
  `DOC`, back to 2004 (§6). Not loaded.

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
| VIX                           | **missing**   | none                                                              | licensed by Cboe; not ingested, see §3.C                                                                                     |
| MOVE                          | **missing**   | none                                                              | proprietary, see §3.C                                                                                                        |
| Sovereign risk                | **missing**   | none                                                              | see §3.D                                                                                                                     |
| Commodities                   | **missing**   | none                                                              |                                                                                                                              |
| DI constant-maturity points   | **derivable** | from the B3 reference curve or DI1 contracts                      | research code, not stored                                                                                                    |
| Slopes, curvature             | **derivable** | from the constant-maturity points                                 | research code                                                                                                                |
| Momentum, realised vol, corr  | **derivable** | from any daily series above                                       | research code                                                                                                                |
| Breakeven inflation           | **derivable** | B3 `DPL` curve (clean IPCA coupon) from the same reference file   | built by the builder from `PRE` and `DPL` (§3.A); `DPL` is in the file from mid-2007                                         |
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
| VIX (now: OFR FSI)       | 3        | global risk regime                                                  |
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

**B3 extrapolates the long end.** B3's Manual de Curvas v21 (2025-12-12)
§2.1: between DI1 maturities `PRE` is flat-forward on 252 business days, and
after the last DI1 maturity B3 extends the last segment's forward rate. The
long vertices (out to 34 years in 2026) are B3's extrapolation, not prices.
In (business days, log accumulation factor) space that tail is one straight
line, so its start can be found from the published curve alone: the longest
suffix whose least-squares line fits every vertex within 1.5 times the
3rd-decimal rounding. Validated where the contract list is known (the Price
Report of every 2 January, 2018 to 2026, _measured_): the detected start
never lies past the second-to-last DI1 maturity. On 2026-09-25 it is 3,289
business days, against DI1 maturities at 3,322 (second-to-last) and 3,572
(last). Over monthly samples 2008 to 2026 the 5-year tenor (1,260 business
days) was always anchored; the 10-year (2,520) fell in the extrapolated tail
in 8 of 12 months of 2008, 9 of 12 of 2013 and 7 of 12 of 2015. The builder
leaves a tenor NULL past the detected start, so `di_10y` is often NULL early
in the sample.

**Breakeven inflation.** Manual §3.2: `DPL` ("Cupom Limpo de IPCA") is the
IPCA clean coupon, a real rate on 252 business days to 2 decimals, from DAP
futures settlements and, where DAP is missing, ANBIMA's NTN-B indicative
rates. B3 defines implied inflation as (1 + `PRE`) / (1 + `DPL`) − 1, and the
builder computes exactly that at 1, 2 and 5 years. `DIC` (§3.1), the Stage 1
plan, is dropped: it is a dirty coupon from the median of a poll of
informants, and it steps with the IPCA release calendar (_measured_ on
2026-09-25: 9.85 at 362 calendar days, 9.63 at 399). `DPL` is in all 225
monthly samples from 2008-01 to 2026-09 (_measured_) and first appears
between the April and July 2007 samples. Its short end leans on the current
month's IPCA projection, which is why the shortest breakeven read is one
year. A breakeven carries an inflation risk premium: it is market pricing,
not an expectation. OPTIONAL.

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

### C. Risk regime: VIX, MOVE and the OFR FSI

| Dataset | Candidate source                                                                                | Official?    | Frequency         | Earliest                | Update lag                                 | Access                           | Auth | Licence                                                              | Reliability                   | Selected?                 |
| ------- | ----------------------------------------------------------------------------------------------- | ------------ | ----------------- | ----------------------- | ------------------------------------------ | -------------------------------- | ---- | -------------------------------------------------------------------- | ----------------------------- | ------------------------- |
| VIX     | **Cboe `VIX_History.csv`** (`cdn.cboe.com/api/global/us_indices/daily_prices/`)                 | yes          | business day      | 1990-01-02 (_measured_) | same day                                   | one CSV, OHLC                    | none | Cboe Use of Content: **approval in advance and a signed licence**    | high                          | **no** (code kept, gated) |
| VIX     | FRED `VIXCLS`                                                                                   | copy         | business day      | 1990                    | next day                                   | CSV / API                        | key  | FRED marks it Cboe copyright                                         | copy                          | no                        |
| OFR FSI | **OFR Financial Stress Index `fsi.csv`** (`financialresearch.gov/financial-stress-index/data/`) | yes (US gov) | U.S. business day | 2000-01-03 (_measured_) | two business days (OFR's note; _measured_) | one CSV, index + 8 contributions | none | no copyright on OFR's own work; credit requested (OFR legal notices) | high; revisions listed by OFR | **yes**                   |
| MOVE    | ICE BofA MOVE Index                                                                             | yes (ICE)    | business day      | 1988                    | same day                                   | ICE Data Indices, terminals      | paid | **proprietary**                                                      | high                          | **no**                    |
| MOVE    | Yahoo `^MOVE`                                                                                   | no           | —                 | —                       | —                                          | scrape                           | —    | republication of licensed data                                       | —                             | **no**                    |

**VIX is not ingested.** Cboe requires advance approval and a signed licence
for any use of data on its websites (Updates, above). The code stays, gated on
`CBOE_VIX_LICENSED=1`: if a licence is signed, set that repository variable
and VIX flows again with no code change. FRED's copy carries the same Cboe
copyright.

**The risk-regime input is the OFR Financial Stress Index** (Office of
Financial Research, U.S. Treasury). A daily index of systemic financial stress
from 33 market variables, zero at average stress, positive above; it is the
sum of five category contributions (credit, equity valuation, funding, safe
assets, volatility) and, again, of three regional ones. Two series are kept:
the index, and its **Volatility** category: nine implied and realised
volatilities (OFR Working Paper 17-04, Appendix A), namely VIX, V2X, the
Nikkei volatility index, JPMorgan's EM volatility index, 6-month EUR/USD and
USD/JPY implied vols, Brent 22-day realised vol, and Merrill Lynch's US and
Euro **swaption** volatility estimates (the swaption siblings of MOVE, which
is on Treasury options). It is the closest public counterpart of the
VIX-and-MOVE block, not a copy of either. OFR's 2023 update replaced only
funding variables.

- **Why it fits point-in-time work.** OFR, Working Paper 17-04: "the OFR FSI
  respects the arrow of time. The OFR FSI's value on a given day depends only
  on information available that day and, once estimated, its value does not
  change." The exceptions are listed in OFR's revision history (four entries
  2018 to 2023, _measured_): data corrections on 2018-05-18 (2017-10-02 to
  2018-05-17) and 2018-12-04 (2018-08-30 and 2018-11-01), a regional
  reclassification on 2021-02-12 (the index and the categories unchanged) and
  new funding variables on 2023-06-27 (2022-01-03 to 2023-06-23). OFR's
  workbook keeps the value before each revision; SILO stores those as
  `*_FIRST_RELEASE` series and the builder uses them. Measured revision size
  on the index: mean 0.07 in 2018-05, 0.77 in 2018-12, 0.41 (max 1.49) in
  2023-06, against a standard deviation of 1.28 over the whole history. The
  current file equals every "updated" value in the workbook (_measured_).
- **Publication lag.** OFR: "The FSI publishes with data that is current from
  two business days prior." _Measured_: on Sunday 2026-09-27 the newest value
  was dated Wednesday 09-23. The builder uses a value three weekdays after its
  date (§8).
- **What is lost against VIX.** A composite moves less sharply than a single
  implied vol, and it arrives two days late: a shock on Monday reaches the
  row of Thursday. The ingest also keeps a revision SILO sees itself: if a
  fetch brings a changed value for a stored date, the stored one is kept as
  the first release.

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
long end of `DOC` is thin, and B3 extrapolates it past the last DDI
maturity as it does `PRE` (the builder applies the same tail detector). Rate
conventions differ: `DOC` is a **linear rate on 360 calendar days**, factor
1 + r·DC/36000 (Manual de Curvas v21 §4.5, confirmed), so over 365 days the
effective annual rate is r·365/360; UST par yields are semi-annual
bond-equivalent, (1 + y/2)² − 1. The builder compares the two in effective
annual terms. Call it `brazil_sovereign_risk_proxy`, never "CDS".

**Checked against EMBI+ Brazil, 2008-01-02 to 2024-07-24** (a one-off, not
ingested: IPEA's copy stopped). Weekly Wednesdays, the builder's own
functions on B3's `DOC` and Treasury's 1-year par yield, against IPEA's
`JPM366_EMBI366`: 865 Wednesdays asked, 30 holidays, 827 aligned weeks
(_measured_).

| Measure (827 weeks)            | Proxy vs EMBI+ |
| ------------------------------ | -------------- |
| level, Pearson                 | 0.37           |
| level, rank (Spearman)         | 0.04           |
| 1-week changes                 | 0.20           |
| 4-week changes                 | 0.41           |
| 13-week changes                | 0.59           |
| mean level, bp (proxy / EMBI+) | 171 / 266      |

- **Stress episodes** (start → end of the window, bp): the 2008 crisis,
  proxy 228 → 516 (peak 624) against EMBI+ 248 → 671; the 2015 downgrade,
  208 → 369 against 277 → 454; COVID in 2020, 92 → 109 (peak 252) against
  189 → 370 (peak 441).
- **Within a year the levels track** (0.86 to 0.93 in 2008, 2012, 2014,
  2015, 2016 and 2018) and **across years they do not**: the proxy's yearly
  mean fell from 307 bp in 2008 to 86 in 2021 while EMBI+ stayed between 183
  and 385, and in 2021 and 2022 the two moved against each other (-0.13 and
  -0.45).

**Verdict.** The proxy catches Brazil-specific stress (2008, 2015) and moves
with EMBI+ over one to three months, but its level carries onshore-dollar
effects that drift for years, and it missed most of the 2020 widening. It is
reclassified **OPTIONAL** (§6), and the model should read it in changes (its
21- and 63-session momentum columns), not in level.

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

| Dataset                                                  | Source                                        | Stored in                                    | Grain                           | Served via `api`? |
| -------------------------------------------------------- | --------------------------------------------- | -------------------------------------------- | ------------------------------- | ----------------- |
| DI1 per contract                                         | B3 Price Report `BVBG.086.01`                 | `b3_futures_settlement` (new)                | session × ticker                | no                |
| DI x pré, onshore USD, IPCA clean coupon curves          | B3 `TaxaSwap.txt`, curves `PRE`, `DOC`, `DPL` | `b3_reference_rate` (new)                    | session × curve × calendar days | no                |
| UST par curve                                            | U.S. Treasury CSV                             | `mkt_series` (new)                           | US business day × tenor         | no                |
| VIX OHLC                                                 | Cboe CSV                                      | `mkt_series`, **only with a signed licence** | US business day × field         | no (licence)      |
| Brent spot                                               | EIA API v2                                    | `mkt_series`                                 | business day                    | no                |
| OFR FSI and its Volatility category, with first releases | OFR `fsi.csv` and revision workbook           | `mkt_series`                                 | US business day                 | no                |
| IC-Br (4 series)                                         | BCB SGS 27574 to 27577                        | `bacen_sgs` (existing)                       | month                           | no                |

**The DI1 contracts and the B3 curves are served since catalog v42**
(`api.future_curve`, `future_series`, `curve`, `curve_history`;
`27_api_rates.sql`), as published, with the extrapolated long end stated.
The global series in `mkt_series` and IC-Br are not served. VIX would never
be served without a licence that allows it. The landing tables are
covered by the `anon` revoke sweep. The research builder reads them with the
operator's database connection.

## 5. Rejected sources, and why

| Source                                         | Why rejected                                                                                  |
| ---------------------------------------------- | --------------------------------------------------------------------------------------------- |
| www2.bmf.com.br pages (ajustes, pregão, taxas) | retired by B3 on 2025-12-10; answer with database errors                                      |
| BCB SGS swap DI x pré series                   | stopped in 2019                                                                               |
| BDI `ConsolidatedTradesDerivatives`            | 21-business-day retention; the Price Report carries the same fields with history              |
| FRED                                           | a secondary copy of Treasury, Cboe and EIA; primary sources exist; unreachable here           |
| Yahoo Finance (`^TNX`, `^MOVE`, `^VIX`)        | not authoritative, republishes licensed data, ToS                                             |
| Cboe `VIX_History.csv`                         | licensed: Cboe requires advance approval and a signed licence (§3.C); the code is kept, gated |
| CDS (Markit, ICE), MOVE (ICE), GSCI, BCOM      | proprietary                                                                                   |
| EMBI+ via IPEA                                 | stopped 2024-07-30; used once, offline, to check the sovereign proxy (§3.D)                   |
| World Bank Pink Sheet                          | monthly, URL changes per release; IC-Br metals covers iron ore for Brazil                     |
| WTI                                            | redundant with Brent for this purpose                                                         |

---

## 6. Historical coverage

| Series                                    | Class             | Starts                                      | Notes                                                                                                      |
| ----------------------------------------- | ----------------- | ------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| DI constant-maturity 1Y/2Y/3Y/5Y (PRE)    | **CORE**          | 2008-01-02                                  | from B3 `PRE`; the same 72-character files, with `PRE` and `DOC`, go back to 2004 (_measured_, not loaded) |
| DI slope, curvature                       | **CORE**          | 2008-01-02                                  | derived                                                                                                    |
| DI 10Y (PRE)                              | **OPTIONAL**      | 2008-01-02, with gaps                       | NULL where 10 years falls in B3's extrapolated tail (§3.A)                                                 |
| Breakeven inflation 1Y/2Y/5Y (PRE vs DPL) | **OPTIONAL**      | 2008-01-02 (`DPL` from mid-2007)            | includes an inflation risk premium (§3.A)                                                                  |
| USDBRL (PTAX, SGS 1)                      | **CORE**          | before 2008 (existing)                      |                                                                                                            |
| UST 2Y/5Y/10Y/30Y                         | **CORE**          | 1990 (loaded from 2008)                     |                                                                                                            |
| OFR FSI, Volatility category              | **CORE**          | 2000-01-03 (loaded from 2007)               | two-business-day lag and first releases (§3.C, §8); replaces VIX                                           |
| Brent                                     | **CORE**          | 1987 (loaded from 2008)                     | weekly publication lag, §8                                                                                 |
| Sovereign proxy (DOC minus UST)           | **OPTIONAL**      | 2008-01-02                                  | derived; tracks EMBI+ in 1- to 3-month changes, not in level (§3.D)                                        |
| Rates-vol proxy                           | **CORE**          | 2008 + 63 sessions                          | derived                                                                                                    |
| SELIC target                              | **CORE**          | before 2008 (existing)                      |                                                                                                            |
| IPCA                                      | **CORE**          | 1980 (existing, after the SGS history load) | monthly, lagged                                                                                            |
| IC-Br                                     | **OPTIONAL**      | 2008-01 at least                            | monthly, lagged                                                                                            |
| Focus expectations                        | **OPTIONAL**      | depends on the stored history               | needs the §8 lag; history may need a re-fetch                                                              |
| DI1 volume, open interest, trades         | **LATE-STARTING** | 2018-01-02                                  | Price Report history limit                                                                                 |
| DI1 per-contract OHLC                     | **LATE-STARTING** | 2018-01-02                                  | same                                                                                                       |

**Earliest date for a consistent CORE matrix: 2008-01-02**, subject to the
backfills in §10 actually landing. It could move to 2004: B3's `TaxaSwap`
files keep the 72-character layout with `PRE` and `DOC` back to at least
2004-01-12 (_measured_: quarterly samples 2004 to 2007; 65 characters in
2001, 67 in 2003), every other CORE series starts earlier, and `DPL` (an
OPTIONAL input) appears only in mid-2007. That needs the loader's start date
and a curve list that lets `DPL` be absent before 2007 (parking lot). Rolling features consume their own
warm-up: 63-session features are first defined in early April 2008, and the
builder leaves them NULL until then rather than shortening the sample.

---

## 7. Licensing and access

- **B3** files are public downloads; SILO already republishes B3's COTAHIST.
  No login, cookie or token (_measured_). The Price Report is large: 12 MB zip,
  135 MB XML per version on 2026-09-25, so the backfill is bound by download
  and parse time, not rows.
- **U.S. Treasury** and **EIA**: US government works, public domain. EIA's API
  wants a key; a free one goes in the `EIA_API_KEY` secret (an owner step:
  register at eia.gov/opendata). Without it the ingest uses EIA's public
  `DEMO_KEY`, which is rate-limited and logged as such.
- **Cboe**: its Use of Content policy requires advance approval and a
  licence signed by both sides for any use of website data (§3.C). Not
  ingested; requests go to permissions@cboe.com. The gate
  (`CBOE_VIX_LICENSED`, a repository variable) is set only once a licence
  is signed.
- **OFR**: "No copyright may be claimed for any work on this website that was
  created by a federal employee in the course of his or her duties. However,
  credit is requested if you reproduce or copy any such work" (OFR legal
  notices, _measured_ 2026-09-27). Credit: Office of Financial Research, OFR
  Financial Stress Index.
- **BCB SGS**: public, already ingested.

## 8. Point-in-time integrity

The builder produces one row per Brazilian session `t`: every value in it must
have been **public by the end of day t (Brasília)**. Each source gets an
explicit availability rule. Where the rule is an assumption, it is marked and
chosen to be conservative (later, never earlier).

| Series         | Observation date                           | Published                                                                                                             | Revised?                                                                                         | Rule used by the builder                                                                                                                                                  |
| -------------- | ------------------------------------------ | --------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| DI (PRE, PR)   | B3 session                                 | same evening (_measured_ 18:37 to 20:31 BRT)                                                                          | settlement is final                                                                              | available at t                                                                                                                                                            |
| DOC, DPL       | B3 session                                 | same evening                                                                                                          | final                                                                                            | available at t                                                                                                                                                            |
| USDBRL (SGS 1) | business day                               | PTAX closes ~13:00 BRT                                                                                                | final                                                                                            | available at t                                                                                                                                                            |
| UST            | US business day                            | US evening, before 23:00 BRT                                                                                          | rare corrections (logged by the ingest)                                                          | as-of join: last UST date ≤ t                                                                                                                                             |
| OFR FSI        | US business day                            | **two business days later** (OFR's note; _measured_: on Sunday 2026-09-27 the newest value was dated Wednesday 09-23) | only as OFR's revision history lists; the value before each revision is kept (`*_FIRST_RELEASE`) | the **first release**, available **three weekdays** after the observation date (one weekday of buffer for a U.S. holiday)                                                 |
| Brent (EIA)    | business day                               | **weekly**, Wednesdays, through the previous day (_measured_)                                                         | occasional revisions (logged)                                                                    | available the day after the **first Wednesday strictly after** the observation date (a Wednesday price waits a full week; the extra day absorbs holiday-shifted releases) |
| SELIC target   | calendar day, dated when in force          | ahead of time                                                                                                         | no                                                                                               | value dated t                                                                                                                                                             |
| IPCA           | month M, dated the 1st                     | IBGE releases around the 10th of M+1                                                                                  | no                                                                                               | **assumption**: available from the 15th of M+1                                                                                                                            |
| IC-Br          | month M, dated the 1st                     | early M+1 (exact day unverified)                                                                                      | **unknown**                                                                                      | **assumption**: available from the 15th of M+1                                                                                                                            |
| Focus          | survey day D (the stored `reference_date`) | **the Monday after D's week** (_measured_: on Sunday 2026-09-27 the newest daily value was dated 2026-09-18)          | vintage not kept                                                                                 | available from the **Tuesday after D's week** (one day of buffer for holiday Mondays)                                                                                     |

Rules the builder enforces:

1. **Observation date and publication date are separate columns.** Every
   feature is joined on its `available_date`, never on its observation date.
2. **No blind forward fill.** An as-of join carries the last available value
   forward only within a staleness limit per source (5 sessions for daily
   series, 10 for Brent, 45 for monthly series); past it the feature is NULL
   and the gap is counted.
3. **No revised value as point-in-time.** IPCA is not revised by IBGE. IC-Br
   revisions are unknown; until measured, IC-Br is OPTIONAL. The OFR FSI is
   read at its first release wherever OFR revised it, and the daily ingest
   re-fetches only its last 30 days, so a later revision of an older date
   never replaces what was first stored (and one inside the window is kept
   as the first release). SILO keeps no
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

Row volumes: ~150 DI1 rows a day from 2018 (~0.1 M); `PRE` + `DOC` + `DPL`
about 340 to 860 rows a day from 2008 (~3 M; the three curves share B3's
vertex grid, 286 vertices each on 2026-09-25); `mkt_series` ~20 rows a day
(~0.1 M).

## 10. Implementation plan

**Stage 2, ingestion** (in priority order, each with offline fixture tests):

1. `src/fetchers/b3_pesquisapregao_fetcher.py`: one downloader for `PR` and
   `TS` files. An empty zip is "not published" (logged `skipped`), not an error.
   So is a `TS` file B3 republished from an earlier session under a later date:
   every PRE/DOC/DPL line carries the earlier date. This was _measured_ on
   2010-12-24 and 2010-12-31, whose files are the 12-23 and 12-30 files vertex
   for vertex. It raises `TaxaSwapStaleFile`, is logged `skipped` and stores
   nothing. Any other date mismatch is still an error.
2. `src/parsers/b3_price_report.py` (streaming XML, the latest version in the
   zip, DI1 outright tickers, typed + `raw`) and
   `src/parsers/b3_taxa_swap.py` (fixed-width, strict layout check).
3. `src/fetchers/global_market_fetcher.py` + `src/parsers/global_market.py`:
   Treasury CSV (unknown column header raises), Cboe CSV (licence-gated),
   EIA API v2, OFR `fsi.csv` and its revision workbook (both headers
   checked whole).
4. IC-Br: `RESEARCH_SGS_SERIES` in `bacen_pipeline.py`, fetched with the
   rest of SGS.
5. Migration 48 + `schema.sql`; `mkt_` in the revoke sweep.
6. `src/pipeline/market_pipeline.py` (`MarketIngestor`): `daily_update()`
   (last 7 calendar days of B3 files, current year of Treasury, trailing
   windows of EIA and OFR, Cboe only where licensed) and
   `backfill(source, start, end)`; one audit row per slice, revisions to
   stored values counted on the audit row, and a changed OFR value keeps the
   stored one as its first release.
7. Wiring: its own step in `daily_ingest.yml`, after the analytical layer
   (the FNET pattern: foreign hosts must not block the core run), and a
   `market_backfill.yml` dispatch (one year per job, `supabase-ingest`
   concurrency group).

**Data-quality checks** (in parsers and the ingest):

- duplicates: the natural key is unique within a file; a duplicate raises;
- impossible values: PU ≤ 0, rates outside (−5, 100) %, business days >
  calendar days, VIX ≤ 0, Brent ≤ 0 or > 1000, an OFR value outside ±100 →
  row dropped and counted;
- schema changes: an unknown Treasury column, a TaxaSwap row that is not 72
  characters, a Price Report without `TradDt`, an OFR header or revision
  layout we do not know, a configured curve missing from a file → raise;
- dates: every row's date must equal the file's session date;
- missing sessions: the builder's quality report
  (`research_examples/dustin_br/quality.py`, run by `research_build.yml`)
  reconciles the `PRE` session grid against `b3_cotahist` (PETR4, held from
  2019) and DI1 against `PRE`. Measured 2026-09-28, gaps at the source: B3
  serves an empty `TS150827.ex_` although COTAHIST shows trading that day,
  so 2015-08-27 is not in the grid; an empty `PR210610.zip` and a malformed
  newest version of `PR210104.zip` leave DI1 NULL on 2021-06-10 and
  2021-01-04. Against PTAX days, every other 2008-2018 day without `PRE` is
  a B3 closure (São Paulo holidays, 24 and 31 December, the year's last
  business day, the 2014 World Cup opening);
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
`research_build.yml` (manual, read only) builds the matrix from the warehouse
and uploads it with its quality report, which re-runs the no-look-ahead check
on the real inputs.

**Operator steps after merge** (a merge deploys nothing to the database),
one dispatch at a time, since all share the `supabase-ingest` queue:
`market_backfill.yml` with `us_treasury,eia_brent` 2008 to 2026,
`ofr_fsi` 2007 to 2026, `b3_reference_rate` 2008 to 2026 and
`b3_price_report` 2018 to 2026 (the longest: about an hour a year); then
`backfill.yml` with `bacen_only`, `bacen_sources=sgs`,
`bacen_start=2008-01-01` for IC-Br. Optional: an `EIA_API_KEY` secret.
**Done 2026-09-28**, the `EIA_API_KEY` secret included; the gaps left are the
source's (see missing sessions above).

## Parking lot

Open:

- The futures arm of `api.panel` (`id_type='future'`, `INSTRUMENTS.md`
  phase B); the typed endpoints are served since catalog v42.
- Load `TaxaSwap` 2004 to 2007 (§6): the loader's start date, and a curve
  list that lets `DPL` be absent before mid-2007.
- Ibovespa level, if the equity channel is added.
- A Cboe licence, if VIX itself is wanted (permissions@cboe.com); then set
  `CBOE_VIX_LICENSED=1`.

Done (2026-09-27): the DI1 contracts and the B3 curves served (catalog v42,
`future_curve`, `future_series`, `curve`, `curve_history`); breakeven inflation, from `DPL` rather than `DIC` (§3.A);
the `DOC` convention (§3.D); the EMBI+ check of the sovereign proxy (§3.D);
`TaxaSwap` before 2008 probed (§6); Cboe's terms read (§3.C, §7).
