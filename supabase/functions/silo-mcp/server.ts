// silo-mcp server wiring (index.ts serves it) — a read-only remote MCP server
// over SILO's schema `api`.
//
// Streamable HTTP, stateless: createMcpHandler builds a fresh McpServer per
// request (Supabase's recommended pattern for Edge Functions,
// https://supabase.com/docs/guides/getting-started/byo-mcp). Every tool is one
// PostgREST request with the public key; see tools.ts for the behaviour.
//
// Public: verify_jwt = false (supabase/config.toml, or --no-verify-jwt on
// deploy). The caller's own headers are never forwarded, so every call runs at
// the anonymous tier.

import { createMcpHandler, fromJsonSchema, McpServer } from "@modelcontextprotocol/server";

import { CONTRACT_VERSION } from "./contract.generated.ts";
import { callTool, configFromEnv, SERVER_INSTRUCTIONS, TOOLS } from "./tools.ts";

export interface ServerDeps {
  fetchImpl?: typeof fetch;
  env?: (name: string) => string | undefined;
}

export function buildServer(deps: ServerDeps = {}): McpServer {
  const fetchImpl = deps.fetchImpl ?? fetch;
  const cfg = configFromEnv(deps.env ?? ((name) => Deno.env.get(name)));
  const server = new McpServer(
    { name: "silo", title: "SILO — Brazilian public financial data (read-only)", version: `contract-${CONTRACT_VERSION}` },
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
      (args: unknown) => callTool(tool.name, args, cfg, fetchImpl) as any,
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
  const handler = createMcpHandler(() => buildServer(deps));
  return async (req: Request) => {
    if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: CORS });
    const res = await handler.fetch(req);
    const headers = new Headers(res.headers);
    for (const [k, v] of Object.entries(CORS)) headers.set(k, v);
    return new Response(res.body, { status: res.status, statusText: res.statusText, headers });
  };
}
