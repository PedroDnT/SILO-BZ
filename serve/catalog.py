"""Machine-readable map of the Silo read API for agents.

The primitive is a panel: (id, date, metric, value). An agent should:
  1. GET /v1/catalog (once, cache it)
  2. GET /v1/lookup to resolve ids
  3. GET /v1/panel with those ids and a subset of catalog metrics
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
    "catalog_payload",
    "tool_specs",
]

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
# v24: the panel REFUSES instead of trimming. More than 1000 rows now raises
# 22023 unless the caller pages with p_after ('' = first page, then the last
# row's 'date|id|metric|asset_class'); the unreachable 100001 sentinel leaves
# the contract (limits.page replaces limits.sql_sentinel.panel). The grain is
# stated as (id, asset_class, date, metric) and p_entity_type narrows the fund
# arms to one family. Universe mode (p_ids empty + p_entity_type, optional
# p_min_nav / p_min_months) walks a whole family for signed-in callers.
CATALOG_VERSION = 26

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
            "Unadjusted close. Cash tickers: the ticker's latest BDI board by "
            "default, classified from published TPMERC/ESPECI. Option/termo "
            "codnegs: that derivative segment's session close. "
            "Month = last session."
        ),
    },
    "volume": {
        "id_type": ["ticker", "option", "termo"],
        "asset_class": [*B3_CASH_ASSET_CLASSES, "derivative"],
        "grain": ["day", "month"],
        "source": "b3_cotahist",
        "meaning": (
            "Session traded volume (BRL). Cash: the ticker's latest BDI board "
            "by default; option/termo: that derivative segment. "
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
            "p_t/p_{t-1}-1 from stored unadjusted closes. Corporate actions "
            "appear as spurious jumps (a 2:1 split reports roughly -50%). "
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
        # The one `since` this catalog states as a constant, because it is a
        # published regime boundary (see `regime_breaks`) and a lockstep test
        # pins it. Every other span is MEASURED — call api.metric_coverage()
        # rather than trusting a date written here once.
        "since": {"fidc": "2025-01-31"},
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
    "FIDC DELINQUENCY STARTS IN 2025-01. CVM's pre-2025 monthly FIDC file (tab II/III) carried no delinquency field, so `delinquency` is null on every fidc row through 2024-12-31 — not zero, not clean books, not a missing month. From 2025-01-31 the tab IV/VI format is ingested and delinquency is filed on every row. Never chain-link, difference or average a FIDC delinquency series across 2024-12 → 2025-01; the series begins there. Machine-readable in `regime_breaks`, and on the funds_fidc coverage row's `notes`.",
    "A FUND'S DEBENTURE HOLDINGS ARE A DIFFERENT SHAPE FROM ITS EQUITY HOLDINGS. api.fund_debentures (CDA block 6) is one row per (fund, month, issuer, maturity, rate structure, application type), as filed and never summed — two series of one issuer maturing the same day at different coupons are different securities. The issuer is its own filed CPF/CNPJ (issuer_id); p_issuer also takes a listed company's ticker or CVM code, resolved only through CVM's published FCA map, and issuer_tickers carries the issuer's active listed codes back (NULL when not listed — most debenture issuers are not). Nothing is matched by name.",
    "ANBIMA CLASS ROWS ARE INDUSTRY AGGREGATES, NOT FUNDS. api.anbima_classes serves the Boletim de Fundos de Investimento as published — R$ milhões (unit brl_mm) and percentage points (unit pct) — per class, ANBIMA type or industry total (`level`; class aggregates by default). No fund in this warehouse is mapped to an ANBIMA class: CVM's `classe` is CVM's taxonomy, so never join a fund to a class by name, and there is no panel arm because these rows carry no id. An unknown category, metric or level raises 22023 listing what exists rather than returning an empty array.",
    "LISTED-COMPANY FINANCIALS ARE FILED, NOT DERIVED. api.financials returns one row per account line exactly as the company filed it; nothing is summed, annualised or restated. Read period_months before comparing two rows: an ITR publishes the SAME account twice under one reference date, once for the three months and once year-to-date, and they are distinguished only by the period span. Adding a 3-month row to a 6-month row double-counts the quarter.",
    "FINANCIALS DEFAULT TO CONSOLIDATED (scope=con) AND TO THE PERIOD THE DOCUMENT IS FOR (ordem_exerc ULTIMO). The prior-year comparative printed beside it is never returned. When a company re-files, only the newest version of each statement is served and `version` carries it; in company_financials a balance sheet from a different version than the income statement reads NULL rather than being paired across filings.",
    "A TICKER RESOLVES TO A COMPANY ONLY THROUGH CVM'S PUBLISHED FCA MAP, active listings only — the CNPJ and the trading code arrive on the same filed row. financials('PETR4'), financials('33000167000101') and financials('9512') are the same company. A delisted code resolves to nothing rather than to a guess, and no company↔ticker edge is ever inferred from a name.",
    "PANEL GRAIN IS (id, asset_class, date, metric), NOT (id, date, metric). A CNPJ can file under two fund families in one month (385 do, fi + fidc), and the panel returns one row per family for it — pivoting on (id, date, metric) then either raises on the duplicate or silently averages two vehicles. Pass p_entity_type (fi|fidc|fii|fip|fiagro) to keep one family, or keep asset_class in your pivot key.",
    "Never invent a price, NAV, or identifier match.",
    "Missing observations stay null; do not ffill or interpolate.",
    "freq=day is quotes only. Mix equity with fund fundamentals on freq=month.",
    "close_return across a missing month is null, not a multi-month return.",
    "close_return is unadjusted: a 2:1 split reports roughly -50%. It is not a total return.",
    "close is the price as published, which for a paper quoted per lot refers "
    "to 1000 shares; close_unit divides it by the published quotation_factor so "
    "levels are comparable. Neither is corporate-action adjusted — no split, "
    "grouping or bonus adjustment exists yet, and `adjusted` is FALSE on every row.",
    "Daily close_return is null when the previous session is more than 7 "
    "calendar days back (halts, listing gaps), and null across a quotation-"
    "factor change — a fatcot flip rescales the quote with no market move "
    "behind it.",
    "Default windows are honest: with no explicit `to`, fund metrics end at "
    "each family's latest COMPLETE period (coverage() reports it as "
    "complete_through) — a partially-filed trailing month is not served. An "
    "explicit `to` serves the window verbatim, partial months included.",
    "Company↔ticker IS joined — via CVM's published FCA valores-mobiliários map only (lookup returns a tickers array on company rows). Nothing is matched by name; a company with no active published listing has tickers null.",
    "Analysis (corr, OLS, copulas, event studies) is a reduction of a panel. Fetch the panel first.",
    "Row caps — getting this wrong means silently analysing a TRUNCATED "
    "series, the exact fabrication this API exists to prevent. THE PAGE IS "
    "1000 ROWS, imposed by PostgREST (db-max-rows) on every response. EVERY "
    "set-returning function now REFUSES rather than trims: a window that "
    "would produce more than 1000 rows raises SQLSTATE 22023 naming the "
    "function, so a short result can no longer look complete. That is all "
    "eight — panel, quote_history, fund_nav, option_history, termo_history, "
    "financials, company_financials, anbima_classes (`limits.page.all`). "
    "THREE OF THEM PAGE with p_after: panel, quote_history and fund_nav. Send "
    "p_after='' for the first page, then the key from the last row — for the "
    "panel 'date|id|metric|asset_class', for quote_history and fund_nav just "
    "that row's date as 'YYYY-MM-DD'; every page is exactly 1000 rows until "
    "the last, which is shorter. fund_nav ALSO REQUIRES p_entity_type when "
    "paging, because its cursor is a bare period and one CNPJ can file under "
    "two families in the same month. The other five do not page: narrow "
    "p_from/p_to instead. The old sentinels (5001 on the series functions, "
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

EXAMPLES = [
    {
        "ask": "How does PETR4 relate to delinquency in this FIDC?",
        "call": (
            "GET /v1/panel?ids=PETR4,<cnpj>"
            "&metrics=close_return,delinquency&freq=month&format=wide"
        ),
        "then": "Pairwise-complete correlation in the notebook. Do not ffill.",
    },
    {
        "ask": "Rank these funds by latest NAV",
        "call": "GET /v1/panel?ids=<cnpj>,<cnpj>&metrics=nav&freq=month&format=wide",
        "then": "Take the last non-null NAV per id from the wide matrix.",
    },
    {
        "ask": "Did inflows and quota move together for this FI?",
        "call": "GET /v1/panel?ids=<cnpj>&metrics=inflows,quota&freq=month&format=wide",
        "then": "Correlate the two columns; nulls stay null.",
    },
    {
        "ask": "Spread of two equity closes at month end",
        "call": "GET /v1/panel?ids=PETR4,VALE3&metrics=close&freq=month&format=wide",
        "then": "Subtract aligned columns; a missing month is null, not interpolated.",
    },
    {
        "ask": "Which of these FIDCs is most exposed to one debtor?",
        "call": (
            "GET /v1/panel?ids=<cnpj>,<cnpj>,<cnpj>"
            "&metrics=sacado_top1,receivables&freq=month&format=wide"
        ),
        "then": "Divide sacado_top1 by receivables per row; the debtor is anonymized, so this is a ratio, not a name.",
    },
    {
        "ask": "Just give me the panel; I will run a factor model",
        "call": (
            "GET /v1/panel?ids=PETR4,VALE3,<cnpj>"
            "&metrics=close_return,nav&freq=month&format=wide"
        ),
        "then": "Model in the notebook from the matrix.",
    },
]

AGENT_INSTRUCTIONS = (
    "You are querying Silo, a Brazilian public-markets warehouse (CVM funds, "
    "B3 COTAHIST cash quotes, options and termo). Call catalog once and cache "
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
    "returns `close` for tickers and `nav` for CNPJs, and that is the call to "
    "make unless you actually need another measure — name metrics explicitly "
    "only when you will use them. The wide endpoints are the exception and "
    "behave the other way round: quote_latest, quote_history and the views "
    "return their full OHLCV/identity row every time, so trim them with "
    "PostgREST `?select=` (e.g. `?select=ticker,trade_date,close`) rather than "
    "pulling 22 columns to read one. See `defaults`."
)

# What a caller gets when it asks for nothing. Machine-readable because an
# agent that has to infer the default from prose will instead request every
# metric it can see — which is how a price lookup turns into seven columns of
# fund accounting it never reads.
DEFAULTS = {
    "principle": "price by default; every other measure is opt-in",
    "panel": {
        "metrics": ["close", "nav"],
        "means": "close for ticker ids, nav for cnpj ids; a metric absent for an id type simply yields no rows",
        "grain": "(id, asset_class, date, metric) — a CNPJ filing under two families yields one row per family; p_entity_type narrows to one",
        "to_widen": "pass p_metrics explicitly, e.g. p_metrics=['close','volume']",
    },
    "wide_endpoints": {
        "which": ["quote_latest", "quote_history", "fund_nav", "api.quotes and the typed views"],
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
            "termo_history", "financials", "company_financials",
            "anbima_classes",
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
                "company_financials", "anbima_classes",
            ],
        },
        "over_cap": (
            "SQLSTATE 22023 naming the function — nothing is trimmed to fit; "
            "the message says to page or narrow"
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
            "fund_holdings_rows": 500,
            "fund_debentures_rows": 500,
            "fidc_cedentes_rows": 500,
            "fidc_sacados_rows": 500,
            "fidc_portfolio_rows": 500,
            "statement_timeout_seconds": 3,
        },
        "authenticated": {
            "panel_ids": 50,
            "panel_universe": True,
            "search_funds_rows": 200,
            "option_chain_rows": 2000,
            "option_exercises_rows": 5000,
            "fund_holdings_rows": 5000,
            "fund_debentures_rows": 5000,
            "fidc_cedentes_rows": 5000,
            "fidc_sacados_rows": 5000,
            "fidc_portfolio_rows": 5000,
            "statement_timeout_seconds": 8,
        },
        "exceeding_an_id_ceiling": (
            "SQLSTATE 22023 naming the limit — a panel is never silently "
            "trimmed to fit"
        ),
        "how_to_sign_in": (
            "GitHub at https://silo-bz.vercel.app/signin.html; send "
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
        "boundary": "2025-01-31",
        "before": (
            "CVM's monthly FIDC file (tab II/III, ingested for 2019-01..2024-12) "
            "carries no delinquency field: delinquency is null on every fidc row "
            "through 2024-12-31 — not zero, not clean books, not a missing month"
        ),
        "after": (
            "from 2025-01-31 the inf_mensal tab IV/VI format is ingested; "
            "delinquency is tab VI's total, filed on every row (a fund with no "
            "delinquent receivables files 0)"
        ),
        "never": (
            "chain-link, difference or average delinquency across 2024-12 → "
            "2025-01, or read a pre-2025 null as zero; a FIDC delinquency series "
            "starts at 2025-01"
        ),
    },
]


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
            "company_financials": "POST /rest/v1/rpc/company_financials",
            "anbima_classes": "POST /rest/v1/rpc/anbima_classes",
            "fund_debentures": "POST /rest/v1/rpc/fund_debentures",
            "fidc_cedentes": "POST /rest/v1/rpc/fidc_cedentes",
            "fidc_sacados": "POST /rest/v1/rpc/fidc_sacados",
            "fidc_portfolio": "POST /rest/v1/rpc/fidc_portfolio",
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
