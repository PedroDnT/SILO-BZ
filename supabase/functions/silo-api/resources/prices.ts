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
// source publishes is never dropped from fields=all. A view answer is cut at
// PostgREST's 1,000 rows, so a full page is refused (over_limit), never served.

import { ApiError } from "../errors.ts";
import type { Envelope } from "../envelope.ts";
import { type ParsedRequest, todayUtcMinus3, type Value } from "../params.ts";
import { callView, type CallContext } from "../postgrest.ts";
import { type Plan, RESOURCES_BY_NAME } from "../registry.ts";
import { type Row, runKind, VIEW_PAGE } from "./run.ts";

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

function overLimit(view: string, what: string, total: number | null): ApiError {
  const held = total === null ? `at least ${VIEW_PAGE}` : String(total);
  return new ApiError(
    400,
    "over_limit",
    `prices kind=session: api.${view} holds ${held} rows for ${what}, more than one page (${VIEW_PAGE}). The gateway refuses rather than trim. Narrow with asset_class, board or id.`,
    "asset_class",
    { sqlstate: null, hint: `A view answer is cut at ${VIEW_PAGE} rows (db-max-rows).` },
  );
}

/** YYYY-MM-DD minus n calendar days. */
function daysBefore(date: string, n: number): string {
  const d = new Date(`${date}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() - n);
  return d.toISOString().slice(0, 10);
}

/**
 * kind=session: one GET (callView) on the view asset_class picks, eq on id,
 * board and date. With no date, the newest session in the lookback.
 */
async function readSession(plan: Plan, values: Record<string, Value>, ctx: CallContext): Promise<{ endpoint: string; rows: Row[] }> {
  const by = plan.view_by!;
  const view = by.views[String(values[by.parameter])];
  if (!view) throw new ApiError(500, "internal", `prices: no view for ${by.parameter}=${values[by.parameter]}.`);

  const eq: Record<string, unknown> = {};
  for (const [name, column] of Object.entries(plan.args)) {
    const v = values[name];
    if (v === null || v === undefined || name === "date") continue;
    eq[column] = name === "id" ? String(v).toUpperCase() : v;
  }
  const date = typeof values.date === "string" ? values.date : null;
  const since = daysBefore(todayUtcMinus3(), SESSION_LOOKBACK_DAYS);
  const page = await callView(ctx, view, eq, plan.order, VIEW_PAGE, { trade_date: date ? `eq.${date}` : `gte.${since}` });
  const n = page.rows.length;
  // Every row of the selection arrived: the count says so, or (no count) the page is not full.
  const whole = page.total !== null ? n >= page.total : n < VIEW_PAGE;
  if (date) {
    if (!whole) throw overLimit(view, `session ${date}`, page.total);
    return { endpoint: view, rows: page.rows };
  }
  if (n === 0) {
    throw new ApiError(
      400,
      "bad_request",
      `prices kind=session: api.${view} has no session from ${since} to today that matches. Pass date=YYYY-MM-DD.`,
      "date",
    );
  }
  // Rows come newest first, so the newest session is a block at the top. It
  // is whole when an older row follows it, or when every row arrived.
  const top = page.rows[0].trade_date;
  const rows = page.rows.filter((r) => r.trade_date === top);
  if (rows.length === n && !whole) throw overLimit(view, `the latest session (${top})`, null);
  return { endpoint: view, rows };
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
