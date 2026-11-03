// silo-api: run one registry kind. Shared by every resource module.
//
// One kind = one plan = one api.* call, then the declared selections. The
// resource modules (search.ts, coverage.ts) add only what the registry cannot
// declare.

import { ApiError } from "../errors.ts";
import { type Envelope, envelope } from "../envelope.ts";
import { applySelections, buildArgs, checkApplicable, type ParsedRequest, selectPlan } from "../params.ts";
import { callRpc, type CallContext } from "../postgrest.ts";
import type { ResourceSpec } from "../registry.ts";

export async function runKind(resource: ResourceSpec, req: ParsedRequest, ctx: CallContext): Promise<Envelope> {
  const kindName = req.kind;
  const kind = kindName ? resource.kinds?.[kindName] : undefined;
  if (!kindName || !kind) throw new ApiError(500, "internal", `${resource.name} has no kind \`${kindName}\` in the registry.`);

  const plan = selectPlan(kind, req.values);
  checkApplicable(resource, kindName, plan, req.values);
  const result = await callRpc(ctx, plan.endpoint, buildArgs(resource, plan, req.values));

  let rows: Record<string, unknown>[];
  if (plan.single) {
    rows = result === null ? [] : [result as Record<string, unknown>];
  } else if (Array.isArray(result)) {
    rows = result as Record<string, unknown>[];
  } else {
    throw new ApiError(500, "internal", `api.${plan.endpoint} returned a single value where the registry expects rows.`);
  }

  return envelope(applySelections(plan, req.values, rows), {
    resource: resource.name,
    kind: kindName,
    request: req.values,
    id_known: null,
    endpoint: `api.${plan.endpoint}`,
  });
}
