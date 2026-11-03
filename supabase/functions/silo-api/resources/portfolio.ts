// silo-api resource `portfolio`: diagnose a portfolio (#1058). POST only.
//
// kind, month and the hidden parameters come in the query string; the lists
// come in a JSON body (params.ts parseBody): id, and for resolve names,
// quotas and quota_dates. One kind per api.portfolio_* function, each a
// read-only rpc: resolve, fees, fee_peers, lookthrough, movement,
// instruments, fund_terms, equivalents, debenture_returns. id maps to the
// function's list (p_cnpjs, p_codes, p_classes or p_tickers). Each function
// caps its lists and refuses above the cap (over_limit), never trims.
//
// Not served: portfolio_credit_returns (held back with the ANBIMA-linked
// endpoints, docs/planning/API_V2.md section 8). fees, fee_peers, movement
// and equivalents read the ANBIMA class LABEL as filed in the CVM Extrato
// (cvm_fi_extrato.classe_anbima); none reads an anbima_* table.

import { ApiError } from "../errors.ts";
import type { Envelope } from "../envelope.ts";
import type { ParsedRequest } from "../params.ts";
import type { CallContext } from "../postgrest.ts";
import { RESOURCES_BY_NAME } from "../registry.ts";
import { runKind } from "./run.ts";

const PORTFOLIO = RESOURCES_BY_NAME.get("portfolio")!;

/** The body list each kind cannot run without. */
function requiredList(kind: string): string {
  return kind === "resolve" ? "names" : "id";
}

export async function portfolio(req: ParsedRequest, ctx: CallContext): Promise<Envelope> {
  const kindName = req.kind ?? "resolve";
  const plan = PORTFOLIO.kinds?.[kindName];
  if (!plan) throw new ApiError(500, "internal", `portfolio has no kind \`${kindName}\` in the registry.`);
  const body = req.body ?? {};

  // A list the kind cannot use is refused, never ignored (an empty list is no value).
  for (const [name, list] of Object.entries(body)) {
    if (list.length && !(name in plan.args)) {
      const takers = Object.entries(PORTFOLIO.kinds ?? {}).filter(([, k]) => name in k.args).map(([n]) => n);
      throw new ApiError(400, "bad_request", `${name} does not apply to portfolio kind=${kindName}; it applies to kind ${takers.join(", ")}. Leave it out, or change kind.`, name);
    }
  }
  const need = requiredList(kindName);
  if (!body[need]?.length) {
    throw new ApiError(
      400,
      "bad_request",
      `portfolio kind=${kindName} needs a non-empty \`${need}\` list in the JSON body, e.g. {"${need}": [...]}. See /v2/portfolio?help.`,
      need,
    );
  }

  const env = await runKind(PORTFOLIO, { ...req, kind: kindName }, ctx, {
    args: (p, _values, args) => {
      const out = { ...args };
      for (const [name, pName] of Object.entries(p.args)) if (body[name]?.length) out[pName] = body[name];
      return out;
    },
  });
  env.meta.body = body;
  return env;
}
