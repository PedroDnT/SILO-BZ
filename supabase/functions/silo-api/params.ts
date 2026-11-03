// silo-api: parse and validate a request's query string against the registry.
//
// Pure: no network. Rules (docs/planning/API_V2.md, section 3):
//   * a name the resource does not declare is unknown_parameter, named in target;
//   * every declared parameter gets a value: the caller's, or its default;
//   * a value that is not one the parameter accepts is bad_request;
//   * a non-default value the chosen kind cannot use is bad_request, never
//     silently ignored (a typo or a misplaced filter must not look like an answer).

import { ApiError } from "./errors.ts";
import type { FilterSpec, KindSpec, ParamSpec, Plan, ResourceSpec } from "./registry.ts";
import { REGISTRY, SHARED_NAMES } from "./registry.ts";

export type Value = string | number | string[] | null;

export interface ParsedRequest {
  /** null for a data call; "main" for ?help, "all" for ?help=all. */
  help: null | "main" | "all";
  kind: string | null;
  /** Every parameter the resource takes, with the value applied. */
  values: Record<string, Value>;
}

const DATE = /^\d{4}-\d{2}-\d{2}$/;

function isRealDate(s: string): boolean {
  if (!DATE.test(s)) return false;
  const d = new Date(`${s}T00:00:00Z`);
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === s;
}

/** The shared parameters as ParamSpecs, so one validator serves both. */
function sharedSpec(name: string): ParamSpec {
  const s = REGISTRY.shared_parameters[name];
  const type = name === "from" || name === "to" ? "date" : name === "limit" ? "integer" : "string";
  return { name, visibility: "main", type, default: s.default, default_doc: s.default_doc, doc: s.doc };
}

/** Every parameter a resource takes: its own, then the shared ones it declares. */
export function acceptedParams(resource: ResourceSpec): ParamSpec[] {
  return [...(resource.parameters ?? []), ...(resource.shared ?? []).map(sharedSpec)];
}

function coerce(spec: ParamSpec, raw: string): Value {
  switch (spec.type) {
    case "enum":
      if (!spec.values?.includes(raw)) {
        throw new ApiError(400, "bad_request", `${spec.name} must be one of ${spec.values?.join(", ")}; got \`${raw}\`.`, spec.name);
      }
      return raw;
    case "date":
      if (!isRealDate(raw)) throw new ApiError(400, "bad_request", `${spec.name} must be a date, YYYY-MM-DD; got \`${raw}\`.`, spec.name);
      return raw;
    case "integer": {
      if (!/^\d+$/.test(raw)) throw new ApiError(400, "bad_request", `${spec.name} must be an integer; got \`${raw}\`.`, spec.name);
      const n = Number(raw);
      if (spec.name === "limit" && (n < 1 || n > 1000)) {
        throw new ApiError(400, "bad_request", `limit must be in 1..1000; got ${n}.`, "limit");
      }
      return n;
    }
    case "list": {
      const items = raw.split(",").map((s) => s.trim()).filter((s) => s !== "");
      if (items.length === 0) throw new ApiError(400, "bad_request", `${spec.name} is empty; leave it out for the default.`, spec.name);
      return items.length === 1 && items[0] === spec.default ? items[0] : items;
    }
    default:
      return raw.trim();
  }
}

export function parseQuery(resource: ResourceSpec, query: URLSearchParams): ParsedRequest {
  const seen = new Set<string>();
  for (const key of query.keys()) {
    if (seen.has(key)) throw new ApiError(400, "bad_request", `${key} is given more than once; send it once (a list is comma-separated).`, key);
    seen.add(key);
  }

  if (query.has("help")) {
    const h = query.get("help");
    if (h !== "" && h !== "all") throw new ApiError(400, "bad_request", "help takes no value (?help) or all (?help=all).", "help");
    return { help: h === "all" ? "all" : "main", kind: null, values: {} };
  }

  const specs = acceptedParams(resource);
  const byName = new Map(specs.map((p) => [p.name, p]));
  for (const key of query.keys()) {
    if (byName.has(key)) continue;
    const taken = specs.map((p) => p.name).join(", ");
    const why = SHARED_NAMES.includes(key)
      ? `${key} is a shared parameter, but ${resource.name} does not take it.`
      : `${resource.name} has no parameter \`${key}\`.`;
    throw new ApiError(400, "unknown_parameter", `${why} It takes: ${taken}. See /v2/${resource.name}?help=all.`, key);
  }

  const values: Record<string, Value> = {};
  for (const spec of specs) {
    const raw = query.get(spec.name);
    values[spec.name] = raw === null ? spec.default : coerce(spec, raw);
  }
  const kind = typeof values.kind === "string" ? values.kind : null;
  return { help: null, kind, values };
}

// ---------------------------------------------------------------------------
// Plans: which endpoint a kind calls, with which arguments.
// ---------------------------------------------------------------------------

function isEmpty(v: Value): boolean {
  return v === null || v === "" || (Array.isArray(v) && v.length === 0);
}

/** The kind's plan, or its when_empty plan when the named parameter is empty. */
export function selectPlan(kind: KindSpec, values: Record<string, Value>): Plan {
  if (kind.when_empty && isEmpty(values[kind.when_empty.parameter] ?? null)) return kind.when_empty.plan;
  return kind;
}

function planUses(plan: Plan, name: string): boolean {
  return name in plan.args || (plan.filters ?? []).some((f) => f.parameter === name);
}

function sameValue(a: Value, b: Value): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

/**
 * Refuse a non-default value the plan cannot use. `kind` selects the plan, and
 * the when_empty parameter is what selected the fallback, so both are used.
 */
export function checkApplicable(resource: ResourceSpec, kindName: string, plan: Plan, values: Record<string, Value>): void {
  const kind = resource.kinds?.[kindName];
  for (const spec of acceptedParams(resource)) {
    if (spec.name === "kind") continue;
    if (kind?.when_empty?.parameter === spec.name && plan !== kind) continue;
    if (sameValue(values[spec.name] ?? null, spec.default)) continue;
    if (planUses(plan, spec.name)) continue;
    const takers = Object.entries(resource.kinds ?? {})
      .filter(([, k]) => planUses(k, spec.name) || (k.when_empty && planUses(k.when_empty.plan, spec.name)))
      .map(([n]) => n);
    const where = plan === kind ? `kind=${kindName}` : `kind=${kindName} with an empty ${kind?.when_empty?.parameter}`;
    throw new ApiError(
      400,
      "bad_request",
      `${spec.name} does not apply to ${resource.name} ${where}; it applies to ${takers.length ? `kind ${takers.join(", ")}` : "no kind yet"}. Leave it out, or change kind.`,
      spec.name,
    );
  }
}

/** The endpoint's `p_` arguments. A null value, or the parameter's null_value, is not sent. */
export function buildArgs(resource: ResourceSpec, plan: Plan, values: Record<string, Value>): Record<string, unknown> {
  const specs = new Map(acceptedParams(resource).map((p) => [p.name, p]));
  const args: Record<string, unknown> = {};
  for (const [name, pName] of Object.entries(plan.args)) {
    const v = values[name] ?? null;
    if (v === null) continue;
    if (specs.get(name)?.null_value !== undefined && v === specs.get(name)?.null_value) continue;
    args[pName] = v;
  }
  return args;
}

type Row = Record<string, unknown>;

/**
 * The gateway's selections on the rows the endpoint returned. A selection
 * keeps or drops whole rows the caller asked to narrow to; it never edits a
 * value, and an `in` value no row carries is refused with the known values,
 * so an empty answer always means "none", never "you mistyped".
 */
export function applySelections(plan: Plan, values: Record<string, Value>, rows: Row[]): Row[] {
  let out = rows;
  for (const [col, want] of Object.entries(plan.where ?? {})) out = out.filter((r) => r[col] === want);
  for (const f of plan.filters ?? []) out = applyFilter(f, values[f.parameter] ?? null, out);
  if (plan.rename) {
    const ren = plan.rename;
    out = out.map((r) => Object.fromEntries(Object.entries(r).map(([k, v]) => [ren[k] ?? k, v])));
  }
  return out;
}

function applyFilter(f: FilterSpec, v: Value, rows: Row[]): Row[] {
  if (v === null || (f.all !== undefined && v === f.all)) return rows;
  if (f.op === "in") {
    const col = f.column as string;
    const want = Array.isArray(v) ? v : [String(v)];
    const known = [...new Set(rows.map((r) => r[col]).filter((x) => x !== null && x !== undefined).map(String))].sort();
    const missing = want.filter((w) => !known.includes(w));
    if (missing.length) {
      throw new ApiError(400, "bad_request", `${f.parameter}: no row has ${col} ${missing.join(", ")}. Known: ${known.join(", ")}.`, f.parameter);
    }
    return rows.filter((r) => want.includes(String(r[col])));
  }
  // between: low <= v <= high, ISO dates compare as strings. A row with a
  // null bound cannot be shown to hold on that date, so it is not kept.
  const d = String(v);
  return rows.filter((r) => {
    const lo = r[f.low as string];
    const hi = r[f.high as string];
    return typeof lo === "string" && typeof hi === "string" && lo <= d && d <= hi;
  });
}
