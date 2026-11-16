// silo-api: what a response is cited by (#1176).
//
// Every data response's meta carries three things a reader can cite:
//
//   meta.source        the canonical request, /v2/<resource>?kind=...&id=...,
//                      built from meta.request (every parameter, defaults
//                      applied), so pasting it replays the same rows.
//   meta.endpoint      the api.* function or view that answered (run.ts).
//   meta.data_through  the newest elapsed period SILO holds for the dataset
//                      the endpoint reads: api.coverage()'s as_of for that
//                      dataset (v2 names it data_through; as_of is a
//                      point-in-time parameter in v2). meta.coverage_dataset
//                      names the coverage row it came from.
//
// The coverage read is cached per gateway for FRESHNESS_TTL_MS, so a call
// costs no extra round trip while the cache is warm, and it runs beside the
// data call, not after it. An endpoint with no coverage row (lookup, panel,
// screens, portfolio, ...) gets data_through null and coverage_dataset null.
// A failed coverage read is never a fill: data_through stays null and
// meta.data_through_error says why; the data rows are served unchanged.

import type { Envelope } from "./envelope.ts";
import type { Value } from "./params.ts";
import { callRpc, type CallContext } from "./postgrest.ts";

/** The caller's HTTP method (portfolio is the one POST). */
export type HttpMethod = "GET" | "POST";

/** Dataset name -> coverage as_of (data_through), from one api.coverage() read. */
export type FreshnessMap = Map<string, string | null>;
/** Reads the freshness map; cached by the default implementation. */
export type Freshness = (ctx: CallContext) => Promise<FreshnessMap>;

/** How long one api.coverage() read is reused. Landed data moves once a day. */
export const FRESHNESS_TTL_MS = 10 * 60_000;
/** How long a failed read is remembered, so a broken coverage does not cost every call a retry. */
export const FRESHNESS_FAIL_MS = 60_000;

/** api.coverage() through PostgREST, anonymously, cached per gateway (one map for every caller). */
export function cachedCoverage(now: () => number = () => Date.now()): Freshness {
  let held: { at: number; ttl: number; value: Promise<FreshnessMap> } | null = null;
  return (ctx) => {
    const t = now();
    if (held && t - held.at < held.ttl) return held.value;
    const value = callRpc({ ...ctx, bearer: null }, "coverage", {}).then((rows) => {
      if (!Array.isArray(rows)) throw new Error("api.coverage did not answer with rows");
      const map: FreshnessMap = new Map();
      for (const r of rows as Record<string, unknown>[]) {
        if (typeof r.dataset === "string") map.set(r.dataset, typeof r.as_of === "string" ? r.as_of : null);
      }
      return map;
    });
    const entry = { at: t, ttl: FRESHNESS_TTL_MS, value };
    held = entry;
    value.catch(() => {
      if (held === entry) entry.ttl = FRESHNESS_FAIL_MS;
    });
    return value;
  };
}

/** The api.* endpoint (no prefix) -> the api.coverage() dataset it reads. */
export const COVERAGE_DATASET: Readonly<Record<string, string>> = {
  // prices
  quotes: "quotes",
  equities: "quotes",
  bdrs: "quotes",
  units: "quotes",
  fund_quotas: "quotes",
  cash_securities: "quotes",
  auctions: "quotes",
  quote_history: "quotes",
  quote_latest: "quotes",
  research_universe: "quotes",
  index_history: "index_history",
  trade_consolidated_history: "trade_consolidated_history",
  // derivatives and curves
  option_chain: "derivatives",
  option_history: "derivatives",
  option_exercises: "derivatives",
  termo_history: "derivatives",
  future_curve: "di_futures",
  future_series: "di_futures",
  future_nth_series: "di_futures",
  di_settlement: "di_futures",
  curve: "reference_curves",
  curve_history: "reference_curves",
  reference_rate: "reference_curves",
  // macro
  macro_series: "macro_series",
  ptax: "ptax",
  ptax_daily: "ptax",
  inflation: "inflation",
  inflation_items: "inflation_items",
  focus_expectations: "focus_expectations",
  // positioning
  short_interest: "short_interest",
  short_interest_by_sector: "short_interest_by_sector",
  lending_trades: "lending_trades",
  lending_participants: "lending_participants",
  investor_flow: "investor_flow",
  // funds and fidc
  funds: "funds",
  search_funds: "funds",
  fund_profile: "funds",
  fund_holdings: "funds",
  fund_debentures: "funds",
  fund_nav: "fund_nav",
  fii_property_history: "fii_property_history",
  fidc_portfolio: "fidc_sectors",
  fidc_tranches: "fidc_tranches",
  fidc_aging: "fidc_aging",
  fidc_cedentes: "fidc_cedentes",
  fidc_sacados: "fidc_sacados",
  // filings and events
  fund_documents: "fnet_documents",
  fund_restatements: "fnet_documents",
  fund_restatement_diff: "fnet_documents",
  company_events: "company_events",
  financials: "financials",
  company_financials: "financials",
  income_statements: "financials",
  balance_sheets: "financials",
  cash_flow_statements: "financials",
  financial_statement_history: "financials",
};

const DOLLAR_ROOT = /^(DOL|WDO)/i;

/**
 * The coverage dataset an answer read: by endpoint, except that a DOL or WDO
 * future is dollar_futures, not di_futures. Null when coverage has no row for it.
 */
export function datasetFor(endpoint: string | undefined, request: Record<string, Value>): string | null {
  if (!endpoint) return null;
  const name = endpoint.replace(/^api\./, "");
  const dataset = COVERAGE_DATASET[name] ?? null;
  if (dataset === "di_futures" && name !== "di_settlement") {
    const id = request.id;
    if (typeof id === "string" && DOLLAR_ROOT.test(id)) return "dollar_futures";
  }
  return dataset;
}

/** The canonical request: /v2/<resource>?<every applied parameter>, lists comma-separated. POST says so. */
export function canonicalSource(resource: string, request: Record<string, Value>, verb: HttpMethod = "GET"): string {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(request)) {
    if (v === null || v === undefined) continue;
    qs.set(k, Array.isArray(v) ? v.join(",") : String(v));
  }
  const q = qs.toString();
  const path = `/v2/${resource}${q ? `?${q}` : ""}`;
  return verb === "POST" ? `POST ${path} (with the JSON body in meta.body)` : path;
}

/** Sets meta.source, meta.coverage_dataset and meta.data_through on a data envelope. */
export function applyProvenance(
  env: Envelope,
  verb: HttpMethod,
  fresh: { map: FreshnessMap } | { error: string },
): Envelope {
  const meta = env.meta;
  meta.source = canonicalSource(meta.resource, meta.request ?? {}, verb);
  const dataset = datasetFor(meta.endpoint, meta.request ?? {});
  meta.coverage_dataset = dataset;
  if (dataset === null) {
    meta.data_through = null;
  } else if ("map" in fresh) {
    meta.data_through = fresh.map.get(dataset) ?? null;
  } else {
    meta.data_through = null;
    meta.data_through_error = `api.coverage could not be read, so data_through is unknown: ${fresh.error}`;
  }
  return env;
}
