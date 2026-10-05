"""Machine-readable map of the Silo read API for agents.

The primitive is a panel: (id, date, metric, value). An agent should:
  1. POST /rest/v1/rpc/catalog (once, cache it)
  2. POST /rest/v1/rpc/lookup to resolve ids
  3. POST /rest/v1/rpc/panel with those ids and a subset of catalog metrics
  4. reduce in the notebook (corr, rank, OLS, …) — not over HTTP

reduce_panel / pearson stay in this module for tests and notebooks.
They are not routes.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

__all__ = [
    "CATALOG_VERSION",
    "CONSTRAINTS",
    "LIMITS",
    "METRICS",
    "SCREENS",
    "catalog_payload",
    "tool_specs",
]

# v43: the research universe (docs/planning/RESEARCH_SEAM.md §4, #411), in
# 28_api_research.sql. api.research_universe — one row per ticker+ISIN pair of
# listed shares and units traded on the B3 cash market since 2019-01-02;
# membership by the ISIN's own instrument code (ACN; CDA / UNT with a ticker
# ending 11), so subscription receipts are out. The ISIN is the identity, a
# rename is a new row, and cnpj_basis says how the company link was made.
# Served from a view rebuilt daily, so last_observed lags by up to a day.
# Raise-only; capped count forty-three -> forty-four.
# v42: the Brazilian rate curve (INSTRUMENTS.md phases B and C, OPEN_ITEMS
# B8), in 27_api_rates.sql over migration 48's landing tables.
# api.future_curve — every outright DI1 contract on one B3 session, nearest
# maturity first (B3 Price Report, from 2018-01-02); api.future_series — one
# contract through time. DI1 is quoted in rate, so the quote columns are
# % a.a.; contract_month (from B3's month letters) is the one derived column.
# api.curve — one B3 reference curve (PRE, DOC, DPL; TaxaSwap, from
# 2008-01-02) on one session, every vertex, rate_basis on every row (DOC is
# linear 360); api.curve_history — one of B3's FIXED vertices through time,
# never an interpolation. The long end of every curve is B3's extrapolation,
# and the comments say so. coverage() gains di_futures and reference_curves.
# All four raise-only; capped count thirty-nine -> forty-three.
# v41: api.fund_holdings / api.fund_debentures stop trimming. Until v40 they
# were tiered 500 anonymous / 5000 signed in and cut the result SILENTLY at
# that ceiling with a 200 — the last two functions that did, and the MCP
# (always anonymous) passed the short answer on as whole. They are raise-only
# on the 1000-row page now, like the FIDC trio since v34: p_limit is an
# explicit newest-first head (1..1000; NULL or above one page = the whole
# window, served whole or refused; < 1 = 22023). Their *_rows tier ceilings
# leave limits.tiers. Capped count thirty-seven -> thirty-nine.
# v40: what a restatement changed (backlog B4, docs/planning/DOCUMENTS.md),
# in 24_api_fnet.sql over the diff tables of migration 46. New
# api.fund_restatement_diff — one row per field a re-filed document changed,
# for the documents SILO has diffed (the FIDC informe mensal, delivered from
# 2026 on): field_path (repeated blocks by declared key, else by position,
# match_basis says which), old / new text as printed, old_num / new_num /
# delta on numeric leaves only, both versions' source_url; needs p_cnpj or
# p_fnet_id; raise-only. api.fund_restatements gains n_fields_changed and
# diff_status, for THIS pair only (NULL = not diffed). Capped count
# thirty-six -> thirty-seven.
# v39: three more held datasets reach the API, in 19_api_contract.sql (#295).
# api.financial_statement_history — raw CIA account lines across every stored
# filing version for one required statement and company id (financials stays
# latest-version only). api.fii_property_history — one FII's property rows
# (cvm_fii_imovel) by exact CNPJ and reference-date window; row_hash names a
# source row, not a durable asset. api.focus_expectations — the weekly Focus
# path (bacen_expectativas) for one endpoint and required horizon. All three
# refuse above one page; capped count thirty-three -> thirty-six.
# v38: three held-but-unserved datasets reach the API (DATA_INVENTORY.md §3,
# wave 3), in 26_api_events_macro.sql. api.company_events — a listed
# company's IPE filings (cia_event), one row per protocol at its newest
# version, text as filed, source_url = CVM's RAD link, the company resolved by
# api.company_ref exactly as api.financials resolves p_id (FCA map / CNPJ /
# CVM code, never a name); history from 2015 and incomplete, because filings
# CVM published without a protocol number are not held. api.macro_series —
# the nine non-inflation SGS series (SELIC target and daily, CDI, IGP-M, INPC,
# old-rule poupança, SGS BRL/USD and BRL/EUR, monthly GDP), registry mirrored
# from SGS_SERIES minus INFLATION_SERIES, unit and frequency on every row, the
# IPCA codes refused with a pointer to api.inflation. api.ptax — PTAX compra /
# venda per currency and day as published (the Fechamento bulletin for a
# completed day, measured). Nothing derived. coverage() gains company_events,
# macro_series and ptax rows; capped count thirty -> thirty-three.
# v37: three FILING-BEHAVIOUR screens (25_api_filing_screens.sql), signals
# not verdicts like the seven in 23, but native functions rather than wrappers
# because no dashboard page runs them. api.screen_restatements — funds whose
# FNET re-filings (versao > 1; RE voluntary vs RC CVM-required) in a trailing
# delivery window cross a count AND a rate threshold, fund identity by
# cnpjFundo link only. api.screen_late_filers — FII / FIDC monthly informes
# whose first FNET delivery came p_min_days_late or more days after the
# deadline RESOLUÇÃO CVM 175 states (Anexo Normativo II art. 27, III for FIDC;
# Anexo Normativo III art. 36, I for FII: 15 days after month end), measured
# only from the first full month after each family's adaptation deadline
# (2024-12 FIDC, 2025-07 FII); lag and days past the cited deadline are served,
# the citation rides on every row. api.screen_silent_filers — funds the CVM
# registry still lists as active whose last periodic informe in CVM's own
# tables (dim_fund) is N complete months behind latest_complete_period, with
# the newest FNET delivery as context. Late and silent are two screens, not
# one: different sources (FNET vs CVM's deep history), grains and failure
# modes. Capped count twenty-seven -> thirty.
# v36: company_financials.net_income is keyed on the FILED LABEL, like
# income_statements (register item 2, option 2, owner's call 2026-09-25). A
# behaviour change: 282 bank-B statements that read NULL (no 3.11) now carry
# net income from 3.09's net-income label, and insurers get 3.13 (net income)
# instead of 3.11 (continuing operations). No code fallback is added.
# v35: api.balance_sheets and api.cash_flow_statements — the other two
# statements as PERIODS, on the income_statements design (FINANCIALS_API.md §8
# step 2). Fields keyed on the as-filed label, measured first (FY2024, con,
# annual): equity sits on 2.03 / 2.07 / 2.08 across the industrial [450], bank A
# [10] and bank B [7] charts. Where one label is filed twice in a filing —
# `Empréstimos e Financiamentos` under both current and non-current liabilities —
# the parent's LABEL disambiguates; no code is consulted. Banks file no
# current/non-current split and no debt line, so those fields are NULL for them.
# Cash flows map only the section totals and the cash reconciliation (6.01 –
# 6.05.02, uniform across charts); capex and dividends are free text per filer
# (20+ spellings of capex alone) and are deliberately NOT fields. `method` says
# direct (DFC_MD) or indirect (DFC_MI).
# v34: two owner-approved changes (plans 2e and 1c). (a) fidc_cedentes,
# fidc_sacados and fidc_portfolio stop TRIMMING SILENTLY at the tier ceiling
# (500 anonymous / 5,000 signed in) and become raise-only on the one 1000-row
# page like fidc_tranches: their `*_rows` tier ceilings leave limits.tiers,
# they join limits.page.raise_only, and the capped count goes twenty-two ->
# twenty-five. p_limit stays, as an EXPLICIT newest-first head (1..1000). The
# 22023 from api.assert_row_cap now says WHY (one 1000-row page; SILO never
# returns a silently truncated result) and HOW for that function, in the
# message and again as DETAIL / HINT. (b) Lineage: cvm_ingest_log gains
# git_sha (GITHUB_SHA, NULL when unset — never invented) and parser_version
# (src.pipeline.ingest_log.PARSER_VERSION), migration 44; coverage() gains a
# typed landed_git_sha column — the commit of the very run that set landed_at,
# i.e. which code produced this data.
# v33: the FNET document register reaches the API (backlog B1, plan item 1b).
# Two functions in 24_api_fnet.sql over fnet_document / fnet_document_filter
# (migration 42): api.fund_documents — every B3 Fundos.NET document LINKED to
# one fund (FNET rows carry no CNPJ; the link is "FNET returned this id for
# cnpjFundo = X" from the fortnightly sweep, never the fund name), newest
# delivery first, with FNET's own download link as source_url; and
# api.fund_restatements — every document with versao > 1 (modalidade RE / RC as
# published), paired with the version it most plausibly replaced by a STATED
# group key (cnpj link, categoria, tipo_documento, especie, reference_raw),
# because FNET links no versions: highest lower versao, greatest fnet_id on a
# tie (a group can hold several v1 assemblies). Unlinked documents are served
# with cnpj NULL and never paired. Both raise_only. coverage() gains an
# fnet_documents row keyed on the delivery day.
# v31: the forensic screens reach the API (COMPETITIVE_GAPS.md §7 B3). Seven
# api.screen_* functions (23_api_screens.sql) wrap the public screens the
# dashboard already reads (15_fraud_screens.sql) — zombie_growth,
# captive_vehicles, evergreen_aging, overdue_securit, dormant_funds,
# dormant_trend, delinquency_drivers — one definition, called, never restated.
# SIGNALS, NOT VERDICTS: every row carries `screen` and `params` (the arguments
# it was evaluated with), `screens` below says what each one measures and what
# else produces the same pattern, and nothing is scored or rated. Defaults are
# the dashboard's own calls; out-of-range thresholds raise 22023; more than
# one page raises 22023 (raise_only). The public screens lost their
# GRANT EXECUTE to anon/authenticated in the same change — the wrappers are
# the only client door.
# v32: the FIDC structure tabs reach the API (backlog B3). Two functions over
# tables /fidc has read since the start and no caller could reach:
# api.fidc_tranches — one row per (fund, month, tranche) from informe tabs
# X_2/X_3/X_6, quotas, quota value, the month's return and PROMISED vs
# REALISED performance as filed, with the tranche's tab X_4 operations as a
# `flows` array keyed by CVM's own TP_OPER label (free text whose vocabulary
# has drifted, so it is never bucketed into subscription / redemption
# columns that could silently drop a label); and api.fidc_aging — tab VI
# long, to_maturity and overdue ladders in ten day-bands plus CVM's FILED
# overdue total, which is not a sum of the bands. Both refuse over one page
# (limits.page.raise_only), derive nothing, and carry the honest limit on
# their coverage() rows: HISTORY BEGINS IN 2025, because CVM's HIST archive
# publishes no equivalent member — an upstream limit, not a backfill gap.
# v30: inflation. Two functions, two sources, one derived number each.
# api.inflation serves BACEN's SGS long — IPCA, IPCA-15, BACEN's own 12-month
# accumulation (13522), the five BCB cores (MS, MA, EX0, EX2, DP), the
# monitorados / livres, comercializáveis / não, duráveis / semi / não / serviços
# splits, the diffusion index and IBGE's nine expenditure groups — as monthly
# changes in percent AS PUBLISHED, plus acc_12m: the trailing twelve chained,
# NULL unless all twelve are present and consecutive (measured: it reproduces
# 13522 exactly, 4.22 for 2026-08). api.inflation_items serves IBGE SIDRA's
# item tree (1419 from 2012-01, 7060 from 2020-01): weight, monthly / YTD /
# 12-month change per node as published, plus contribution = weight × change
# / 100 in percentage points. THE SGS GROUP CODES ARE NOT IN IBGE'S ORDER
# (1640 Comunicação, 1641 Saúde, 1642 Despesas pessoais, 1643 Educação),
# matched value for value against SIDRA on three months; the EX1/EX3/P55
# cores are absent because BACEN's catalogue does not name their codes. No
# panel arm: these rows carry no id.
# v29: api.income_statements — the income statement as a PERIOD (one row, named
# fields) rather than as lines, the shape docs.financialdatasets.ai uses. The
# fields are keyed on the AS-FILED LABEL, not on cd_conta and not on setor,
# because CVM ships FOUR DRE charts and the same code is a different concept
# across them. Measured (FY2024, con, annual): net income sits on 3.11 for the
# industrial [448] and bank A [10] charts, on 3.09 for bank B [7] which files no
# 3.11 at all, and on 3.13 for the insurer chart [2] whose 3.11 is the
# continuing-operations line. Three codes, one pair of labels. So label-keying is
# not merely safer than code-keying, it is strictly MORE COMPLETE: it resolves
# net income for the 282 statements company_financials must return NULL for.
# `de` vs `da` Intermediação is NOT normalised — it separates two charts with
# different layouts. A concept a chart does not file reads NULL (operating_income
# is industrial-only). `chart` names the layout; net_income_controlling /
# _noncontrolling carry the attribution split that per-share figures are built on.
# v28: two changes to the listed-company financials, one of them a BEHAVIOUR
# change. (1) `setor` and `segmento` now ship on every financials and
# company_financials row, appended so nothing positional moves. They are a
# PARTITION KEY, not a label: CVM's chart of accounts is sector-specific, so
# 3.01 is sales for an industrial filer and intermediation income for a bank,
# and any median, rank or percentile computed across sectors on one account
# code ranks two different quantities. (2) company_financials.net_income is
# conta 3.11 ONLY — the COALESCE to 3.09 behind it is GONE. 3.09 is profit
# BEFORE statutory profit-sharing (3.10), so it was never net income; measured
# across the whole table, 282 of 50,439 DRE statements (0.56%) have no 3.11 and
# those now read NULL instead of silently reporting a pre-participations
# figure. Callers who want that figure read 3.09/3.10/3.11 from financials.
# Not exposed, deliberately: escala_moeda. cia_account.vl_conta is already
# multiplied to absolute reais at ingest, so publishing the filed scale would
# invite a caller to apply it twice. Every value in these functions is reais.
# 15: api.universe dropped at the owner's request — removed from the contract,
# the /v1 route, the SDK and the tool specs, and DROPped in production by
# migration 31. Cash and fund ids are still discoverable through lookup and the
# funds/quotes views. Option and termo codnegs are NOT: option_chain needs a
# 3-character prefix, so there is no longer any way to browse that namespace
# cold. That is a deliberate reduction in surface, not an oversight.
# 14: the documented row cap was unreachable and the real one was silent.
# PostgREST caps EVERY response at 1000 rows (db-max-rows) and keeps the OLDEST,
# so a panel for PETR4 from 2019 returned 1000 rows ending 2023-01-09 with a 200
# — a truncated series that reads as a complete one. The cap+1 sentinel this
# catalog told agents to check (100001/5001) can never fire behind that ceiling.
# Content-Range is the only real signal, and Range paging does NOT work on RPC
# (page 2 returns page 1); both are now stated. Found by an independent audit of
# the live deployment, reproduced 2026-08-28.
# 13: price is the default and the catalog now says so, machine-readably —
# panel already defaulted to close+nav, but an agent that cannot see a default
# asks for every metric instead.
# 12: instrument typing v3 — index / right / bonus split out of the residual
# cash_security bucket (measured: its top members by volume were subscription
# rights and bonus rights, not debt), and an ETF keeps its subtype across the
# board-code change B3 made in late 2019.
# 11: the catalog described only the local /v1 adapter while the deployed
# surface is PostgREST — an agent following it issued the wrong verb and, worse,
# believed an over-cap panel answers 400 when PostgREST returns cap+1 rows with
# a 200. Both surfaces are now named, the cap constraint explains the sentinel,
# and the postgrest section carries the core contract (panel/lookup/coverage/
# funds/quotes), not just the typed-cash extras. (universe was part of that
# set until v15 dropped it.)
# 10: close_unit — close divided by the published quotation factor, so price
# levels are comparable across papers quoted per lot; raw close untouched.
# 9: lookup company rows carry `tickers` — CVM's published FCA
# valores-mobiliários CNPJ↔ticker map (cia_ticker / vw_company_ticker),
# replacing the old "not joined here" stance: the join is published, not
# inferred.
# 8: honest default windows — with no explicit `to`, fund metrics clamp to
# each family's latest COMPLETE period (mv_period_completeness) instead of
# serving a partially-filed trailing month; coverage() adds complete_through
# and per-family rows; close_return gains session-adjacency and
# quotation-factor guards; postgrest endpoints split into their own section.
# 7: option rows resolve underlying_ticker via the published ISIN mapping;
# fund_quotas carry fund_type (etf/fii/fidc/fiagro from CODBDI); equities carry
# share_class/governance_segment from ESPECI; exercise (tpmerc 012/013) and
# auction (017) events get their own endpoints.
# 6: one endpoint per cash instrument type, each carrying both lot sizes.
# 5: main's typed cash asset classes (4) merged with the option/termo id_types
# and list-valued id_type this branch introduced (3).
# 22: GitHub is the only sign-in provider. The catalog said "GitHub or Google";
# Google was never enabled in Supabase Auth, so the sign-in page offered a
# button that failed on click and the machine-readable how_to_sign_in sent
# agents to a provider that does not exist. Prose corrected, button removed.
# Also: api.fund_holdings had been missing from the postgrest endpoint map since
# v17 (only its tier row was listed), so an agent caching the catalog could not
# discover holdings. Added.
# 21: api.fund_debentures — CDA block 6, the fund → corporate-credit edge.
# Not a third p_kind of fund_holdings: a debenture has no CD_ATIVO and its
# identity is (issuer, maturity, rate structure), so it gets a shape that
# carries them. The issuer is reached by its own filed CPF/CNPJ, or — for a
# listed company — by ticker/CVM code through the published FCA map;
# issuer_tickers carries the listed codes back. Tiered 500 / 5000 like
# fund_holdings.
# 20: api.anbima_classes — the ANBIMA Boletim de Fundos class series (AUM, net
# flows, returns, fund counts per class / type / industry total) reach the API
# as the industry aggregates they are: no id, no panel arm, no fund↔class join
# (CVM's `classe` is not ANBIMA's taxonomy). coverage() gains an
# `anbima_classes` row with as_of = complete_through — a published edition is
# complete by construction.
# 19: `limits` — every ceiling in one machine-readable block. The numbers were
# already in the contract, but scattered across prose constraints, the agents
# page and the SDK README, and an agent that has to parse "3 ids anonymous,
# 50 signed in" out of a sentence will get one of them wrong. rows_per_response
# (server-wide 1000, with how to detect and what pages), the functions' own
# unreachable LIMIT sentinels (named so nobody waits for them), and the per-tier
# ceilings — read from the same SQL a lockstep test pins them to.
# 18: listed-company financial statements reach the API. api.financials
# serves the statement lines long (one row per account, carrying doc_type,
# statement, scope, the ÚLTIMO/restatement choice as `version`, and the
# dt_ini_exerc span as `period_months`); api.company_financials serves the
# headline lines wide with margin and ROE. Both resolve a B3 ticker to the
# company through CVM's published FCA map, so `panel('PETR4', close)` and
# `financials('PETR4')` take the same id. coverage() gains a `financials`
# row. No panel arm yet: an ITR files a 3-month AND a year-to-date figure
# under one date and the panel is 1-D per (id, date, metric), so choosing a
# span silently is exactly the fabricated number this contract forbids.
# v23: honest nulls per family, and the one regime break in the fund
# series. `applicability` says which fund_nav / panel columns each family
# actually files into fact_fund_monthly, so a null OUTSIDE that list reads
# as not-applicable (the fact table sets it NULL by construction) rather
# than as missing data; the `quotaholders` metric drops fidc/fip/fiagro,
# where it was never served. `regime_breaks` records that FIDC
# `delinquency` is null on every row through 2024-12 (CVM's pre-2025 tab
# II/III monthly file carried no delinquency field) and filed on every row
# from 2025-01 (tab IV + VI): a series that changes meaning mid-stream must
# not be chain-linked through the boundary. coverage() gains a `notes`
# column carrying the same boundary on the funds_fidc row.
# v26: the REST of the contract refuses instead of trimming. The seven series
# and statement functions (quote_history, fund_nav, option_history,
# termo_history, financials, company_financials, anbima_classes) join the panel
# on one 1000-row page and raise 22023 above it; quote_history and fund_nav
# also take a p_after date cursor, and fund_nav's paging REQUIRES p_entity_type
# because its cursor is a bare period and a CNPJ can file under two families in
# one month. The unreachable 5001 sentinel leaves the contract with
# limits.sql_sentinel. coverage() gains newest_period and landed_at and bounds
# as_of by today (funds.as_of read 2026-12-31 in production on 2026-09-16,
# because FIP is keyed to 31-December). New api.metric_coverage() publishes the
# filed span of every (family, metric) pair, measured rather than declared.
# v25: the FIDC concentration tabs reach the API. Three functions —
# fidc_cedentes (tab I, the fund → named-originator edge, by fund or by
# cedente CPF/CNPJ/ticker, cedente_tickers from the FCA map like
# fund_debentures.issuer_tickers), fidc_sacados (tab VIII, the 25 largest
# debtors as anonymized ranks, as filed), fidc_portfolio (tab II sector
# hierarchy and tab X SCR grade ladders, long: kind/code/parent/item/value) —
# and three fidc panel metrics: receivables (tab II portfolio total),
# sacado_top1 and sacado_top25 (the rank-1 exposure and the sum of the filed
# ranks). A concentration ratio is a notebook division of two of them, not a
# served number. `applicability` gains a fidc_concentration block so the
# per-metric family list stays pinned to a source; coverage() gains
# fidc_cedentes / fidc_sacados / fidc_sectors / fidc_scr rows whose notes
# carry the start months (cedente slots from 2019-11, tab X from 2023-10).
# v27: the B3 securities-lending and investor-flow group reaches the catalog.
# Five views were GRANTed to anon/authenticated by the #235/#240-#245 work and
# have been answering on the publishable key ever since, but they were in no
# catalog, no docs page and no SDK method — so an agent following this
# contract's own catalog-first instruction could not discover them, and the
# only way to find them was to already know their names. Registered in
# `postgrest` (short_interest, short_interest_by_sector, investor_flow,
# lending_trades, lending_participants) with coverage() rows so freshness
# reports them like every other dataset. Three constraints come with them,
# because each one is a way to be confidently wrong: the RATCHET (B3 keeps ~21
# business days and publishes no archive, so history starts at first capture
# and cannot be bought), FLOAT_BASIS (pct_float is two different metrics and
# they are never comparable), and BROKERAGES (doador/tomador are the
# intermediary, not the owner — ~75% of trades are a broker crossing its own
# clients). investor_flow's first-difference semantics join the same list.
# Also: the `examples` were written as GET /v1/panel — the local Flask adapter
# that this same catalog's `agent` string calls "not necessarily deployed" —
# so an agent copying them verbatim against the hosted surface got a 404 from
# the one section meant to be copyable. They are POST /rest/v1/rpc/panel now.
# v24: the panel REFUSES instead of trimming. More than 1000 rows now raises
# 22023 unless the caller pages with p_after ('' = first page, then the last
# row's 'date|id|metric|asset_class'); the unreachable 100001 sentinel leaves
# the contract (limits.page replaces limits.sql_sentinel.panel). The grain is
# stated as (id, asset_class, date, metric) and p_entity_type narrows the fund
# arms to one family. Universe mode (p_ids empty + p_entity_type, optional
# p_min_nav / p_min_months) walks a whole family for signed-in callers.
# v44: quote_history gains close_price_adjusted (continuous across splits,
# groupings and bonus shares, anchored to the latest session, NULL with a
# reason until the issuer's events are proven swept) and close_total_return
# (NULL with a reason until the cash history is backfilled), #417 / #413.
# v45: the benchmark index (docs/planning/RESEARCH_SEAM.md §5, #412 / #415), in
# 29_api_index.sql over migration 55's b3_index_level. api.index_history serves
# the daily levels of a B3-published index AS PUBLISHED (IBOV from 1968), by
# index code only: a ticker, BOVA11 and IBOV11 included, raises 22023. The
# series is not adjusted and divisor_step marks the eleven sessions on which B3
# re-scaled it. Pages with p_after like quote_history; paged count three -> four,
# capped count forty-four -> forty-five. api.coverage() gains an index_history
# row with the depth of each index in its notes.
# v46: quote_history's close_total_return is served (#418). It is the
# price-adjusted close divided by the product of (1 + cash / ex-session close)
# over the distributions that went ex after the session, from migration 56's
# mv_b3_cash_event: DIVIDENDO, JRS CAP PROPRIO (gross), RENDIMENTO and REST CAP
# DIN from B3's full cash history, resolved to an ISIN only where the published
# pre-ex close agrees with the tape. NULL with a reason where a distribution
# cannot be valued (no proven ISIN for that issuer's class, listed by B3's
# supplement and missing from the history, no ex-date close within 7 days) or
# the ISIN has no resolved distribution at all. No new function and no new
# column: the version moves because the published meaning of a column did.
# v47: the five latest-version fundamentals functions (financials,
# company_financials, income_statements, balance_sheets, cash_flow_statements)
# gain a trailing p_as_of DATE DEFAULT NULL (#414). NULL keeps today's meaning,
# now labelled not point-in-time. A date T reads only documents CVM had
# received before T (cia_filing.dt_receb < T), keeps the highest remaining
# version of each, and drops a document with no header. The shared internal
# api.cia_statement_rows carries it. No new function and no new column.
# v48: the research price contract (#410). quote_history returns one JSON
# object per session holding only the selected fields (p_fields); the default
# is ticker, trade_date, close_adj, and the raw close, OHLC and volume are an
# explicit selection. close_price_adjusted becomes close_adj and is never NULL
# in disguise: a window it cannot adjust (outside shares/units, issuer events
# not proven swept, an unsupported, unreadable or ambiguous event) is refused
# with ticker, period and cause. close_total_return (v46) becomes a selectable
# field with its reason, same meaning. The series follows the ISIN across boards (ETER3 had lost 1,396
# sessions to the latest-board default); an unknown ticker, a window outside
# the coverage, a second ISIN in the window or two rows on one session refuse.
# data_revision identifies the data behind a response. The panel defaults to
# close_adj for shares and units (new metric), close for other tickers.
# v49: the benchmark-index constraint no longer says IBOV11 "prints on expiry days
# only". It did through 2024 (12 prints a year), printed weekly in 2025 and has
# printed on nearly every session since December 2025 (181 of 187 sessions of
# 2026). None of those prints equals the official close (mean difference 0.18%,
# up to 1.07%), so the rule stands: index_history takes an index code and
# refuses IBOV11, which is a settlement index, not the benchmark. A description
# fixed, no behaviour changed.
# v50: panel's close_return is NULL on a session whose price comparison crosses a
# share-count event (DESDOBRAMENTO, GRUPAMENTO, BONIFICACAO), #396 step 1: the
# raw close read a split as a return (BBAS3's 2:1 split, 56.46 -> 27.91, served
# -50.57%). It is the raw-close return with that session nulled, not an adjusted
# return. Behaviour and descriptions change; no signature or column does.
# v51: the portfolio-diagnosis reads (map #510, docs/reference/research/
# portfolio-diagnosis-phase0.md), in 31_api_portfolio.sql. api.portfolio_resolve
# turns statement lines (name, optional CNPJ, optional quota and its date) into
# scored candidate funds over the WHOLE name history (CDA DENOM_SOCIAL since
# 2005 plus the registry), tie-broken by the quota on its date and flagged
# ambiguous rather than picked; api.portfolio_fees puts the DISCLOSED fee
# (lamina, else cad_fi, one source and date per fund, NULL is not zero) beside a
# separate balancete ESTIMATE with the fiscal-year reset handled;
# api.portfolio_lookthrough follows CDA block 2 recursively (CYCLE guard, depth
# cap) down to the assets of blocks 1, 4 and 6 with weights over the root's NAV.
# All three raise-only, anon-callable; capped count forty-five -> forty-eight.
# v52: api.portfolio_fees reads the disclosed fee from the CVM Extrato das
# Informacoes FIRST (cvm_fi_extrato, migration 66: a fee for 84.3% of the active FI
# funds against 15.9% for the lamina), then the lamina, then cad_fi, one source and
# date per fund, named in the new disclosed_origin (extrato | lamina | cad_fi). The
# owner's reading rules on the single administration fee: a filed 0 comes back as 0
# with filed_zero TRUE, a value above 5 is withheld (disclosed_taxa_adm NULL,
# implausible_filed TRUE, the value in taxa_adm_filed_raw). 25 columns are appended
# after estimate_label (the Extrato's performance, entry, exit and custody fees as
# filed, the class note, the lamina's declared expense ratio with its period); the
# existing 21 columns keep their names, order and types. The return type changed,
# so the function is dropped and created again. No new endpoint: capped count stays
# forty-eight.
# v53: the benchmark-index text says what B3 says: IBOV and every other code
# index_history holds are TOTAL-RETURN indices (#416; v45 to v52 called the series
# "a price index, not total return", which B3's own pages and Manual contradict).
# Eight codes join IBOV (IBXX, IBXL, IFIX, SMLL, IDIV, ICON, IMOB, UTIL), each
# served from its own first session; coverage() already reads the depth of each
# from the table. A description and a data set change; no signature, column or
# endpoint does, so the capped count stays forty-eight.
# v54: api.portfolio_movement (31_api_portfolio.sql, map #510, owner decisions of
# 2026-10-03): is a fund's month unusual for its own class (movimento incomum).
# Per CNPJ and month, the fund's monthly QUOTA RETURN (month-end vl_quota over the
# previous month's, fact_fund_monthly) against the same return over the FI funds of
# its ANBIMA class as filed in the CVM Extrato; the class mean and sample sd are
# taken on values winsorized at the class's 1st and 99th percentile, z = (own -
# mean) / sd, level atencao beyond |z| 2 and forte beyond |z| 3 (strictly), and
# nao_avaliado with a reason (fewer than 30 peers, no class, no return, an ETF or
# FIDC/FII/FIP/FIAGRO, an incomplete month). Raise-only, anon-callable; capped
# count forty-eight -> forty-nine. No existing signature or column changes.
# v55: api.portfolio_fees when the Extrato and the lamina disagree (issue #552,
# measured 2026-10-03: 180 funds with an Extrato fee of 0 and 15 above 5 have a
# lamina fee in (0, 5], 115 and 14 of them newer than the Extrato). The Extrato
# stays the source as filed, except when it filed exactly 0 or above 5 AND the
# lamina's single fee is in (0, 5] AND the lamina is NEWER: then the newer lamina
# is the source. Nothing is rescaled. Ten columns are appended after
# lamina_expense_note: fee_resolution (extrato | extrato_lamina_beside |
# extrato_to_check | lamina_newer | lamina | cad_fi), the lamina's own fee for
# every fund (lamina_taxa_adm, _min, _max, lamina_n_classes, lamina_age_months),
# the Extrato's as filed (extrato_taxa_adm_filed, extrato_as_of), their ratio and
# extrato_scale_factor (10 or 100 within two-decimal rounding: a flag, never a
# correction). The existing 46 columns keep their names, order and types; the
# return type changed, so the function is dropped and created again. No new
# endpoint: capped count stays forty-nine.
# v56: ETFs carry a fee, and a newer lamina's fee is summed (owner, 2026-10-03,
# follow-up of #552 on map #510). api.portfolio_resolve gains match_kind
# etf_ticker: a name that is exactly a ticker of the curated ETF registry gives
# that ETF's CNPJ (api.lookup returns no CNPJ for a ticker; a fixed income ETF is
# not in COTAHIST). api.portfolio_fees appends five columns after
# extrato_scale_factor: etf_ticker and etf_site_taxa_adm / _as_of / _source /
# _note, the etfsbrasil.com.br fee (etf_market_snapshot), because CVM's Extrato,
# lamina and cad_fi hold no fee for any of the 178 active registry ETFs
# (measured 2026-10-03). A third-party value, never in disclosed_*. The text now
# says a lamina_newer fee is the cost to sum. No new endpoint: capped count
# stays forty-nine.
# v57: an ETF's cotistas and PL (owner, 2026-10-03, map #510). CVM has no 2026
# diario row (no cotistas, no PL) for any of the 178 active registry ETFs, so
# api.portfolio_fees appends two columns after etf_site_note: etf_site_nr_cotistas
# and etf_site_pl (R$), etfsbrasil.com.br's 'Numero de cotistas' and 'Patrimonio
# liquido' from the same etf_market_snapshot row as the fee (etf_site_as_of,
# etf_site_source). Descriptive third-party facts, never summed. The existing
# columns keep their names, order and types. No new endpoint: capped count stays
# forty-nine.
# v58: FIDC history text (#556). Tranches (tabs X_2/X_3/X_6 + X_4), the aging
# ladder (tab VI) and fund-level delinquency are loaded from CVM's yearly HIST
# archive back to 2013-01 (#569), so the notes that said they begin in 2025
# because CVM publishes no archive are rewritten. The delinquency regime break
# moves from 2025-01-31 to 2020-11-30: the same filed field on both sides,
# null for funds with no tab VI row before, on every row from. delinquency's
# `since` becomes 2013-01-31. Text only: no column, no endpoint, no behaviour
# change (fidc_delinquency_drivers still refuses a window before 2025-01).
# v59: panel's close_return is ADJUSTED across a share-count event (#396 step 2,
# owner decision 2026-10-04) instead of NULL: the previous close is divided by
# the event's share ratio (B3's rule, the one api.close_adj_ratio uses) before
# the return is taken, so a 1:4 split from 100.00 to 26.00 is +4% and BBAS3's
# 2:1 split is -1.13%. An unreadable factor or one label on one date with two
# factors still nulls it. Behaviour and descriptions change; no signature or
# column does.
# v60: quote_history follows a ticker's lineage across an ISIN change (#381
# follow-up, owner decision 2026-10-04, docs/adr/0002-ticker-activity-and-lineage.md):
# api.ticker_lineage splices an older (ticker, ISIN) only for the same company
# (same ticker or one FCA CNPJ), the same share class, adjacent sessions with no
# overlap, no stock event at the seam and one candidate. Rows keep their own
# ticker and ISIN; close_adj is continuous across the seam; close_total_return is
# NULL before it. coverage_start/coverage_end and isin_change say so. No
# signature or column change.
# v61: two portfolio reads for the engine's instrument and fund-terms sections
# (31_api_portfolio.sql). api.portfolio_instruments(p_codes) looks a statement's
# CRA / CRI up by CETIP code in cvm_securit_serie (match_kind securit_cetip, the
# code's newest informe, one row per series and class at its highest versao),
# else a debenture by its ticker in CDA block 4 (cda_ticker: the most common
# ISIN, issuer_code, the number of holding funds and their own mark, sum of value
# over sum of quantity, at the newest month the code appears in), else a row
# with match_kind NULL and a reason. api.portfolio_fund_terms(p_cnpjs) gives the
# manager and administrator as filed in cvm_fund_registry (one row picked per
# CNPJ, the rule stated) and the redemption terms of the CVM Extrato, else of the
# lamina, as filed, NULL when not filed. Both refuse above 200 inputs and above
# one page; capped count forty-nine -> fifty-one. Migration 73 indexes
# cvm_securit_serie (codigo_cetip, data_referencia DESC). No existing signature
# or column changes.
CATALOG_VERSION = 61

B3_CASH_ASSET_CLASSES = [
    "equity",
    "unit",
    "bdr",
    "fund_quota",
    # v12: measured in the tape, these three were being swallowed by the
    # residual bucket. `index` is an index line (IBOV11, ESPECI IBO + an IND
    # ISIN segment) — emphatically NOT an ETF, whatever its ticker looks like.
    # `right` is a subscription right (ESPECI DIR) and `bonus` a bonus right
    # (BNS); both are claims, not the security itself.
    "index",
    "right",
    "bonus",
    # Now a genuine residual: an ESPECI none of the above names.
    "cash_security",
]

# Grain + metric map. Agents must not invent metrics.
# id_type is a list (since version 3): one metric name can apply to several
# id namespaces — e.g. close serves equity tickers and option/termo codnegs.
METRICS: Dict[str, Dict[str, Any]] = {
    "close": {
        "id_type": ["ticker", "option", "termo"],
        "asset_class": [*B3_CASH_ASSET_CLASSES, "derivative"],
        "grain": ["day", "month"],
        "source": "b3_cotahist",
        "meaning": (
            "Unadjusted close, as traded. Cash tickers: every BDI board "
            "(the instrument's own series), classified from published "
            "TPMERC/ESPECI. Option/termo codnegs: that derivative segment's "
            "session close. Month = last session. The default for tickers "
            "outside shares and units, and for options and termo."
        ),
    },
    "close_adj": {
        # Owned by SILO, never the caller (RESEARCH_SEAM.md §3). The same
        # value quote_history serves: api.close_adj_ratio / assert_close_adj.
        "id_type": ["ticker"],
        "asset_class": ["equity", "unit"],
        "grain": ["day", "month"],
        "source": "b3_cotahist",
        "meaning": (
            "Close per single share, backward-adjusted for splits, groupings "
            "and bonus shares by B3's rule and anchored to the instrument's "
            "latest session; 6 decimal places. No dividend, JCP or subscription-right adjustment. "
            "Shares (ISIN code ACN) and units (CDA/UNT, ticker ending 11) "
            "only. A window it cannot adjust REFUSES (22023) naming ticker, "
            "period and cause; it is never the raw close under this name. The "
            "panel default for shares and units. Month = last session."
        ),
        "derived": True,
    },
    "volume": {
        "id_type": ["ticker", "option", "termo"],
        "asset_class": [*B3_CASH_ASSET_CLASSES, "derivative"],
        "grain": ["day", "month"],
        "source": "b3_cotahist",
        "meaning": (
            "Session traded volume (BRL). Cash: every BDI board (the "
            "instrument's own series); option/termo: that derivative segment. "
            "Month = last session."
        ),
    },
    "close_unit": {
        # Not an adjustment: division by a published COTAHIST field. FATCOT is
        # the number of shares the quoted price refers to (1, or 1000 for papers
        # quoted per lot), so close alone is not comparable across papers or
        # across a factor change. close and quotation_factor are still served
        # raw beside it. Splits/groupings/bonuses are NOT handled here.
        "id_type": ["ticker"],
        "asset_class": B3_CASH_ASSET_CLASSES,
        "grain": ["day", "month"],
        "source": "b3_cotahist",
        "meaning": (
            "Close per single quoted unit: close / quotation_factor, both "
            "published. Use this to compare price levels across papers; "
            "a paper quoted per lot (factor 1000) otherwise reads 1000x its "
            "unit price. Still unadjusted for corporate actions."
        ),
        "derived": True,
    },
    "close_return": {
        # Cash only. Derivatives carry strike/expiry/term effects that make a
        # naive close-to-close ratio misleading in a way the cash series is not.
        "id_type": ["ticker"],
        "asset_class": B3_CASH_ASSET_CLASSES,
        "grain": ["day", "month"],
        "source": "b3_cotahist",
        "meaning": (
            "p_t/p'_{t-1}-1, where p' is the previous stored close divided by "
            "the share ratio of every split, grouping or bonus (DESDOBRAMENTO, "
            "GRUPAMENTO, BONIFICACAO) between the two prints: 1 + factor/100 "
            "for DESDOBRAMENTO and BONIFICACAO, factor for GRUPAMENTO. A share-"
            "count change never reads as a return: 100.00 before a 1:4 split is "
            "25.00, so a 26.00 close is +4%, not -74%. On the monthly grain the "
            "event may sit anywhere between the two month-end prints. NULL (no "
            "row) across an event whose factor is unreadable or published twice "
            "with two factors. Price only: dividends and JCP still move it, so it "
            "is not a total return. "
            "Daily: previous session. Monthly: previous calendar month else null."
        ),
        "derived": True,
    },
    "nav": {
        "id_type": ["cnpj"],
        "asset_class": ["fi", "fidc", "fii", "fip", "fiagro"],
        "grain": ["month"],
        "source": "cvm",
        "meaning": "Fund net assets (vl_patrim_liq).",
        "coverage": "api.metric_coverage()",
    },
    "quota": {
        "id_type": ["cnpj"],
        "asset_class": ["fi"],
        "grain": ["month"],
        "source": "cvm",
        "meaning": "FI unit quota. Comparable subclass only.",
        "coverage": "api.metric_coverage()",
    },
    "delinquency": {
        "id_type": ["cnpj"],
        "asset_class": ["fidc", "fiagro"],
        "grain": ["month"],
        "source": "cvm",
        "meaning": "Delinquent portfolio value (not a rate unless you divide by nav).",
        # The one `since` this catalog states as a constant: the first month of
        # CVM's FIDC HIST archive, where the series starts (the 2020-11 coverage
        # boundary is in `regime_breaks`), and a lockstep test pins it. Every
        # other span is MEASURED — call api.metric_coverage() rather than
        # trusting a date written here once.
        "since": {"fidc": "2013-01-31"},
        "coverage": "api.metric_coverage()",
    },
    "yield": {
        "id_type": ["cnpj"],
        "asset_class": ["fii"],
        "grain": ["month"],
        "source": "cvm",
        "meaning": "Monthly yield % as published (FII complemento).",
        "coverage": "api.metric_coverage()",
    },
    "inflows": {
        "id_type": ["cnpj"],
        "asset_class": ["fi"],
        "grain": ["month"],
        "source": "cvm",
        "meaning": "Gross monthly subscriptions.",
        "coverage": "api.metric_coverage()",
    },
    "redemptions": {
        "id_type": ["cnpj"],
        "asset_class": ["fi"],
        "grain": ["month"],
        "source": "cvm",
        "meaning": "Gross monthly redemptions.",
        "coverage": "api.metric_coverage()",
    },
    "quotaholders": {
        "id_type": ["cnpj"],
        # fi and fii only: fact_fund_monthly's fidc, fiagro and fip arms set
        # nr_cotst NULL by construction (see `applicability`), so the panel
        # emits no quotaholders row for those families — not a gap, not served.
        "asset_class": ["fi", "fii"],
        "grain": ["month"],
        "source": "cvm",
        "meaning": "Number of unit-holders (fi, fii). Not served for fidc, fiagro, fip.",
        "coverage": "api.metric_coverage()",
    },
    # FIDC concentration (migration 38). These read the informe's own tabs,
    # not fact_fund_monthly, so their family list is pinned by
    # applicability.fidc_concentration rather than by fund_nav's arms.
    "receivables": {
        "id_type": ["cnpj"],
        "asset_class": ["fidc"],
        "grain": ["month"],
        "source": "cvm",
        "meaning": (
            "Receivables portfolio total (tab II TAB_II_VL_CARTEIRA), the "
            "denominator for any concentration ratio. Sector lines are in "
            "fidc_portfolio."
        ),
    },
    "sacado_top1": {
        "id_type": ["cnpj"],
        "asset_class": ["fidc"],
        "grain": ["month"],
        "source": "cvm",
        "meaning": (
            "Exposure to the single largest sacado (tab VIII rank 1), as "
            "filed. The debtor is anonymized in the source; divide by "
            "receivables in the notebook for a concentration ratio."
        ),
    },
    "sacado_top25": {
        "id_type": ["cnpj"],
        "asset_class": ["fidc"],
        "grain": ["month"],
        "source": "cvm",
        "meaning": (
            "Sum of the exposures to the largest sacados the fund filed "
            "(tab VIII ranks 1..n, n at most 25). A fund that files fewer "
            "than 25 ranks sums fewer; nothing is imputed for the missing "
            "ranks. Divide by receivables in the notebook."
        ),
        "derived": True,
    },
}

# Suggested notebook reductions. Not HTTP.
NOTEBOOK_REDUCERS: Dict[str, str] = {
    "describe": "Per-column n, null_rate, min, max, last. No model.",
    "corr": "Pairwise Pearson on complete pairs of the wide matrix. One relation among many.",
    "rank": "Latest non-null value per id for the first metric, descending.",
    "spread": "First column minus second column of the wide matrix, dates aligned.",
}

CONSTRAINTS = [
    "A NULL OUTSIDE A FAMILY'S COLUMN SET IS NOT APPLICABLE, NOT MISSING. fund_nav returns the same eleven columns for every family, but each family files only some of them (`applicability` in this catalog, read off fact_fund_monthly's per-family arms): fi files quota, quotaholders, inflows and redemptions; fidc and fiagro file delinquency; fii files quotaholders, monthly_yield and assets; fip files nav alone. A null outside that list is set by construction and carries no information; a null inside it is a blank in that month's filing.",
    "A FIDC CEDENTE SHARE IS A PERCENT OF ITS BLOCK, NOT OF THE FUND. fidc_cedentes serves tab I''s nine slots per block: bloco A is the receivables acquired WITH substantial retention of risks and benefits by the originator, B WITHOUT, and share_pct is the cedente''s share of that block. The block totals are not served (tab I''s asset lines are not ingested), so a share cannot be turned into reais here. cedente_id is the originator''s own filed CPF/CNPJ, kept only when its check digits verify — placeholders (all-zero, all-nine) and unrecoverable identifiers were dropped at ingest, never coerced — and cedente_tickers is the FCA map''s active listings for it, NULL when not listed. share_pct is AS FILED and dirty in the way CVM''s percentage fields are: 9% of slots carry a value above 100 (max 19,771 in 2026-07); validate the range in the notebook, never read it as a fraction. Slots exist from 2019-11; nothing is matched by name.".replace("''", "'"),
    "FIDC SACADOS ARE ANONYMIZED RANKS. fidc_sacados and the sacado_top1 / sacado_top25 metrics come from tab VIII, which publishes the 25 largest debtors as (rank, value) with no identity — CVM''s dictionary describes neither column. seq is CVM''s rank as filed and is never recomputed from valor (65 of 3,043 funds filed a non-descending series in 2026-07; they are served as filed). sacado_top25 sums the ranks the fund filed, which may be fewer than 25. Concentration = sacado_top1 / receivables (or top25 / receivables) is a notebook division, not a served number — and it can exceed 1: tab VIII and tab II do not share a base for every fund (2026-07: the top-25 sum exceeds the receivables total for 1.9% of funds, rank 1 alone for 0.5%), served as filed and never capped.".replace("''", "'"),
    "FIDC PORTFOLIO ROWS ARE A HIERARCHY. fidc_portfolio kind=sector serves tab II as one row per code: TOTAL is the whole receivables book, a lettered code (A..K) a sector, and a code with a digit (C1, F3) a member of its lettered parent (`parent`). Sum leaves or sum parents, never both. kind=scr_debtor and kind=scr_operation are the BACEN SCR grade ladders AA..H for the same receivables, graded by debtor and by operation respectively — two views of one book, not two books. tab X exists from 2023-10 only; earlier months have no scr rows, not zero-graded ones.",
    "WHICH CODE PRODUCED THIS DATA. coverage().landed_git_sha is the git commit of the very ingest run that set landed_at — the code that parsed and stored the newest data for that dataset — read from GITHUB_SHA on the run. It is NULL when that run recorded none (a run from before lineage existed, 2026-09-24, or one started outside GitHub Actions), and it is never borrowed from an older run, because an older run's code did not produce the newest rows. The audit log behind it also records parser_version, bumped only when a parser or field map changes what a stored value means; neither is a property of the SOURCE, so neither says anything about how much CVM, B3 or BACEN have published (that is complete_through).",
    "FIDC TRANCHES AND AGING BEGIN IN 2013-01, AND ARE SERVED AS FILED. fidc_tranches (informe tabs X_2/X_3/X_6 + X_4) and fidc_aging (tab VI) are loaded from 2013-01: CVM's yearly HIST archive through 2024-12, the monthly informe from 2025-01. The value columns have the same names in both; only the fund identifier column changes (coverage() measures the span). fidc_tranches is one row per (fund, month, classe_serie): quotas, quota_value, return_month, and performance_expected vs performance_realised (what the series promised vs delivered, percent), dirty the way CVM's percentage fields are (CVM files magnitudes of 1e14 and more) — never rescaled, never clipped, range-check in the notebook. Its `flows` array carries tab X_4's operations with CVM's TP_OPER label verbatim (e.g. Captações no Mês, Resgates no Mês, Amortizações); the vocabulary has drifted, so match labels yourself and never read a label you did not find as zero. tranche_filed = FALSE marks a series with flows but no X_2 row. fidc_aging is long: kind=to_maturity (not yet due, by days to maturity) and kind=overdue (by days past due), ten day-bands each, plus kind=overdue_total — CVM's FILED total, not a sum of the bands, and the two can disagree. Nothing is derived by either function: no performance gap, no subordination ratio, no band sums.",
    "THE FNET REGISTER KNOWS A DOCUMENT'S FUND ONLY BY LINK, AND LINKS NO VERSIONS. fund_documents and fund_restatements serve B3 Fundos.NET's document register as published, metadata only: each version is its own fnet_id, versao counts the filings, modalidade is AP (original), RE (voluntary restatement) or RC (a restatement CVM required), and status is AC / IC (superseded) / CC (cancelled) AS OF fetched_at, not live. FNET rows carry NO CNPJ: a document belongs to a fund because FNET returned it when SILO queried cnpjFundo = that CNPJ, in a sweep that reaches every FII/FIDC once a fortnight — so a document delivered since the fund's last sweep is not in fund_documents yet, and fund_restatements serves it with cnpj NULL rather than dropping it. fund_name is FNET's label and is never joined on. Because FNET does not say which document a re-filing replaces, fund_restatements PAIRS each versao > 1 with the document in the same group — (cnpj link, categoria, tipo_documento, especie, reference_raw) — carrying the highest lower versao, the greatest fnet_id winning a tie (a group can legitimately hold several v1 documents, e.g. assemblies); an unlinked document or one with no reference text is never paired, so its previous_fnet_id and lag_days are NULL — not 'no predecessor', just not pairable. lag_days is days between deliveries. source_url is FNET's own download link for the id. History starts at SILO's first crawl or backfill, not at FNET's; coverage() reports the fnet_documents span.",
    "A RESTATEMENT DIFF COMPARES FNET'S TWO VERSIONS OF ONE DOCUMENT, FIELD BY FIELD, AND ONLY WHERE SILO HAS DIFFED THEM. fund_restatement_diff returns one row per field that differs between a re-filed document and the version fund_restatements pairs it with (previous_fnet_id): for now the FIDC informe mensal only, restatements delivered from 2026 on. field_path is the XML path; a repeated block (a tranche, a cedente) is addressed by its declared key, CLASSE_SENIOR[SERIE=Série 1], and one with no usable key by position, [#2] — match_basis says which, and position rows are approximate by construction (a dropped duplicate block reads as removed fields). old_value / new_value are the text exactly as printed, comma decimals included; NULL is nil or absent and change_kind says which (changed, added, removed, nil_to_value, value_to_nil). old_num / new_num / delta exist only on numeric leaves (amounts, quantities, percentages, rates): an identifier such as a CNPJ is compared as text, and nothing is coerced. cvm_column stays NULL until an XML-to-CVM-column crosswalk exists, so do not assume a path maps onto a SILO column. A document with no rows was re-filed with nothing changed OR was not diffed: read fund_restatements' diff_status (compared, or why not — unlinked, no predecessor yet, not XML, a declared key or a stored body hash that disagrees; NULL = not diffed) and n_fields_changed, which counts this function's rows for the pair. The diff is of FNET's documents, not of CVM's CSVs (republished in place), and tab VIII (debtors) is not in the XML, so its restatements are invisible here.",
    "FIDC DELINQUENCY STARTS IN 2013-01 AND IS ON EVERY ROW FROM 2020-11. `delinquency` is tab VI's total of overdue credits (TAB_VI_B_VL_DIRCRED_INAD) as filed: from CVM's yearly HIST archive through 2024-12, from the monthly informe from 2025-01, the same field on both. Through 2020-10-31 a fund with no tab VI row that month, or a blank cell, is null (about 70% to 93% of fidc rows carry a value); from 2020-11-30 it is filed on every row, and a fund with no delinquent receivables files 0. A null is not zero and not clean books: never read it as zero or fill it, and never compare a count of reporting funds across 2020-10 → 2020-11. Machine-readable in `regime_breaks`, and on the funds_fidc coverage row's `notes`.",
    "A FUND'S DEBENTURE HOLDINGS ARE A DIFFERENT SHAPE FROM ITS EQUITY HOLDINGS. api.fund_debentures (CDA block 6) is one row per (fund, month, issuer, maturity, rate structure, application type), as filed and never summed — two series of one issuer maturing the same day at different coupons are different securities. The issuer is its own filed CPF/CNPJ (issuer_id); p_issuer also takes a listed company's ticker or CVM code, resolved only through CVM's published FCA map, and issuer_tickers carries the issuer's active listed codes back (NULL when not listed — most debenture issuers are not). Nothing is matched by name.",
    "ANBIMA CLASS ROWS ARE INDUSTRY AGGREGATES, NOT FUNDS. api.anbima_classes serves the Boletim de Fundos de Investimento as published — R$ milhões (unit brl_mm) and percentage points (unit pct) — per class, ANBIMA type or industry total (`level`; class aggregates by default). No fund in this warehouse is mapped to an ANBIMA class: CVM's `classe` is CVM's taxonomy, so never join a fund to a class by name, and there is no panel arm because these rows carry no id. An unknown category, metric or level raises 22023 listing what exists rather than returning an empty array.",
    "INFLATION IS SERVED AS PUBLISHED, IN PERCENT, WITH ONE DERIVED COLUMN PER FUNCTION. api.inflation is BACEN's SGS, long: value is the change in the month (unit pct_month) except IPCA_12M — BACEN's own 12-month accumulation, code 13522 (pct_12m) — and IPCA_DIFUSAO, the share of items that rose (pct_items). acc_12m is DERIVED: the trailing twelve monthly changes chained, ((Π(1+v/100))−1)×100, NULL unless all twelve months are present and consecutive — never a shorter chain, never filled; it reproduces IPCA_12M exactly for the headline, which is served beside it so you can check. IPCA15 is the mid-month preview, not a revision of IPCA. Group rows (family = group) are VARIATIONS, not contributions: the weights live only in api.inflation_items, whose contribution column is weight × change_month / 100 in percentage points of the headline — sum contributions within ONE level only (a group and its subgroups are the same money twice). BACEN's group codes are NOT in IBGE's order (1640 is Comunicação, 1641 Saúde, 1642 Despesas pessoais, 1643 Educação; measured against IBGE SIDRA, do not reorder by intuition). SIDRA's item codes changed with the 2020-01 structure; item_number is the continuity and sidra_table says which. Neither function has a panel arm — the rows carry no id — and an unknown series, family, level or item raises 22023 rather than returning an empty array.",
    "THE SCREENS ARE SIGNALS, NOT VERDICTS. api.screen_zombie_growth, screen_captive_vehicles, screen_evergreen_aging, screen_overdue_securit, screen_dormant_funds, screen_dormant_trend, screen_delinquency_drivers, screen_restatements, screen_late_filers and screen_silent_filers return the funds or series that crossed a stated threshold in public filings — never a score, a rating, a rank of suspicion or a finding. Every row carries `screen` (which one produced it) and `params` (the exact arguments, keyed by argument name, so the call can be replayed); `screens` in this catalog says what each measures and what else produces the same pattern (an exclusive FII is legal and looks captive; a distressed-credit mandate looks like zombie growth; an extended CRA looks overdue until it is re-filed). Defaults reproduce the dashboard pages (/suspicious, /dormant, /fidc) for the seven that have one; the three filing screens have no page and their defaults are stated in `screens`. A threshold out of its range or NULL raises 22023 — it is never clamped, because a screen evaluated at a threshold you did not ask for is a different screen. Confirm any row against the fund's own filings before repeating it.",
    "A LATE FILING IS A TIMESTAMP COMPARED WITH A CITED RULE, AND A SILENT ONE IS READ FROM CVM, NOT FNET. screen_late_filers measures the FIRST FNET delivery of a fund's monthly informe (Informe Mensal Estruturado, versao 1) against the deadline Resolução CVM 175 states — FIDC: Anexo Normativo II, art. 27, III; FII: Anexo Normativo III, art. 36, I; both 15 days after the end of the reference month, counted as calendar days because the text says dias — and every row carries that citation in deadline_rule. It measures only months after each family's adaptation deadline (from 2024-12 for FIDC, 2025-07 for FII) and refuses a window ending earlier, because the predecessor instructions' deadlines are not cited here. No holiday calendar is applied, so p_min_days_late (default 5) absorbs a deadline that rolled over a weekend or holiday; CVM extensions are invisible to it. A month with no informe in the register is NOT counted late — FNET history is partial. screen_silent_filers answers absence from CVM's own deep tables (dim_fund: the informe diário for FI, the monthly informe for FIDC / FII / FIAGRO) against latest_complete_period, for funds whose registry row is active; a merged or liquidated fund whose status CVM has not updated, reporting moved to a new class CNPJ, or a SILO ingest gap produce the same row. screen_restatements counts re-filings (versao > 1) by modalidade — RE voluntary, RC required by CVM — per cnpjFundo link. None of the three ever identifies a fund by fund_name.",
    "COMPANY EVENTS ARE IPE FILINGS AS FILED, FROM 2015, AND NOT EVERY FILING IS HELD. api.company_events serves cia_event — CVM's IPE feed: fatos relevantes, comunicados ao mercado, assembly material and the rest — one row per protocol at its NEWEST version (version says which), every text field (category, event_type, species, subject) exactly as filed, and source_url, the document's link on CVM's RAD. The company is resolved exactly as financials resolves p_id: a ticker only through CVM's published FCA map (active listings), a 14-digit CNPJ or a CVM code, never a name. CVM assigned no protocol number to IPE filings before 2015 and still omits it on a minority (12% of 2015); cia_event is keyed on (protocolo, versao) and a key is never synthesized, so those filings are NOT held — an empty window before 2015, or a filing you know exists and cannot find, is that limit, not an absence of events. p_category matches CVM's label exactly; an unknown one raises 22023 listing the categories held.",
    "MACRO SERIES AND PTAX ARE SERVED AS BACEN PUBLISHES THEM, UNIT ON EVERY ROW, NOTHING DERIVED. api.macro_series serves nine non-inflation SGS series by label or code: SELIC_META (432, % a.a.; dated per calendar day and published AHEAD to the next Copom date, so a p_to after today can return forward-dated targets), SELIC_DIARIA (11) and CDI (12) in % PER BUSINESS DAY (never annualise one yourself without saying so), IGPM (189) and INPC (188) as % change in the month, POUPANCA (25) — the OLD-RULE deposit return (deposits until 2012-05-03), one value per anniversary day, each the return over the month starting that day, not a calendar-month figure — USDBRL (1) and EURBRL (21619) in BRL per unit, and PIB (4380) monthly in R$ millions at current prices. The IPCA set is api.inflation's; asking macro_series for it raises 22023 with that pointer. api.ptax serves PTAX compra and venda per currency and business day in BRL per ONE unit of the currency (JPY and ARS included): the last bulletin of the day the ingest received, which for a completed day is the Fechamento PTAX (measured against SGS 1 and Olinda on 2026-09-22/23); the bulletin type is not stored. No mid rate, cross rate, fill or holiday row is invented.",
    "THE RESEARCH UNIVERSE IS A TAPE FACT, NOT A LISTING RECORD, AND ITS COMPANY LINK SAYS HOW IT WAS MADE. api.research_universe returns one row per ticker+ISIN pair of listed shares and units traded on the B3 cash market since 2019-01-02 (the start of the tape). Membership is the ISIN's own instrument code, characters 7-9: ACN (shares), CDA and UNT (units, whose ticker must also end in 11); subscription receipts, BDRs, funds and indices are outside it, so instrument_type = equity on api.quotes is NOT the definition (it lets about 100 receipts in). THE ISIN IS THE IDENTITY: a rename is a NEW row and nothing links it to the old one, and two tickers can share an ISIN (NEOE3 and NEOE3B). first_observed, last_observed and n_sessions are facts about SILO's tape, never listing or delisting dates; n_sessions far below the calendar span is a gap (NATU3: one ISIN, no sessions 2019-12 to 2025-07). cnpj comes from CVM's published FCA ticker map and cnpj_basis says how: fca_ticker (that exact ticker), fca_issuer_stem (the ticker's 4-letter stem, when exactly one CNPJ holds an FCA ticker with it: an inference, so it is labelled), or NULL (no link: cnpj and setor_current are NULL, never guessed from a name). setor_current is CVM's cadastro setor as of TODAY, not the setor on a past date. TO READ THE UNIVERSE AT A DATE T, keep the rows with first_observed <= T <= last_observed; a pair inside a gap still matches that filter. The view is rebuilt daily, so last_observed lags the tape by up to a day (built_at says when). Not trimmed: more than 1000 rows raises 22023.",
    "THE BENCHMARK INDEX IS api.index_history, TAKEN BY INDEX CODE, AND EVERY CODE IT HOLDS IS A TOTAL-RETURN INDEX, AS B3 PUBLISHES IT. It serves the daily level of a B3-published index (IBOV from 1968-01-02, then IBXX, IBXL, IFIX, SMLL, IDIV, ICON, IMOB and UTIL, each from its own first session; coverage() lists the depth of each) from B3's own statistics, and accepts an INDEX CODE only: a ticker raises 22023 naming the codes held, so BOVA11 (an ETF) and IBOV11 (the Ibovespa options settlement code: each of its prints is that session's settlement index, never the official close, and since December 2025 it prints on nearly every session, so a dense series is not a sign that it is the index) can never stand in for the index by construction. The levels are NOT adjusted: B3 re-scaled IBOV eleven times (divided by 100 on 1983-10-04 and by 10 on ten other sessions, the last on 1997-03-03) and divisor_step is TRUE on the first session after each, where a level ratio is not a return; from 1997-03-03 on there is none. B3 itself labels IBOV and each of those codes a total-return index (distributions reinvested, Manual de Definicoes e Procedimentos dos Indices da B3, Feb 2023; IDIV's separate Price Return version is not on this endpoint and is not served), so a level already includes dividends: the like-for-like series from quote_history is close_total_return, never close_adj, which is price only. Levels before an index's publication date are B3's own back-calculation and are not marked. There is no return or adjusted column, and no code is labelled anything but what B3 calls it. It pages with p_after like quote_history, because IBOV from 1968 is 14,489 rows.",
    "THE PORTFOLIO FUNCTIONS RESOLVE, COST AND LOOK THROUGH A SET OF FUNDS AND COMPARE EACH FUND'S MONTH WITH ITS CLASS, AND EACH SAYS WHAT IT DID NOT DECIDE. api.portfolio_resolve takes statement lines (p_names, with optional parallel p_cnpjs, p_quotas and p_quota_dates) and returns up to 5 candidate funds per line, ranked: a CNPJ the line carries wins (match_kind cnpj); else (v56) a name that is exactly a ticker of SILO's curated ETF registry (cvm_etf_registry) gives that ETF's CNPJ (match_kind etf_ticker, one candidate, never ambiguous: api.lookup returns no CNPJ for a ticker and a fixed income ETF is not in COTAHIST); else an exact match, case and accents ignored, on any name the fund ever filed (exact_current, or exact_history for a former legal name, with matched_period the last CDA month it was filed under); else trigram over the whole name history, similarity 0..1 (an input of up to four words also scores by word_similarity, so an abbreviation like XP Bancos can match; anything below 0.25 is no candidate). A quota the statement prints is compared with the candidate's cvm_fi_diario quota on that exact date and one within 0.5% ranks first, which is how the XP Bancos master and its FIC (same words, different quotas) are told apart. ambiguous is TRUE on every row of a line whose top two candidates are within 0.05 of similarity and the quota does not separate them: the line is UNRESOLVED, the reason says why, and nothing is picked silently. No indexer, sector or economic group is ever inferred from a name. At most 200 lines per call. api.portfolio_fees keeps two kinds of number apart. DISCLOSED (disclosed_*) is the fee the fund published: from the Extrato (cvm_fi_extrato, newest version) first, else the lamina (cvm_fi_lamina, newest reference month), else cad_fi (cvm_fund_registry taxa_adm / taxa_perfm, legacy funds only), ONE source per fund, named in disclosed_origin (extrato, lamina or cad_fi) and disclosed_source with disclosed_as_of (the filing date), disclosed_age_months and disclosed_age_days. The order is the CVM Extrato das Informacoes first (cvm_fi_extrato, one row per fund or class, a fee for 84.3% of active FI funds; for a CVM 175 fund it is the CLASS, there is no subclass column and no subclass fee is assumed), then the lamina, then cad_fi. A filed administration fee of exactly 0 comes back as 0 with filed_zero TRUE (read it as not informed, never as a zero cost); a filed value above 5 is NOT returned as the fee: disclosed_taxa_adm is NULL, implausible_filed is TRUE and the value as filed is in taxa_adm_filed_raw. An Extrato row that exists stays the source even then, unless (v55) it filed exactly 0 or above 5 and the lamina's single fee is in (0, 5] and NEWER: then the newer lamina is the source. fee_resolution names the rule that applied (extrato, extrato_lamina_beside when the Extrato filed 0 or above 5 and a lamina fee is returned beside it, extrato_to_check when there is none, lamina_newer, lamina, cad_fi); lamina_taxa_adm (with _min, _max, lamina_n_classes, lamina_age_months) and extrato_taxa_adm_filed (with extrato_as_of) give the other document's fee as filed for every fund, never rescaled and never a fee to add; extrato_lamina_ratio is the Extrato over the lamina when both are above 0, and extrato_scale_factor is 10 or 100 when an Extrato above 5 equals that factor times the lamina within two-decimal rounding, a flag only. Treat every fund whose fee_resolution is extrato_lamina_beside or extrato_to_check as to be checked and sum neither value. For lamina_newer the newer lamina's fee in disclosed_taxa_adm is a disclosed fee like any other: use it as the cost, sum it and compare it with the estimate (owner's decision of 2026-10-03, v56), keep the fund flagged for review because the two documents disagree, and never sum the Extrato value beside it. The Extrato's performance fee (extrato_taxa_perfm with its benchmark, method and text), entry and exit fees and custody fee are returned as filed, and lamina_pr_pl_despesa is the declared total expense ratio from the lamina with its period, never added to the administration fee. ETFs (v56): CVM's Extrato, lamina and cad_fi carry no fee for an ETF (0 of the 178 active registry ETFs on 2026-10-03), so for a CNPJ in SILO's curated ETF registry etf_ticker names its ticker and etf_site_taxa_adm, etf_site_as_of and etf_site_source give the 'Taxa de administracao total' that etfsbrasil.com.br prints (etf_market_snapshot, the newest snapshot with a fee, joined by ticker): a third-party site, not a CVM filing, never in disclosed_*, returned as published; etf_site_note says so and why a value is NULL. Since v57 etf_site_nr_cotistas and etf_site_pl give the number of quotaholders and the net assets in R$ that the same site prints in the SAME snapshot (etf_site_as_of): third-party descriptive facts, never summed, never a fee base (CVM has no 2026 daily report row for any registry ETF, so they are the only ones SILO holds). A part not filed is NULL, never a zero fee, and lamina classes that disclose different fees give a NULL single value, a min and max and a note. The ESTIMATE (adm_fee_flow, perf_fee_flow, *_pct_annual_est) comes from the balancete accruals: the fee accounts accumulate from each fund's fiscal-year start and are filed negative, so the month's accrual is previous minus current accumulated value, times 12 over NAV (groups 6 + 7 + 8) in percent a year. In the fiscal-year reset month the accumulated fee falls: fiscal_reset_suspect is TRUE and the estimate is NULL, unless cad_fi DT_INI_EXERC confirms the fiscal year starts that month, when the month's accumulated value alone is the accrual. The estimate is labelled an estimate on every row and is never the disclosed fee. At most 200 CNPJs per call. api.portfolio_lookthrough follows the fund quotas of CDA block 2 from each root, recursively (cycle-guarded, p_max_depth 1..6, default 4), for ONE CDA month: p_month, or the last month whose block-2 filing count reaches 90% of the median of the 12 before it (the /holdings rule). Every fund on the way lists its own holdings: block 1 government bonds (repo collateral is NOT a holding of the bond and is served apart as asset_kind repo), block 2 quotas (fund_quota when looked through, else fund_quota_unfiled when the held fund filed no CDA that month, fund_quota_depth_cap, fund_quota_cycle), block 4 stocks and debentures (issuer_code is ISIN characters 3-6, never a CNPJ) and block 6 private credit (issuer_cnpj only when the filing says the issuer is a PJ; indexer as filed). weight_in_root is the value over the holder's NAV (fact_fund_monthly, same month) times the weights down the path; NULL when a NAV on the path is unknown. A fund reached by two paths appears once per path: sum weight_in_root over every row but fund_quota. Blocks 3, 5, 7 and 8 are not ingested, so weights need not sum to 1 and cash is not shown. At most 200 CNPJs per call. api.portfolio_movement says whether a fund's month is unusual for its own class (movimento incomum), for ONE month (p_month, or the last complete FI month): own_value_pct is the fund's monthly QUOTA RETURN, month-end vl_quota over the previous month's (fact_fund_monthly, the one stable quota subclass), in percent; a NAV change is not used, because most of it is flows. The class is the ANBIMA class AS FILED in the CVM Extrato (class_as_filed, its newest filing, not the class on the month's date; class and subclass split that label at its first ' - ' for display, nothing is read from a fund's name); the peers are every FI fund of that class with a return that month (n_peers, the fund included). class_mean_pct and class_sd_pct are the mean and sample standard deviation of the peers' returns winsorized at the class's own 1st and 99th percentile of that month (class_p01_pct, class_p99_pct); the fund's own value is not winsorized. z = (own - mean) / sd. level is forte when |z| > 3 (investigator_trigger TRUE), atencao when |z| > 2, normal otherwise, strictly greater: exactly 2 is normal. A fund is nao_avaliado, with a Portuguese reason, when its class has fewer than min_peers (30) peers with a return or a zero standard deviation, it has no class (outside the Extrato, which covers about 84% of active FI funds, or no classe_anbima), no return (no quota in both months), is an ETF, FIDC, FII, FIP or FIAGRO, or the month is not complete; there is no fallback to a wider class. Measured on production over six months to 2026-09, among the funds evaluated, |z| > 2 flagged 5.2% to 5.7% of fund-months and |z| > 3 2.4% to 2.9%. It states a number, a class, a sample size and a month: it is not a forecast, a verdict or a recommendation. api.portfolio_instruments (v61) takes a statement's instrument codes (p_codes; trimmed, upper-cased, a leading CRA-, CRI- or DEB- stripped, the hyphen required) and, per code: match_kind securit_cetip for a CRA or CRI whose codigo_cetip is the code in cvm_securit_serie, every series at the code's newest data_referencia, one row per (numero_serie, classe) at its highest versao, the series columns as filed (instrument_type cra_mensal or cri_mensal, cnpj_securit, data_vencimento, situacao, taxa_juros as text, classificacao_risco_atual, valor_total_integralizado); else match_kind cda_ticker for a debenture in CDA block 4 (tp_aplic Debêntures) at the newest month the code appears in at all (cda_period; the newest CDA month may still be filling): cd_isin (the most common ISIN), issuer_code (ISIN characters 3-6, never a CNPJ), n_fundos (distinct holding funds) and preco_marcacao_fundos (sum of the funds' market value over the sum of their quantity, 6 places: their own mark, not a trade price); a code held that month as something else is no match and the reason names what it was held as; else one row with match_kind NULL and the reason. Nothing is inferred from a code's letters. At most 200 codes per call. api.portfolio_fund_terms (v61) returns one row per input CNPJ: gestor_id (a CNPJ or a CPF, never padded), gestor_name, admin_cnpj and admin_name as filed in cvm_fund_registry, one registry row per CNPJ picked by is_active, then no dt_cancel, then the newest dt_cancel, then the newest fetched_at, then entity_type (the reason names it); and the redemption terms qt_dia_conversao_cota, qt_dia_pagto_resgate, tp_dia_pagto_resgate and qt_dia_resgate_cotas (lock-up) from the CVM Extrato (terms_source extrato, terms_dt_comptc its filed version's date), or, only when the CNPJ has no Extrato, from the lamina (terms_source lamina; its conversion and lock-up columns mapped by name to the same meanings, the row with no subclass else the newest). Values are as filed, NULL is not filed and never zero; a FII, FIDC, FIP or FIAGRO is in neither document and the reason says so, in Portuguese like every reason of both functions. At most 200 CNPJs per call. All six refuse above one 1000-row page (22023), never trim.",
    "DI FUTURES AND B3'S REFERENCE CURVES ARE SERVED AS B3 PUBLISHES THEM, AND THE LONG END OF EVERY CURVE IS B3'S EXTRAPOLATION. api.future_curve lists every outright DI1 contract on one session (B3 Price Report, from 2018-01-02) and api.future_series follows one contract; DI1 is QUOTED IN RATE, so settlement_rate and the open/low/high/avg/close columns are % a.a. on 252 business days (the low rate is the high price) and settlement_price is the PU. contract_month, read from the ticker with B3's month letters (F = January … Z = December), is the one derived column; nothing is rolled or spliced into a continuous series. api.curve serves one reference curve on one session, every vertex (TaxaSwap, from 2008-01-02): PRE is DI x pré, DPL the clean IPCA coupon (a real rate; B3's implied inflation is (1 + PRE) / (1 + DPL) − 1 at the same tenor), both compounded on 252 business days, and DOC the clean onshore dollar coupon, LINEAR on 360 calendar days — read rate_basis before comparing two curves. Past the last maturity of the contract anchoring a curve (DI1, DDI, DAP) B3 EXTENDS the last forward rate (Manual de Curvas v21), so the long vertices are extrapolation, not prices. api.curve_history serves one of B3's FIXED vertices through time by its nominal tenor (p_tenor_days: 30, 90, 360, 720 …); any other tenor raises 22023 with the list, because interpolating is analysis for the notebook.",
    "THE B3 LENDING AND FLOW GROUP IS A RATCHET, AND IT IS THE ONLY PART OF THIS WAREHOUSE THAT IS. short_interest, short_interest_by_sector, lending_trades, lending_participants and investor_flow read B3 tables that B3 keeps for about 21 BUSINESS DAYS and publishes no archive for. History therefore starts at SILO's first capture and cannot be extended backwards at any price — a missed session is gone, not late, and no backfill exists to ask for. coverage() reports the real span per endpoint; read it before describing any of these series as short, broken or anomalous, and never infer a level change from a window that simply begins where capture began. An over-wide request to the source returns HTTP 200 with a silently clamped window, which is why the ingest reconciles what it asked for against what it received.",
    "pct_float IS TWO DIFFERENT METRICS AND float_basis SAYS WHICH ONE YOU HAVE. api.short_interest divides the balance on loan by whichever denominator exists for that ticker. float_basis = 'index_free_float' means B3's published free float (theoretical_qty from the broadest index portfolio carrying the ticker) and exists for index constituents only, ~149 tickers; float_basis = 'shares_outstanding' means capital social from the cash instrument registry, a LARGER denominator that yields a SMALLER percentage for the same position. They are not the same measure and are never comparable: ANY ranking, screen or cross-section on pct_float must filter to ONE basis first, or it sorts index members against non-members on an axis they do not share. float_denominator carries the number actually used. pct_float and days_to_cover are NULL — never 0 — when their denominator is missing or the name did not trade; 0 would sort an unknown to exactly the wrong end.",
    "IN THE LENDING TAPE, doador AND tomador ARE BROKERAGES, NOT BENEFICIAL OWNERS. lending_participants' broker_code / broker_name and lending_trades' lender_brokers / borrower_brokers identify the B3 PARTICIPANT intermediating a trade, never who ends up long or short. B3 names ~33 participants in a whole session, and about three quarters of trades carry the SAME code on both legs (measured 2026-09-10: 32,197 of 43,165, 74.6%) — a broker crossing its own client book. So a large borrow through a broker is its clients' position, not the broker's view, and 'the biggest short' read off this tape is a statement about order flow routing. internal_legs / internal_qty (lending_participants) and internal_trades (lending_trades) are what tell the two apart: high internal share is client churn, low internal share is flow that actually crossed the market. They are published beside the totals rather than netted away, because dropping them makes the remainder look like conviction and keeping them silently makes churn look like demand.",
    "investor_flow IS A FIRST DIFFERENCE, NOT A PUBLISHED DAILY SERIES. B3 publishes investor participation as a MONTH-TO-DATE CUMULATIVE snapshot with a T+2 lag; the daily figures are consecutive snapshots subtracted WITHIN one month, and the difference never reaches across a month boundary (that would report a whole month as one day's flow). flow_basis says which kind of row you have: 'delta' is a real one-session difference, 'month_open' is the month's first session where MTD equals the day, and 'unknown_opening_snapshot' is a row whose predecessor SILO does not hold — those carry NULL flows ON PURPOSE and must never be read, filled or summed as zeros. mtd_buy_value_thousands / mtd_sell_value_thousands carry the cumulative figures as published, so the difference can be checked against the source rather than trusted. Values are R$ thousands. Sum a month only over rows whose flow_basis you have inspected.",
    "LISTED-COMPANY FINANCIALS ARE FILED, NOT DERIVED. api.financials returns one row per account line exactly as the company filed it; nothing is summed, annualised or restated. Read period_months before comparing two rows: an ITR publishes the SAME account twice under one reference date, once for the three months and once year-to-date, and they are distinguished only by the period span. Adding a 3-month row to a 6-month row double-counts the quarter.",
    "THE LATEST-VERSION FUNDAMENTALS ARE NOT POINT-IN-TIME UNLESS p_as_of IS GIVEN. financials, company_financials, income_statements, balance_sheets and cash_flow_statements take a trailing p_as_of DATE (default NULL). NULL reads the latest stored version of every document, so a later filing or a restatement appears as if it had been known on an earlier date: fine for a current screen, look-ahead in a backtest. A date T reads only the documents CVM had received before T (cia_filing.dt_receb < T; a document received ON T is excluded), keeps the highest remaining version of each and all its lines, and drops a document with no filing header. ref_date still says which period a row is FOR; the window p_from/p_to is on that, not on the receipt date. CVM's files carry only the newest version of each document and most versions superseded before 2026 are not held, so an as-of read is stale for a company that restated, never early. financial_statement_history already exposes every stored version with its filing_received_date.",
    "FINANCIALS DEFAULT TO CONSOLIDATED (scope=con) AND TO THE PERIOD THE DOCUMENT IS FOR (ordem_exerc ULTIMO). The prior-year comparative printed beside it is never returned. When a company re-files, only the newest version of each statement is served and `version` carries it; in company_financials a balance sheet from a different version than the income statement reads NULL rather than being paired across filings.",
    "CVM'S CHART OF ACCOUNTS IS SECTOR-SPECIFIC, SO `setor` IS A PARTITION KEY, NOT A LABEL. financials and company_financials carry setor and segmento on every row for exactly one reason: the same account code is a different quantity in a different chart. Measured live, 3.01 is `Receita de Venda de Bens e/ou Serviços` for PETR4 and `Receitas de Intermediação Financeira` for Banco do Brasil (cd_cvm 1023), and 3.05 is EBIT for the first and pre-tax profit for the second. So company_financials.revenue and gross_profit are NOT like-for-like across sectors: PARTITION every median, rank, percentile and peer comparison BY setor, and read the as-filed Portuguese account_name rather than assuming a code carries one concept. There is deliberately no canonical English line-item mapping, because keying one on account_code would mislabel at least one sector.",
    "company_financials.net_income IS KEYED ON THE FILED LABEL (since v36), exactly as in api.income_statements, so the two surfaces agree. It matches `Lucro/Prejuízo Consolidado do Período` / `Lucro ou Prejuízo Líquido Consolidado do Período`, which sits on 3.11 for the industrial and bank-A charts, on 3.09 for bank B (which files no 3.11) and on 3.13 for insurers (whose 3.11 is continuing operations). Until v35 it read 3.11 alone, so 282 bank-B statements (Itaú and BTG among them) read NULL and insurers got their continuing-operations line. No code is ever substituted: 3.09 is pre-participations profit on the other charts. revenue and gross_profit remain code-keyed (3.01 / 3.03) and are not like-for-like across sectors — use api.income_statements for label-keyed revenue. Every value in both functions is in absolute reais: the filed ESCALA_MOEDA is applied at ingest, so never scale by thousands again.",
    "api.income_statements IS KEYED ON THE FILED LABEL, NOT THE ACCOUNT CODE. It returns the income statement as one row per filed period with named fields, and it resolves each field by matching the as-filed Portuguese account_name (case-folded, nothing else folded) rather than by cd_conta. This is measured: CVM ships FOUR DRE charts of accounts and net income sits on 3.11 for the industrial and bank-A charts, on 3.09 for the bank-B chart which files no 3.11, and on 3.13 for the insurer chart whose 3.11 is the continuing-operations line. `chart` tells you which layout a filing used. A concept a chart does not file reads NULL rather than borrowing a neighbouring line: operating_income (EBIT) is an industrial line only, and insurers get NULL operating_expenses because their filed line is the narrower `Despesas Administrativas`. Never read a NULL here as zero. net_income_controlling is the figure per-share numbers are built on, not net_income.",
    "api.balance_sheets AND api.cash_flow_statements FOLLOW THE SAME LABEL-KEYED DESIGN. balance_sheets returns one row per filed period with named fields matched on the as-filed account_name (case-folded only); where a filing files one label twice (industrial `Empréstimos e Financiamentos` under both current and non-current liabilities) the PARENT's label disambiguates, and no code is ever consulted. Equity sits on 2.03, 2.07 or 2.08 depending on the chart; `chart` says which. Banks file no current/non-current split and no debt line, so current_assets, current_liabilities, noncurrent_*, short_term_debt and long_term_debt read NULL for them — never zero, and never a deposits line standing in for debt. cash_flow_statements maps ONLY the section totals and the cash reconciliation (operating / investing / financing, fx_effect, net_change_in_cash, cash_start, cash_end), which are uniform across charts; `method` is direct or indirect. There is no capex or dividends field on purpose: those lines are free text per filer (capex alone has 20+ spellings), so read those lines with api.financials, where the filed label is on the row. operating_cash_generated and working_capital_changes are indirect-method lines and read NULL on a direct-method filing.",
    "A TICKER RESOLVES TO A COMPANY ONLY THROUGH CVM'S PUBLISHED FCA MAP, active listings only — the CNPJ and the trading code arrive on the same filed row. financials('PETR4'), financials('33000167000101') and financials('9512') are the same company. A delisted code resolves to nothing rather than to a guess, and no company↔ticker edge is ever inferred from a name.",
    "PANEL GRAIN IS (id, asset_class, date, metric), NOT (id, date, metric). A CNPJ can file under two fund families in one month (385 do, fi + fidc), and the panel returns one row per family for it — pivoting on (id, date, metric) then either raises on the duplicate or silently averages two vehicles. Pass p_entity_type (fi|fidc|fii|fip|fiagro) to keep one family, or keep asset_class in your pivot key.",
    "Never invent a price, NAV, or identifier match.",
    "Missing observations stay null; do not ffill or interpolate.",
    "freq=day is quotes only. Mix equity with fund fundamentals on freq=month.",
    "close_return across a missing month is null, not a multi-month return.",
    "close_return is adjusted for splits, groupings and bonus shares: across one (DESDOBRAMENTO, GRUPAMENTO, BONIFICACAO in B3's corporate-event history; monthly: anywhere between the two month-end prints) the previous close is divided by the event's share ratio, B3's rule (1 + factor/100 for DESDOBRAMENTO and BONIFICACAO, factor for GRUPAMENTO, events multiplied), before the return is taken, so a 1:4 split from 100.00 to a 26.00 close is +4% and BBAS3's 2:1 split (56.46 to 27.91) is -1.13%, not -50.57%. An event with an unreadable factor, or one label on one date published with two factors, makes that return NULL (no row), never a guess. It is a price return, not a total return: dividends and JCP still move it. The adjustment reads the share-count events stored for the ISIN from B3's published history; an event the nightly corporate-event sweep has not stored yet (an issuer without a sweep proof) is not seen and still reads as a return.",
    "close is the price as published, which for a paper quoted per lot refers "
    "to 1000 shares; close_unit divides it by the published quotation_factor so "
    "levels are comparable. Neither is corporate-action adjusted, and `adjusted` "
    "is FALSE on every view row because it describes close. The adjusted price "
    "is close_adj (quote_history's default field, the panel's default metric "
    "for shares and units; see the next constraint).",
    "close_adj IS CONTINUOUS ACROSS SPLITS, GROUPINGS AND BONUS SHARES ONLY, AND "
    "IT IS ANCHORED TO THE INSTRUMENT'S LATEST SESSION. It is the close per "
    "single share divided by the share ratio of every later event, by B3's rule: "
    "1 + factor/100 for DESDOBRAMENTO and BONIFICACAO, factor for GRUPAMENTO, "
    "distinct events on one date multiplied. Past levels change when a new event "
    "lands and returns do not, so never read a past level as the price seen that "
    "day, and never combine pages with different data_revision values. Dividends, "
    "JCP and subscription rights are not adjusted in this version (they move "
    "value to holders and change no share count; total return is separate). A "
    "window close_adj cannot cover is REFUSED (22023, DETAIL "
    "reason=adjustment_unavailable; cause=...) naming ticker, period and cause, "
    "never served as the raw close: outside shares (ISIN code ACN) and units "
    "(CDA/UNT, ticker ending 11); issuer events not proven swept, or the proof "
    "older than the last session; a stretch on or before a stock event this "
    "version does not adjust (spin-off CIS RED CAP, INCORPORACAO, REST CAP "
    "ACOES, RESG TOTAL RV, any new stock label), an unreadable factor, or one "
    "label on one date published with two factors. "
    "The absence of events is never taken as proof: the sweep proof is. Select "
    "close explicitly for the raw close.",
    "quote_history IS KEYED ON THE ISIN AND REFUSES WHAT IT CANNOT SERVE WHOLE. "
    "The series follows the instrument across BDI boards (p_board restricts it). "
    "22023 with DETAIL reason=: unknown_ticker (never printed on the cash tape); "
    "outside_coverage (no session in the window, or the window starts before "
    "the instrument's first session; the tape starts 2019-01-02, see "
    "coverage()); isin_change (the ticker printed under two ISINs in the "
    "window that its lineage does not splice; a reused receipt code is a new "
    "instrument and is never joined); "
    "ambiguous_session (two rows on one session; pass p_board); invalid_field; "
    "adjustment_unavailable. Inside the coverage a missing session is a session "
    "with no trade (COTAHIST lists only papers that traded; "
    "prior_no_trade_sessions counts them), holidays are not sessions, and a "
    "field with no value is a JSON null. A ticker whose company changed its trading code or ISIN runs through its older instrument (ticker lineage, #381): an older (ticker, ISIN) is spliced in front only when it is the same company (the same ticker, or one CNPJ in CVM's FCA map), the same share class (ISIN characters 7-11), its last cash session is the one right before the newer first session with no overlap, no stock event goes ex at the seam, and exactly one candidate qualifies; every row keeps its own ticker and ISIN, close_adj divides older rows by the later instruments' share ratios too, and close_total_return is NULL before a seam (VIIA3 BRVIIAACNOR7 to BHIA3 BRBHIAACNOR1 on 2023-09-20).",
    "close_total_return (SELECT IT IN p_fields) IS close_adj with cash distributions reinvested at the ex-date "
    "close, also anchored to the latest session: the level is divided by the "
    "product of (1 + cash / ex-session close) over every distribution that went "
    "ex after the session, so the latest session equals close_adj "
    "and earlier levels are lower by the cash paid since. Cash is B3's "
    "full history (DIVIDENDO, JRS CAP PROPRIO gross of withholding tax, "
    "RENDIMENTO, REST CAP DIN), counted only where its ISIN is proven against "
    "the tape. It is NULL, with close_total_return_null_reason saying why, "
    "where close_adj cannot be served for that session; where the ISIN has no resolved "
    "distribution in B3's history (a non-payer, or one B3's history does not "
    "match: the two look the same, so neither gets a price return labelled as "
    "a total return); where a later distribution of the issuer's share class "
    "has no proven ISIN; where a distribution B3's supplement lists is missing "
    "from the history; and where a later distribution has no ex-date close "
    "within 7 days. A NULL is never the price return in disguise.",
    "Daily close_return is null when the previous session is more than 7 "
    "calendar days back (halts, listing gaps), and null across a quotation-"
    "factor change — a fatcot flip rescales the quote with no market move "
    "behind it. Across a split, grouping or bonus between the two prints both "
    "grains adjust the previous close by the event's share ratio (#396).",
    "Default windows are honest: with no explicit `to`, fund metrics end at "
    "each family's latest COMPLETE period (coverage() reports it as "
    "complete_through) — a partially-filed trailing month is not served. An "
    "explicit `to` serves the window verbatim, partial months included.",
    "Company↔ticker IS joined — via CVM's published FCA valores-mobiliários map only (lookup returns a tickers array on company rows). Nothing is matched by name; a company with no active published listing has tickers null.",
    "Analysis (corr, OLS, copulas, event studies) is a reduction of a panel. Fetch the panel first.",
    "CIA, FII AND FOCUS HELD DATA. api.financial_statement_history returns raw CIA account lines across all stored filing versions for one required statement and company id; `financials` remains latest-version only. Filing header metadata is present only on an exact key match. Values are already scaled at ingest and remain in filed currency. api.fii_property_history filters one exact fund CNPJ and reference-date window; CVM publishes no stable property id, so row_hash identifies a source row, not a durable asset. Nullable measurements remain NULL. api.focus_expectations returns the weekly path across BCB survey dates for one exact endpoint and required forecast horizon, with an optional indicator. The stored key retains each date/horizon; `baseCalculo=0` is the trailing 30-day respondent sample and 12-month inflation is unsmoothed. It is not a vintage archive of corrected old reports, and migration 16-era missing horizons may await re-fetch. All three endpoints refuse above 1,000 rows.",
    "Row caps — getting this wrong means silently analysing a TRUNCATED "
    "series, the exact fabrication this API exists to prevent. THE PAGE IS "
    "1000 ROWS, imposed by PostgREST (db-max-rows) on every response. EVERY "
    "set-returning function now REFUSES rather than trims: a window that "
    "would produce more than 1000 rows raises SQLSTATE 22023 naming the "
    "function, so a short result can no longer look complete. The error says "
    "WHY (the response is one 1000-row page and SILO never returns a silently "
    "truncated result) and HOW to fix it for that function, in the message and "
    "again as PostgREST's `details` / `hint`. That is all "
    "fifty-one — panel, quote_history, fund_nav, option_history, termo_history, "
    "financials, financial_statement_history, company_financials, "
    "income_statements, balance_sheets, "
    "cash_flow_statements, anbima_classes, "
    "inflation, inflation_items, fii_property_history, focus_expectations, "
    "fidc_cedentes, fidc_sacados, fidc_portfolio, "
    "fidc_tranches, fidc_aging, fund_holdings, fund_debentures, fund_documents, "
    "fund_restatements, fund_restatement_diff, company_events, macro_series, "
    "ptax, future_curve, future_series, curve, curve_history, research_universe, index_history, portfolio_resolve, portfolio_fees, portfolio_lookthrough, portfolio_movement, portfolio_instruments, portfolio_fund_terms and the ten "
    "screen_* functions "
    "(`limits.page.all`). "
    "FOUR OF THEM PAGE with p_after: panel, quote_history, fund_nav and index_history. Send "
    "p_after='' for the first page, then the key from the last row — for the "
    "panel 'date|id|metric|asset_class', for quote_history, fund_nav and index_history just "
    "that row's date as 'YYYY-MM-DD'; every page is exactly 1000 rows until "
    "the last, which is shorter. fund_nav ALSO REQUIRES p_entity_type when "
    "paging, because its cursor is a bare period and one CNPJ can file under "
    "two families in the same month. The rest do not page: narrow "
    "p_from/p_to instead (inflation and inflation_items default to the last "
    "36 months for that reason), for fidc_cedentes / fidc_sacados / "
    "fidc_portfolio narrow the months (a p_cedente lookup spans many funds), "
    "for fund_holdings / fund_debentures narrow the months (a p_ticker or "
    "p_issuer lookup spans many funds), "
    "pin one p_kind on fidc_portfolio, or ask for the "
    "newest N rows with an explicit p_limit (1..1000 — until v34 the FIDC "
    "three, and until v41 fund_holdings and fund_debentures, "
    "trimmed SILENTLY at 500 anonymous / 5,000 signed in; they no longer do), "
    "or for a screen raise its thresholds or pin "
    "its output filter (p_dormancy / p_min_nav, p_driver, p_family, p_modalidade). The old sentinels (5001 on the series functions, "
    "100001 on the panel) are GONE and were never observable anyway — "
    "PostgREST cut the response at 1000 first (measured 2026-08-28: "
    "quote_history from 2019 returned exactly 1000 rows, 200, OLDEST rows "
    "kept). On GET views the Content-Range RESPONSE HEADER is still the "
    "signal: `0-999/*` means cut; send `Prefer: count=exact` to read the true "
    "total. The RPC functions no longer need it — they raise instead. "
    "RANGE PAGING DOES NOT WORK ON RPC (a Range header on /rest/v1/rpc/panel "
    "returns the same first page again); p_after is the RPC cursor, Range/"
    "limit/offset are the view cursor. The local /v1 Flask adapter pages the "
    "SQL itself and answers 400 above its own total; do not carry its rules "
    "over.",
    "An unrecognised metric name is IGNORED, not rejected: the panel comes "
    "back smaller and perfectly plausible. Take metric names from this "
    "catalog's `metrics` map, never from memory.",
    "Option chains require a codneg prefix of at least 3 characters "
    "(api.option_chain); an unfiltered whole-market chain is refused.",
    "CALLER TIERS. Anonymous access is free but deliberately small: panel "
    "accepts at most 3 ids per call, search_funds returns at most 25 rows, "
    "and option_chain pages at most 200. Signing in (GitHub) raises "
    "those to 50 ids, 200 rows and 2000 respectively, and the query timeout "
    "from 3s to 8s, and unlocks panel universe mode (p_ids empty + "
    "p_entity_type: a whole family, paged with p_after). Exceeding the id "
    "ceiling raises SQLSTATE 22023 naming the limit — the panel is never "
    "silently truncated to fit.",
    "Signing in does NOT raise rows-per-response: the 1000-row cap is a "
    "server-wide PostgREST setting applied identically to every caller. Page "
    "views, and narrow the window on functions, whatever tier you are.",
    "Option rows carry underlying_ticker resolved from the PUBLISHED ISIN "
    "mapping (an option row's ISIN is its underlying's ISIN), never from the "
    "codneg root; it is null when the underlying had no cash print that "
    "session. Termo rows still carry no underlying column.",
    "tpmerc 012/013 are option exercise EVENTS served by option_exercises, "
    "and 017 auction prints by auctions — neither is a quote series; do not "
    "compute returns over them.",
    "fund_quotas rows carry fund_type (etf | fii | fidc | fiagro) from B3's "
    "published CODBDI board code, null when the board has no family signal "
    "(odd lot). equities rows carry share_class (ON/PN/PNA/PNB/PNC/PND) and "
    "governance_segment (NM/N1/N2/MA/M2/MB) parsed from published ESPECI, "
    "never from the ticker suffix.",
    "Each cash instrument type has its own endpoint (equities, bdrs, units, "
    "fund_quotas, cash_securities) — the same rows as quotes, split by the type "
    "derived from published TPMERC/ESPECI. Their grain adds `lot` "
    "(standard = tpmerc 010, odd = 020/021); filter lot=eq.standard for round "
    "lots. quotes itself stays standard-lot only.",
    "Price series stay unified: a codneg has exactly one instrument type, so "
    "quote_history works for any cash ticker without knowing its type first.",
]

# Written against the DEPLOYED surface, which is PostgREST. These were /v1/*
# query strings until v27 — the local Flask adapter's form, which the `agent`
# instructions above themselves describe as "not necessarily deployed", so an
# agent that copied the one section meant to be copyable got a 404 on the
# hosted API. The `format=wide` envelope went with them: it exists only in
# serve/app.py, so the RPC hands back long (id, date, metric, value) rows and
# the pivot is the notebook's job, as `then` now says.
EXAMPLES = [
    {
        "ask": "How does PETR4 relate to delinquency in this FIDC?",
        "call": (
            "POST /rest/v1/rpc/panel "
            '{"p_ids": ["PETR4", "<cnpj>"], '
            '"p_metrics": ["close_return", "delinquency"], "p_freq": "month"}'
        ),
        "then": "Pivot the long rows on (date, id, metric), then a pairwise-complete correlation in the notebook. Do not ffill.",
    },
    {
        "ask": "Rank these funds by latest NAV",
        "call": (
            "POST /rest/v1/rpc/panel "
            '{"p_ids": ["<cnpj>", "<cnpj>"], "p_metrics": ["nav"], '
            '"p_freq": "month"}'
        ),
        "then": "Take the last non-null NAV per id. Keep asset_class in the key: a CNPJ filing under two families returns one row per family.",
    },
    {
        "ask": "Did inflows and quota move together for this FI?",
        "call": (
            "POST /rest/v1/rpc/panel "
            '{"p_ids": ["<cnpj>"], "p_metrics": ["inflows", "quota"], '
            '"p_freq": "month"}'
        ),
        "then": "Correlate the two metrics' series; nulls stay null.",
    },
    {
        "ask": "Spread of two equity closes at month end",
        "call": (
            "POST /rest/v1/rpc/panel "
            '{"p_ids": ["PETR4", "VALE3"], "p_metrics": ["close"], '
            '"p_freq": "month"}'
        ),
        "then": "Subtract the aligned series; a missing month is null, not interpolated.",
    },
    {
        "ask": "Which of these FIDCs is most exposed to one debtor?",
        "call": (
            "POST /rest/v1/rpc/panel "
            '{"p_ids": ["<cnpj>", "<cnpj>", "<cnpj>"], '
            '"p_metrics": ["sacado_top1", "receivables"], "p_freq": "month"}'
        ),
        "then": "Divide sacado_top1 by receivables per row; the debtor is anonymized, so this is a ratio, not a name.",
    },
    {
        "ask": "Did this FIDC's senior tranche deliver what it promised?",
        "call": (
            "POST /rest/v1/rpc/fidc_tranches "
            '{"p_cnpj": "<cnpj>", "p_from": "2025-01-01"}'
        ),
        "then": (
            "Compare performance_realised with performance_expected per "
            "classe_serie in the notebook; both are as filed and can carry "
            "CVM's outliers. History starts 2013-01 (CVM's HIST archive "
            "through 2024-12). Read the aging ladder under it with "
            "fidc_aging; overdue_total is CVM's filed total, not a sum."
        ),
    },
    {
        "ask": "Which FIDCs restated a filing this month, and how late?",
        "call": (
            "POST /rest/v1/rpc/fund_restatements "
            '{"p_tipo_fundo": "FIDC", "p_from": "<month start>"}'
        ),
        "then": (
            "Each row is a re-filed document (versao > 1; modalidade RE is "
            "voluntary, RC was required by CVM) with lag_days since the version "
            "it replaced. The pairing is by a stated group key because FNET "
            "links no versions; cnpj NULL means the fortnightly fund sweep has "
            "not linked it yet — never match it to a fund by fund_name. Open "
            "the versions with fund_documents' source_url."
        ),
    },
    {
        "ask": "What did this FIDC change when it restated its December informe?",
        "call": (
            "POST /rest/v1/rpc/fund_restatement_diff "
            '{"p_fnet_id": <fund_restatements.fnet_id>}'
        ),
        "then": (
            "One row per field that differs from previous_fnet_id, text as "
            "printed, delta on numeric leaves (delinquency, PL, quota values). "
            "Check fund_restatements' diff_status first: no rows with "
            "diff_status 'compared' means re-filed with nothing changed; any "
            "other status (or NULL) means not diffed. match_basis 'position' "
            "rows are approximate. Open both versions with source_url and "
            "previous_source_url."
        ),
    },
    {
        "ask": "Which FIDCs keep filing their monthly informe late?",
        "call": (
            "POST /rest/v1/rpc/screen_late_filers "
            '{"p_family": "fidc"}'
        ),
        "then": (
            "Each row is a SIGNAL: a fund whose first FNET delivery of the "
            "informe mensal came at least p_min_days_late days after the "
            "deadline in deadline_rule (Resolução CVM 175, cited on the row) in "
            "at least p_min_late of the last 12 measured months. It says nothing "
            "about extensions CVM may have granted, and a month missing from "
            "the register is not counted. Open the filings with "
            "fund_documents(cnpj) and check screen_silent_filers for funds "
            "that stopped filing altogether."
        ),
    },
    {
        "ask": "What material facts has PETR4 published this year?",
        "call": (
            "POST /rest/v1/rpc/company_events "
            '{"p_id": "PETR4", "p_category": "Fato Relevante", "p_from": "<year start>"}'
        ),
        "then": (
            "One row per protocol at its newest version, text as filed; open "
            "source_url for the document on CVM's RAD. Filings CVM published "
            "without a protocol number (all before 2015) are not held, so an "
            "empty early window is that limit, not a quiet company."
        ),
    },
    {
        "ask": "How did CDI and the Selic target move over the last year?",
        "call": (
            "POST /rest/v1/rpc/macro_series "
            '{"p_series": "CDI"}  then  {"p_series": "SELIC_META"}'
        ),
        "then": (
            "Read `unit` first: CDI is % per business day, SELIC_META % a.a. "
            "Compound or annualise in the notebook and say so. For PTAX buy "
            "and sell per currency call ptax; for IPCA call inflation."
        ),
    },
    {
        "ask": "What is the DI curve pricing, and how has the one-year point moved?",
        "call": (
            "POST /rest/v1/rpc/future_curve {}  then  "
            "POST /rest/v1/rpc/curve_history "
            '{"p_curve": "PRE", "p_tenor_days": 360}'
        ),
        "then": (
            "future_curve lists every DI1 contract of the newest session: "
            "settlement_rate is % a.a. on 252 business days and the quote "
            "columns are rates too. curve_history is B3's own fixed 360-day "
            "vertex of PRE, never an interpolation; any other tenor means "
            "reading curve and interpolating in the notebook. The long end "
            "of every curve is B3's extrapolation, not a price."
        ),
    },
    {
        "ask": "Just give me the panel; I will run a factor model",
        "call": (
            "POST /rest/v1/rpc/panel "
            '{"p_ids": ["PETR4", "VALE3", "<cnpj>"], '
            '"p_metrics": ["close_return", "nav"], "p_freq": "month"}'
        ),
        "then": "Model in the notebook from the long rows. Anonymous callers are capped at 3 ids — a 4th raises 22023, it is not trimmed.",
    },
    {
        "ask": "Is core inflation running above the headline?",
        "call": (
            "POST /rest/v1/rpc/inflation "
            '{"p_family": "core"}'
        ),
        "then": (
            "Rows are monthly changes in percent as published, one per "
            "(month, series); acc_12m is the trailing twelve chained and NULL "
            "until a series has twelve consecutive months. Put IPCA "
            "(p_series='IPCA', or family headline) beside them; never annualise "
            "a single month."
        ),
    },
    {
        "ask": "What moved the IPCA last month?",
        "call": (
            "POST /rest/v1/rpc/inflation_items "
            '{"p_level": 1, "p_from": "<month start>"}'
        ),
        "then": (
            "contribution is weight × change_month / 100 in percentage points; "
            "the nine level-1 rows sum to the headline to rounding. Drill with "
            "p_level=2..4 and p_item=<structure number> — but sum ONE level at "
            "a time, a group and its subgroups are the same money twice."
        ),
    },
    {
        "ask": "Which FIDCs match the evergreen-aging screen?",
        "call": "POST /rest/v1/rpc/screen_evergreen_aging {}",
        "then": (
            "Each row is a SIGNAL, not a finding: it carries `screen` and "
            "`params` (the thresholds it crossed). Read `screens.evergreen_aging."
            "meaning` for what else looks the same, then take the cnpjs to "
            "fund_nav or panel and the fund's own filings before saying "
            "anything about it."
        ),
    },
    {
        "ask": "Which names are most heavily shorted right now?",
        "call": (
            "GET /rest/v1/short_interest"
            "?trade_date=eq.<the trade_date coverage() reports>"
            "&float_basis=eq.index_free_float"
            "&order=pct_float.desc&limit=25"
        ),
        "then": (
            "A view, not an RPC: filter and page it with PostgREST syntax. "
            "The float_basis filter is REQUIRED for a ranking — index_free_float "
            "and shares_outstanding are different denominators and sorting them "
            "together is meaningless. Read the ratchet constraint before calling "
            "the window short."
        ),
    },
    {
        "ask": "Who was borrowing PETR4 last session, and was it real demand?",
        "call": (
            "GET /rest/v1/lending_participants"
            "?ticker=eq.PETR4&trade_date=eq.<session>"
            "&order=quantity_borrowed.desc"
        ),
        "then": (
            "broker_code is the INTERMEDIARY, never the owner. Compare "
            "internal_qty against quantity_lent + quantity_borrowed per broker: "
            "a high internal share is that broker crossing its own clients, not "
            "a position it took."
        ),
    },
    {
        "ask": "What did foreign investors do this month?",
        "call": (
            "GET /rest/v1/investor_flow"
            "?investor_type=eq.<type>&reference_date=gte.<month start>"
            "&order=reference_date.asc"
        ),
        "then": (
            "Check flow_basis on every row first. 'unknown_opening_snapshot' "
            "rows carry NULL flows by construction — drop them, never read them "
            "as zero. Values are R$ thousands, differenced from a month-to-date "
            "snapshot published T+2."
        ),
    },
]

AGENT_INSTRUCTIONS = (
    "You are querying Silo, a Brazilian public-markets warehouse (CVM funds, "
    "B3 COTAHIST cash quotes, options and termo, the B3 securities-lending "
    "and investor-flow group, B3's DI1 futures and reference-rate curves, "
    "and Brazilian inflation — BACEN's IPCA series "
    "and IBGE's item tree with weights). Call catalog once and cache "
    "it. Resolve names with lookup, then fetch a panel. The primitive "
    "is a panel (id, date, metric, value). Correlation, ranking, spreads, "
    "regressions and other relations are reductions of that panel — compute "
    "them in the notebook. Do not fabricate ids, fills, or ticker-CNPJ "
    "matches. "
    "TWO SURFACES, AND THEY DIFFER: the DEPLOYED api is Supabase PostgREST — "
    "POST /rest/v1/rpc/<function> with a JSON body of p_-prefixed named "
    "arguments (arrays stay arrays), views at GET /rest/v1/<view>, header "
    "`apikey`. The /v1/* routes in `endpoints` are an optional local Flask "
    "adapter (serve/app.py) that is not necessarily deployed; its query-string "
    "form and its `format=wide` envelope exist ONLY there. Prefer the "
    "postgrest section unless you know the /v1 adapter is running. Read the "
    "row-cap constraint: EVERY function REFUSES (SQLSTATE 22023) a window "
    "over 1000 rows instead of trimming it — page panel, quote_history and "
    "fund_nav with p_after, narrow the rest. fund_nav also needs "
    "p_entity_type to page. The GET views still cut at 1000 and keep the "
    "OLDEST rows, so READ THE Content-Range RESPONSE HEADER on those: "
    "`0-999/*` is the only thing that tells you. BEFORE READING A NULL AS A "
    "GAP, call coverage() and metric_coverage(): a null outside a family's "
    "column set is not applicable, and a metric absent from metric_coverage() "
    "is one that family never files. coverage().as_of is the newest ELAPSED "
    "period; newest_period can sit in the future when a family files "
    "forward-dated (FIP is keyed 31-December), so never read it as freshness. "
    "PRICE IS THE DEFAULT, everything else is opt-in: panel with no p_metrics "
    "returns `close_adj` (split-, grouping- and bonus-adjusted) for share and "
    "unit tickers, `close` for other tickers and `nav` for CNPJs, and "
    "quote_history with no p_fields returns ticker, trade_date and close_adj; "
    "that is the call to make unless you actually need another measure — name "
    "metrics or fields explicitly only when you will use them (p_fields=['close'] "
    "for the raw close). A close_adj window SILO cannot adjust is refused with "
    "the cause, never served raw. The wide endpoints are the exception and "
    "behave the other way round: quote_latest and the views return their full "
    "OHLCV/identity row every time, so trim them with PostgREST `?select=` "
    "(e.g. `?select=ticker,trade_date,close`) rather than pulling 22 columns to "
    "read one. See `defaults`."
)

# What a caller gets when it asks for nothing. Machine-readable because an
# agent that has to infer the default from prose will instead request every
# metric it can see — which is how a price lookup turns into seven columns of
# fund accounting it never reads.
# quote_history's selectable fields (p_fields) and their JSON types, the same
# list as api.quote_history_fields() in 19_api_contract.sql;
# tests/test_quote_history_contract.py pins the two together.
QUOTE_HISTORY_FIELDS: Dict[str, str] = {
    "ticker": "string",
    "trade_date": "date",
    "close_adj": "number",
    "close": "number",
    "open": "number",
    "high": "number",
    "low": "number",
    "average": "number",
    "bid": "number",
    "ask": "number",
    "close_unit": "number",
    "trades": "integer",
    "quantity": "number",
    "volume": "number",
    "quotation_factor": "integer",
    "board": "string",
    "isin": "string",
    "short_name": "string",
    "spec": "string",
    "currency": "string",
    "asset_class": "string",
    "source": "string",
    "coverage_start": "date",
    "coverage_end": "date",
    "prior_no_trade_sessions": "integer",
    "events_proven_at": "string",
    "data_revision": "string",
    "close_total_return": "number",
    "close_total_return_null_reason": "string",
}

DEFAULTS = {
    "principle": "price by default; every other measure is opt-in",
    "panel": {
        "metrics": ["close", "close_adj", "nav"],
        "means": "p_metrics omitted: close_adj for share and unit tickers, close for every other ticker, option and termo, nav for cnpj ids; an explicit list is served as asked, and a metric absent for an id type simply yields no rows",
        "grain": "(id, asset_class, date, metric) — a CNPJ filing under two families yields one row per family; p_entity_type narrows to one",
        "to_widen": "pass p_metrics explicitly, e.g. p_metrics=['close','volume']",
    },
    "quote_history": {
        "fields": ["ticker", "trade_date", "close_adj"],
        "means": "one JSON object per session with only the selected keys; ticker and trade_date are in every row",
        "to_widen": "pass p_fields, e.g. p_fields=['close','volume'] for the raw close and volume; an unknown name refuses (22023)",
        "precision": "prices are decimals as published (6 decimal places on the tape); close_adj is rounded to 6 decimal places",
        "available": QUOTE_HISTORY_FIELDS,
    },
    "wide_endpoints": {
        "which": ["quote_latest", "fund_nav", "api.quotes and the typed views"],
        "behaviour": "fixed full row (OHLCV + identity); the column list cannot vary by argument",
        "to_narrow": "PostgREST ?select=, e.g. /rest/v1/rpc/quote_latest?select=ticker,trade_date,close",
    },
}


# Every ceiling a caller can hit, as numbers. The prose constraints above say
# the same things; this is the copy an agent can read without parsing a
# sentence. tests/test_api_contract_sql.py pins each tier number to the CASE
# api.caller_tier() expression in 19_api_contract.sql, so this block cannot
# quietly lag the SQL.
LIMITS = {
    "rows_per_response": {
        "value": 1000,
        "scope": (
            "every response, every tier — PostgREST db-max-rows, a server-wide "
            "setting; signing in does not change it"
        ),
        "kept": "the OLDEST rows; a cut-short series looks like one that simply ends",
        "detect": (
            "the Content-Range response header: `0-999/*` is a truncated page; "
            "send `Prefer: count=exact` and it reads `0-999/<total>`"
        ),
        "paging": {
            "views": "limit/offset (and Range) page normally on GET /rest/v1/<view>",
            "rpc": (
                "does not page: a Range on /rest/v1/rpc/<function> returns the "
                "first page again — narrow p_from/p_to, ids or metrics instead"
            ),
        },
    },
    "page": {
        "size": 1000,
        # Every set-returning function, split by what it offers ABOVE one page.
        "all": [
            "panel", "quote_history", "fund_nav", "option_history",
            "termo_history", "financials", "company_financials", "income_statements",
            "balance_sheets", "cash_flow_statements",
            "anbima_classes", "inflation", "inflation_items",
            "financial_statement_history", "fii_property_history",
            "focus_expectations",
            "fidc_cedentes", "fidc_sacados", "fidc_portfolio",
            "fidc_tranches", "fidc_aging",
            "fund_holdings", "fund_debentures",
            "fund_documents", "fund_restatements", "fund_restatement_diff",
            "screen_zombie_growth", "screen_captive_vehicles",
            "screen_evergreen_aging", "screen_overdue_securit",
            "screen_dormant_funds", "screen_dormant_trend",
            "screen_delinquency_drivers",
            "screen_restatements", "screen_late_filers", "screen_silent_filers",
            "company_events", "macro_series", "ptax",
            "future_curve", "future_series", "curve", "curve_history",
            "research_universe", "index_history",
            "portfolio_resolve", "portfolio_fees", "portfolio_lookthrough", "portfolio_movement",
            "portfolio_instruments", "portfolio_fund_terms",
        ],
        # The protocol every cursor below shares.
        "cursor_protocol": (
            "p_after: null = whole result (refused above 1000 rows); "
            "'' = first page; the function's key copied from the last row = "
            "the next page; a page shorter than 1000 is the last"
        ),
        "functions": {
            # Walking the whole series is the normal case, so these take a
            # cursor, keyed as below.
            "paged": {
                "panel": (
                    "'<date>|<id>|<metric>|<asset_class>' copied from the last "
                    "row; order is date, id, metric, asset_class"
                ),
                "quote_history": (
                    "the last row's trade_date as 'YYYY-MM-DD'; order is "
                    "trade_date. Keep the same p_fields on every page, and "
                    "restart when data_revision changes between pages"
                ),
                # v45: the index levels (29_api_index.sql) — IBOV from 1968 is
                # 14,489 rows, so walking it is the normal case.
                "index_history": (
                    "the last row's trade_date as 'YYYY-MM-DD'; order is "
                    "trade_date"
                ),
                "fund_nav": (
                    "the last row's period as 'YYYY-MM-DD'; order is period, "
                    "entity_type. PAGING REQUIRES p_entity_type — the cursor "
                    "is a bare period, which is unique only within one family, "
                    "and 385 CNPJs file under two (fi + fidc) in the same "
                    "month. Without it you get 22023, not a wrong answer. "
                    "Whole-result mode needs no p_entity_type and labels every "
                    "row with its family"
                ),
            },
            # A window over one page here is a mistake, not a walk (an option
            # series lives months; a statement has tens of rows), so these
            # refuse and ask you to narrow instead of handing you a cursor.
            "raise_only": [
                "option_history", "termo_history", "financials",
                "company_financials", "income_statements",
                "balance_sheets", "cash_flow_statements", "anbima_classes",
                "inflation", "inflation_items",
                "financial_statement_history", "fii_property_history",
                "focus_expectations",
                # v34: the FIDC concentration tabs, which until v33 trimmed
                # silently at the tier ceiling. p_limit (1..1000) is an
                # explicit newest-first head, not a cursor.
                "fidc_cedentes", "fidc_sacados", "fidc_portfolio",
                # v32: the FIDC structure tabs.
                "fidc_tranches", "fidc_aging",
                # v41: fund holdings (CDA blocks 4, 2, 6), which until v40
                # trimmed silently at the tier ceiling. p_limit (1..1000) is
                # an explicit newest-first head, not a cursor.
                "fund_holdings", "fund_debentures",
                # v33: the FNET register — a year of one fund's documents,
                # or a month of restatements, is a window to narrow.
                "fund_documents", "fund_restatements",
                # v40: what a restatement changed — one document, or one
                # fund's window, is small; narrow it, never walk it.
                "fund_restatement_diff",
                # v31: a screen is a short list or the wrong screen — raise
                # its thresholds or pin its output filter, never walk it.
                "screen_zombie_growth", "screen_captive_vehicles",
                "screen_evergreen_aging", "screen_overdue_securit",
                "screen_dormant_funds", "screen_dormant_trend",
                "screen_delinquency_drivers",
                # v37: the filing-behaviour screens (25_api_filing_screens.sql).
                "screen_restatements", "screen_late_filers", "screen_silent_filers",
                # v38: held-but-unserved datasets (26_api_events_macro.sql) —
                # a window to narrow, never a series to walk.
                "company_events", "macro_series", "ptax",
                # v42: the rate curve (27_api_rates.sql) — one session is
                # tens to hundreds of rows, and a history is a window.
                "future_curve", "future_series", "curve", "curve_history",
                # v43: the research universe (28_api_research.sql) — no
                # parameter narrows it; it is one page today (639 pairs).
                "research_universe",
                # v51: the portfolio reads (31_api_portfolio.sql) — a set of
                # funds or lines is split by the caller, never walked.
                "portfolio_resolve", "portfolio_fees", "portfolio_lookthrough", "portfolio_movement",
                # v61: statement codes and fund terms, split by the caller too.
                "portfolio_instruments", "portfolio_fund_terms",
            ],
        },
        "over_cap": (
            "SQLSTATE 22023 naming the function — nothing is trimmed to fit. "
            "The message says WHY (one 1000-row page; SILO never returns a "
            "silently truncated result) and HOW for that function (page with "
            "p_after, narrow p_from/p_to, take an explicit p_limit head, "
            "raise a screen's "
            "thresholds); PostgREST also returns the two halves as `details` "
            "and `hint`"
        ),
        "no_sentinel": (
            "there is no cap+1 row to count any more. The old 5001 (series) "
            "and 100001 (panel) sentinels were unobservable on the hosted API, "
            "because PostgREST cuts every response at 1000 rows long before "
            "either is reached; they are gone, and the 22023 replaces them"
        ),
    },
    "tiers": {
        "anon": {
            "panel_ids": 3,
            "panel_universe": False,
            "search_funds_rows": 25,
            "option_chain_rows": 200,
            "option_exercises_rows": 500,
            "statement_timeout_seconds": 3,
        },
        "authenticated": {
            "panel_ids": 50,
            "panel_universe": True,
            "search_funds_rows": 200,
            "option_chain_rows": 2000,
            "option_exercises_rows": 5000,
            "statement_timeout_seconds": 8,
        },
        "exceeding_an_id_ceiling": (
            "SQLSTATE 22023 naming the limit — a panel is never silently "
            "trimmed to fit"
        ),
        "how_to_sign_in": (
            "GitHub at https://silo-bz-deloslabs.vercel.app/signin.html; send "
            "the JWT as `Authorization: Bearer <jwt>` beside `apikey` (the SDK "
            "takes it as token= or SILO_TOKEN)"
        ),
    },
}


# Which fund_nav columns (and therefore which panel metrics) each family
# actually files. Read off fact_fund_monthly's per-family arms in
# 04_fact_fund_monthly.sql, where every column outside a family's list is
# `NULL::<type> AS <col>` by construction. tests/test_api_contract_sql.py
# parses those arms and fails if this block drifts from the SQL, and pins
# every fund metric's asset_class list in METRICS to the same source.
APPLICABILITY = {
    "fund_nav": {
        "rule": (
            "every family returns the same eleven columns; a null OUTSIDE the "
            "family's list below is set by construction (not applicable), a "
            "null INSIDE it is a blank in that month's filing"
        ),
        "columns_by_family": {
            "fi": ["nav", "quota", "quotaholders", "inflows", "redemptions"],
            "fidc": ["nav", "delinquency"],
            "fiagro": ["nav", "delinquency"],
            "fii": ["nav", "quotaholders", "monthly_yield", "assets"],
            "fip": ["nav"],
        },
        "period_convention": {
            "fi": "first day of the month",
            "fidc": "last day of the month",
            "fiagro": "first day of the month",
            "fii": "first day of the month",
            "fip": "31-Dec of the filing year (annual)",
        },
        "panel_metric_names": {"monthly_yield": "yield"},
    },
    # The three concentration metrics read the FIDC informe's own tabs
    # (cvm_fidc_setor, cvm_fidc_sacado — migration 38), which only FIDCs
    # file. tests/test_api_contract_sql.py pins every cnpj metric's family
    # list to the union of these blocks.
    "fidc_concentration": {
        "rule": (
            "receivables, sacado_top1 and sacado_top25 exist for fidc only; "
            "a fund of any other family simply has no rows for them"
        ),
        "columns_by_family": {
            "fidc": ["receivables", "sacado_top1", "sacado_top25"],
        },
        "starts": {
            "receivables": "2013-01 (tab II)",
            "sacado_top1": "2013-01 (tab VIII)",
            "sacado_top25": "2013-01 (tab VIII)",
        },
    },
}

# Points where a served series changes meaning mid-stream because the SOURCE
# format changed. A caller that chain-links across one of these fabricates a
# move the market never made. Each entry is also carried as prose on the
# matching coverage() row's `notes` column (19_api_contract.sql).
REGIME_BREAKS = [
    {
        "dataset": "funds_fidc",
        "column": "delinquency",
        "boundary": "2020-11-30",
        "before": (
            "through 2020-10-31 delinquency comes from CVM's HIST tab VI, which "
            "has no row for some funds in some months: such a fund, or a blank "
            "cell, is null (about 70% to 93% of fidc rows carry a value) — not "
            "zero, not clean books, not a missing month"
        ),
        "after": (
            "from 2020-11-30 tab VI is filed for every fund and delinquency is on "
            "every row (a fund with no delinquent receivables files 0). It is the "
            "same filed field from 2013-01 to date: TAB_VI_B_VL_DIRCRED_INAD, from "
            "the HIST archive through 2024-12 and the monthly informe from 2025-01"
        ),
        "never": (
            "read a pre-2020-11 null as zero or fill it, or compare a count of "
            "reporting funds across 2020-10 → 2020-11; the filed values on both "
            "sides are the same measure"
        ),
    },
]


# The forensic screens (v31), served by 23_api_screens.sql. SIGNALS, NOT
# VERDICTS: `meaning` says what crossing the threshold measures AND what else
# produces the same pattern, because a screen that only says the first half is
# an accusation. `params` are the defaults — the dashboard's own calls — and
# `bounds` the ranges outside which the SQL raises 22023. `filters` narrow the
# output without changing the screen. tests/test_api_screens_contract.py pins
# params to the SQL DEFAULTs and to the dashboard sources, and every row the
# function returns carries `screen` and `params` beside its own columns.
SCREENS: Dict[str, Dict[str, Any]] = {
    "zombie_growth": {
        "function": "screen_zombie_growth",
        "family": "fidc",
        "source": "cvm_fidc_aging (tab VI total) and cvm_fidc_mensal, one aging month",
        "grain": "one row per FIDC in the chosen aging month",
        "params": {"p_period": None, "p_min_delinq_pct": 5, "p_min_aum": 1000000},
        "bounds": {
            "p_period": "an aging month-end; null = the latest aging period",
            "p_min_delinq_pct": "0..100, percent of NAV",
            "p_min_aum": ">= 0, BRL",
        },
        "dashboard": "/suspicious",
        "meaning": (
            "Delinquent receivables above p_min_delinq_pct of NAV while NAV stays "
            "above p_min_aum: credit going bad inside a fund that still carries "
            "meaningful money. The same pattern comes from a distressed-credit "
            "mandate, a fund in orderly wind-down, or one late payer in a small "
            "book. delinquency_pct is delinquency / NAV, and can exceed 100."
        ),
    },
    "captive_vehicles": {
        "function": "screen_captive_vehicles",
        "family": "fii",
        "source": "cvm_fii_mensal (complemento), trailing window from today",
        "grain": "one row per FII",
        "params": {"p_lookback_months": 3, "p_max_investors": 10, "p_min_aum": 50000000},
        "bounds": {
            "p_lookback_months": "1..36",
            "p_max_investors": "1..1000; flagged when the window minimum is below it",
            "p_min_aum": ">= 0, BRL, against the window maximum NAV",
        },
        "dashboard": "/suspicious",
        "meaning": (
            "An FII whose NAV peaked above p_min_aum while its quotaholder count "
            "never reached p_max_investors in the window: a large vehicle held by "
            "a handful of investors. Exclusive and family-office FIIs are legal "
            "and look exactly like this."
        ),
    },
    "evergreen_aging": {
        "function": "screen_evergreen_aging",
        "family": "fidc",
        "source": "cvm_fidc_aging, trailing window from today, funds with > R$100k delinquent",
        "grain": "one row per FIDC",
        "params": {"p_lookback_months": 12, "p_min_longtail_pct": 70, "p_max_variation_pp": 10},
        "bounds": {
            "p_lookback_months": "3..36",
            "p_min_longtail_pct": "0..100, share of delinquency overdue > 1080 days",
            "p_max_variation_pp": "0..100 percentage points across the window",
        },
        "dashboard": "/suspicious",
        "meaning": (
            "Receivables overdue more than 1080 days stay a large and nearly "
            "constant share of delinquency: old credit neither written off nor "
            "recovered, the pattern of rolled rather than resolved receivables. "
            "A slow judicial recovery, or a policy of not writing off, looks the "
            "same. months_observed counts the aging months actually filed."
        ),
    },
    "overdue_securit": {
        "function": "screen_overdue_securit",
        "family": "securit",
        "source": "cvm_securit_serie, each series' newest monthly filing",
        "grain": "one row per series (instrument_type, securitizer, code, series number)",
        "params": {"p_min_volume": 100000},
        "bounds": {"p_min_volume": ">= 0, BRL paid in"},
        "dashboard": "/suspicious",
        "meaning": (
            "A CRI/CRA/other series past its filed maturity whose newest filing "
            "still reports a non-terminal status (not Cancelado, Vencido, "
            "Liquidado or Encerrado). The FILING is stale; the screen cannot say "
            "whether the series was extended, renegotiated, not yet re-filed or "
            "is in silent default. status is served as filed. The series number "
            "is not a column, so two series under one instrument_code read as "
            "two rows with the same identity."
        ),
    },
    "dormant_funds": {
        "function": "screen_dormant_funds",
        "family": "fi",
        "source": "fact_fund_monthly (fi), anchored on latest_complete_period('fi')",
        "grain": "one row per FI class",
        "params": {"p_lookback_months": 3, "p_dormancy": None, "p_min_nav": None},
        "bounds": {"p_lookback_months": "2..12"},
        "filters": {
            "p_dormancy": "empty_shell | parked_capital; null = both (output filter)",
            "p_min_nav": "keep last_nav >= this, BRL; null = no floor (output filter)",
        },
        "dashboard": "/dormant",
        "meaning": (
            "An FI class that filed every month of the window with zero "
            "subscriptions and zero redemptions. empty_shell: no quotaholder at "
            "all — a registered, filing vehicle holding nobody's money. "
            "parked_capital: quotaholders present, no money in or out — "
            "exclusive and closed structures look exactly like this. A month "
            "with unreported flows or quotaholders disqualifies the fund rather "
            "than counting as zero. FI only: the other families file no monthly "
            "flows. parked_capital alone exceeds one page; pin p_dormancy and "
            "walk p_min_nav bands."
        ),
    },
    "dormant_trend": {
        "function": "screen_dormant_trend",
        "family": "fi",
        "source": "fact_fund_monthly (fi), the dormant_funds screen at every month-end",
        "grain": "one row per month",
        "params": {"p_lookback_months": 3, "p_history_months": 36},
        "bounds": {"p_lookback_months": "2..12", "p_history_months": "1..60"},
        "dashboard": "/dormant",
        "meaning": (
            "dormant_funds evaluated at every month-end: funds_filing, "
            "empty_shells and parked_capital counts, and parked_nav (NAV sitting "
            "in parked_capital classes). Counts of a screen, not of misconduct."
        ),
    },
    "delinquency_drivers": {
        "function": "screen_delinquency_drivers",
        "family": "fidc",
        "source": "fact_fund_monthly (fidc) — the series fund_nav and panel serve",
        "grain": "one row per FIDC with >= p_min_months observations in the window",
        "params": {
            "p_end": None, "p_months": 12, "p_min_months": 6,
            "p_min_delta_brl": 1000000, "p_min_delta_pp": 1.0, "p_driver": None,
        },
        "bounds": {
            "p_end": "window end; null = latest_complete_period('fidc'); the window may not start before 2025-01",
            "p_months": "2..24",
            "p_min_months": "2..p_months",
            "p_min_delta_brl": ">= 0, BRL",
            "p_min_delta_pp": ">= 0, percentage points",
        },
        "filters": {
            "p_driver": (
                "consistent_worsening | value_up_rate_masked | denominator_only | "
                "improvement | stable; null = all (output filter)"
            ),
        },
        "dashboard": "/fidc",
        "meaning": (
            "First vs last observation of FIDC delinquency in BRL and in "
            "percentage points of NAV, the move classified by the two "
            "thresholds: consistent_worsening (value up and rate up), "
            "value_up_rate_masked (value up, rate flat or down — NAV grew with "
            "it), denominator_only (rate up, value flat or down — NAV shrank, "
            "not new delinquency), improvement (both down), stable. No sector, "
            "no debtor, no guarantee: a classification of two numbers, not a "
            "finding about the fund. stopped_reporting flags a last filing two "
            "or more months behind the window end. Every FIDC gets a row, so the "
            "unfiltered set exceeds one page; pin p_driver."
        ),
    },
    # v37: the filing-behaviour screens (25_api_filing_screens.sql). No
    # dashboard page runs them, so `dashboard` is None and the api function is
    # the one definition; the defaults below are pinned to its SQL DEFAULTs.
    "restatements": {
        "function": "screen_restatements",
        "family": "fii, fidc, etf (FNET)",
        "source": "fnet_document + fnet_document_filter (cnpjFundo links), trailing delivery window",
        "grain": "one row per fund CNPJ (cnpjFundo link)",
        "params": {
            "p_months": 12, "p_end": None, "p_min_restatements": 3,
            "p_min_rate_pct": 20, "p_modalidade": None,
        },
        "bounds": {
            "p_months": "1..36, trailing months of delivery days",
            "p_end": "last delivery day of the window; null = today",
            "p_min_restatements": "1..1000 re-filings (versao > 1) in the window",
            "p_min_rate_pct": "0..100, re-filings as percent of the fund's documents in the window",
        },
        "filters": {
            "p_modalidade": "RE | RC: count only voluntary or only CVM-required re-filings; null = every versao > 1",
        },
        "dashboard": None,
        "meaning": (
            "A fund whose FNET re-filings (versao > 1) in the window number at "
            "least p_min_restatements AND are at least p_min_rate_pct of its "
            "documents. restatements_re (voluntary) and restatements_rc "
            "(required by CVM) split them as FNET publishes modalidade. The "
            "same pattern comes from routine typo corrections, an "
            "administrator or custodian migration re-submitting a whole book, "
            "the resolution-175 adaptation, a FNET template change forcing "
            "re-submission, one error cascading through consecutive informes, "
            "or a CVM supervision sweep across an administrator's funds; an RC "
            "says CVM asked, not what was wrong. Fund identity is the "
            "cnpjFundo link only; unlinked documents and history before "
            "SILO's first crawl are not counted."
        ),
    },
    "late_filers": {
        "function": "screen_late_filers",
        "family": "fii, fidc (FNET)",
        "source": (
            "fnet_document 'Informe Mensal Estruturado', versao 1, first "
            "delivery per (cnpjFundo link, reference month)"
        ),
        "grain": "one row per fund CNPJ with at least p_min_late late months",
        "params": {
            "p_months": 12, "p_end": None, "p_min_days_late": 5,
            "p_min_late": 2, "p_family": None,
        },
        "bounds": {
            "p_months": "1..36 reference months ending at p_end",
            "p_end": (
                "any day in the last reference month; null = the newest month "
                "whose deadline has passed; a window ending before 2024-12 "
                "raises 22023"
            ),
            "p_min_days_late": "1..90 days past the cited deadline",
            "p_min_late": "1..p_months late months",
        },
        "filters": {"p_family": "fii | fidc; null = both (output filter)"},
        "deadline_rule": {
            "fidc": (
                "Resolução CVM 175, Anexo Normativo II, art. 27, III — informe "
                "mensal within 15 days after the end of the reference month; "
                "measured from reference month 2024-12 (FIDC adaptation "
                "deadline 2024-11-29)"
            ),
            "fii": (
                "Resolução CVM 175, Anexo Normativo III, art. 36, I — monthly "
                "form (Suplemento I) within 15 days after the end of the "
                "reference month; measured from reference month 2025-07 "
                "(adaptation deadline 2025-06-30)"
            ),
            "counting": (
                "calendar days (the text says dias); no holiday calendar is "
                "applied — p_min_days_late absorbs a weekend or holiday rollover"
            ),
            "text_read": "conteudo.cvm.gov.br consolidated annexes, 2026-09-25",
        },
        "dashboard": None,
        "meaning": (
            "A FII or FIDC whose monthly informe first reached FNET at least "
            "p_min_days_late days after the cited deadline, in at least "
            "p_min_late measured months. informes counts the months measured, "
            "informes_late the late ones, max_days_late the worst, "
            "median_lag_days the fund's median delivery lag after month end. "
            "A timestamp compared with a rule, not a finding: CVM can grant "
            "extensions, delivered_at is FNET's upload time, an administrator "
            "transfer can delay one month for a whole book, and a fund with "
            "several classes is measured on its earliest filing. A month with "
            "no informe in the register is not counted (the register is "
            "partial) — absence is silent_filers."
        ),
    },
    "silent_filers": {
        "function": "screen_silent_filers",
        "family": "fi, fidc, fii, fiagro (CVM)",
        "source": (
            "dim_fund (last period filed in CVM's datasets) against "
            "latest_complete_period(family), cvm_fund_registry.is_active"
        ),
        "grain": "one row per (fund CNPJ, family)",
        "params": {"p_min_silent_months": 3, "p_max_silent_months": 24, "p_family": None},
        "bounds": {
            "p_min_silent_months": "1..120 complete months with no filing",
            "p_max_silent_months": "p_min_silent_months..240",
        },
        "filters": {"p_family": "fi | fidc | fii | fiagro; null = all four (output filter)"},
        "dashboard": None,
        "meaning": (
            "A fund CVM's registry still lists as active whose last periodic "
            "informe in CVM's own dataset (informe diário for FI, the monthly "
            "informe for FIDC / FII / FIAGRO) is N complete months behind the "
            "family's latest complete period — never today, so an unpublished "
            "month is not silence. fnet_last_delivered_at (FII / FIDC) shows a "
            "fund still delivering to FNET. The same row comes from a fund "
            "merged, incorporated or liquidated whose status CVM has not "
            "updated, reporting moved to a class CNPJ other than the fund's "
            "by the resolution-175 adaptation, CVM's dataset lagging the "
            "filing, or a SILO ingest gap (check coverage() first). FIP files "
            "annually and is not screened."
        ),
    },
}


def catalog_payload() -> Dict[str, Any]:
    return {
        "kind": "catalog",
        "version": CATALOG_VERSION,
        "primitive": "panel",
        "agent": AGENT_INSTRUCTIONS,
        "defaults": DEFAULTS,
        "metrics": METRICS,
        "notebook_reducers": NOTEBOOK_REDUCERS,
        "constraints": CONSTRAINTS,
        "limits": LIMITS,
        "applicability": APPLICABILITY,
        "regime_breaks": REGIME_BREAKS,
        "screens": SCREENS,
        "examples": EXAMPLES,
        "id_types": ["ticker", "cnpj", "cd_cvm", "option", "termo"],
        "asset_classes": [
            *B3_CASH_ASSET_CLASSES,
            "fi", "fidc", "fii", "fip", "fiagro", "cia", "derivative",
        ],
        "freq": ["day", "month"],
        # Two surfaces, split so an agent holding only the local serve/
        # adapter never dials a route that host cannot answer:
        #   endpoints  — the /v1/* routes serve/app.py itself serves;
        #   postgrest  — resources that exist ONLY on the Supabase Data API
        #                (views under /rest/v1/, functions under /rest/v1/rpc/),
        #                relative to that deployment's base URL.
        "endpoints": {
            "catalog": "GET /v1/catalog",
            "tools": "GET /v1/tools",
            "panel": "GET /v1/panel",
            "lookup": "GET /v1/lookup?q=",
            "quotes": "GET /v1/quotes/{ticker}",
            "funds": "GET /v1/funds/{cnpj}/nav",
            "coverage": "GET /v1/coverage",
            "metric_coverage": "GET /v1/metric-coverage",
        },
        "postgrest": {
            # The core contract. These were absent from this section, so an
            # agent reading the catalog could not tell that the primitive
            # itself is reachable on the deployed surface.
            "panel": "POST /rest/v1/rpc/panel",
            "lookup": "POST /rest/v1/rpc/lookup",
            "coverage": "POST /rest/v1/rpc/coverage",
            "metric_coverage": "POST /rest/v1/rpc/metric_coverage",
            "search_funds": "POST /rest/v1/rpc/search_funds",
            "fund_profile": "POST /rest/v1/rpc/fund_profile",
            "fund_holdings": "POST /rest/v1/rpc/fund_holdings",
            "fund_nav": "POST /rest/v1/rpc/fund_nav",
            "quote_history": "POST /rest/v1/rpc/quote_history",
            "quote_latest": "POST /rest/v1/rpc/quote_latest",
            "quotes_view": "GET /rest/v1/quotes",
            "funds_view": "GET /rest/v1/funds",
            "equities": "GET /rest/v1/equities",
            "bdrs": "GET /rest/v1/bdrs",
            "units": "GET /rest/v1/units",
            "fund_quotas": "GET /rest/v1/fund_quotas",
            "cash_securities": "GET /rest/v1/cash_securities",
            "auctions": "GET /rest/v1/auctions",
            "option_chain": "POST /rest/v1/rpc/option_chain",
            "option_history": "POST /rest/v1/rpc/option_history",
            "option_exercises": "POST /rest/v1/rpc/option_exercises",
            "termo_history": "POST /rest/v1/rpc/termo_history",
            "financials": "POST /rest/v1/rpc/financials",
            "financial_statement_history": "POST /rest/v1/rpc/financial_statement_history",
            "company_financials": "POST /rest/v1/rpc/company_financials",
            "income_statements": "POST /rest/v1/rpc/income_statements",
            "balance_sheets": "POST /rest/v1/rpc/balance_sheets",
            "cash_flow_statements": "POST /rest/v1/rpc/cash_flow_statements",
            "anbima_classes": "POST /rest/v1/rpc/anbima_classes",
            # Inflation (v30). BACEN's SGS series long, and IBGE's item tree
            # with weights and contributions. No id, no panel arm.
            "inflation": "POST /rest/v1/rpc/inflation",
            "inflation_items": "POST /rest/v1/rpc/inflation_items",
            "fii_property_history": "POST /rest/v1/rpc/fii_property_history",
            "focus_expectations": "POST /rest/v1/rpc/focus_expectations",
            "fund_debentures": "POST /rest/v1/rpc/fund_debentures",
            "fidc_cedentes": "POST /rest/v1/rpc/fidc_cedentes",
            "fidc_sacados": "POST /rest/v1/rpc/fidc_sacados",
            "fidc_portfolio": "POST /rest/v1/rpc/fidc_portfolio",
            # The forensic screens (v31). Signals, not verdicts: every row
            # carries screen + params; `screens` says what each one means.
            "screen_zombie_growth": "POST /rest/v1/rpc/screen_zombie_growth",
            "screen_captive_vehicles": "POST /rest/v1/rpc/screen_captive_vehicles",
            "screen_evergreen_aging": "POST /rest/v1/rpc/screen_evergreen_aging",
            "screen_overdue_securit": "POST /rest/v1/rpc/screen_overdue_securit",
            "screen_dormant_funds": "POST /rest/v1/rpc/screen_dormant_funds",
            "screen_dormant_trend": "POST /rest/v1/rpc/screen_dormant_trend",
            "screen_delinquency_drivers": "POST /rest/v1/rpc/screen_delinquency_drivers",
            # The filing-behaviour screens (v37): restatements, late and
            # silent filers. No dashboard page; same signal-not-verdict rules.
            "screen_restatements": "POST /rest/v1/rpc/screen_restatements",
            "screen_late_filers": "POST /rest/v1/rpc/screen_late_filers",
            "screen_silent_filers": "POST /rest/v1/rpc/screen_silent_filers",
            # FIDC structure (v32): tranches and the aging ladder, 2013-01 on (v58).
            "fidc_tranches": "POST /rest/v1/rpc/fidc_tranches",
            "fidc_aging": "POST /rest/v1/rpc/fidc_aging",
            # The FNET document register (v33): one fund's documents, and
            # restatement events paired by a stated group key.
            "fund_documents": "POST /rest/v1/rpc/fund_documents",
            "fund_restatements": "POST /rest/v1/rpc/fund_restatements",
            # What a restatement changed (v40), field by field.
            "fund_restatement_diff": "POST /rest/v1/rpc/fund_restatement_diff",
            # Held-but-unserved datasets (v38): a company's IPE filings, the
            # non-inflation SGS series and PTAX, all as published.
            "company_events": "POST /rest/v1/rpc/company_events",
            "macro_series": "POST /rest/v1/rpc/macro_series",
            "ptax": "POST /rest/v1/rpc/ptax",
            "future_curve": "POST /rest/v1/rpc/future_curve",
            "future_series": "POST /rest/v1/rpc/future_series",
            "curve": "POST /rest/v1/rpc/curve",
            "curve_history": "POST /rest/v1/rpc/curve_history",
            "research_universe": "POST /rest/v1/rpc/research_universe",
            "index_history": "POST /rest/v1/rpc/index_history",
            "portfolio_resolve": "POST /rest/v1/rpc/portfolio_resolve",
            "portfolio_fees": "POST /rest/v1/rpc/portfolio_fees",
            "portfolio_lookthrough": "POST /rest/v1/rpc/portfolio_lookthrough",
            "portfolio_movement": "POST /rest/v1/rpc/portfolio_movement",
            "portfolio_instruments": "POST /rest/v1/rpc/portfolio_instruments",
            "portfolio_fund_terms": "POST /rest/v1/rpc/portfolio_fund_terms",
            # B3 securities lending and investor flow (v27). VIEWS, not
            # functions: filter them with PostgREST's own syntax
            # (?ticker=eq.PETR4&trade_date=gte.2026-09-01) and page with
            # limit/offset, which works here because they are GET resources.
            # All five are a RATCHET — see the constraint: history begins at
            # first capture and B3 publishes no archive.
            "short_interest": "GET /rest/v1/short_interest",
            "short_interest_by_sector": "GET /rest/v1/short_interest_by_sector",
            "lending_trades": "GET /rest/v1/lending_trades",
            "lending_participants": "GET /rest/v1/lending_participants",
            "investor_flow": "GET /rest/v1/investor_flow",
        },
    }


def tool_specs() -> List[Dict[str, Any]]:
    """OpenAI/AI-SDK style tools. An agent loads these and calls the HTTP API."""
    metric_ids = list(METRICS.keys())
    return [
        {
            "type": "function",
            "function": {
                "name": "silo_catalog",
                "description": "Map of metrics, grains, constraints, and example questions. Call first.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "silo_lookup",
                "description": "Resolve a ticker, ISIN, CNPJ, fund name, or company name to ids. Does not invent matches.",
                "parameters": {
                    "type": "object",
                    "properties": {"q": {"type": "string"}},
                    "required": ["q"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "silo_panel",
                "description": (
                    "Fetch a panel of mixed market and fundamental series via "
                    "GET /v1/panel. Omit reduce — compute corr/rank/OLS in the notebook."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Tickers and/or 14-digit CNPJs",
                        },
                        "metrics": {
                            "type": "array",
                            "items": {"type": "string", "enum": metric_ids},
                            "description": "Subset of catalog metrics",
                        },
                        "freq": {"type": "string", "enum": ["day", "month"]},
                        "from": {"type": "string", "description": "ISO date"},
                        "to": {"type": "string", "description": "ISO date"},
                        "entity_type": {
                            "type": "string",
                            "enum": ["fi", "fidc", "fii", "fip", "fiagro"],
                            "description": "Keep one fund family; a CNPJ can file under two",
                        },
                        "format": {"type": "string", "enum": ["long", "wide"]},
                    },
                    "required": ["ids", "metrics"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "silo_coverage",
                "description": "Latest date per dataset. Use before claiming freshness.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            },
        },
    ]


def _pairs(xs: Sequence[Optional[float]], ys: Sequence[Optional[float]]) -> List[tuple]:
    out = []
    for a, b in zip(xs, ys):
        if a is None or b is None:
            continue
        try:
            fa, fb = float(a), float(b)
        except (TypeError, ValueError):
            continue
        out.append((fa, fb))
    return out


def pearson(xs: Sequence[Optional[float]], ys: Sequence[Optional[float]]) -> Optional[float]:
    pts = _pairs(xs, ys)
    n = len(pts)
    if n < 3:
        return None
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    num = sum((p[0] - mx) * (p[1] - my) for p in pts)
    dx = sum((p[0] - mx) ** 2 for p in pts) ** 0.5
    dy = sum((p[1] - my) ** 2 for p in pts) ** 0.5
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


def reduce_panel(wide: Dict[str, Any], kind: Optional[str]) -> Optional[Dict[str, Any]]:
    """Notebook helper on a wide panel. Never fills nulls. Not an HTTP route."""
    if not kind:
        return None
    columns: List[str] = list(wide.get("columns") or [])
    values: List[List[Any]] = list(wide.get("values") or [])
    dates: List[str] = list(wide.get("dates") or [])
    if kind == "describe":
        stats = []
        for j, col in enumerate(columns):
            col_vals = [row[j] for row in values]
            nums = [float(v) for v in col_vals if v is not None]
            last = next((v for v in reversed(col_vals) if v is not None), None)
            stats.append({
                "column": col,
                "n": len(nums),
                "null_rate": 1 - (len(nums) / len(col_vals) if col_vals else 0),
                "min": min(nums) if nums else None,
                "max": max(nums) if nums else None,
                "last": last,
            })
        return {"kind": "describe", "columns": stats}
    if kind == "corr":
        matrix = []
        for i, ci in enumerate(columns):
            row = []
            for j, cj in enumerate(columns):
                xs = [r[i] for r in values]
                ys = [r[j] for r in values]
                row.append({"a": ci, "b": cj, "r": pearson(xs, ys), "n": len(_pairs(xs, ys))})
            matrix.append(row)
        return {
            "kind": "corr",
            "method": "pearson_pairwise_complete",
            "pairs": matrix,
            "note": "One relation. For OLS, copulas, or lags, take the panel.",
        }
    if kind == "rank":
        if not columns:
            return {"kind": "rank", "by": None, "rows": []}
        first_metric = columns[0].rsplit(".", 1)[-1]
        last = []
        for j, col in enumerate(columns):
            metric = col.rsplit(".", 1)[-1]
            if metric != first_metric:
                continue
            val = next((row[j] for row in reversed(values) if row[j] is not None), None)
            last.append({"column": col, "value": val})
        last.sort(key=lambda x: (x["value"] is None, -(x["value"] or 0)))
        return {"kind": "rank", "by": first_metric, "rows": last}
    if kind == "spread":
        if len(columns) < 2:
            raise ValueError("spread needs at least two wide columns")
        series = []
        for d, row in zip(dates, values):
            a, b = row[0], row[1]
            series.append({
                "date": d,
                "a": columns[0],
                "b": columns[1],
                "spread": None if a is None or b is None else float(a) - float(b),
            })
        return {"kind": "spread", "series": series}
    raise ValueError(f"unknown reduce {kind}; catalog.notebook_reducers lists the built-ins")
