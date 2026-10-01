# Research seam: SILO as the data layer for external quant research

**Status: spec drafted 2026-09-29 from the wayfinder map ([#371](https://github.com/PedroDnT/SILO-BZ/issues/371), 11 of 11 tickets resolved). Approved 2026-09-29; the build tickets are under epic #410. The research universe (#411) is built (§4), and so are the price-adjusted close in `quote_history` with the per-issuer sweep proof (§3; #413, #417 without the pre-2019 refusal) the benchmark index `api.index_history` (§5; #412, #415, catalog v45) the total-return close in `quote_history` (§3; #418, catalog v46) the as-of date on the fundamentals (§6; #414, catalog v47) the pre-2019 window refusal with the tape start in `coverage()` (§3; #417, catalog v48) the SDK fan-out helper, the two SDK clients and the research usage guide (§7, §8; #419) and the verification script (§9; #420, its READY verdict is run after the production apply).**

A *research caller* is an external repository that builds features, signals or
backtests on SILO data (terms: `CONTEXT.md`, *Research data*). Its first
consumer is cross-sectional market-neutral strategies in Brazilian equities.
The seam is schema `api` over PostgREST with the anon key. The SDK is a thin
convenience client, not the contract. Signals, factor models, ML, portfolio
optimisation and backtesting stay outside SILO.

## 1. Outcome

Most of the seam already exists. The spec changes four things and documents the rest:

| Need | Answer | Change |
|---|---|---|
| Prices for a ticker | extend `api.quote_history` | adjusted fields (§3) |
| The universe, without a hard-coded list | new `api.research_universe` | new function (§4) |
| The benchmark index | new `api.index_history` | new function, new table (§5) |
| Fundamentals without look-ahead | `as_of` date on the latest-version functions | parameter (§6) |
| Macro series | none | usage doc only (§7) |

Every retrieval returns the full request or refuses with a narrowing or paging
instruction (`api.assert_row_cap`, error `22023`). None trims silently.

## 2. Measured baseline

From #376, on today's interface: 100 names over the window is 188 quote requests,
70 s sequential and 8 s with 16 workers, no rate limiting. The tape starts
2019-01-02, so a "10-year" request silently returns 7.7 years. CDI fits only
3-year chunks. PETR4 fundamentals from 2019 refuse on 6 of 8 statements or
time out cold (`57014`). The cost today is caller complexity, not speed.

## 3. Market observations: extend `api.quote_history` (#377, #372, #387, #386)

One ticker per call, the existing `p_after` date cursor, and the SDK fans out.
No new function. `api.quotes`, the typed views (`adjusted` stays FALSE) and
`api.panel` are unchanged.

1. **Two new fields:** a price-adjusted close and a total-return close. Adjustment
   is owned by SILO, never the caller. The raw close stays in the same row.
2. **Backward adjustment, anchored to the latest session.** Returns are
   point-in-time, levels are not. A new event changes past levels. The glossary
   states this under *Price-adjusted close*.
3. **Windows before the tape refuse.** A `p_from` before 2019-01-02 raises
   `22023` naming the start date. `api.coverage()` publishes the tape start for `quotes`.
4. **Both adjusted fields are NULL-with-reason until proven**, one reason column
   per field (their coverage is independent):
   - price-adjusted: NULL until the issuer's corporate events are proven swept from 2019;
   - total-return: NULL until the ISIN has a resolved cash distribution in B3's history
     and no later distribution is unvalued. Built in #418 (catalog v46): an event with
     no proven ISIN NULLs the earlier closes of its issuer's same share class (by the
     class B3 publishes and the ticker prefixes the issuer has used, never a guessed
     ISIN), and a supplement event absent from the history NULLs its own ISIN's.
     See `docs/reference/API.md`, "The total-return close".
5. **Equity and unit only.** Every other asset class gets NULL with reason
   `outside research universe`.
6. **Board default unchanged.** The verification script (§9) adds a query for
   equity/unit tickers whose `codbdi` changed since 2019. If any exist, the
   refusal rule is decided then.

**Price-adjusted, evidence (#372).** B3's rule reproduces 161 of 165 events. The
regression pins are BBAS3 2024-04-15 (split) and MGLU3 2024-05-24 (grouping).
Not covered: spin-offs, mergers, subscriptions, JCP gross vs net, and linking
series across a rename (a rename changes the ISIN).

**Event-history completeness (build).** The corporate-event sweep covers only 400
days, so about 115 issuer codes have no events. The build widens it to
everything traded since 2019. How an issuer's sweep is "proven" (so its
price-adjusted close leaves NULL) is settled in the build ticket.

**Total-return, staged (#387, #386).** Price-adjusted ships without waiting.
A new additive cash table, keyed on the history row as published with an
`n_published` count column, is backfilled per issuer from B3's
`GetListedCashDividends`. No re-key of `b3_corporate_event`. Cash = value ×
`n_published`, a rule proven once on the supplement overlap. The history maps to
ISINs by exact pre-ex-date close on the tape: 1,054 of 1,054 keys on 14 issuers,
177 of 177 against ISIN-bearing supplement rows. History lags at least 17 days, so
the current supplement feed stays for the recent window. JCP is gross only.
Still to settle in the build: how the per-issuer fetch is driven (trading names
from the tape, renames by CNPJ as a search key only), the overlap check that
proves the rule, how supplement and history rows coexist for the recent window,
the NULL-reason vocabulary, and how a caller sees each ISIN's total-return start date.

## 4. The research universe: `api.research_universe` (#378, #373, #381)

A separate call, one row per ticker+ISIN pair traded since 2019-01-02.

- **Membership by ISIN instrument code**, characters 7-9 of the ISIN: `ACN`
  (shares), `CDA` and `UNT` (units) in; `R##` subscription receipts and every
  other code out. Units must also have a ticker ending in `11` (B3's unit
  convention); without that clause 6 non-units pass (BPAC13 three rows, AZUL97,
  AZUL98, AZUL99). The `instrument_type` rule (`equity` + `unit`) is not the
  definition: it leaks about 130 receipts whose `especi` starts with ON/PN.
  Live on 2026-09-29 the rule gives 639 pairs. BDRs, funds and indices are out.
- **The ISIN is the identity.** A rename is a new row and is never linked. A gap
  shows as `n_sessions` far below the calendar span (NATU3: one ISIN, 2019-12 to
  2025-07).
- **Fields:** ticker, isin, instrument_type, cnpj, cnpj_basis, first_observed,
  last_observed, n_sessions, setor_current, built_at. There is no
  `segmento_current`: `cia_company.segmento` is CVM's registration category
  (Categoria A/B), not a market segment.
- **No listing or delisting dates and no `is_active`.** FCA dates are not
  historical (#373), and `vw_company_ticker.is_active` marks 241 dead tickers
  active (#381).
- **Company link with its basis:**

  | `cnpj_basis` | Meaning | Pairs today |
  |---|---|---|
  | `fca_ticker` | the FCA row for that exact ticker | 584 |
  | `fca_issuer_stem` | same 4-letter stem, exactly one CNPJ in the FCA pair table | 17 |
  | NULL | no link; `cnpj` and `setor_current` are NULL too | 38 |

  No name matching: no published ISIN-to-CNPJ source exists. 38 of the 59
  unlinked pairs (of 59 before the units clause) still trade in 2026 (CSNA3, CMIN3, BPAC3, ALUP3).
- **`setor_current` and `segmento_current`** are current classifications, labelled as such.
- **No `as_of` parameter.** The caller filters. **Survivorship rule for the usage
  doc:** a rebalance on T selects pairs with `first_observed <= T <= last_observed`;
  a pair inside a gap (NATU3) still matches that filter. A server-side `as_of` was
  deferred and can be added without breaking callers.
- **Built (#411):** `28_api_research.sql` over `mv_research_universe`, a
  materialized view refreshed daily (`anon`'s statement timeout is 3 s, the bare
  aggregate 1.6 s warm), so `last_observed` lags the tape by up to a day and
  `built_at` says when. Both the exact-ticker and the stem link refuse an
  ambiguous match. The `CONTEXT.md` sentence excludes receipts.

## 5. The benchmark index: `api.index_history` (#379, #374)

`api.index_history(p_index, p_from, p_to, p_after)` over B3's own published
levels, from a closed, extensible list of index codes.

- **Index codes only.** A ticker, including BOVA11 and IBOV11, raises `22023`
  naming the accepted codes, so substitution cannot happen by construction.
  `quote_history('IBOV11')` and `api.quotes` keep today's behaviour (IBOV11 is
  `asset_class = 'index'` and each print is that session's settlement index, never the
  official close; it printed on expiry days only through 2024, weekly in 2025 and on
  nearly every session since December 2025, **corrected 2026-10-01**: the spec said
  "prints only on expiry days"); the usage doc warns about it.
- **Source:** B3's administrator-published daily close, `indexStatisticsProxy/IndexCall/GetPortfolioDay`
  (undocumented; one year per call). SGS 7 is discontinued since 2019-09-30 and is not used.
- **Columns:** `index_code`, `trade_date`, `level`, `source`, a flag for a divisor
  step as published (IBOV: eleven, 1983-10-04 ÷100 and ten ÷10 sessions, the last 1997-03-03; found in the series on 2026-09-30). Same 1,000-row cap and date cursor as
  `quote_history`. The tape-start refusal does not apply; depth per index is published in `api.coverage()`.
- **Storage:** a new table keyed on `(index_code, trade_date)`, one `cvm_ingest_log`
  row per ingest, idempotent upsert, level as published. **A null endpoint result
  for a configured index is an error, never empty**: the endpoint answers HTTP 200
  with `null` results for an unknown code (IFNM did on 2026-09-29).
- **Which indices ship first** is a build ticket. IBOV is verified (2025-12-30 =
  161,125.37, equal to B3's year-end news item). IBXX, IBXL, SMLL, IFIX, IDIV,
  IEEX, ICON, IMOB and UTIL answered with a 2025 grid but are unverified.
- Price-index levels only. Whether any code is a total-return variant is checked in
  the build, and a price index is never labelled as total return. No return or adjusted columns.

## 6. Fundamentals: an as-of date (#375, #380)

Every latest-version function (`financials`, `income_statements`, `balance_sheets`,
`cash_flow_statements`, `company_financials`) leaks look-ahead today. "Latest"
stays the default, labelled not point-in-time. Each gains an as-of date that
applies #375's recipe on the server:

1. drop rows with `filing_received_date` NULL or on or after T;
2. keep the highest remaining version per document;
3. keep all its lines.

Data starts in 2019. Superseded versions from before 2026 are not held, so the
result is stale, never early. Recovering them was ruled out (5 of 5 sampled
restated documents equal v1). Build: the parameter's name and type, whether rows
carry `version` and `filing_received_date`, and the look-ahead test (PETR4 DFP
2023 at 2024-02-29 must return the ITR 2023-09-30). Recording every new version
([#383](https://github.com/PedroDnT/SILO-BZ/issues/383)) is on the route but deferred for cost.

## 7. Macro: usage doc only (#380)

No change. There is no cursor: the caller splits by date. CDI fits about 3 years
per call (#376), SELIC_META about 2.7, so 2019 onward is 2 to 3 calls.

## 8. SDK and MCP surface

- The SDK gets a fan-out helper over `quote_history` (concurrency is observed
  free today, not guaranteed) and clients for the two new functions.
- One MCP tool per new function (`t()` line in `supabase/functions/silo-mcp/tools.ts`).
- Each new endpoint needs a catalog entry, a regenerated `openapi.json`
  (`scripts/gen_openapi.py`) and MCP contract (`scripts/gen_mcp_contract.py`);
  `tests/test_mcp_contract.py` fails until all three agree.
- A merge deploys nothing to the database: apply analytics first, then deploy the MCP function.

## 9. Verification and tests

Verification script (extends `docs/reference/research/retrieval_measurement.py` on
`research/retrieval-measurement`): PETR4; PETR4 + VALE3; the Ibovespa; CDI; PETR4
fundamentals; the ~100-ticker research-sized retrieval; the `codbdi`-change query.

Public-interface tests: raw vs adjusted; equity vs index; unknown ticker; over-cap
refusal; pre-2019 window refusal; non-equity/unit class returns NULL adjusted;
no BOVA11 or IBOV11 substitution; no look-ahead; universe has no `R##` receipt;
NATU3 is one row with `n_sessions` below its span; every `fca_issuer_stem` stem has one CNPJ.

Regression pin for adjustment: BBAS3 2024-04-15 and MGLU3 2024-05-24 (#372).

## 10. Out of scope

Historical index membership; BDRs in the universe; sector history (daily CAD snapshots);
spin-offs, mergers, subscriptions and linking across renames; fundamentals before 2019;
recovering superseded ITR/DFP versions; a multi-ticker prices function; adjusted values
for classes other than equity and unit; everything in the brief's non-goals.

Recorded separately, off the route: #381 (`api.lookup` serves dead tickers as active),
#382 (`cia_ticker` drops per-segment rows), #384 (four 2026 ITR filings lack
year-to-date lines), #385 (`b3_corporate_event` collapses installments), #388
(IBOV11 fatcot direction noted backwards), #396 (`api.panel` `close_return` shows
splits as returns).

## 11. Open owner calls

- The map's Notes still tell sessions to consult a `codebase-design` skill that is not installed here. Install it or drop the line.
- ~~Approve this spec so it can be cut into tickets and built.~~ Approved 2026-09-29 (epic #410).
