// silo-api resource `prices`: what did it trade at?
//
// kind history -> api.quote_history (adjust=split selects close_adj, adjust=none
// the raw close; with no id, the research universe), latest -> api.quote_latest,
// session -> one GET on a price view (asset_class picks quotes, equities, bdrs,
// units, fund_quotas, cash_securities or auctions), index -> api.index_history,
// forward -> api.trade_consolidated_history. freq=month is a selection of the
// last session of each month from the daily rows (params.ts), never a fill.
//
// Every price row carries `adjusted` (true only for close_adj); a column the
// source publishes is never dropped from fields=all. A session is paged with
// order + limit + offset and an exact count (#1059): never cut, never refused
// for its size.

import { ApiError } from "../errors.ts";
import type { Envelope } from "../envelope.ts";
import { type ParsedRequest, todayUtcMinus3, type Value } from "../params.ts";
import { callView, type CallContext } from "../postgrest.ts";
import { type Plan, RESOURCES_BY_NAME } from "../registry.ts";
import { type Row, runKind, type ViewQuery } from "./run.ts";

const PRICES = RESOURCES_BY_NAME.get("prices")!;

/**
 * Every field api.quote_history can return besides ticker and trade_date
 * (which it always returns), in the order of api.quote_history_fields().
 * tests/test_api_v2_registry.py pins this list to the SQL.
 */
export const HISTORY_FIELDS: string[] = [
  "close_adj", "close", "open", "high", "low", "average", "bid", "ask", "close_unit",
  "trades", "quantity", "volume", "quotation_factor", "board", "isin", "short_name",
  "spec", "currency", "asset_class", "source", "coverage_start", "coverage_end",
  "prior_no_trade_sessions", "events_proven_at", "data_revision", "close_total_return",
  "close_total_return_null_reason", "market", "term_days", "contract_price",
  "contract_expiry", "contract_correction", "contract_points", "contract_points_raw",
  "distribution_number", "fetched_at",
];

/** The adjusted fields: never served with adjust=none. */
const ADJUSTED_FIELDS = ["close_adj", "close_total_return", "close_total_return_null_reason"];

/** fields=core for latest and session: kept in this order where the row has them. */
export const QUOTE_CORE = [
  "ticker", "trade_date", "board", "lot", "isin", "asset_class", "fund_type",
  "open", "high", "low", "close", "volume", "trades", "adjusted",
];

/** How far back the default session (the latest one) is looked for. */
export const SESSION_LOOKBACK_DAYS = 14;

function historyFields(values: Record<string, Value>): string[] {
  const split = values.adjust === "split";
  if (values.fields === "all") return split ? HISTORY_FIELDS : HISTORY_FIELDS.filter((f) => !ADJUSTED_FIELDS.includes(f));
  return [split ? "close_adj" : "close", "isin"];
}

function project(rows: Row[], keep: string[]): Row[] {
  return rows.map((r) => Object.fromEntries(keep.filter((k) => k in r).map((k) => [k, r[k]])));
}

/** A raw price row says so; a row that already carries `adjusted` keeps it. */
function raw(rows: Row[]): Row[] {
  return rows.map((r) => ("adjusted" in r ? r : { ...r, adjusted: false }));
}

/** YYYY-MM-DD minus n calendar days. */
function daysBefore(date: string, n: number): string {
  const d = new Date(`${date}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() - n);
  return d.toISOString().slice(0, 10);
}

/**
 * kind=session: the view asset_class picks, eq on id and board, and one
 * session: the date asked, or the newest session in the lookback, resolved by
 * one GET of one row (callView) and pinned in the cursor so every page reads
 * the same session. The session is then paged with order + limit + offset
 * (run.ts, #1059), so a session of any size is served whole, page by page.
 */
async function readSession(plan: Plan, values: Record<string, Value>, ctx: CallContext, pin: string | null): Promise<ViewQuery> {
  const by = plan.view_by!;
  const view = by.views[String(values[by.parameter])];
  if (!view) throw new ApiError(500, "internal", `prices: no view for ${by.parameter}=${values[by.parameter]}.`);

  const eq: Record<string, unknown> = {};
  for (const [name, column] of Object.entries(plan.args)) {
    const v = values[name];
    if (v === null || v === undefined || name === "date") continue;
    eq[column] = name === "id" ? String(v).toUpperCase() : v;
  }
  let date = typeof values.date === "string" ? values.date : pin;
  if (date === null) {
    const since = daysBefore(todayUtcMinus3(), SESSION_LOOKBACK_DAYS);
    const newest = await callView(ctx, view, eq, plan.order, 1, { trade_date: `gte.${since}` });
    const top = newest.rows[0]?.trade_date;
    if (typeof top !== "string") {
      throw new ApiError(
        400,
        "bad_request",
        `prices kind=session: api.${view} has no session from ${since} to today that matches. Pass date=YYYY-MM-DD.`,
        "date",
      );
    }
    date = top;
  }
  return { view, eq, filters: { trade_date: `eq.${date}` }, pin: typeof values.date === "string" ? null : date };
}

export function prices(req: ParsedRequest, ctx: CallContext): Promise<Envelope> {
  return runKind(PRICES, req, ctx, {
    args: (plan, values, args) => (plan.endpoint === "quote_history" ? { ...args, p_fields: historyFields(values) } : args),
    view: readSession,
    rows: (plan, values, rows) => {
      if (plan.endpoint === "research_universe") return rows;
      if (plan.endpoint === "quote_history") return rows.map((r) => ({ ...r, adjusted: values.adjust === "split" }));
      const out = raw(rows);
      if (plan.endpoint === "quote_latest" || plan.view) return values.fields === "all" ? out : project(out, QUOTE_CORE);
      return out;
    },
  });
}
