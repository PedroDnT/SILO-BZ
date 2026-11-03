// silo-mcp-v2 server wiring (index.ts serves it): 14 read-only tools, one per
// v2 resource, over the silo-api gateway (tools.ts).
//
// Streamable HTTP, stateless: createMcpHandler builds a fresh McpServer per
// request, the same pattern as silo-mcp (v1), which stays untouched beside it.
//
// Public: verify_jwt = false (supabase/config.toml, or --no-verify-jwt on
// deploy). The MCP request's Authorization header, when present, is handed to
// the gateway, which forwards a user JWT so the signed-in tier applies and
// treats the publishable key sent as a Bearer as anonymous. Nothing else of
// the caller's is forwarded.

import { createMcpHandler, fromJsonSchema, McpServer } from "@modelcontextprotocol/server";

import { REGISTRY } from "../silo-api/registry.ts";
import { callTool, type FetchLike, SERVER_INSTRUCTIONS, TOOLS } from "./tools.ts";

export interface ServerDeps {
  fetchImpl?: FetchLike;
  env?: (name: string) => string | undefined;
}

export function buildServer(deps: ServerDeps = {}, authorization: string | null = null): McpServer {
  const fetchImpl: FetchLike = deps.fetchImpl ?? ((input, init) => fetch(input, init));
  const env = deps.env ?? ((name: string) => Deno.env.get(name));
  const server = new McpServer(
    { name: "silo-v2", title: "SILO v2 (preview): Brazilian public financial data, read-only", version: `api-${REGISTRY.version}` },
    { instructions: SERVER_INSTRUCTIONS },
  );
  for (const tool of TOOLS) {
    server.registerTool(
      tool.name,
      {
        title: tool.title,
        description: tool.description,
        // deno-lint-ignore no-explicit-any
        inputSchema: fromJsonSchema(tool.inputSchema as any),
        annotations: { ...tool.annotations, title: tool.title },
      },
      // deno-lint-ignore no-explicit-any
      (args: unknown) => callTool(tool.name, args, { env, fetchImpl, authorization }) as any,
    );
  }
  return server;
}

const CORS: Record<string, string> = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "POST, GET, DELETE, OPTIONS",
  "Access-Control-Allow-Headers":
    "authorization, x-client-info, apikey, content-type, accept, mcp-session-id, mcp-protocol-version, last-event-id",
  "Access-Control-Expose-Headers": "mcp-session-id, mcp-protocol-version",
};

export function makeHandler(deps: ServerDeps = {}): (req: Request) => Promise<Response> {
  const handler = createMcpHandler((ctx) => buildServer(deps, ctx.requestInfo?.headers.get("authorization") ?? null));
  return async (req: Request) => {
    if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: CORS });
    const res = await handler.fetch(req);
    const headers = new Headers(res.headers);
    for (const [k, v] of Object.entries(CORS)) headers.set(k, v);
    return new Response(res.body, { status: res.status, statusText: res.statusText, headers });
  };
}
