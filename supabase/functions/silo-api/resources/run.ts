// silo-api: run one registry kind. Shared by every resource module.
//
// One kind = one plan = the plan's api.* endpoint, read through the plan's
// paging method (registry.ts PagingSpec, #1059), then the declared
// selections. The resource modules (search.ts, coverage.ts, ...) add only
// what the registry cannot declare, through `prepare` (e.g. funds normalises
// a CNPJ id) or the hooks of KindHooks (prices: the arguments of a call, how
// a view is read, and a projection or a column the kind always carries).
//
// Paging (#1059): `limit` is the page size, defaulting to the tier's page
// maximum and coerced down to it. While rows remain, next_page_url carries an
// opaque cursor (paging.ts). A call stops at the tier's rows-per-call cap
// with meta.tier_cap_reached and no next_page_url. Nothing is cut silently.

import { HIGHER_TIER, type Tier, TIERS } from "../config.ts";
import { ApiError } from "../errors.ts";
import { type Envelope, envelope, type Meta } from "../envelope.ts";
import {
  applySelections,
  applyWindow,
  buildArgs,
  checkApplicable,
  checkRequired,
  given,
  minusMonths,
  type ParsedRequest,
  selectPlan,
  todayUtcMinus3,
  type Value,
} from "../params.ts";
import {
  afterPos,
  cursorDay,
  type CursorState,
  encodeCursor,
  type Method,
  offsetPos,
  slicePage,
  type Walked,
  walkAfter,
  walkWindows,
  windowPos,
} from "../paging.ts";
import { callRpc, callView, type CallContext } from "../postgrest.ts";
import type { Plan, ResourceSpec } from "../registry.ts";

export type Row = Record<string, unknown>;
type Values = Record<string, Value>;

/** A resource's own step between validation and the call; returns the values to send. */
export type Prepare = (kindName: string, plan: Plan, values: Record<string, Value>, ctx: CallContext) => Record<string, Value>;

/** What a view plan reads: which view, its eq. and other filters, and the session it pinned. */
export interface ViewQuery {
  view: string;
  eq: Record<string, unknown>;
  filters: Record<string, string>;
  /** A session date the read resolved (the default, newest session), kept in the cursor. */
  pin: string | null;
}

// -- hooks (prices, #1055; derivatives, curves, #1057) -----------------------
export interface KindHooks {
  prepare?: Prepare;
  /** Change an rpc plan's `p_` arguments before the call. */
  args?: (plan: Plan, values: Values, args: Record<string, unknown>) => Record<string, unknown>;
  /** Say which view a view plan reads, and with which filters; `pin` is the cursor's pinned session. */
  view?: (plan: Plan, values: Values, ctx: CallContext, pin: string | null) => Promise<ViewQuery>;
  /**
   * After an rpc call, before any selection: throw when the rows may be a cut
   * the SQL made without refusing. An ApiError with rowCap set lets a
   * date-window walk halve the window.
   */
  check?: (plan: Plan, values: Values, rows: Row[]) => void;
  /** After the declared selections: a projection, or a column the kind always carries. Never a fill. */
  rows?: (plan: Plan, values: Values, rows: Row[]) => Row[];
}

/** The paging method a plan runs with these values (fund_nav pages with p_after only with a family). */
export function pagingMethod(resource: ResourceSpec, plan: Plan, values: Values): { method: Method; order: "asc" | "desc" } {
  const p = plan.paging;
  if (!p) throw new ApiError(500, "internal", `${resource.name}: api.${plan.endpoint} has no paging in the registry.`);
  if (p.method === "p_after" && p.requires && !given(resource, p.requires, values)) {
    return { method: p.otherwise ?? "single_page", order: p.order ?? "asc" };
  }
  return { method: p.method, order: p.order ?? "asc" };
}

function isDaily(plan: Plan, values: Values): boolean {
  const d = plan.daily;
  if (d === true) return true;
  return typeof d === "object" && d !== null && values[d.parameter] === d.value;
}

/**
 * The tier's window on daily data (config.ts daily_window_months). A default
 * window wider than it is narrowed to it (meta.request.from says so); a from
 * the caller sent that is earlier is forbidden_for_tier, never trimmed.
 */
function tierWindow(
  resource: ResourceSpec,
  kindName: string,
  plan: Plan,
  values: Values,
  sentFrom: boolean,
  tier: Tier,
  meta: Meta,
  today: string,
): Values {
  const months = TIERS[tier].daily_window_months;
  if (months === null || !("from" in plan.args) || !isDaily(plan, values)) return values;
  const end = typeof values.to === "string" ? values.to : today;
  const earliest = minusMonths(end, months);
  if (typeof values.from === "string" && values.from >= earliest) return values;
  if (!sentFrom) {
    meta.window_narrowed_to_tier = { months, tier };
    return { ...values, from: earliest };
  }
  throw new ApiError(
    403,
    "forbidden_for_tier",
    `${resource.name} kind=${kindName} is daily data, and the ${tier} tier reads at most ${months} months per call; from ${values.from} to ${end} is wider. ` +
      `Send from=${earliest} or later. ${HIGHER_TIER[tier]}`,
    "from",
  );
}

export async function runKind(
  resource: ResourceSpec,
  req: ParsedRequest,
  ctx: CallContext,
  hooksOrPrepare: KindHooks | Prepare = {},
): Promise<Envelope> {
  const hooks: KindHooks = typeof hooksOrPrepare === "function" ? { prepare: hooksOrPrepare } : hooksOrPrepare;
  const kindName = req.kind;
  const kind = kindName ? resource.kinds?.[kindName] : undefined;
  if (!kindName || !kind) throw new ApiError(500, "internal", `${resource.name} has no kind \`${kindName}\` in the registry.`);
  const tier: Tier = ctx.tier ?? "anonymous";
  const limits = TIERS[tier];

  const plan = selectPlan(kind, req.values);
  checkApplicable(resource, kindName, plan, req.values);
  checkRequired(resource, kindName, plan, req.values);
  const meta: Meta = { resource: resource.name, kind: kindName, request: {}, id_known: null, endpoint: `api.${plan.endpoint}` };
  // A defaulted from/to counts from the day the walk started, not from today:
  // a cursor carries that day, so a walk that crosses midnight keeps its window (#1103).
  const cursor: CursorState | null = req.paging?.cursor ?? null;
  const day = cursorDay(cursor, todayUtcMinus3(new Date(ctx.now ? ctx.now() : Date.now())));
  let values = applyWindow(resource, plan, req.values, day);
  values = tierWindow(resource, kindName, plan, values, req.values.from !== null, tier, meta, day);
  if (hooks.prepare) values = hooks.prepare(kindName, plan, values, ctx);

  // limit is the page size: the tier's maximum by default, coerced down to it (AIP-158).
  const asked = typeof req.values.limit === "number" ? req.values.limit : null;
  const pageSize = Math.min(asked ?? limits.page_max, limits.page_max);
  if (asked !== null && asked > limits.page_max) meta.limit_coerced_from = asked;
  if ("limit" in values) values = { ...values, limit: pageSize };
  meta.request = values;
  meta.tier = tier;

  const { method, order } = pagingMethod(resource, plan, values);
  if (cursor && cursor.m !== method) {
    throw new ApiError(400, "bad_request", "The cursor was written by another paging method than this request uses. Start again without cursor.", "cursor");
  }
  // The position, checked before anything is served: an edited cursor is refused, not trusted.
  const at = cursor?.p ?? null;
  const from = typeof values.from === "string" ? values.from : null;
  const to = typeof values.to === "string" ? values.to : null;
  const pos = {
    after: method === "p_after" ? afterPos(at) : "",
    offset: method === "view_offset" || method === "single_page" ? offsetPos(at) : { off: 0, pin: null },
    window: method === "date_window" ? windowPos(at, from, to) : null,
  };
  const served = cursor?.n ?? 0;
  const cap = limits.rows_per_call;
  const need = cap === null ? pageSize : Math.min(pageSize, cap - served);
  if (need <= 0) {
    // Only a cursor written for a higher tier gets here: this tier's cap is already met.
    return capped(envelope([], meta), tier, served);
  }

  // One rpc call with these values (and extra p_ arguments): the rows as returned.
  const rpcRows = async (v: Values, extra: Record<string, unknown> = {}): Promise<Row[]> => {
    let args = buildArgs(resource, plan, v);
    if (hooks.args) args = hooks.args(plan, v, args);
    const result = await callRpc(ctx, plan.endpoint, { ...args, ...extra });
    let rows: Row[];
    if (plan.single) rows = result === null ? [] : [result as Row];
    else if (Array.isArray(result)) rows = result as Row[];
    else throw new ApiError(500, "internal", `api.${plan.endpoint} returned a single value where the registry expects rows.`);
    if (hooks.check) hooks.check(plan, v, rows);
    return rows;
  };
  const finish = (rows: Row[]): Row[] => {
    const out = applySelections(plan, values, rows);
    return hooks.rows ? hooks.rows(plan, values, out) : out;
  };

  let walked: Walked<Record<string, unknown>>;
  if (method === "view_offset") {
    walked = await readView(resource, plan, values, ctx, hooks, pos.offset, need, meta, finish);
  } else if (method === "p_after") {
    const key = plan.paging.key ?? [];
    const month = (plan.filters ?? []).find((f) => f.op === "month_last" && values[f.parameter] !== f.all);
    const w = await walkAfter({
      after: pos.after,
      need,
      fetch: (after) => rpcRows(values, { p_after: after }),
      select: (rows) => applySelections(plan, values, rows),
      key: (r) => key.map((k) => String(r[k] ?? "")).join("|"),
      holdBackMonth: month?.column ?? null,
    });
    walked = { ...w, rows: hooks.rows ? hooks.rows(plan, values, w.rows) : w.rows };
  } else if (method === "date_window") {
    walked = await walkWindows({
      pos: pos.window!,
      order,
      need,
      today: day,
      fetch: async (lo, hi) => finish(await rpcRows({ ...values, from: lo, to: hi })),
    }) as unknown as Walked<Record<string, unknown>>;
  } else {
    walked = slicePage(finish(await rpcRows(values)), pos.offset.off, need);
  }

  const total = served + walked.rows.length;
  meta.page_size = pageSize;
  meta.rows_served = total;
  const env = envelope(walked.rows, meta);
  if (!walked.more) return env;
  if (cap !== null && total >= cap) return capped(env, tier, total);
  const p = req.paging;
  if (!p) throw new ApiError(500, "internal", "More rows remain, but the request carries no paging context to build next_page_url.");
  const state: CursorState = { v: 1, r: resource.name, q: p.q, m: method, p: walked.pos, n: total, t: day };
  if (p.body !== undefined) state.b = p.body;
  env.next_page_url = `${p.base}?cursor=${encodeCursor(state)}`;
  return env;
}

/** The tier's rows-per-call cap is met: no next_page_url, and the envelope says so. */
function capped(env: Envelope, tier: Tier, served: number): Envelope {
  env.meta.tier_cap_reached = true;
  env.meta.tier_cap_message =
    `This call has served ${served} rows, the ${tier} tier's cap per call (${TIERS[tier].rows_per_call}); more rows may remain and were not served. ` +
    `Narrow the request (from/to, id) and call again, or use a higher tier. ${HIGHER_TIER[tier]}`;
  delete env.next_page_url;
  return env;
}

// -- a view plan (#1056; paged by order + limit + offset since #1059) -------------

/** PostgREST's db-max-rows: one page of a GET view. */
export const VIEW_PAGE = 1000;

/** The view query a plan declares: eq. on its args and `where`, its range, no pinned session. */
function declaredView(resource: ResourceSpec, plan: Plan, values: Values): ViewQuery {
  const args = buildArgs(resource, plan, values);
  const filters = rangeFilters(plan, values, args);
  return { view: plan.endpoint, eq: { ...(plan.where ?? {}), ...args }, filters, pin: null };
}

/**
 * One GET on a view: eq. filters (applied before PostgREST's row cap), the
 * plan's order, and `need` + 1 rows from `off`. Rows remain when the extra row
 * came back; it is not served. No exact count is asked (#1098), so
 * meta.rows_total is null. A page of VIEW_PAGE rows cannot ask for one more
 * (db-max-rows would cut it), so a full page there may have more.
 */
async function readView(
  resource: ResourceSpec,
  plan: Plan,
  values: Values,
  ctx: CallContext,
  hooks: KindHooks,
  pos: { off: number; pin: string | null },
  need: number,
  meta: Meta,
  finish: (rows: Row[]) => Row[],
): Promise<Walked<Record<string, unknown>>> {
  const q = hooks.view ? await hooks.view(plan, values, ctx, pos.pin) : declaredView(resource, plan, values);
  const probe = need < VIEW_PAGE;
  const page = await callView(ctx, q.view, q.eq, plan.order, probe ? need + 1 : need, q.filters, pos.off);
  const more = probe ? page.rows.length > need : page.rows.length >= need && need > 0;
  const rows = more ? page.rows.slice(0, need) : page.rows;
  const n = rows.length;
  meta.endpoint = `api.${q.view}`;
  meta.rows_total = null;
  if (q.pin) meta.session = q.pin;
  const next: Record<string, unknown> = { off: pos.off + n };
  if (q.pin) next.pin = q.pin;
  return { rows: finish(rows), more, pos: next };
}

// -- a date range on a view (derivatives, curves, macro, positioning: #1057) --

/**
 * A view plan's `range`: from and to select that date column with gte and lte
 * (PostgREST `and=(...)` when both are given), never an eq. filter. buildArgs
 * mapped both to the one column, so it is taken out of the eq. arguments.
 */
export function rangeFilters(plan: Plan, values: Values, args: Record<string, unknown>): Record<string, string> {
  const col = plan.range;
  if (!col) return {};
  delete args[col];
  const lo = typeof values.from === "string" ? values.from : null;
  const hi = typeof values.to === "string" ? values.to : null;
  if (lo && hi) return { and: `(${col}.gte.${lo},${col}.lte.${hi})` };
  if (lo) return { [col]: `gte.${lo}` };
  if (hi) return { [col]: `lte.${hi}` };
  return {};
}
