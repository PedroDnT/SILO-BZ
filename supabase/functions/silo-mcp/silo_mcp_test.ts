// Offline tests for silo-mcp. fetch is stubbed: no network, no database.
//
//   deno test supabase/functions/silo-mcp/
//
// The first block exercises tools.ts directly (the behaviour); the second
// drives the real MCP SDK handler end to end over streamable HTTP, so the
// tool list, the annotations and the isError pass-through are checked as an
// MCP client would see them.

import { assert, assertEquals, assertStringIncludes } from "@std/assert";

import { callTool, configFromEnv, SEMANTICS, TOOLS } from "./tools.ts";
import { makeHandler } from "./server.ts";

const MINIMUM = [
  "catalog", "coverage", "metric_coverage", "lookup", "panel", "quote_history", "quote_latest",
  "option_chain", "fund_profile", "fund_nav", "search_funds", "fund_holdings", "fund_debentures",
  "fidc_cedentes", "fidc_sacados", "fidc_portfolio", "fidc_tranches", "fidc_aging",
  "screen_zombie_growth", "screen_captive_vehicles", "screen_evergreen_aging", "screen_overdue_securit",
  "screen_dormant_funds", "screen_dormant_trend", "screen_delinquency_drivers",
  "financials", "company_financials", "income_statements", "balance_sheets",
  "cash_flow_statements", "anbima_classes", "inflation",
  "inflation_items", "short_interest", "investor_flow",
];

const ENV: Record<string, string> = {
  SUPABASE_URL: "https://example-ref.supabase.co/",
  SUPABASE_ANON_KEY: "test-anon-key",
};
const env = (name: string) => ENV[name];
const CFG = configFromEnv(env);

interface Captured {
  url: string;
  init: RequestInit;
}

function stubFetch(status: number, body: string, headers: Record<string, string> = {}) {
  const calls: Captured[] = [];
  const impl = (input: string | URL | Request, init?: RequestInit): Promise<Response> => {
    calls.push({ url: String(input), init: init ?? {} });
    return Promise.resolve(
      new Response(body, { status, headers: { "content-type": "application/json", ...headers } }),
    );
  };
  return { calls, impl };
}

// ---------------------------------------------------------------- tools.ts --

Deno.test("tool list contains the minimum set", () => {
  const names = new Set(TOOLS.map((t) => t.name));
  for (const name of MINIMUM) assert(names.has(name), `missing tool ${name}`);
  assertEquals(names.size, TOOLS.length, "duplicate tool names");
});

Deno.test("every tool is read-only, closed-world, and carries the refusal semantics", () => {
  for (const tool of TOOLS) {
    assertEquals(tool.annotations.readOnlyHint, true, tool.name);
    assertEquals(tool.annotations.openWorldHint, false, tool.name);
    assertEquals(tool.annotations.destructiveHint, false, tool.name);
    assertStringIncludes(tool.description, SEMANTICS, tool.name);
    assertStringIncludes(tool.description, "22023", tool.name);
    assert(tool.kind === "rpc" ? tool.path.startsWith("/rpc/") : !tool.path.includes("rpc"), tool.name);
  }
});

Deno.test("config reads the anon key, falls back to publishable keys, refuses a secret key", () => {
  assertEquals(CFG, { restUrl: "https://example-ref.supabase.co/rest/v1", anonKey: "test-anon-key" });
  const pub = configFromEnv((n) =>
    ({ SUPABASE_URL: "https://x.supabase.co", SUPABASE_PUBLISHABLE_KEYS: '{"default":"sb_publishable_abc"}' } as Record<string, string>)[n]
  );
  assertEquals(pub, { restUrl: "https://x.supabase.co/rest/v1", anonKey: "sb_publishable_abc" });
  const secret = configFromEnv((n) => ({ SUPABASE_URL: "https://x", SUPABASE_ANON_KEY: "sb_secret_zzz" } as Record<string, string>)[n]);
  assert("error" in secret);
});

Deno.test("an RPC call is exactly one POST to /rpc/<fn> with the api profile headers", async () => {
  const rows = [{ id: "PETR4", asset_class: "equity", date: "2026-08-31", metric: "close", value: 37.1 }];
  const { calls, impl } = stubFetch(200, JSON.stringify(rows));
  const args = { p_ids: ["PETR4"], p_metrics: ["close"], p_freq: "month" };
  const res = await callTool("panel", args, CFG, impl);

  assertEquals(calls.length, 1);
  const [call] = calls;
  assertEquals(call.url, "https://example-ref.supabase.co/rest/v1/rpc/panel");
  assertEquals(call.init.method, "POST");
  assertEquals(JSON.parse(String(call.init.body)), args);
  const h = call.init.headers as Record<string, string>;
  assertEquals(h["apikey"], "test-anon-key");
  assertEquals(h["Accept-Profile"], "api");
  assertEquals(h["Content-Profile"], "api");
  assertEquals(h["Content-Type"], "application/json");
  assertEquals(h["Authorization"], undefined, "the publishable key is never sent as a Bearer token");

  assertEquals(res.isError, undefined);
  const text = res.content[0].text;
  assertStringIncludes(text, "rows: 1");
  assertStringIncludes(text, "provenance: POST /rest/v1/rpc/panel · schema api · params " + JSON.stringify(args));
  assertStringIncludes(text, JSON.stringify(rows));
});

Deno.test("a no-argument RPC sends {}", async () => {
  const { calls, impl } = stubFetch(200, "[]");
  const res = await callTool("coverage", {}, CFG, impl);
  assertEquals(calls[0].url, "https://example-ref.supabase.co/rest/v1/rpc/coverage");
  assertEquals(calls[0].init.body, "{}");
  assertStringIncludes(res.content[0].text, "rows: 0");
});

Deno.test("a PostgREST error passes through verbatim as isError, with one request and no retry", async () => {
  const body = JSON.stringify({
    code: "22023",
    details: null,
    hint: "page with p_after or narrow the window",
    message: "api.panel: window would return 1432 rows; the page is 1000",
  });
  const { calls, impl } = stubFetch(400, body);
  const res = await callTool("panel", { p_ids: ["PETR4"], p_freq: "day", p_from: "2019-01-01" }, CFG, impl);
  assertEquals(calls.length, 1, "never retried into a different answer");
  assertEquals(res.isError, true);
  const text = res.content[0].text;
  assertStringIncludes(text, "HTTP 400");
  assertStringIncludes(text, body, "the body is carried verbatim");
  assertStringIncludes(text, "22023");
  assertStringIncludes(text, "provenance: POST /rest/v1/rpc/panel");
});

Deno.test("unknown RPC arguments are refused before any request is sent", async () => {
  const { calls, impl } = stubFetch(200, "[]");
  const res = await callTool("lookup", { p_query: "PETR4", sql: "select 1" }, CFG, impl);
  assertEquals(res.isError, true);
  assertEquals(calls.length, 0);
});

Deno.test("a view call is one GET with encoded column filters and an estimated count", async () => {
  const { calls, impl } = stubFetch(200, JSON.stringify([{ ticker: "PETR4" }]), { "content-range": "0-0/1" });
  const res = await callTool(
    "short_interest",
    {
      filters: { ticker: "eq.PETR4", trade_date: "gte.2026-09-01" },
      select: "ticker,trade_date,pct_float,float_basis",
      order: "trade_date.desc",
      limit: 10,
    },
    CFG,
    impl,
  );
  assertEquals(calls.length, 1);
  const url = new URL(calls[0].url);
  assertEquals(url.origin + url.pathname, "https://example-ref.supabase.co/rest/v1/short_interest");
  assertEquals(url.searchParams.get("ticker"), "eq.PETR4");
  assertEquals(url.searchParams.get("trade_date"), "gte.2026-09-01");
  assertEquals(url.searchParams.get("order"), "trade_date.desc");
  assertEquals(url.searchParams.get("limit"), "10");
  assertEquals(calls[0].init.method, "GET");
  const h = calls[0].init.headers as Record<string, string>;
  assertEquals(h["Accept-Profile"], "api");
  assertEquals(h["Prefer"], "count=estimated");
  assertEquals(calls[0].init.body, undefined);
  assertStringIncludes(res.content[0].text, "content-range: 0-0/1");
});

Deno.test("a cut view page says so instead of looking complete", async () => {
  const page = JSON.stringify(Array.from({ length: 1000 }, (_, i) => ({ i })));
  const { impl } = stubFetch(200, page, { "content-range": "0-999/4210" });
  const res = await callTool("investor_flow", { order: "reference_date.asc" }, CFG, impl);
  assertEquals(res.isError, undefined);
  assertStringIncludes(res.content[0].text, "rows: 1000");
  assertStringIncludes(res.content[0].text, "PARTIAL PAGE");
});

Deno.test("view arguments cannot smuggle a logic tree, an unknown column, or a raw operator", async () => {
  const { calls, impl } = stubFetch(200, "[]");
  for (
    const bad of [
      { or: "(ticker.eq.A,ticker.eq.B)" },
      { filters: { not_a_column: "eq.1" } },
      { filters: { ticker: "PETR4" } },
      { select: "ticker,sum(x)" },
      { limit: 5000 },
    ]
  ) {
    const res = await callTool("short_interest", bad, CFG, impl);
    assertEquals(res.isError, true, JSON.stringify(bad));
  }
  assertEquals(calls.length, 0);
});

Deno.test("a network failure is an error, never a fabricated answer", async () => {
  const impl = () => Promise.reject(new TypeError("connection reset"));
  const res = await callTool("coverage", {}, CFG, impl);
  assertEquals(res.isError, true);
  assertStringIncludes(res.content[0].text, "connection reset");
});

// ------------------------------------------------ through the MCP SDK -------

async function rpc(handler: (r: Request) => Promise<Response>, method: string, params: unknown, id = 1) {
  const res = await handler(
    new Request("http://localhost/silo-mcp", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        accept: "application/json, text/event-stream",
        "mcp-protocol-version": "2025-06-18",
      },
      body: JSON.stringify({ jsonrpc: "2.0", id, method, params }),
    }),
  );
  const text = await res.text();
  assertEquals(res.status, 200, text);
  // A stateless streamable-HTTP answer is JSON, or one SSE `data:` frame.
  const payload = text.trimStart().startsWith("{")
    ? text
    : text.split("\n").filter((l) => l.startsWith("data:")).map((l) => l.slice(5)).join("");
  return { res, body: JSON.parse(payload) };
}

Deno.test("MCP: initialize advertises tools and SILO's instructions", async () => {
  const handler = makeHandler({ env, fetchImpl: stubFetch(200, "[]").impl });
  const { body } = await rpc(handler, "initialize", {
    protocolVersion: "2025-06-18",
    capabilities: {},
    clientInfo: { name: "test", version: "0" },
  });
  assert(body.result, JSON.stringify(body));
  assert(body.result.capabilities.tools);
  assertStringIncludes(body.result.instructions, "22023");
});

Deno.test("MCP: tools/list returns every tool, read-only, with a JSON input schema", async () => {
  const handler = makeHandler({ env, fetchImpl: stubFetch(200, "[]").impl });
  const { body } = await rpc(handler, "tools/list", {});
  const tools = body.result.tools as Array<{
    name: string;
    annotations?: { readOnlyHint?: boolean; openWorldHint?: boolean };
    inputSchema: { type: string; properties: Record<string, unknown>; required?: string[] };
  }>;
  assertEquals(tools.length, TOOLS.length);
  for (const name of MINIMUM) assert(tools.some((t) => t.name === name), `missing ${name}`);
  for (const t of tools) {
    assertEquals(t.annotations?.readOnlyHint, true, t.name);
    assertEquals(t.annotations?.openWorldHint, false, t.name);
    assertEquals(t.inputSchema?.type, "object", t.name);
  }
  const panel = tools.find((t) => t.name === "panel")!;
  assert("p_ids" in panel.inputSchema.properties);
  assertEquals(panel.inputSchema.required, ["p_ids"]);
});

Deno.test("MCP: tools/call maps to one PostgREST request and returns rows + provenance", async () => {
  const stub = stubFetch(200, JSON.stringify([{ id: "12345678000199", kind: "fund" }]));
  const handler = makeHandler({ env, fetchImpl: stub.impl });
  const { body } = await rpc(handler, "tools/call", { name: "lookup", arguments: { p_query: "PETR4" } });
  assertEquals(stub.calls.length, 1);
  assertEquals(stub.calls[0].url, "https://example-ref.supabase.co/rest/v1/rpc/lookup");
  assertEquals(JSON.parse(String(stub.calls[0].init.body)), { p_query: "PETR4" });
  assert(!body.result.isError, JSON.stringify(body));
  assertStringIncludes(body.result.content[0].text, "rows: 1");
  assertStringIncludes(body.result.content[0].text, "provenance: POST /rest/v1/rpc/lookup");
});

Deno.test("MCP: typed arguments (dates, integers, nullable enums) validate and pass through", async () => {
  const stub = stubFetch(200, "[]");
  const handler = makeHandler({ env, fetchImpl: stub.impl });
  const args = { p_cnpj: "12345678000199", p_kind: null, p_from: "2025-01-01", p_limit: 50 };
  const { body } = await rpc(handler, "tools/call", { name: "fidc_portfolio", arguments: args });
  assert(!body.result?.isError, JSON.stringify(body));
  assertEquals(JSON.parse(String(stub.calls[0].init.body)), args);
});

Deno.test("MCP: a PostgREST error comes back as isError with the body verbatim", async () => {
  const errBody = '{"code":"22023","details":null,"hint":null,"message":"api.panel: at most 3 ids for anonymous callers"}';
  const stub = stubFetch(400, errBody);
  const handler = makeHandler({ env, fetchImpl: stub.impl });
  const { body } = await rpc(handler, "tools/call", {
    name: "panel",
    arguments: { p_ids: ["A", "B", "C", "D"] },
  });
  assertEquals(stub.calls.length, 1);
  assertEquals(body.result.isError, true);
  assertStringIncludes(body.result.content[0].text, errBody);
});

Deno.test("MCP: CORS preflight is answered", async () => {
  const handler = makeHandler({ env, fetchImpl: stubFetch(200, "[]").impl });
  const res = await handler(new Request("http://localhost/silo-mcp", { method: "OPTIONS" }));
  assertEquals(res.status, 204);
  assertEquals(res.headers.get("access-control-allow-origin"), "*");
});
