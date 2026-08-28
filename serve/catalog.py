"""Machine-readable map of the Silo read API for agents.

The primitive is a panel: (id, date, metric, value). An agent should:
  1. GET /v1/catalog (once, cache it)
  2. GET /v1/lookup or /v1/universe to resolve ids
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
    "METRICS",
    "catalog_payload",
    "tool_specs",
]

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
# and the postgrest section carries the core contract (panel/lookup/universe/
# coverage/funds/quotes), not just the typed-cash extras.
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
CATALOG_VERSION = 14

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
    },
    "quota": {
        "id_type": ["cnpj"],
        "asset_class": ["fi"],
        "grain": ["month"],
        "source": "cvm",
        "meaning": "FI unit quota. Comparable subclass only.",
    },
    "delinquency": {
        "id_type": ["cnpj"],
        "asset_class": ["fidc", "fiagro"],
        "grain": ["month"],
        "source": "cvm",
        "meaning": "Delinquent portfolio value (not a rate unless you divide by nav).",
    },
    "yield": {
        "id_type": ["cnpj"],
        "asset_class": ["fii"],
        "grain": ["month"],
        "source": "cvm",
        "meaning": "Monthly yield % as published (FII complemento).",
    },
    "inflows": {
        "id_type": ["cnpj"],
        "asset_class": ["fi"],
        "grain": ["month"],
        "source": "cvm",
        "meaning": "Gross monthly subscriptions.",
    },
    "redemptions": {
        "id_type": ["cnpj"],
        "asset_class": ["fi"],
        "grain": ["month"],
        "source": "cvm",
        "meaning": "Gross monthly redemptions.",
    },
    "quotaholders": {
        "id_type": ["cnpj"],
        "asset_class": ["fi", "fidc", "fii", "fip", "fiagro"],
        "grain": ["month"],
        "source": "cvm",
        "meaning": "Number of unit-holders.",
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
    "Row caps — getting this wrong means silently analysing a TRUNCATED panel, "
    "the exact fabrication this API exists to prevent. THE BINDING CAP IS 1000 "
    "ROWS, imposed by PostgREST (db-max-rows) on every response. It is NOT the "
    "SQL cap+1 sentinel (panel 100001, series 5001): that sentinel is "
    "unreachable on the deployed surface and must not be used to detect "
    "truncation. Measured 2026-08-28 against production: panel for one ticker "
    "from 2019 returns exactly 1000 rows spanning 2019-01-02..2023-01-09 with a "
    "200, and the OLDEST rows are the ones kept — so a truncated series looks "
    "like a complete series that simply ends three years ago. "
    "DETECT IT WITH THE Content-Range RESPONSE HEADER, which is the only signal "
    "there is: `0-999/*` means truncated, and sending `Prefer: count=exact` "
    "turns it into `0-999/1906` so you also learn the true total. A range whose "
    "end is below 999 is complete. "
    "RANGE PAGING DOES NOT WORK ON RPC: sending `Range: 1000-1999` to "
    "/rest/v1/rpc/panel returns the SAME first page again (verified), so a "
    "panel cannot be paged — narrow p_from/p_to, ids or metrics until "
    "Content-Range comes back under 1000. GET views do page with Range "
    "normally. The local /v1 Flask adapter is a different surface with its own "
    "cap+1 400 behaviour; do not carry its rules over.",
    "An unrecognised metric name is IGNORED, not rejected: the panel comes "
    "back smaller and perfectly plausible. Take metric names from this "
    "catalog's `metrics` map, never from memory.",
    "universe is capped at 500 rows, alphabetical, and does not paginate — it "
    "is a sampler, not a census. To enumerate a family, page the funds view "
    "(GET /rest/v1/funds?entity_type=eq.fidc with Prefer: count=exact) and "
    "batch the resulting ids into panel calls.",
    "Option chains require a codneg prefix of at least 3 characters "
    "(api.option_chain); an unfiltered whole-market chain is refused.",
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
    "Option/termo codnegs resolve via universe(asset_class=option|termo) or "
    "option_chain, not lookup — option series have no names to resolve.",
    "Each cash instrument type has its own endpoint (equities, bdrs, units, "
    "fund_quotas, cash_securities) — the same rows as quotes, split by the type "
    "derived from published TPMERC/ESPECI. Their grain adds `lot` "
    "(standard = tpmerc 010, odd = 020/021); filter lot=eq.standard for round "
    "lots. quotes itself stays standard-lot only.",
    "Price series stay unified: a codneg has exactly one instrument type, so "
    "quote_history works for any cash ticker without knowing its type first.",
    "universe(asset_class=option|termo) lists the codnegs that printed on that "
    "segment's most recent session — currently-listed series, not every series "
    "ever listed. Expired series stay queryable by codneg in option_history.",
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
    "it. Resolve names with lookup/universe, then fetch a panel. The primitive "
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
    "row-cap constraint carefully, and READ THE Content-Range RESPONSE HEADER "
    "ON EVERY CALL: PostgREST truncates every response at 1000 rows and keeps "
    "the OLDEST ones, so a cut-short series is indistinguishable from a "
    "complete one by its contents alone — `0-999/*` is the only thing that "
    "tells you. "
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
        "to_widen": "pass p_metrics explicitly, e.g. p_metrics=['close','volume']",
    },
    "wide_endpoints": {
        "which": ["quote_latest", "quote_history", "fund_nav", "api.quotes and the typed views"],
        "behaviour": "fixed full row (OHLCV + identity); the column list cannot vary by argument",
        "to_narrow": "PostgREST ?select=, e.g. /rest/v1/rpc/quote_latest?select=ticker,trade_date,close",
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
            "universe": "GET /v1/universe?asset_class=",
            "quotes": "GET /v1/quotes/{ticker}",
            "funds": "GET /v1/funds/{cnpj}/nav",
            "coverage": "GET /v1/coverage",
        },
        "postgrest": {
            # The core contract. These were absent from this section, so an
            # agent reading the catalog could not tell that the primitive
            # itself is reachable on the deployed surface.
            "panel": "POST /rest/v1/rpc/panel",
            "lookup": "POST /rest/v1/rpc/lookup",
            "universe": "POST /rest/v1/rpc/universe",
            "coverage": "POST /rest/v1/rpc/coverage",
            "search_funds": "POST /rest/v1/rpc/search_funds",
            "fund_profile": "POST /rest/v1/rpc/fund_profile",
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
                "name": "silo_universe",
                "description": (
                    "List identifiers by asset_class: equity, unit, bdr, "
                    "fund_quota, cash_security, fi, fidc, fii, fip, fiagro, "
                    "option, termo."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "asset_class": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 500},
                    },
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
