// silo-api: parse and validate a request's query string against the registry.
//
// Pure: no network. Rules (docs/planning/API_V2.md, section 3):
//   * a name the resource does not declare is unknown_parameter, named in target;
//   * every declared parameter gets a value: the caller's, or its default;
//   * a value that is not one the parameter accepts is bad_request;
//   * a non-default value the chosen kind cannot use is bad_request, never
//     silently ignored (a typo or a misplaced filter must not look like an answer).

import { ApiError } from "./errors.ts";
import type { CursorState } from "./paging.ts";
import type { BodySpec, FilterSpec, KindSpec, ParamSpec, Plan, ResourceSpec } from "./registry.ts";
import { REGISTRY, SHARED_NAMES } from "./registry.ts";

export type Value = string | number | string[] | null;

export interface ParsedRequest {
  /** null for a data call; "main" for ?help, "all" for ?help=all. */
  help: null | "main" | "all";
  kind: string | null;
  /** Every parameter the resource takes, with the value applied. */
  values: Record<string, Value>;
  /** portfolio (#1058): the POST body's lists, by field name (parseBody). */
  body?: Record<string, unknown[]>;
  /** #1059: what a next_page_url needs, and the cursor this request sent (server.ts). */
  paging?: PagingContext;
}

export interface PagingContext {
  /** The cursor the request sent, decoded; null on a first page. */
  cursor: CursorState | null;
  /** Every query parameter of the walk, as sent (cursor excluded). */
  q: Record<string, string>;
  /** The URL a next page is fetched from, without its query. */
  base: string;
  /** POST only: the body's digest (paging.ts bodyDigest). */
  body?: string;
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
      // limit is the page size: above the tier's maximum it is coerced (run.ts, #1059), never refused.
      if (spec.name === "limit" && n < 1) {
        throw new ApiError(400, "bad_request", `limit must be 1 or more; got ${n}.`, "limit");
      }
      return n;
    }
    case "number": // #1058: a screen threshold or a BRL floor, never negative.
      if (!/^\d+(\.\d+)?$/.test(raw)) throw new ApiError(400, "bad_request", `${spec.name} must be a number >= 0; got \`${raw}\`.`, spec.name);
      return Number(raw);
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
      : resource.body?.some((b) => b.name === key)
      ? `${key} is a list: send it in the JSON body, not the query string.`
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
  const w = kind.when_empty;
  if (w && (isEmpty(values[w.parameter] ?? null) || (w.value !== undefined && values[w.parameter] === w.value))) return w.plan;
  return kind;
}

function planUses(plan: Plan, name: string): boolean {
  return name in plan.args ||
    (plan.filters ?? []).some((f) => f.parameter === name) ||
    (plan.uses ?? []).includes(name) ||
    plan.view_by?.parameter === name;
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
    if (spec.name === "kind" || spec.name === "limit") continue; // limit: the page size of every kind (#1059)
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
    const spec = specs.get(name);
    if (spec?.null_value !== undefined && v === spec.null_value) continue;
    args[pName] = typeof v === "string" && spec?.sql_values?.[v] !== undefined ? spec.sql_values[v] : v;
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
  if (f.op === "month_last") return lastPerMonth(rows, f.column as string);
  if (f.op === "in" && f.map) {
    // An enum mapped to a column value: it cannot be mistyped, so a value no
    // row carries is no row (an empty answer), not a refusal.
    const want = (Array.isArray(v) ? v : [String(v)]).map((w) => f.map?.[w] ?? w);
    return rows.filter((r) => want.includes(String(r[f.column as string])));
  }
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

// ---------------------------------------------------------------------------
// Required ids and default windows (funds, fidc, events: #1056).
// ---------------------------------------------------------------------------

/** Given: not null, not empty, and not the parameter's "no value" (null_value). */
export function given(resource: ResourceSpec, name: string, values: Record<string, Value>): boolean {
  const v = values[name] ?? null;
  if (isEmpty(v)) return false;
  const spec = acceptedParams(resource).find((p) => p.name === name);
  return !(spec?.null_value !== undefined && v === spec.null_value);
}

/**
 * require_one_of: exactly one of the named parameters must be given. The SQL
 * refuses a missing id too, but with 22023, which would read as over_limit;
 * the gateway says what is missing instead, before any call.
 */
export function checkRequired(resource: ResourceSpec, kindName: string, plan: Plan, values: Record<string, Value>): void {
  const names = plan.require_one_of;
  if (!names?.length) return;
  const present = names.filter((n) => given(resource, n, values));
  if (present.length === 1) return;
  const what = names.length === 1 ? names[0] : `exactly one of ${names.join(", ")}`;
  const why = present.length === 0 ? "none was given" : `${present.join(" and ")} were both given`;
  throw new ApiError(
    400,
    "bad_request",
    `${resource.name} kind=${kindName} needs ${what}; ${why}. Find an id with /v2/search, or see /v2/${resource.name}?help=all.`,
    present.length === 0 ? names[0] : present[1],
  );
}

/** YYYY-MM-DD minus whole months; the day is clamped to the target month's last day. */
export function minusMonths(iso: string, months: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  const total = y * 12 + (m - 1) - months;
  const ty = Math.floor(total / 12);
  const tm = total - ty * 12;
  const last = new Date(Date.UTC(ty, tm + 1, 0)).getUTCDate();
  const pad = (n: number, w = 2) => String(n).padStart(w, "0");
  return `${pad(ty, 4)}-${pad(tm + 1)}-${pad(Math.min(d, last))}`;
}

/** Today in Brasilia (UTC-3, no daylight saving since 2019), as YYYY-MM-DD. */
export function todayUtcMinus3(now: Date = new Date()): string {
  return new Date(now.getTime() - 3 * 3600 * 1000).toISOString().slice(0, 10);
}

/**
 * The values with the default window applied: when the plan takes `from`
 * and none was sent, from = (to, or today in UTC-3) minus the resource's
 * window_months (or the kind's own). `to` is left as sent; with none, the endpoint's own default
 * applies (fund_nav, for one, ends at the family's latest complete period).
 * A from after to is refused.
 */
export function applyWindow(resource: ResourceSpec, plan: Plan, values: Record<string, Value>, now?: Date): Record<string, Value> {
  const out = { ...values };
  if (!("from" in plan.args)) return out;
  const months = plan.window_months ?? resource.window_months; // a kind's own window (#1057)
  if (out.from === null && months) {
    const end = typeof out.to === "string" ? out.to : todayUtcMinus3(now);
    out.from = minusMonths(end, months);
  }
  if (typeof out.from === "string" && typeof out.to === "string" && out.from > out.to) {
    throw new ApiError(400, "bad_request", `from (${out.from}) is after to (${out.to}).`, "from");
  }
  return out;
}

/** A fund CNPJ id: punctuation (. / -) stripped, then exactly 14 digits, or bad_request. */
export function normalizeCnpjId(resource: ResourceSpec, kindName: string, values: Record<string, Value>): Record<string, Value> {
  const v = values.id;
  if (typeof v !== "string" || v === "") return values;
  const digits = v.replace(/[.\/\-\s]/g, "");
  if (!/^\d{14}$/.test(digits)) {
    throw new ApiError(
      400,
      "bad_request",
      `${resource.name} kind=${kindName} takes a fund CNPJ as id (14 digits, punctuation allowed); got \`${v}\`. Find one with /v2/search?kind=fund&q=<name>.`,
      "id",
    );
  }
  return { ...values, id: digits };
}

// ---------------------------------------------------------------------------
// prices freq=month (#1055).
// ---------------------------------------------------------------------------

/**
 * The last session of each month: of the rows whose `col` (an ISO date) falls
 * in one calendar month, the one with the latest date. A selection of rows
 * that exist, never an interpolation: a month with no row has no row. Order
 * is kept. A row with no date cannot be placed in a month and is not kept.
 */
export function lastPerMonth(rows: Row[], col: string): Row[] {
  const last = new Map<string, string>();
  for (const r of rows) {
    const d = r[col];
    if (typeof d !== "string" || d.length < 10) continue;
    const m = d.slice(0, 7);
    const seen = last.get(m);
    if (seen === undefined || d > seen) last.set(m, d);
  }
  return rows.filter((r) => {
    const d = r[col];
    return typeof d === "string" && last.get(d.slice(0, 7)) === d;
  });
}

// ---------------------------------------------------------------------------
// portfolio: the POST body (#1058).
// ---------------------------------------------------------------------------

/** The most a body may hold; each function caps its lists far below this. */
export const BODY_MAX_BYTES = 1_000_000;

function bodyItemOk(spec: BodySpec, x: unknown): boolean {
  if (x === null) return true;
  if (spec.items === "number") return typeof x === "number" && Number.isFinite(x);
  if (spec.items === "date") return typeof x === "string" && isRealDate(x);
  return typeof x === "string";
}

/**
 * A JSON object whose every key is a body field the resource declares and
 * whose every value is a list of that field's items (null entries allowed).
 * An unknown key is unknown_parameter; anything else wrong is bad_request.
 */
export function parseBody(resource: ResourceSpec, text: string): Record<string, unknown[]> {
  const fields = new Map((resource.body ?? []).map((b) => [b.name, b]));
  const names = [...fields.keys()].join(", ");
  if (text.length > BODY_MAX_BYTES) throw new ApiError(400, "bad_request", `The body is over ${BODY_MAX_BYTES} bytes.`, "body");
  let parsed: unknown;
  try {
    parsed = text.trim() === "" ? {} : JSON.parse(text);
  } catch {
    throw new ApiError(400, "bad_request", `The body is not JSON. Send an object of lists: ${names}.`, "body");
  }
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new ApiError(400, "bad_request", `The body must be a JSON object of lists: ${names}.`, "body");
  }
  const out: Record<string, unknown[]> = {};
  for (const [key, v] of Object.entries(parsed as Record<string, unknown>)) {
    const spec = fields.get(key);
    if (!spec) {
      throw new ApiError(400, "unknown_parameter", `${resource.name} has no body field \`${key}\`. It takes: ${names}. See /v2/${resource.name}?help.`, key);
    }
    if (!Array.isArray(v)) throw new ApiError(400, "bad_request", `${key} must be a JSON list.`, key);
    const bad = v.findIndex((x) => !bodyItemOk(spec, x));
    if (bad >= 0) {
      const what = spec.items === "date" ? "a date, YYYY-MM-DD" : `a ${spec.items}`;
      throw new ApiError(400, "bad_request", `${key}[${bad}] must be ${what} or null; got ${JSON.stringify(v[bad])}.`, key);
    }
    out[key] = v;
  }
  return out;
}
