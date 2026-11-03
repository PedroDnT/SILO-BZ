// silo-api resource `panel`: a clean (id, date, metric, value) table (#1058).
//
// One kind, so no kind parameter: api.panel. id is a comma-separated list
// (tickers, fund CNPJs, option and termo tickers, futures codes) sent as
// p_ids. The gateway's tier ceiling (config.ts panel_ids: 1 anonymous, 3
// signed in, #1059) is refused above it (forbidden_for_tier), before the
// SQL's own (3 anonymous, 50 signed in, refused verbatim as over_limit);
// never trimmed. Universe mode (no id) is the pro tier's (config.ts
// panel_universe), which no caller reaches until #1064. metric -> p_metrics (auto:
// each family's default, p_metrics not sent), freq -> p_freq, family ->
// p_entity_type. Default window: 3 years back from `to` (or today, UTC-3).
//
// api.panel ignores an unknown metric name and returns a smaller, plausible
// panel; the gateway refuses it instead (unknown_parameter, the name in
// target). The valid names are catalog().metrics, listed in PANEL_METRICS;
// tests/test_api_v2_registry.py pins that list to the SQL catalog.

import { HIGHER_TIER, TIERS } from "../config.ts";
import { ApiError } from "../errors.ts";
import type { Envelope } from "../envelope.ts";
import type { ParsedRequest, Value } from "../params.ts";
import type { CallContext } from "../postgrest.ts";
import { RESOURCES_BY_NAME } from "../registry.ts";
import { runKind } from "./run.ts";

const PANEL = RESOURCES_BY_NAME.get("panel")!;

/** catalog().metrics, in catalog order. Pinned to the SQL by a pytest. */
export const PANEL_METRICS: string[] = [
  "close", "close_adj", "volume", "close_unit", "close_return", "settlement_rate",
  "settlement_price", "open_interest", "nav", "quota", "delinquency", "yield",
  "inflows", "redemptions", "quotaholders", "receivables", "sacado_top1", "sacado_top25",
];

function prepare(_kind: string, _plan: unknown, values: Record<string, Value>, ctx: CallContext): Record<string, Value> {
  const tier = ctx.tier ?? "anonymous";
  const limits = TIERS[tier];
  const out = { ...values };
  if (Array.isArray(out.metric) || (typeof out.metric === "string" && out.metric !== "auto")) {
    const asked = Array.isArray(out.metric) ? out.metric : [out.metric];
    for (const m of asked) {
      if (!PANEL_METRICS.includes(m.toLowerCase())) {
        throw new ApiError(
          400,
          "unknown_parameter",
          `panel has no metric \`${m}\`. Metrics: ${PANEL_METRICS.join(", ")} (coverage?kind=catalog, metrics). Or leave metric out for each family's default.`,
          m,
        );
      }
    }
    out.metric = asked;
  }
  const ids = typeof out.id === "string" ? out.id.split(",").map((s) => s.trim()).filter((s) => s !== "") : [];
  if (ids.length) {
    if (ids.length > limits.panel_ids) {
      throw new ApiError(
        403,
        "forbidden_for_tier",
        `panel takes at most ${limits.panel_ids} id${limits.panel_ids === 1 ? "" : "s"} per call for the ${tier} tier; ${ids.length} were given. ` +
          `Split the ids across calls (never trimmed). ${HIGHER_TIER[tier]}`,
        "id",
      );
    }
    out.id = ids;
    for (const name of ["min_nav", "min_months"]) {
      if (out[name] !== null) {
        throw new ApiError(400, "bad_request", `${name} applies only with no id (universe mode: a whole family). Leave it out, or drop id.`, name);
      }
    }
    return out;
  }
  out.id = null;
  if (out.family === "auto") {
    throw new ApiError(
      400,
      "bad_request",
      "panel needs id (a comma-separated list of tickers or CNPJs), or a family to walk with no id (universe mode, signed-in callers). Find ids with /v2/search.",
      "id",
    );
  }
  if (out.freq !== "month") {
    throw new ApiError(400, "bad_request", "Universe mode (no id) is monthly: funds file monthly. Leave freq out, or pass id.", "freq");
  }
  if (!limits.panel_universe) {
    throw new ApiError(
      403,
      "forbidden_for_tier",
      `panel universe mode (no id, a whole family) is not served to the ${tier} tier. Pass id (at most ${limits.panel_ids}). ${HIGHER_TIER[tier]}`,
      "id",
    );
  }
  return out;
}

export function panel(req: ParsedRequest, ctx: CallContext): Promise<Envelope> {
  return runKind(PANEL, { ...req, kind: "panel" }, ctx, prepare);
}
