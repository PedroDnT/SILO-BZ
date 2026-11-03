// Offline tests for silo-mcp-v2. fetch is stubbed: no network, no database.
//
//   deno test --allow-env supabase/functions/silo-mcp-v2/
//
// The first block exercises tools.ts directly (the 14 tools and the call into
// the silo-api gateway); the second drives the real MCP SDK handler end to
// end over streamable HTTP, as an MCP client would see it.
// tests/test_mcp_v2.py checks the tool list against the registry offline.

import { assert, assertEquals, assertStringIncludes } from "@std/assert";

import { acceptedParams } from "../silo-api/params.ts";
import { REGISTRY, SHARED_NAMES } from "../silo-api/registry.ts";
import { callTool, paramSchema, planCall, TOOLS, TOOLS_BY_NAME } from "./tools.ts";
import { idDoc } from "./id_docs.ts";
// A static JSON import needs no --allow-read: the generated v2 OpenAPI file (scripts/gen_openapi_v2.py).
import OPENAPI from "../../../api-docs/v2/openapi.json" with { type: "json" };
import { makeHandler } from "./server.ts";

const ENV: Record<string, string> = {
  SUPABASE_URL: "https://example-ref.supabase.co/",
  SUPABASE_ANON_KEY: "test-anon-key",
};
const env = (name: string) => ENV[name];
const JWT = "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoiYXV0aGVudGljYXRlZCJ9.sig";

interface Captured {
  url: string;
  init: RequestInit;
}

/**
 * A stub PostgREST. The gateway's own gate RPCs (api.my_tier, api.rate_hit;
 * silo-api/tier.ts) are answered here and recorded in gateCalls: a bearer is
 * signed_in, and every hit is the first of the minute. Every other request
 * gets `body` and is recorded in calls.
 */
function stubFetch(status: number, body: string) {
  const calls: Captured[] = [];
  const gateCalls: Captured[] = [];
  const impl = (input: string, init: RequestInit): Promise<Response> => {
    const url = String(input);
    const json = (b: string, s = 200) => Promise.resolve(new Response(b, { status: s, headers: { "content-type": "application/json" } }));
    if (url.endsWith("/rpc/my_tier")) {
      gateCalls.push({ url, init });
      return json('"signed_in"');
    }
    if (url.endsWith("/rpc/rate_hit")) {
      gateCalls.push({ url, init });
      return json("1");
    }
    calls.push({ url, init });
    return json(body, status);
  };
  return { calls, gateCalls, impl };
}

const bearer = (token: string) => new Headers({ authorization: `Bearer ${token}` });

const sent = (c: Captured) => JSON.parse(String(c.init.body));

// ---------------------------------------------------------------- tools.ts --

Deno.test("exactly 14 tools, one per registry resource, named silo_<resource>", () => {
  assertEquals(TOOLS.length, 14);
  assertEquals(TOOLS.map((t) => t.name), REGISTRY.resources.map((r) => `silo_${r.name}`));
  assertEquals(TOOLS_BY_NAME.size, 14, "no duplicate names");
  for (const t of TOOLS) {
    assertEquals(t.annotations.readOnlyHint, true, t.name);
    assertEquals(t.annotations.destructiveHint, false, t.name);
  }
});

Deno.test("schemas come from the registry: main and shared on top, hidden in options, enums with defaults", () => {
  for (const r of REGISTRY.resources) {
    const tool = TOOLS_BY_NAME.get(`silo_${r.name}`)!;
    const props = tool.inputSchema.properties as Record<string, Record<string, unknown>>;
    const all = acceptedParams(r);
    const top = [...new Set([...all.filter((p) => p.visibility === "main").map((p) => p.name), "cursor"])];
    const hidden = all.filter((p) => p.visibility === "hidden").map((p) => p.name);
    const extra = [hidden.length ? ["options"] : [], r.body?.length ? ["body"] : []].flat();
    assertEquals(Object.keys(props).sort(), [...top, ...extra].sort(), r.name);
    assert(top.filter((n) => !SHARED_NAMES.includes(n)).length <= 3, `${r.name}: at most 3 main parameters`);
    for (const p of all.filter((p) => p.visibility === "main" && p.name !== "id")) {
      assertEquals(props[p.name], paramSchema(p), `${r.name}.${p.name}`);
      if (p.type === "enum") {
        assertEquals(props[p.name].enum, p.values, `${r.name}.${p.name} enum`);
        assertEquals(props[p.name].default, p.default, `${r.name}.${p.name} default`);
      }
    }
    if (hidden.length) {
      const opts = props.options as { properties: Record<string, unknown>; additionalProperties: boolean };
      assertEquals(Object.keys(opts.properties).sort(), [...hidden].sort(), `${r.name} options`);
      assertEquals(opts.additionalProperties, false);
    }
    assertEquals(tool.inputSchema.additionalProperties, false, r.name);
  }
});

Deno.test("id is described per resource, never with the shared generic sentence, and matches the OpenAPI file", () => {
  const generic = REGISTRY.shared_parameters.id.doc;
  const spec = OPENAPI as { paths: Record<string, Record<string, { parameters?: Array<{ name: string; description: string }> }>> };
  let described = 0;
  for (const r of REGISTRY.resources) {
    const props = TOOLS_BY_NAME.get(`silo_${r.name}`)!.inputSchema.properties as Record<string, { description?: string }>;
    const doc = idDoc(r);
    assertEquals("id" in props, doc !== null, `${r.name}: an id argument exactly when the resource takes id`);
    if (doc === null) continue;
    described++;
    assertEquals(props.id.description, `${doc} Default: none.`, r.name);
    assert(!props.id.description!.includes(generic), `${r.name} reuses the generic id sentence`);
    const op = Object.values(spec.paths[`/${r.name}`])[0];
    const oasId = op.parameters!.find((p) => p.name === "id")!;
    assertEquals(oasId.description, props.id.description, `${r.name}: MCP and OpenAPI say the same about id`);
  }
  assertEquals(described, 9);
  assertStringIncludes(idDoc(REGISTRY.resources.find((r) => r.name === "fidc")!)!, "14-digit fund CNPJ");
});

Deno.test("prices: fields defaults to core and lives in options; the description says so", () => {
  const t = TOOLS_BY_NAME.get("silo_prices")!;
  const opts = (t.inputSchema.properties as Record<string, { properties: Record<string, { default?: unknown }> }>).options;
  assertEquals(opts.properties.fields.default, "core");
  assertStringIncludes(t.description, "options.fields=all");
});

Deno.test("planCall: top-level and options become one query; a list is comma-separated", () => {
  const plan = planCall(TOOLS_BY_NAME.get("silo_prices")!, { id: "PETR4", kind: "history", options: { fields: "all" } });
  assertEquals(plan.method, "GET");
  assertEquals(plan.path, "/v2/prices?id=PETR4&kind=history&fields=all");
  const cov = planCall(TOOLS_BY_NAME.get("silo_coverage")!, { dataset: ["quotes", "funds_fidc"] });
  assertEquals(cov.query.get("dataset"), "quotes,funds_fidc");
  const nulls = planCall(TOOLS_BY_NAME.get("silo_search")!, { q: "petrobras", kind: null });
  assertEquals(nulls.path, "/v2/search?q=petrobras", "a null argument is the default");
});

Deno.test("a call runs the gateway: one PostgREST request, the envelope verbatim", async () => {
  const rows = [{ id: "9512", id_type: "cd_cvm", asset_class: "cia", name: "X", isin: null, cnpj: "33000167000101", tickers: [], truncated: false }];
  const stub = stubFetch(200, JSON.stringify(rows));
  const res = await callTool("silo_search", { q: "petrobras" }, { env, fetchImpl: stub.impl });
  assert(!res.isError, JSON.stringify(res));
  assertEquals(stub.calls.length, 1);
  assertEquals(stub.calls[0].url, "https://example-ref.supabase.co/rest/v1/rpc/lookup");
  assertEquals(sent(stub.calls[0]), { p_query: "petrobras" });
  const h = stub.calls[0].init.headers as Record<string, string>;
  assertEquals(h["apikey"], "test-anon-key");
  assertEquals(h["Authorization"], undefined, "no caller token: anonymous");
  const envelope = JSON.parse(res.content[0].text);
  assertEquals(envelope.data, rows, "rows pass through; null stays null");
  assertEquals(envelope.meta.resource, "search");
  assertEquals(envelope.meta.request.kind, "any", "the default is applied and echoed");
  assertStringIncludes(res.content[1].text, "GET /v2/search?q=petrobras");
});

Deno.test("a gateway error is returned verbatim as isError", async () => {
  const pg = { code: "22023", message: "fidc_portfolio: refused, more than 1000 rows", hint: "pin p_kind", details: null };
  const stub = stubFetch(400, JSON.stringify(pg));
  const res = await callTool("silo_search", { q: "fundo", kind: "fund" }, { env, fetchImpl: stub.impl });
  assertEquals(res.isError, true);
  const err = JSON.parse(res.content[0].text).error;
  assertEquals(err.code, "over_limit");
  assertEquals(err.message, pg.message, "SILO's refusal text is unchanged");
  assertEquals(err.innererror.sqlstate, "22023");
});

Deno.test("a bad argument is refused before any request, in the v2 error shape", async () => {
  const stub = stubFetch(200, "[]");
  const misplaced = await callTool("silo_prices", { id: "PETR4", fields: "all" }, { env, fetchImpl: stub.impl });
  assertEquals(misplaced.isError, true);
  const e1 = JSON.parse(misplaced.content[0].text).error;
  assertEquals(e1.code, "unknown_parameter");
  assertEquals(e1.target, "fields");
  assertStringIncludes(e1.message, "put it in options");
  const typo = await callTool("silo_prices", { id: "PETR4", options: { kind: "latest" } }, { env, fetchImpl: stub.impl });
  assertEquals(JSON.parse(typo.content[0].text).error.target, "options.kind");
  const enumBad = await callTool("silo_prices", { id: "PETR4", adjust: "dividends" }, { env, fetchImpl: stub.impl });
  assertEquals(JSON.parse(enumBad.content[0].text).error.code, "bad_request", "the gateway validates the value");
  assertEquals(stub.calls.length, 0);
  const unknown = await callTool("silo_nothing", {}, { env, fetchImpl: stub.impl });
  assertEquals(unknown.isError, true);
});

Deno.test("portfolio: body lists in the JSON body; a caller's Bearer gives the signed-in tier", async () => {
  const stub = stubFetch(200, "[]");
  const args = { kind: "lookthrough", month: "2026-08-31", body: { id: ["33000167000101"] } };
  const anon = await callTool("silo_portfolio", args, { env, fetchImpl: stub.impl });
  assertEquals(JSON.parse(anon.content[0].text).error.code, "forbidden_for_tier", "portfolio is signed-in only");
  assertEquals(stub.calls.length, 0);
  const signed = await callTool("silo_portfolio", args, { env, fetchImpl: stub.impl, headers: bearer(JWT) });
  assert(!signed.isError, signed.content[0].text);
  assertEquals(stub.calls.length, 1);
  assert(stub.calls[0].url.endsWith("/rpc/portfolio_lookthrough"));
  assertEquals(sent(stub.calls[0]), { p_cnpjs: ["33000167000101"], p_month: "2026-08-31", p_max_depth: 4 });
  assertEquals((stub.calls[0].init.headers as Record<string, string>)["Authorization"], `Bearer ${JWT}`);
});

Deno.test("a next page is a cursor the tool takes back", async () => {
  const rows = Array.from({ length: 11 }, (_, i) => ({ ticker: `T${i}`, isin: `I${i}`, first_observed: "2019-01-02", last_observed: "2026-10-30" }));
  const stub = stubFetch(200, JSON.stringify(rows));
  const first = await callTool("silo_search", { kind: "universe" }, { env, fetchImpl: stub.impl });
  assert(!first.isError, first.content[0].text);
  const envelope = JSON.parse(first.content[0].text);
  assert(envelope.next_page_url, "more rows than one anonymous page");
  const cursor = new URL(envelope.next_page_url).searchParams.get("cursor")!;
  assertStringIncludes(first.content[2].text, cursor);
  const second = await callTool("silo_search", { cursor }, { env, fetchImpl: stub.impl });
  assert(!second.isError, second.content[0].text);
  assertEquals(JSON.parse(second.content[0].text).data.length, 1);
});

// ------------------------------------------------ through the MCP SDK -------

async function rpc(handler: (r: Request) => Promise<Response>, method: string, params: unknown, headers: Record<string, string> = {}) {
  const res = await handler(
    new Request("http://localhost/silo-mcp-v2", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        accept: "application/json, text/event-stream",
        "mcp-protocol-version": "2025-06-18",
        ...headers,
      },
      body: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params }),
    }),
  );
  const text = await res.text();
  assertEquals(res.status, 200, text);
  const payload = text.trimStart().startsWith("{")
    ? text
    : text.split("\n").filter((l) => l.startsWith("data:")).map((l) => l.slice(5)).join("");
  return JSON.parse(payload);
}

Deno.test("MCP: initialize advertises tools and the v2 instructions", async () => {
  const handler = makeHandler({ env, fetchImpl: stubFetch(200, "[]").impl });
  const body = await rpc(handler, "initialize", { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "test", version: "0" } });
  assert(body.result?.capabilities?.tools, JSON.stringify(body));
  assertStringIncludes(body.result.instructions, "silo_search");
});

Deno.test("MCP: tools/list returns the 14 tools, read-only, with their enums and defaults", async () => {
  const handler = makeHandler({ env, fetchImpl: stubFetch(200, "[]").impl });
  const body = await rpc(handler, "tools/list", {});
  const tools = body.result.tools as Array<{ name: string; annotations?: { readOnlyHint?: boolean }; inputSchema: { properties: Record<string, { enum?: string[]; default?: unknown }> } }>;
  assertEquals(tools.map((t) => t.name).sort(), TOOLS.map((t) => t.name).sort());
  for (const t of tools) assertEquals(t.annotations?.readOnlyHint, true, t.name);
  const prices = tools.find((t) => t.name === "silo_prices")!;
  assertEquals(prices.inputSchema.properties.adjust.default, "split");
  assertEquals(prices.inputSchema.properties.kind.enum, ["history", "latest", "session", "index", "forward"]);
  assert("options" in prices.inputSchema.properties);
});

Deno.test("MCP: tools/call returns the envelope; an error is isError; the Bearer reaches the gateway", async () => {
  const stub = stubFetch(200, "[]");
  const handler = makeHandler({ env, fetchImpl: stub.impl });
  const ok = await rpc(handler, "tools/call", { name: "silo_coverage", arguments: {} });
  assert(!ok.result.isError, JSON.stringify(ok));
  assertEquals(JSON.parse(ok.result.content[0].text).meta.resource, "coverage");
  const refused = await rpc(handler, "tools/call", { name: "silo_screens", arguments: {} });
  assertEquals(refused.result.isError, true);
  assertEquals(JSON.parse(refused.result.content[0].text).error.code, "forbidden_for_tier");
  const n = stub.calls.length;
  await rpc(handler, "tools/call", { name: "silo_screens", arguments: {} }, { authorization: `Bearer ${JWT}` });
  assert(stub.calls.length > n, "signed in: screens is served, so the gateway called PostgREST");
  assertEquals((stub.calls[stub.calls.length - 1].init.headers as Record<string, string>)["Authorization"], `Bearer ${JWT}`);
});

Deno.test("the caller's IP headers reach the gateway's rate bucket; nothing else is forwarded", async () => {
  const stub = stubFetch(200, "[]");
  const headers = new Headers({ "cf-connecting-ip": "203.0.113.7", "x-forwarded-for": "198.51.100.9", cookie: "s=1", apikey: "theirs" });
  const res = await callTool("silo_coverage", {}, { env, fetchImpl: stub.impl, headers });
  assert(!res.isError, res.content[0].text);
  const hit = stub.gateCalls.find((c) => c.url.endsWith("/rpc/rate_hit"))!;
  assertEquals(sent(hit), { p_bucket: "ip:203.0.113.7" }, "counted by the caller's address, not one shared MCP bucket");
  const viaXff = stubFetch(200, "[]");
  await callTool("silo_coverage", {}, { env, fetchImpl: viaXff.impl, headers: new Headers({ "x-forwarded-for": "198.51.100.9, 10.0.0.1" }) });
  assertEquals(sent(viaXff.gateCalls.find((c) => c.url.endsWith("/rpc/rate_hit"))!), { p_bucket: "ip:198.51.100.9" });
  const sentHeaders = stub.calls[0].init.headers as Record<string, string>;
  assertEquals(sentHeaders["apikey"], "test-anon-key", "the caller's apikey is never forwarded");
  assert(!Object.keys(sentHeaders).some((k) => k.toLowerCase() === "cookie"));
});

Deno.test("MCP: one gateway per handler, so the tier cache spans calls; the IP header reaches it", async () => {
  const stub = stubFetch(200, "[]");
  const handler = makeHandler({ env, fetchImpl: stub.impl });
  for (let i = 0; i < 3; i++) {
    const out = await rpc(handler, "tools/call", { name: "silo_coverage", arguments: {} }, { authorization: `Bearer ${JWT}` });
    assert(!out.result.isError, JSON.stringify(out));
  }
  assertEquals(stub.gateCalls.filter((c) => c.url.endsWith("/rpc/my_tier")).length, 1, "api.my_tier once for three calls: the 60 s cache works");
  assertEquals(stub.gateCalls.filter((c) => c.url.endsWith("/rpc/rate_hit")).length, 3, "every call is still counted");
  await rpc(handler, "tools/call", { name: "silo_coverage", arguments: {} }, { "cf-connecting-ip": "203.0.113.8" });
  assertEquals(sent(stub.gateCalls[stub.gateCalls.length - 1]), { p_bucket: "ip:203.0.113.8" });
});

Deno.test("MCP: CORS preflight is answered", async () => {
  const handler = makeHandler({ env, fetchImpl: stubFetch(200, "[]").impl });
  const res = await handler(new Request("http://localhost/silo-mcp-v2", { method: "OPTIONS" }));
  assertEquals(res.status, 204);
  assertEquals(res.headers.get("access-control-allow-origin"), "*");
});
