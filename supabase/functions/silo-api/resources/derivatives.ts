// silo-api resource `derivatives`: options, termo and futures.
//
// kind chain -> api.option_chain (id = option prefix), history ->
// api.option_history, exercises -> api.option_exercises, termo ->
// api.termo_history, futures -> api.future_series, futures_curve ->
// api.future_curve (id = root, default DI1), di_settlement -> the
// api.di_settlement view (a GET through callView, newest first). Default
// window: 1 year back from `to` (or today, UTC-3). B3 codes are upper case,
// so id is sent upper case.
//
// option_chain and option_exercises CUT at a tier ceiling (LIMIT LEAST(...))
// without refusing. The gateway asks for 1,001 rows, so a cut is visible: a
// count above 1,000, or equal to a known ceiling, cannot be told from a cut.
// chain (one call, served in pages) refuses it (over_limit). exercises walks
// date windows (#1059), so the refusal is marked a row cap and the window is
// halved; a single day still cut is refused. Never a silent trim.

import { ApiError } from "../errors.ts";
import type { Envelope } from "../envelope.ts";
import type { ParsedRequest } from "../params.ts";
import type { CallContext } from "../postgrest.ts";
import { RESOURCES_BY_NAME } from "../registry.ts";
import { type Row, runKind } from "./run.ts";

const DERIVATIVES = RESOURCES_BY_NAME.get("derivatives")!;

/** What one call asks for: one SQL page and one row more, so a cut shows. */
export const ASK = 1001;

/**
 * The functions that cut instead of refusing, and every count at which the
 * answer may be a cut (the SQL's anonymous and signed-in ceilings, and
 * PostgREST's db-max-rows).
 */
export const CLAMPED: Record<string, { ceilings: number[]; narrow: string }> = {
  option_chain: { ceilings: [200, 1000, 2000], narrow: "a longer id prefix, date or expiry_from" },
  option_exercises: { ceilings: [500, 1000, 5000], narrow: "a longer id prefix or from/to" },
};

function cutRefusal(endpoint: string, n: number): ApiError {
  const c = CLAMPED[endpoint];
  const e = new ApiError(
    400,
    "over_limit",
    `derivatives: api.${endpoint} answered ${n} rows, a count the SQL may have cut at (it cuts at a tier ceiling without refusing). ` +
      `The gateway refuses rather than trims. Narrow with ${c.narrow}.`,
    "id",
    { sqlstate: null, hint: `api.${endpoint} cuts at a tier ceiling (${c.ceilings.join(", ")}) without refusing.` },
  );
  e.rowCap = true; // exercises: the date-window walk halves the window and tries again
  return e;
}

export function derivatives(req: ParsedRequest, ctx: CallContext): Promise<Envelope> {
  return runKind(DERIVATIVES, req, ctx, {
    prepare: (_kind, _plan, values) => (typeof values.id === "string" ? { ...values, id: values.id.toUpperCase() } : values),
    args: (plan, _values, args) => (plan.endpoint in CLAMPED ? { ...args, p_limit: ASK } : args),
    check: (plan, _values, rows: Row[]) => {
      const c = CLAMPED[plan.endpoint];
      if (c && (rows.length > ASK - 1 || c.ceilings.includes(rows.length))) throw cutRefusal(plan.endpoint, rows.length);
    },
  });
}
