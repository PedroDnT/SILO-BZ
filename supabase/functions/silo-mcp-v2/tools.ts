// silo-mcp-v2: the 14 v2 tools and the call into the silo-api gateway.
//
// No npm imports here on purpose: this module is the whole behaviour of the
// server and is tested offline with a stubbed fetch. server.ts only wires it
// into the MCP SDK's streamable-HTTP handler.
//
// Nothing about a resource is decided here. The tools, their parameters,
// enums and defaults come from the silo-api registry (imported, never
// copied), and a call runs the silo-api gateway itself, in process:
//   * one tool per registry resource, named silo_<resource>;
//   * the resource's main parameters and its shared ones are top-level
//     arguments; its hidden parameters go in one optional `options` object;
//     portfolio's JSON lists go in `body`;
//   * the result is the gateway's envelope, as the gateway returned it;
//   * an error is the gateway's error object, verbatim (isError);
//   * the only key the gateway sends PostgREST is the public one. A caller's
//     own `Authorization: Bearer <user JWT>` is passed to the gateway, which
//     forwards it so the signed-in tier applies (silo-api/postgrest.ts). The
//     client IP headers are copied too, so an anonymous caller is counted in
//     its own rate bucket, not in one shared by every MCP caller (tier.ts).
//
// Spec: docs/planning/API_V2.md (#1052, #1060).

import { ApiError } from "../silo-api/errors.ts";
import { acceptedParams } from "../silo-api/params.ts";
import { type BodySpec, type ParamSpec, REGISTRY, type ResourceSpec, SHARED_NAMES } from "../silo-api/registry.ts";
import { makeHandler as makeGateway } from "../silo-api/server.ts";
import { CLIENT_IP_HEADERS, type Gate } from "../silo-api/tier.ts";
import { idDoc } from "./id_docs.ts";

export const TOOL_PREFIX = "silo_";

export interface ToolAnnotations {
  readOnlyHint: true;
  openWorldHint: false;
  destructiveHint: false;
  idempotentHint: true;
}

export const ANNOTATIONS: ToolAnnotations = Object.freeze({
  readOnlyHint: true,
  openWorldHint: false,
  destructiveHint: false,
  idempotentHint: true,
}) as ToolAnnotations;

export interface V2Tool {
  name: string;
  /** The registry resource this tool calls. */
  resource: string;
  title: string;
  description: string;
  method: "GET" | "POST";
  /** Top-level argument names: main parameters, then shared ones. */
  top: string[];
  /** Hidden parameter names, accepted inside `options`. */
  hidden: string[];
  /** POST body list names, accepted inside `body`. */
  body: string[];
  inputSchema: Record<string, unknown>;
  annotations: ToolAnnotations;
}

// ---------------------------------------------------------------------------
// Schemas, from the registry.
// ---------------------------------------------------------------------------

type Json = Record<string, unknown>;

function defaultText(p: ParamSpec): string {
  const doc = p.default_doc?.replace(/\.$/, "");
  if (p.default === null || p.default === "") return doc || "none";
  return doc ? `${p.default} (${doc})` : String(p.default);
}

/** One parameter's JSON Schema. Enums carry their values and their default. */
export function paramSchema(p: ParamSpec): Json {
  const description = `${p.doc} Default: ${defaultText(p)}.`;
  const hasDefault = p.default !== null && p.default !== "";
  switch (p.type) {
    case "enum":
      return { type: "string", enum: p.values ?? [], ...(hasDefault ? { default: p.default } : {}), description };
    case "date":
      return { type: "string", format: "date", description };
    case "integer":
      return { type: "integer", minimum: p.name === "limit" ? 1 : 0, ...(hasDefault ? { default: p.default } : {}), description };
    case "number":
      return { type: "number", minimum: 0, ...(hasDefault ? { default: p.default } : {}), description };
    case "list":
      return {
        type: "array",
        items: { type: "string" },
        ...(hasDefault ? { default: [p.default] } : {}),
        description: `${description} A JSON list; the gateway receives it comma-separated.`,
      };
    default:
      return { type: "string", ...(hasDefault ? { default: p.default } : {}), description };
  }
}

function bodySchema(b: BodySpec): Json {
  const item = b.items === "number" ? { type: ["number", "null"] } : b.items === "date"
    ? { type: ["string", "null"], format: "date" }
    : { type: ["string", "null"] };
  return { type: "array", items: item, description: `${b.doc} Default: ${b.default_doc}.` };
}

function firstSentence(s: string): string {
  const i = s.indexOf(". ");
  return i < 0 ? s.replace(/\.$/, "") : s.slice(0, i);
}

/** Said in every tool description: what the result is and how to read it. */
export const SEMANTICS =
  "Read-only. The result is the v2 envelope as the gateway returns it: data (always a list), meta (resource, kind, " +
  "request with every default applied, id_known, endpoint), and next_page_url only when more rows remain. To read the " +
  "next page, call this tool again with only `cursor` set to the cursor in next_page_url (a POST tool takes `body` " +
  "too: the same body as the first page, unchanged). A call stops at the tier's " +
  "rows-per-call cap with meta.tier_cap_reached; nothing is cut silently. Errors come back verbatim (isError) as " +
  "{error: {code, message, target, innererror}}; over_limit means narrow the request, not retry it. null means not " +
  "declared at source: never fill it or read it as zero.";

function describe(r: ResourceSpec, hidden: ParamSpec[]): string {
  const parts: string[] = [r.summary, `Example: ${r.example}`];
  const kinds = Object.entries(r.kinds ?? {});
  if (kinds.length > 1) parts.push(`Kinds:\n${kinds.map(([n, k]) => `- ${n}: ${firstSentence(k.doc)}.`).join("\n")}`);
  if (r.window_months) parts.push(`With no from, a dated kind reads the last ${r.window_months} months to \`to\`.`);
  if (hidden.length) {
    parts.push(`Hidden parameters, in options: ${hidden.map((p) => `${p.name} (default ${defaultText(p)})`).join("; ")}.`);
  }
  if (hidden.some((p) => p.name === "fields")) {
    parts.push("fields defaults to core (concise rows); options.fields=all is the detailed form, every column the endpoint publishes.");
  }
  if (r.method === "POST") parts.push("The lists go in body; every other argument goes in the query string the gateway reads.");
  for (const n of r.notes ?? []) parts.push(n);
  parts.push(SEMANTICS);
  return parts.join("\n\n");
}

export function buildTool(r: ResourceSpec): V2Tool {
  const all = acceptedParams(r);
  const main = all.filter((p) => p.visibility === "main" && !SHARED_NAMES.includes(p.name));
  const shared = all.filter((p) => SHARED_NAMES.includes(p.name));
  // The gateway reads cursor on every resource (server.ts), declared or not.
  if (!shared.some((p) => p.name === "cursor")) {
    const c = REGISTRY.shared_parameters.cursor;
    shared.push({ name: "cursor", visibility: "main", type: "string", default: c.default, default_doc: c.default_doc, doc: c.doc });
  }
  const hidden = all.filter((p) => p.visibility === "hidden");
  const properties: Json = {};
  for (const p of [...main, ...shared]) properties[p.name] = paramSchema(p);
  // id means something different on each resource (id_docs.ts), never the shared generic sentence.
  const id = idDoc(r);
  if (id && properties.id) properties.id = { ...(properties.id as Json), description: `${id} Default: none.` };
  if (hidden.length) {
    properties.options = {
      type: "object",
      description: `Hidden parameters of ${r.name}. Leave it out for every default.`,
      properties: Object.fromEntries(hidden.map((p) => [p.name, paramSchema(p)])),
      additionalProperties: false,
    };
  }
  const body = r.body ?? [];
  if (body.length) {
    properties.body = {
      type: "object",
      description: `The JSON body of lists that POST /v2/${r.name} takes.`,
      properties: Object.fromEntries(body.map((b) => [b.name, bodySchema(b)])),
      additionalProperties: false,
    };
  }
  return {
    name: `${TOOL_PREFIX}${r.name}`,
    resource: r.name,
    title: `SILO v2 ${r.name}: ${firstSentence(r.summary)}`,
    description: describe(r, hidden),
    method: r.method ?? "GET",
    top: [...main, ...shared].map((p) => p.name),
    hidden: hidden.map((p) => p.name),
    body: body.map((b) => b.name),
    inputSchema: { type: "object", properties, additionalProperties: false },
    annotations: ANNOTATIONS,
  };
}

export const TOOLS: V2Tool[] = REGISTRY.resources.map(buildTool);
export const TOOLS_BY_NAME: Map<string, V2Tool> = new Map(TOOLS.map((t) => [t.name, t]));

export const SERVER_INSTRUCTIONS =
  `SILO v2 (preview): Brazilian public financial data (CVM funds and FIDC internals, listed-company filings, B3 quotes, ` +
  `derivatives, lending and flows, BACEN and IBGE macro), read-only, as ${TOOLS.length} tools, one per v2 resource. ` +
  "Procedure: (1) silo_coverage before claiming freshness; (2) silo_search to resolve a name to an id, never guess a " +
  "ticker or CNPJ; (3) call the resource with id and kind; every other parameter has a default, echoed in " +
  "meta.request. Page with cursor from next_page_url. Errors are returned verbatim: over_limit means narrow the call. " +
  "Never fabricate a price, NAV or match; null stays null.";

// ---------------------------------------------------------------------------
// The call: arguments to one gateway request, run in process.
// ---------------------------------------------------------------------------

export interface TextContent {
  type: "text";
  text: string;
}

export interface ToolResult {
  content: TextContent[];
  isError?: boolean;
  [key: string]: unknown;
}

export type FetchLike = (input: string, init: RequestInit) => Promise<Response>;
type EnvGetter = (name: string) => string | undefined;

function asObject(v: unknown, what: string): Record<string, unknown> {
  if (v === undefined || v === null) return {};
  if (typeof v !== "object" || Array.isArray(v)) throw new ApiError(400, "bad_request", `${what} must be a JSON object.`, what);
  return v as Record<string, unknown>;
}

function scalar(name: string, v: unknown): string {
  if (Array.isArray(v)) {
    for (const x of v) {
      if (typeof x !== "string" && typeof x !== "number") throw new ApiError(400, "bad_request", `${name} must be a list of strings.`, name);
    }
    return v.join(",");
  }
  if (typeof v === "string" || typeof v === "number" || typeof v === "boolean") return String(v);
  throw new ApiError(400, "bad_request", `${name} must be a string, a number or a list.`, name);
}

export interface PlannedCall {
  method: "GET" | "POST";
  /** /v2/<resource>?<query>, for the provenance line. */
  path: string;
  query: URLSearchParams;
  body?: string;
}

/** Tool arguments to the gateway request. Throws ApiError for a bad argument. */
export function planCall(tool: V2Tool, rawArgs: unknown): PlannedCall {
  const args = asObject(rawArgs, "arguments");
  const query = new URLSearchParams();
  const put = (k: string, v: unknown) => {
    if (v === undefined || v === null) return;
    query.set(k, scalar(k, v));
  };
  for (const [k, v] of Object.entries(args)) {
    if (k === "options" || (k === "body" && tool.body.length)) continue;
    if (tool.top.includes(k)) {
      put(k, v);
      continue;
    }
    const where = tool.hidden.includes(k) ? `${k} is a hidden parameter: put it in options.` : `${tool.name} has no argument \`${k}\`.`;
    throw new ApiError(400, "unknown_parameter", `${where} Top-level arguments: ${tool.top.join(", ")}.`, k);
  }
  const options = asObject(args.options, "options");
  for (const [k, v] of Object.entries(options)) {
    if (!tool.hidden.includes(k)) {
      const where = tool.top.includes(k) ? `${k} is a top-level argument, not an option.` : `${tool.name} has no option \`${k}\`.`;
      throw new ApiError(400, "unknown_parameter", `${where} Options: ${tool.hidden.join(", ") || "(none)"}.`, `options.${k}`);
    }
    put(k, v);
  }
  let body: string | undefined;
  if (tool.method === "POST") {
    // The gateway pages a POST only with the body of the first page (its digest rides in the cursor).
    if (args.cursor !== undefined && args.cursor !== null && (args.body === undefined || args.body === null)) {
      throw new ApiError(
        400,
        "bad_request",
        `A cursor on ${tool.name} needs the same body as the first page: call it again with that body, unchanged, and this cursor.`,
        "body",
      );
    }
    body = JSON.stringify(asObject(args.body, "body"));
  }
  const qs = query.toString();
  return { method: tool.method, path: `/v2/${tool.resource}${qs ? `?${qs}` : ""}`, query, body };
}

function errorResult(text: string, provenance: string): ToolResult {
  return { content: [{ type: "text", text }, { type: "text", text: provenance }], isError: true };
}

/** The silo-api gateway: one Request in, one Response out (silo-api/server.ts makeHandler). */
export type Gateway = (req: Request) => Promise<Response>;

export interface CallDeps {
  env: EnvGetter;
  fetchImpl: FetchLike;
  /**
   * The gateway to call. server.ts builds ONE per MCP handler (index.ts
   * builds the handler once at module level), so the gateway's 60 s tier
   * cache outlives a call. Left out, a gateway is built for this call.
   */
  gateway?: Gateway;
  /** Only when gateway is left out: the gateway's Postgres gate (tests inject one). */
  gate?: Gate;
  /**
   * The inbound MCP request's headers. Authorization and the client IP
   * headers the gateway's rate limit reads (CLIENT_IP_HEADERS) are copied to
   * the gateway request; nothing else is.
   */
  headers?: Headers | null;
}

/** Copied from the MCP request to the gateway request: the token, and the caller's address. */
export const FORWARDED_HEADERS: readonly string[] = ["authorization", ...CLIENT_IP_HEADERS];

export function makeGatewayFor(deps: Pick<CallDeps, "env" | "fetchImpl" | "gate">): Gateway {
  return makeGateway({ env: deps.env, fetchImpl: deps.fetchImpl, gate: deps.gate });
}

/** The gateway's base URL for a request: <SUPABASE_URL>/functions/v1/silo-api. */
export function gatewayBase(env: EnvGetter): string {
  const base = (env("SUPABASE_URL") ?? "").trim().replace(/\/+$/, "");
  // With no SUPABASE_URL the gateway answers 503 (misconfigured) before any fetch.
  return `${base || "http://localhost"}/functions/v1/silo-api`;
}

export async function callTool(name: string, rawArgs: unknown, deps: CallDeps): Promise<ToolResult> {
  const tool = TOOLS_BY_NAME.get(name);
  if (!tool) {
    const e = new ApiError(404, "bad_request", `Unknown tool \`${name}\`. Tools: ${TOOLS.map((t) => t.name).join(", ")}.`, "tool");
    return errorResult(JSON.stringify(e.body()), "No request was sent.");
  }
  let plan: PlannedCall;
  try {
    plan = planCall(tool, rawArgs);
  } catch (e) {
    if (e instanceof ApiError) return errorResult(JSON.stringify(e.body()), `No request was sent (${tool.name}).`);
    throw e;
  }
  const headers: Record<string, string> = { accept: "application/json" };
  if (plan.body !== undefined) headers["content-type"] = "application/json";
  for (const h of FORWARDED_HEADERS) {
    const v = deps.headers?.get(h);
    if (v) headers[h] = v;
  }
  const gateway = deps.gateway ?? makeGatewayFor(deps);
  const req = new Request(`${gatewayBase(deps.env)}${plan.path}`, { method: plan.method, headers, body: plan.body });
  const res = await gateway(req);
  const text = await res.text();
  const provenance = `provenance: ${plan.method} ${plan.path} (silo-api gateway) · HTTP ${res.status}`;
  if (!res.ok) return errorResult(text, provenance);
  const content: TextContent[] = [{ type: "text", text }, { type: "text", text: provenance }];
  try {
    const next = (JSON.parse(text) as { next_page_url?: string }).next_page_url;
    const cursor = next ? new URL(next).searchParams.get("cursor") : null;
    if (cursor) {
      const text = plan.body === undefined
        ? `More rows remain. Next page: call ${tool.name} with {"cursor": "${cursor}"} and nothing else.`
        : `More rows remain. Next page: call ${tool.name} again with the same body and this cursor, and nothing else: ` +
          `{"body": ${plan.body}, "cursor": "${cursor}"}.`;
      content.push({ type: "text", text });
    }
  } catch {
    // The envelope is returned verbatim either way; no hint when it is not JSON.
  }
  return { content };
}
