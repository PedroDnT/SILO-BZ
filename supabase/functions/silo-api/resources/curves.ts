// silo-api resource `curves`: what does the rate curve look like?
//
// kind snapshot -> api.curve (one curve on one session), history ->
// api.curve_history (one FIXED vertex through time; tenor is B3's nominal
// tenor in calendar days, default 360, the one-year vertex), vertices -> the
// api.reference_rate view (GETs through callView: one curve on one session,
// the newest in the 14 days to today unless date is given, paged). Default
// window: 1 year back from `to` (or today, UTC-3). Nothing is interpolated.

import { ApiError } from "../errors.ts";
import type { Envelope } from "../envelope.ts";
import { type ParsedRequest, todayUtcMinus3, type Value } from "../params.ts";
import { callView, type CallContext } from "../postgrest.ts";
import { type Plan, RESOURCES_BY_NAME } from "../registry.ts";
import { runKind, type ViewQuery } from "./run.ts";

const CURVES = RESOURCES_BY_NAME.get("curves")!;

/** How far back the default session of kind vertices is looked for. */
export const VERTICES_LOOKBACK_DAYS = 14;

/** YYYY-MM-DD minus n calendar days. */
function minusDays(date: string, n: number): string {
  const d = new Date(`${date}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() - n);
  return d.toISOString().slice(0, 10);
}

/**
 * kind=vertices: eq on curve, and one session: the date asked, or the newest
 * in the lookback (one GET of one row), pinned in the cursor. The session is
 * then paged with order + limit + offset (run.ts, #1059).
 */
async function readVertices(plan: Plan, values: Record<string, Value>, ctx: CallContext, pin: string | null): Promise<ViewQuery> {
  const eq = { curve: values.curve };
  let date = typeof values.date === "string" ? values.date : pin;
  if (date === null) {
    const since = minusDays(todayUtcMinus3(), VERTICES_LOOKBACK_DAYS);
    const newest = await callView(ctx, plan.endpoint, eq, plan.order, 1, { trade_date: `gte.${since}` });
    const top = newest.rows[0]?.trade_date;
    if (typeof top !== "string") {
      throw new ApiError(
        400,
        "bad_request",
        `curves kind=vertices: api.reference_rate has no ${values.curve} session from ${since} to today. Pass date=YYYY-MM-DD.`,
        "date",
      );
    }
    date = top;
  }
  return { view: plan.endpoint, eq, filters: { trade_date: `eq.${date}` }, pin: typeof values.date === "string" ? null : date };
}

export function curves(req: ParsedRequest, ctx: CallContext): Promise<Envelope> {
  return runKind(CURVES, req, ctx, { view: readVertices });
}
