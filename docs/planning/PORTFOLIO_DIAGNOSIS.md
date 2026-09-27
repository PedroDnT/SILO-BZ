# Portfolio diagnosis: mixed portfolio exposure and what-if comparisons

Status: design agreed in the 2026-09-26 grilling session; tickets under #340. Not a claim of existing capability. Open decisions are tracked in `OPEN_ITEMS.md` item 15, not here.

## Agreed direction

SILO's broader ambition is to ingest, process, and serve Brazilian financial data for humans and agents. The first product demonstration should diagnose a mixed portfolio, revealing exposure that is difficult to identify manually. A secondary objective is to demonstrate the builder's ability to deliver useful AI-enabled products.

The demonstration combines shared exposure across funds and direct holdings, material filing revisions, and document-backed contractual relationships where evidence is available. Cross-default clauses are relevant; detecting a clause does not establish that its trigger conditions occurred. Missing or undisclosed holdings remain unknown rather than inferred as facts.

The product provides diagnosis and what-if comparisons using the same assets. Return forecasting and expected-return inputs are excluded from the current scope. Hypothetical allocations are fully invested and long-only, with no borrowing or short selling. Two quantitative benchmarks are agreed: minimum estimated volatility and balanced risk contributions (equal risk contribution as the initial formulation). Both use the same eligible assets, risk estimates, and user-selected constraints, with feasibility and any deviation from equal contributions made explicit.

Qualitative warnings accompany quantitative comparisons. Users may explicitly translate warnings into optional constraints; warnings do not automatically alter optimization constraints.

## Portfolio state

SILO does not store user portfolios. Analysis is stateless: the client supplies a portfolio snapshot (identifiers, quantities or values, valuation date) with each request, and SILO returns exposures, warnings, and benchmark comparisons without persisting the snapshot. Saving portfolios or what-if runs is the client's responsibility. This keeps SILO free of user accounts and personal data, and the same call serves humans and agents (API and MCP).

Reconsider stored portfolios only if monitoring (alerts on new filings or revisions affecting a saved portfolio) enters scope, since monitoring is the first feature that requires SILO to remember a portfolio between requests.

## Success criteria

Acceptance is a fixed demo portfolio of about eight real positions, chosen because it contains three known findings: a shared exposure (a directly held stock also held through a fund), a material FIDC restatement, and an NTN-B position. The demo passes when the diagnosis surfaces all three with supporting source and date, and produces both quantitative benchmarks over the complete demo portfolio. A partial comparison fails acceptance for the demo portfolio (it remains valid behavior for real portfolios), so the Tesouro Direto ingest is a prerequisite.

Before any external showing, the same pipeline runs as a smoke test on two or three real portfolios chosen by the owner. The smoke test does not require specific findings; it passes when every position is either analyzed or reported as unknown with a reason, and nothing is silently excluded. This guards against a demo tuned to its own fixture.

## Material revision

A revision is material when a restatement changes one of a short named list of economically meaningful fields beyond a stated threshold (candidates: net assets beyond a relative threshold, delinquency or subordination beyond a percentage-point threshold, overdue-bucket totals). Every other changed field is reported as "revised, not assessed", never hidden. The warning states the field, old and new values, the threshold applied, and both filing references. Thresholds are SILO's judgement, disclosed with the finding, not a regulatory standard. The exact field list and threshold values are set when the demo FIDC is chosen.

Source: `fnet_document_diff` via `api.fund_restatement_diff` (one row per differing leaf, with `old_num`/`new_num`). The named-field rules key on `field_path`/`leaf`: the API's `cvm_column` is NULL until the XML-to-CSV crosswalk exists, so no rule may depend on a column mapping. Diffs whose `match_basis` is `position` carry their existing flag into the warning's uncertainty.

## Interaction surfaces

One engine, two clients. A single portfolio-diagnosis call takes a portfolio snapshot and returns look-through exposures, qualitative warnings, and benchmark comparisons. It runs server-side as TypeScript in a Supabase Edge Function, because SILO has no production Python server (`serve/` is local only) and the Evidence dashboards are static snapshots that cannot compute per request.

1. First: an MCP tool on `silo-mcp`. The user attaches or pastes a spreadsheet in an MCP client; the agent calls the tool and explains the findings. This exercises the engine interface through a client that cannot work around it.
2. Second: a web page (upload, editable table, exposure view, warnings list, current vs minimum-variance vs equal-risk-contribution comparison) as a thin client over the same call. No analysis logic lives in the page.

The engine is a shared module in `supabase/functions/_shared/portfolio/`. silo-mcp imports it now through a second tool-registry adapter (computed tools) beside the existing PostgREST adapter; a thin HTTP Edge Function imports the same module when the web page is built. No engine code lives inside `silo-mcp/`, and no second function is deployed before the page exists.

Computed tools are declared in a new `computed` section of the catalog (`serve/catalog.py` and so `api.catalog()`), beside `postgrest`. Each entry names the tool, where its input schema lives, and the `api` endpoints it calls. The MCP contract test pins silo-mcp's tools to `postgrest` plus `computed`, and fails if a computed tool depends on an endpoint missing from `postgrest`, so renaming an endpoint the engine uses breaks CI rather than production.

Data access: the engine reads only through schema `api` over PostgREST with the public anon key, and makes a fixed, small number of requests per diagnosis (about four) regardless of portfolio size. The data-heavy work lives in three new set-based `api` functions, each taking the whole portfolio in one call: holdings look-through (CDA blocks 1, 2, 4, 6, fund-of-fund recursion with cycle detection, refusing above one page), issuer resolution (identifier set to ticker, full CNPJ, 8-digit root), and monthly returns per holding type with coverage flags. The TypeScript engine does only covariance estimation, the two benchmark optimizations, and warning assembly. No direct Postgres connection from any Edge Function.

Failure handling is per section. Each part of the diagnosis (exposures, warnings, benchmarks) is either complete or marked unknown, carrying the refused request's SILO error verbatim and the positions it affects. The engine never retries or narrows a refused request on its own, never trims, and returns a provenance list of every request it made (endpoint and parameters). These are the PostgREST bridge's rules, kept by the computed-tool adapter; only "one request per call" is relaxed, to a fixed small number.

## Shared-exposure matching

Shared exposure is matched at two levels, both backed by filings:

1. Security: the same instrument (a directly held ticker and a fund's CDA block 4 `cd_ativo`; a directly held fund and a fund's CDA block 2 held-fund CNPJ).
2. Issuer: the same 8-digit CNPJ root (a directly held stock, via the published ticker map, and a fund's CDA block 6 debenture `cpf_cnpj_emissor`).

Economic-group matching is not assessed: SILO has no public source for group structure, and inferring it from names would synthesize relationships (integrity rule 3). The diagnosis states "economic group not assessed" rather than implying no group exposure exists.

## Asset scope

The agreed target includes Brazilian listed stocks, ETFs, all Brazilian investment-fund types, and Brazilian public debt, explicitly including NTN-B. All fund types are in scope; this does not imply uniform holdings transparency or that all types are currently supported.

Look-through analysis includes debt held by funds, such as debentures, even while direct private-debt portfolio positions remain deferred. Security-specific terms and issuer relationships may be needed to explain the fund's exposures. Fund holdings are underlying exposures, not additional portfolio positions to count twice.

Public-debt ingestion and serving are requested capabilities. The official Tesouro Direto price/rate history is a candidate source, not evidence of complete coverage of every government security held by funds. NTN-B with semiannual coupons and NTN-B Principal are distinct instruments; maturity and cash-flow structure matter.

Source references checked during design:
- https://www.tesourotransparente.gov.br/temas/divida-publica-federal/estatisticas-e-relatorios-da-divida-publica-federal
- https://b3.com.br/pt_br/produtos-e-servicos/tesouro-direto/informacoes-tecnicas.htm

## Portfolio input

Spreadsheet upload plus manual editing is the agreed initial input method, with asset identifiers, quantities or current values, and a valuation date. An Open Finance Brasil connection is an optional addition if integration proves straightforward; it must not block the initial demonstration.

Provider feasibility is not yet established. Pluggy documents an Open Finance connection widget and institution-dependent investment coverage; Belvo documents an Investments Brazil API. These are candidates, not selected providers or activated integrations. Confirm target institutions, investment types, production eligibility, pricing, consent flow, and reliable identifier mapping before deciding whether the optional connection meets the simplicity requirement. Use the provider's regulated Open Finance route when evaluating this request, not an unregulated direct connector by substitution. Open Finance imports the user's positions; underlying fund disclosures and contractual analysis still require SILO's other data sources.

Sources checked during design:
- https://docs.pluggy.ai/en/docs/open-finance/creating-item
- https://v1.docs.pluggy.ai/docs/investments-open-finance-coverage
- https://developers.belvo.com/apis/belvoopenapispec/investments-brazil

## Incomplete-data policy

When a holding lacks reliable valuation history, continue the exposure diagnosis and qualitative warnings supported by evidence, but withhold a complete portfolio optimization benchmark. Identify affected positions and quantify their portfolio share only where valuations permit; otherwise state that the share is unknown. Any optimization of the adequately covered subset must be explicitly labeled a partial comparison. Never silently exclude holdings or present the subset as the entire portfolio.

## Analysis horizon

The user selects the investment horizon; the demonstration defaults to one year. This horizon is distinct from the historical estimation window. Comparisons must state whether they evaluate market value at the selected horizon or cash flows through an instrument's maturity; a short selected horizon must not silently become a hold-to-maturity analysis.

## Risk estimation

Returns are measured monthly for every holding, over a five-year estimation window (about 60 observations), with covariance shrinkage (Ledoit-Wolf as the initial choice). Monthly is the only frequency every priced holding type shares: FI funds (`cvm_fi_diario`) and B3-listed stocks, ETFs and FIIs (`b3_cotahist`) are daily, but FIDC tranches (`cvm_fidc_tranche.vl_cota`) are monthly, and the demo portfolio contains a FIDC by design. Daily series are compounded to month-end returns. Holdings with fewer months than the window follow the incomplete-data policy rather than being silently shortened or dropped.

Listed returns are price-only adjusted for share-count events (splits, groupings, bonuses) from `b3_corporate_event`; cash events are not reinvested, since the returns feed risk benchmarks only. B3's `factor` convention is verified per event label against the tape before any label is applied, and a month containing an event with an unverified label is unknown for that holding, never guessed. Total return is deferred.

NTN-B has no price series in SILO today. A Tesouro Direto price/rate ingest is in scope before the demo; until it lands, any portfolio holding NTN-B gets a labeled partial comparison.

## Quantitative benchmarks

Compare the current portfolio against both minimum variance and equal risk contribution allocations. Equal risk contribution balances estimated contributions to portfolio volatility, not invested amounts. Neither benchmark forecasts returns or establishes maximum future return. Shared underlying exposures and qualitative warnings remain visible for every comparison; equal risk contributions at holding level do not establish balanced exposure to issuers or economic factors.

Method reference: https://www.thierry-roncalli.com/download/erc.pdf

## Proposed details requiring further validation

Each warning should describe the finding, affected positions, supporting source and date, and remaining uncertainty.

Maintain broad document discovery and extract selectively for monitored holdings, with additional history on demand. This ingestion approach remains a hypothesis, not an architectural decision.

## Open decisions

Tracked in `docs/planning/OPEN_ITEMS.md` item 15.

## Deferred

Return forecasting, expected-return optimization, buy/sell recommendations, automatic warning-derived constraints, stored portfolios and portfolio monitoring, and a settled bulk-versus-on-demand architecture are outside the current agreement. Economic-group exposure is parked until a filed source exists (candidate: the group structure disclosed in CVM's Formulário de Referência). The stateless decision is recorded as `docs/adr/0001-stateless-portfolio-analysis.md`.

## Superseded proposal

The earlier efficient-frontier comparisons targeting expected returns were set aside when the user excluded return forecasting. The analysis horizon remains selected by the user, with a one-year demo default; it does not by itself supply return assumptions.
