// silo-api server wiring (index.ts serves it): the v2 gateway over SILO's
// schema `api`. Spec: docs/planning/API_V2.md.
//
// Paths, after the function prefix (/functions/v1/silo-api):
//   GET /v2/                     the 14 resources, one line each
//   GET /v2/<resource>           data, in the one envelope (envelope.ts)
//   GET /v2/<resource>?help      kinds, main parameters, defaults, endpoints
//   GET /v2/<resource>?help=all  the same, with the hidden parameters
//   POST /v2/portfolio           the one POST (#1058): query parameters plus a
//                                JSON body of lists; still read-only rpc calls
//
// Public: verify_jwt = false (supabase/config.toml, or --no-verify-jwt on
// deploy). Every call is one PostgREST request with the publishable key; a
// caller's Bearer JWT is forwarded so the signed-in tier applies (postgrest.ts).

import { ApiError } from "./errors.ts";
import { CORS, type Envelope, envelope, errorResponse, json } from "./envelope.ts";
import { acceptedParams, parseBody, type ParsedRequest, parseQuery } from "./params.ts";
import { type BridgeConfig, callerBearer, type CallContext, configFromEnv, type FetchLike } from "./postgrest.ts";
import { REGISTRY, RESOURCES_BY_NAME, type ResourceSpec } from "./registry.ts";
import { coverage } from "./resources/coverage.ts";
import { events } from "./resources/events.ts";
import { fidc } from "./resources/fidc.ts";
import { funds } from "./resources/funds.ts";
import { search } from "./resources/search.ts";
import { prices } from "./resources/prices.ts";
import { statements } from "./resources/statements.ts";
import { panel } from "./resources/panel.ts"; // #1058
import { portfolio } from "./resources/portfolio.ts"; // #1058
import { screens } from "./resources/screens.ts"; // #1058

export interface ServerDeps {
  fetchImpl?: FetchLike;
  env?: (name: string) => string | undefined;
}

type Handler = (req: ParsedRequest, ctx: CallContext) => Promise<Envelope>;

/** The built resources. A registry entry with status built and no handler fails at load. */
export const HANDLERS: Record<string, Handler> = { search, coverage, funds, fidc, events, prices, statements };
Object.assign(HANDLERS, { screens, panel, portfolio }); // #1058

for (const r of REGISTRY.resources) {
  if ((r.status === "built") !== (r.name in HANDLERS)) {
    throw new Error(`silo-api: resource ${r.name} is ${r.status} in registry.ts but ${r.name in HANDLERS ? "has" : "has no"} handler`);
  }
}

/** The resource path, or "" for the index; null for a path outside /v2. */
export function routeOf(pathname: string): string | null {
  let p = pathname.replace(/^\/functions\/v1/, "").replace(/^\/silo-api/, "");
  p = p.replace(/\/+$/, "");
  if (p === "/v2") return "";
  const m = /^\/v2\/([a-z_]+)$/.exec(p);
  return m ? m[1] : null;
}

export function indexBody(): Envelope {
  const data = REGISTRY.resources.map((r) => ({
    name: r.name,
    status: r.status,
    summary: r.summary,
    example: r.example,
    help: `/v2/${r.name}?help`,
  }));
  return envelope(data, { resource: "index", kind: null, request: {}, id_known: null, version: REGISTRY.version });
}

export function helpBody(resource: ResourceSpec, level: "main" | "all"): Envelope {
  const params = acceptedParams(resource).filter((p) => level === "all" || p.visibility === "main");
  const endpoints = new Set<string>();
  for (const k of Object.values(resource.kinds ?? {})) {
    if (k.view_by) for (const v of Object.values(k.view_by.views)) endpoints.add(`api.${v}`);
    else endpoints.add(`api.${k.endpoint}`);
    if (k.when_empty) endpoints.add(`api.${k.when_empty.plan.endpoint}`);
  }
  const help = {
    name: resource.name,
    status: resource.status,
    summary: resource.summary,
    example: resource.example,
    notes: resource.notes,
    default_window_months: resource.window_months,
    kinds: Object.fromEntries(Object.entries(resource.kinds ?? {}).map(([n, k]) => [n, k.doc])),
    parameters: params,
    hidden_parameters: level === "all" ? undefined : "see ?help=all",
    method: resource.method ?? "GET", // #1058: portfolio is POST, with a JSON body of lists
    body: resource.body,
    endpoints: [...endpoints],
  };
  return envelope([help], { resource: resource.name, kind: "help", request: { help: level }, id_known: null });
}

async function handle(req: Request, cfg: BridgeConfig | { error: string }, fetchImpl: FetchLike): Promise<Response> {
  if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: CORS });
  if (req.method !== "GET" && req.method !== "POST") throw new ApiError(405, "bad_request", `${req.method} is not served; v2 is GET, and POST for portfolio.`);

  const url = new URL(req.url);
  const route = routeOf(url.pathname);
  if (route === null) throw new ApiError(404, "bad_request", `No such path ${url.pathname}. Start at /v2/.`, "path");
  if (route === "") {
    if (req.method !== "GET") throw new ApiError(405, "bad_request", `${req.method} /v2/ is not served; use GET.`, "method");
    if ([...url.searchParams.keys()].length) {
      const key = [...url.searchParams.keys()][0];
      throw new ApiError(400, "unknown_parameter", `The index takes no parameters; got \`${key}\`.`, key);
    }
    return json(200, indexBody());
  }

  const resource = RESOURCES_BY_NAME.get(route);
  if (!resource) {
    throw new ApiError(404, "bad_request", `No resource \`${route}\`. Resources: ${REGISTRY.resources.map((r) => r.name).join(", ")}.`, "resource");
  }
  // #1058: one method per resource for data. ?help is always a GET.
  const method = resource.method ?? "GET";
  const help = url.searchParams.has("help");
  if (req.method !== (help ? "GET" : method)) {
    const want = help ? "GET" : method;
    throw new ApiError(405, "bad_request", `${req.method} /v2/${resource.name}${help ? "?help" : ""} is not served; use ${want}.`, "method");
  }
  if (help) {
    const parsed = parseQuery(resource, url.searchParams);
    return json(200, helpBody(resource, parsed.help ?? "main"));
  }
  if (resource.status !== "built") {
    throw new ApiError(501, "unavailable", `${resource.name} is planned, not built yet (#1052). /v2/${resource.name}?help describes it.`, "resource");
  }

  const parsed = parseQuery(resource, url.searchParams);
  if (method === "POST") parsed.body = parseBody(resource, await req.text());
  if ("error" in cfg) throw new ApiError(503, "unavailable", `silo-api is misconfigured: ${cfg.error}`);
  const ctx: CallContext = { cfg, fetchImpl, bearer: callerBearer(req.headers.get("authorization"), cfg) };
  return json(200, await HANDLERS[resource.name](parsed, ctx));
}

export function makeHandler(deps: ServerDeps = {}): (req: Request) => Promise<Response> {
  const fetchImpl: FetchLike = deps.fetchImpl ?? ((input, init) => fetch(input, init));
  const cfg = configFromEnv(deps.env ?? ((name) => Deno.env.get(name)));
  return async (req: Request) => {
    try {
      return await handle(req, cfg, fetchImpl);
    } catch (e) {
      if (e instanceof ApiError) return errorResponse(e);
      return errorResponse(new ApiError(500, "internal", `Unexpected gateway error: ${e instanceof Error ? e.message : String(e)}`));
    }
  };
}
