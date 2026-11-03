// silo-api resource `screens`: which funds look odd? (#1058)
//
// kind list (the default) -> api.catalog(), projected to one row per screen:
// its kind, one line, the family it reads, and its SQL defaults under v2
// names. Any other kind -> api.screen_<kind>. Every threshold is hidden; one
// left null is sent as the SQL function's own default (the kind's
// sql_defaults, pinned to the SQL by tests/test_api_v2_registry.py), so
// meta.request echoes the value applied. Every response carries meta.signal:
// a screen is a signal, not a verdict.

import { ApiError } from "../errors.ts";
import type { Envelope } from "../envelope.ts";
import type { ParsedRequest, Value } from "../params.ts";
import type { CallContext } from "../postgrest.ts";
import { type Plan, RESOURCES_BY_NAME } from "../registry.ts";
import { type Row, runKind } from "./run.ts";

const SCREENS = RESOURCES_BY_NAME.get("screens")!;

export const SIGNAL =
  "Signal, not a verdict: a row is a pattern worth a look, not a finding. Legal funds match every screen; read the screen's meaning in coverage?kind=catalog (screens) before drawing a conclusion.";

function withSqlDefaults(_kind: string, plan: Plan, values: Record<string, Value>): Record<string, Value> {
  const out = { ...values };
  for (const [name, v] of Object.entries(plan.sql_defaults ?? {})) if (out[name] === null) out[name] = v;
  return out;
}

/** catalog().screens -> one row per screen, its p_ defaults under v2 names. */
function listScreens(rows: Row[]): Row[] {
  const screens = (rows[0]?.screens ?? null) as Record<string, Record<string, unknown>> | null;
  if (!screens || typeof screens !== "object") {
    throw new ApiError(500, "internal", "api.catalog() returned no screens map; the screens list cannot be built.");
  }
  return Object.entries(screens).map(([kind, s]) => {
    const spec = SCREENS.kinds?.[kind];
    const v2 = Object.fromEntries(Object.entries(spec?.args ?? {}).map(([name, p]) => [p, name]));
    const params = (s.params ?? {}) as Record<string, unknown>;
    return {
      kind,
      summary: spec?.doc ?? null,
      family: s.family ?? null,
      endpoint: typeof s.function === "string" ? `api.${s.function}` : null,
      defaults: Object.fromEntries(Object.entries(params).map(([p, v]) => [v2[p] ?? p, v])),
      call: `/v2/screens?kind=${kind}`,
    };
  });
}

export async function screens(req: ParsedRequest, ctx: CallContext): Promise<Envelope> {
  const env = await runKind(SCREENS, req, ctx, {
    prepare: withSqlDefaults,
    rows: (plan, _values, rows) => (plan.endpoint === "catalog" ? listScreens(rows) : rows),
  });
  env.meta.signal = SIGNAL;
  return env;
}
