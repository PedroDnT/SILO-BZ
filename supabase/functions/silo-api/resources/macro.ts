// silo-api resource `macro`: macro series, inflation, PTAX, Focus.
//
// kind series -> api.macro_series (id required), inflation -> api.inflation
// (family -> p_family), inflation_items -> api.inflation_items (with an id,
// p_level NULL so the item is found at its own level; with none, the SQL's
// level 1, the groups), fx -> api.ptax (currency -> p_currency; currency=all
// reads the api.ptax_daily view), expectations -> api.focus_expectations
// (family -> p_endpoint, the Focus survey, default annual; horizon -> p_horizon,
// default the current year for annual). Default window: 1 year, and 3 years
// for inflation and inflation_items (the kinds' own window_months).

import { ApiError } from "../errors.ts";
import type { Envelope } from "../envelope.ts";
import { type ParsedRequest, todayUtcMinus3, type Value } from "../params.ts";
import type { CallContext } from "../postgrest.ts";
import { RESOURCES_BY_NAME } from "../registry.ts";
import { runKind } from "./run.ts";

const MACRO = RESOURCES_BY_NAME.get("macro")!;

/** family values by kind: api.inflation's p_family, and the Focus surveys. */
export const INFLATION_FAMILIES = ["headline", "core", "classification", "diffusion", "group"];
export const FOCUS_SURVEYS = ["annual", "monthly", "selic", "inflation_12m"];

function wrongFamily(kind: string, family: string, accepted: string[]): ApiError {
  return new ApiError(
    400,
    "bad_request",
    `macro kind=${kind} takes family ${accepted.join(", ")}; got \`${family}\`. See /v2/macro?help=all.`,
    "family",
  );
}

function prepare(kind: string, values: Record<string, Value>): Record<string, Value> {
  const family = String(values.family);
  if (kind === "inflation" && FOCUS_SURVEYS.includes(family)) throw wrongFamily(kind, family, ["all", ...INFLATION_FAMILIES]);
  if (kind !== "expectations") return values;
  const survey = family === "all" ? "annual" : family;
  if (!FOCUS_SURVEYS.includes(survey)) throw wrongFamily(kind, family, FOCUS_SURVEYS);
  let horizon = values.horizon;
  if (horizon === null || horizon === "") {
    if (survey !== "annual") {
      throw new ApiError(
        400,
        "bad_request",
        `macro kind=expectations family=${survey} needs horizon, exactly as BACEN publishes it (monthly: MM/YYYY; selic: a COPOM meeting, R6/2028). Only family annual has a default (the current year).`,
        "horizon",
      );
    }
    horizon = todayUtcMinus3().slice(0, 4);
  }
  return { ...values, family: survey, horizon };
}

export function macro(req: ParsedRequest, ctx: CallContext): Promise<Envelope> {
  return runKind(MACRO, req, ctx, {
    prepare: (kind, _plan, values) => prepare(kind, values),
    args: (plan, _values, args) => (plan.endpoint === "inflation_items" && "p_item" in args ? { ...args, p_level: null } : args),
  });
}
