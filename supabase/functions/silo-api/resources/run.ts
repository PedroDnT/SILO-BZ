// silo-api: run one registry kind. Shared by every resource module.
//
// One kind = one plan = one api.* call, then the declared selections. The
// resource modules (search.ts, coverage.ts, ...) add only what the registry
// cannot declare, through `prepare` (e.g. funds normalises a CNPJ id).

import { ApiError } from "../errors.ts";
import { type Envelope, envelope, type Meta } from "../envelope.ts";
import {
  applySelections,
  applyWindow,
  buildArgs,
  checkApplicable,
  checkRequired,
  type ParsedRequest,
  selectPlan,
  type Value,
} from "../params.ts";
import { callRpc, callView, type CallContext } from "../postgrest.ts";
import type { Plan, ResourceSpec } from "../registry.ts";

/** A resource's own step between validation and the call; returns the values to send. */
export type Prepare = (kindName: string, plan: Plan, values: Record<string, Value>) => Record<string, Value>;

export async function runKind(resource: ResourceSpec, req: ParsedRequest, ctx: CallContext, prepare?: Prepare): Promise<Envelope> {
  const kindName = req.kind;
  const kind = kindName ? resource.kinds?.[kindName] : undefined;
  if (!kindName || !kind) throw new ApiError(500, "internal", `${resource.name} has no kind \`${kindName}\` in the registry.`);

  const plan = selectPlan(kind, req.values);
  checkApplicable(resource, kindName, plan, req.values);
  checkRequired(resource, kindName, plan, req.values);
  let values = applyWindow(resource, plan, req.values);
  if (prepare) values = prepare(kindName, plan, values);
  const meta: Meta = {
    resource: resource.name,
    kind: kindName,
    request: values,
    id_known: null,
    endpoint: `api.${plan.endpoint}`,
  };
  if (plan.view) return runView(resource, plan, values, ctx, meta);

  const result = await callRpc(ctx, plan.endpoint, buildArgs(resource, plan, values));

  let rows: Record<string, unknown>[];
  if (plan.single) {
    rows = result === null ? [] : [result as Record<string, unknown>];
  } else if (Array.isArray(result)) {
    rows = result as Record<string, unknown>[];
  } else {
    throw new ApiError(500, "internal", `api.${plan.endpoint} returned a single value where the registry expects rows.`);
  }

  return envelope(applySelections(plan, values, rows), meta);
}

// -- a view plan (#1056) -----------------------------------------------------

/** PostgREST's db-max-rows: one page of a GET view. */
export const VIEW_PAGE = 1000;

/**
 * One GET on a view. Filters are eq. on the view (applied before PostgREST's
 * row cap), `limit` is the page size. A view is cut at db-max-rows and cannot
 * refuse, so the gateway does: with no limit, a selection that holds more
 * than one page is over_limit; with limit=N it is the first N in `order`, and
 * meta.rows_total and meta.truncated say how many the selection holds.
 */
async function runView(resource: ResourceSpec, plan: Plan, values: Record<string, Value>, ctx: CallContext, meta: Meta): Promise<Envelope> {
  const args = buildArgs(resource, plan, values);
  const limitKey = Object.entries(plan.args).find(([v2]) => v2 === "limit")?.[1];
  const asked = limitKey !== undefined && typeof args[limitKey] === "number" ? (args[limitKey] as number) : null;
  if (limitKey !== undefined) delete args[limitKey];
  const eq = { ...(plan.where ?? {}), ...args };

  const page = await callView(ctx, plan.endpoint, eq, plan.order, asked ?? VIEW_PAGE);
  const n = page.rows.length;
  const total = page.total;
  const want = asked === null ? total : total === null ? null : Math.min(asked, total);
  const cut = total === null ? asked === null && n >= VIEW_PAGE : want !== null && n < want;
  if (cut) {
    const narrow = Object.keys(plan.args).filter((k) => k !== "limit");
    const how = narrow.length ? `Narrow with ${narrow.join(" or ")}, or ask` : "Ask";
    const held = total === null ? `at least ${n}` : String(total);
    throw new ApiError(
      400,
      "over_limit",
      `api.${plan.endpoint} holds ${held} rows for this selection, more than one page (${n} served); ` +
        `the gateway refuses rather than trims. ${how} for the first N (ordered ${plan.order ?? "as stored"}) with limit. ` +
        `Cursors arrive in #1052 child 6/8.`,
      "limit",
    );
  }
  meta.rows_total = total;
  meta.truncated = total !== null && n < total;
  return envelope(applySelections(plan, values, page.rows), meta);
}
