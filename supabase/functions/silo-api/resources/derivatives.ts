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
// without refusing. The gateway asks for one row more than it serves, so a
// cut is visible: more rows than wanted is over_limit unless the caller sent
// limit (then the first N, with meta.truncated), and a count equal to a known
// ceiling cannot be told from a cut and is refused too. Never a silent trim.

import { ApiError } from "../errors.ts";
import type { Envelope } from "../envelope.ts";
import type { ParsedRequest, Value } from "../params.ts";
import type { CallContext } from "../postgrest.ts";
import { RESOURCES_BY_NAME } from "../registry.ts";
import { type Row, runKind } from "./run.ts";

const DERIVATIVES = RESOURCES_BY_NAME.get("derivatives")!;

/**
 * The functions that cut instead of refusing: the rows wanted with no limit,
 * and every count at which the answer may be a cut (the SQL's anonymous and
 * signed-in ceilings, and PostgREST's db-max-rows).
 */
export const CLAMPED: Record<string, { want: number; ceilings: number[]; narrow: string }> = {
  option_chain: { want: 100, ceilings: [200, 1000, 2000], narrow: "a longer id prefix, date or expiry_from" },
  option_exercises: { want: 1000, ceilings: [500, 1000, 5000], narrow: "a longer id prefix or from/to" },
};

function wanted(endpoint: string, values: Record<string, Value>): number {
  return typeof values.limit === "number" ? values.limit : CLAMPED[endpoint].want;
}

function cutRefusal(endpoint: string, values: Record<string, Value>, n: number, why: string): ApiError {
  const c = CLAMPED[endpoint];
  const asked = typeof values.limit === "number";
  return new ApiError(
    400,
    "over_limit",
    `derivatives: api.${endpoint} ${why} (${n} rows). The gateway refuses rather than trims. ` +
      `Narrow with ${c.narrow}${asked ? ", or ask a smaller limit" : `, or ask for the first N with limit (default ${c.want})`}.`,
    "limit",
    { sqlstate: null, hint: `api.${endpoint} cuts at a tier ceiling (${c.ceilings.join(", ")}) without refusing.` },
  );
}

export async function derivatives(req: ParsedRequest, ctx: CallContext): Promise<Envelope> {
  // meta.truncated: true (more rows exist), false (every row), null (the N asked, and whether more exist is unknown).
  const cut: { clamped: boolean; truncated: boolean | null } = { clamped: false, truncated: null };
  const env = await runKind(DERIVATIVES, req, ctx, {
    prepare: (_kind, _plan, values) => (typeof values.id === "string" ? { ...values, id: values.id.toUpperCase() } : values),
    args: (plan, values, args) => (plan.endpoint in CLAMPED ? { ...args, p_limit: wanted(plan.endpoint, values) + 1 } : args),
    rows: (plan, values, rows): Row[] => {
      if (!(plan.endpoint in CLAMPED)) return rows;
      cut.clamped = true;
      const asked = typeof values.limit === "number";
      const want = wanted(plan.endpoint, values);
      const n = rows.length;
      if (n > want) {
        if (!asked) throw cutRefusal(plan.endpoint, values, n, `holds more than ${want} rows for this selection`);
        cut.truncated = true;
        return rows.slice(0, want);
      }
      if (CLAMPED[plan.endpoint].ceilings.includes(n)) {
        // The SQL may have cut at this ceiling. Only the exact N the caller asked for is served.
        if (!asked || n < want) throw cutRefusal(plan.endpoint, values, n, "answered exactly a tier ceiling, which cannot be told from a cut");
        return rows;
      }
      cut.truncated = false;
      return rows;
    },
  });
  if (cut.clamped) env.meta.truncated = cut.truncated;
  return env;
}
