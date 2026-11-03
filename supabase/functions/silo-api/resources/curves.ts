// silo-api resource `curves`: what does the rate curve look like?
//
// kind snapshot -> api.curve (one curve on one session), history ->
// api.curve_history (one FIXED vertex through time; tenor is B3's nominal
// tenor in calendar days, default 360, the one-year vertex), vertices -> the
// api.reference_rate view (one GET through callView: one curve on one
// session, the newest in the 14 days to today unless date is given). Default
// window: 1 year back from `to` (or today, UTC-3). Nothing is interpolated.

import { ApiError } from "../errors.ts";
import type { Envelope } from "../envelope.ts";
import { type ParsedRequest, todayUtcMinus3, type Value } from "../params.ts";
import { callView, type CallContext } from "../postgrest.ts";
import { type Plan, RESOURCES_BY_NAME } from "../registry.ts";
import { type Row, runKind, VIEW_PAGE } from "./run.ts";

const CURVES = RESOURCES_BY_NAME.get("curves")!;

/** How far back the default session of kind vertices is looked for. */
export const VERTICES_LOOKBACK_DAYS = 14;

/** YYYY-MM-DD minus n calendar days. */
function minusDays(date: string, n: number): string {
  const d = new Date(`${date}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() - n);
  return d.toISOString().slice(0, 10);
}

function overLimit(what: string, total: number | null): ApiError {
  const held = total === null ? `at least ${VIEW_PAGE}` : String(total);
  return new ApiError(
    400,
    "over_limit",
    `curves kind=vertices: api.reference_rate holds ${held} rows for ${what}, more than one page (${VIEW_PAGE}). The gateway refuses rather than trims.`,
    "date",
    { sqlstate: null, hint: `A view answer is cut at ${VIEW_PAGE} rows (db-max-rows); kind=snapshot (api.curve) refuses instead.` },
  );
}

/** kind=vertices: eq on curve, and on date when given; with none, the newest session in the lookback. */
async function readVertices(plan: Plan, values: Record<string, Value>, ctx: CallContext): Promise<{ endpoint: string; rows: Row[] }> {
  const date = typeof values.date === "string" ? values.date : null;
  const since = minusDays(todayUtcMinus3(), VERTICES_LOOKBACK_DAYS);
  const page = await callView(ctx, plan.endpoint, { curve: values.curve }, plan.order, VIEW_PAGE, {
    trade_date: date ? `eq.${date}` : `gte.${since}`,
  });
  const n = page.rows.length;
  const whole = page.total !== null ? n >= page.total : n < VIEW_PAGE;
  if (date) {
    if (!whole) throw overLimit(`session ${date}`, page.total);
    return { endpoint: plan.endpoint, rows: page.rows };
  }
  if (n === 0) {
    throw new ApiError(
      400,
      "bad_request",
      `curves kind=vertices: api.reference_rate has no ${values.curve} session from ${since} to today. Pass date=YYYY-MM-DD.`,
      "date",
    );
  }
  // Newest first: the newest session is the block at the top, whole when an older row follows it or every row arrived.
  const top = page.rows[0].trade_date;
  const rows = page.rows.filter((r) => r.trade_date === top);
  if (rows.length === n && !whole) throw overLimit(`the latest session (${top})`, null);
  return { endpoint: plan.endpoint, rows };
}

export function curves(req: ParsedRequest, ctx: CallContext): Promise<Envelope> {
  return runKind(CURVES, req, ctx, { view: readVertices });
}
