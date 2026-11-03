// Offline tests for silo-api. fetch is stubbed: no network, no database.
//
//   deno test supabase/functions/silo-api/
//
// CI does not run Deno yet (#1052 child 2/8); tests/test_api_v2_registry.py is
// what CI protects today (the registry rules). This file checks behaviour:
// routing, the envelope, defaults, refusals and the PostgREST bridge.

import { assert, assertEquals, assertStringIncludes } from "@std/assert";

import { ERROR_CODES, fromPostgrest } from "./errors.ts";
import { callerBearer, configFromEnv } from "./postgrest.ts";
import { REGISTRY } from "./registry.ts";
import { makeHandler, routeOf } from "./server.ts";

const ENV: Record<string, string> = {
  SUPABASE_URL: "https://example-ref.supabase.co/",
  SUPABASE_ANON_KEY: "test-anon-key",
};
const env = (name: string) => ENV[name];
const BASE = "https://example-ref.supabase.co/functions/v1/silo-api";

interface Captured {
  url: string;
  init: RequestInit;
}

function stubFetch(status: number, body: string) {
  const calls: Captured[] = [];
  const impl = (input: string, init: RequestInit): Promise<Response> => {
    calls.push({ url: String(input), init });
    return Promise.resolve(new Response(body, { status, headers: { "content-type": "application/json" } }));
  };
  return { calls, impl };
}

async function get(path: string, status = 200, body = "[]", headers: Record<string, string> = {}) {
  const stub = stubFetch(status, body);
  const handler = makeHandler({ fetchImpl: stub.impl, env });
  const res = await handler(new Request(`${BASE}${path}`, { headers }));
  return { res, json: await res.json(), calls: stub.calls };
}

// ------------------------------------------------------------- routing --

Deno.test("routes strip the function prefix and accept a trailing slash", () => {
  assertEquals(routeOf("/functions/v1/silo-api/v2/"), "");
  assertEquals(routeOf("/silo-api/v2"), "");
  assertEquals(routeOf("/silo-api/v2/search"), "search");
  assertEquals(routeOf("/silo-api/v2/search/"), "search");
  assertEquals(routeOf("/silo-api/v1/search"), null);
  assertEquals(routeOf("/silo-api/v2/search/extra"), null);
});

Deno.test("GET /v2/ lists the 14 resources, unbuilt ones as planned, with no upstream call", async () => {
  const { res, json, calls } = await get("/v2/");
  assertEquals(res.status, 200);
  assertEquals(calls.length, 0);
  assertEquals(json.data.length, 14);
  const byName = Object.fromEntries(json.data.map((r: { name: string; status: string }) => [r.name, r.status]));
  assertEquals(byName.search, "built");
  assertEquals(byName.coverage, "built");
  assertEquals(byName.prices, "planned");
  assertEquals(json.meta.resource, "index");
});

Deno.test("an unknown resource and a planned one are refused with v2 error bodies", async () => {
  const unknown = await get("/v2/quotes");
  assertEquals(unknown.res.status, 404);
  assertEquals(unknown.json.error.code, "bad_request");
  assertEquals(unknown.json.error.target, "resource");
  const planned = await get("/v2/prices?id=PETR4");
  assertEquals(planned.res.status, 501);
  assertEquals(planned.json.error.code, "unavailable");
  assertEquals(planned.calls.length, 0);
});

Deno.test("?help lists main parameters with defaults; ?help=all adds the hidden ones", async () => {
  const main = await get("/v2/search?help");
  assertEquals(main.res.status, 200);
  assertEquals(main.calls.length, 0);
  const help = main.json.data[0];
  const names = help.parameters.map((p: { name: string }) => p.name);
  assert(names.includes("q") && names.includes("kind") && names.includes("family"));
  assert(!names.includes("as_of"), "as_of is hidden");
  for (const p of help.parameters) assert("default" in p, p.name);
  assertEquals(help.endpoints.sort(), ["api.lookup", "api.research_universe", "api.search_funds"]);
  const all = await get("/v2/search?help=all");
  assert(all.json.data[0].parameters.some((p: { name: string }) => p.name === "as_of"));
});

// ---------------------------------------------------------- parameters --

Deno.test("an unknown parameter is unknown_parameter, named in target, with no upstream call", async () => {
  const { res, json, calls } = await get("/v2/search?q=petr&qq=1");
  assertEquals(res.status, 400);
  assertEquals(json.error.code, "unknown_parameter");
  assertEquals(json.error.target, "qq");
  assertEquals(calls.length, 0);
  const shared = await get("/v2/coverage?id=PETR4");
  assertEquals(shared.json.error.code, "unknown_parameter");
  assertEquals(shared.json.error.target, "id");
  assertStringIncludes(shared.json.error.message, "shared parameter");
});

Deno.test("a bad enum, a bad date and a misplaced parameter are bad_request", async () => {
  const kind = await get("/v2/search?kind=ticker");
  assertEquals(kind.json.error.code, "bad_request");
  assertEquals(kind.json.error.target, "kind");
  const date = await get("/v2/search?kind=universe&as_of=2020-02-30");
  assertEquals(date.json.error.target, "as_of");
  const family = await get("/v2/search?q=itau&family=fidc");
  assertEquals(family.json.error.code, "bad_request");
  assertEquals(family.json.error.target, "family");
  assertStringIncludes(family.json.error.message, "fund");
  assertEquals(family.calls.length, 0);
});

// -------------------------------------------------------------- search --

Deno.test("search defaults: kind any calls lookup once, and meta.request echoes every default", async () => {
  const rows = [{ id: "9512", id_type: "cd_cvm", asset_class: "cia", name: "PETROBRAS", isin: null, cnpj: "33000167000101", tickers: ["PETR3", "PETR4"], truncated: false }];
  const { res, json, calls } = await get("/v2/search?q=petrobras", 200, JSON.stringify(rows));
  assertEquals(res.status, 200);
  assertEquals(calls.length, 1);
  assertEquals(calls[0].url, "https://example-ref.supabase.co/rest/v1/rpc/lookup");
  assertEquals(calls[0].init.method, "POST");
  assertEquals(JSON.parse(String(calls[0].init.body)), { p_query: "petrobras" });
  const h = calls[0].init.headers as Record<string, string>;
  assertEquals(h["apikey"], "test-anon-key");
  assertEquals(h["Accept-Profile"], "api");
  assertEquals(h["Content-Profile"], "api");
  assertEquals(h["Authorization"], undefined, "anonymous: no Bearer is sent");

  assertEquals(json.data, rows, "rows are passed through, null stays null");
  assertEquals(json.meta.resource, "search");
  assertEquals(json.meta.kind, "any");
  assertEquals(json.meta.request, { q: "petrobras", kind: "any", family: "all", as_of: null, limit: null });
  assertEquals(json.meta.id_known, null);
  assertEquals(json.meta.endpoint, "api.lookup");
  assert(!("next_page_url" in json), "no next page: nothing pages yet");
});

Deno.test("search with no q lists the research universe; as_of reads it at a date", async () => {
  const rows = [
    { ticker: "AAAA3", isin: "BRAAAAACNOR0", first_observed: "2019-01-02", last_observed: "2021-06-30" },
    { ticker: "BBBB3", isin: "BRBBBBACNOR0", first_observed: "2022-01-03", last_observed: "2026-10-30" },
    { ticker: "CCCC3", isin: "BRCCCCACNOR0", first_observed: null, last_observed: null },
  ];
  const all = await get("/v2/search", 200, JSON.stringify(rows));
  assertEquals(all.calls[0].url.endsWith("/rpc/research_universe"), true);
  assertEquals(JSON.parse(String(all.calls[0].init.body)), {});
  assertEquals(all.json.data.length, 3);
  assertEquals(all.json.meta.endpoint, "api.research_universe");

  const at = await get("/v2/search?kind=universe&as_of=2020-01-31", 200, JSON.stringify(rows));
  assertEquals(at.json.data.map((r: { ticker: string }) => r.ticker), ["AAAA3"]);
  assertEquals(at.json.meta.request.as_of, "2020-01-31");
});

Deno.test("search kind=company keeps the company rows; kind=fund maps family and limit", async () => {
  const rows = [
    { id: "PETR4", id_type: "ticker", asset_class: "equity", name: "PETROBRAS PN", truncated: false },
    { id: "9512", id_type: "cd_cvm", asset_class: "cia", name: "PETROBRAS", truncated: false },
  ];
  const company = await get("/v2/search?q=petrobras&kind=company", 200, JSON.stringify(rows));
  assertEquals(company.json.data.map((r: { id: string }) => r.id), ["9512"]);

  const fund = await get("/v2/search?q=itau&kind=fund&family=fidc&limit=10");
  assertEquals(fund.calls[0].url.endsWith("/rpc/search_funds"), true);
  assertEquals(JSON.parse(String(fund.calls[0].init.body)), { p_query: "itau", p_entity_type: "fidc", p_limit: 10 });
  const defaults = await get("/v2/search?q=itau&kind=fund");
  assertEquals(JSON.parse(String(defaults.calls[0].init.body)), { p_query: "itau" }, "family=all and no limit are not sent");
});

Deno.test("a 22023 refusal becomes over_limit with the message, details and hint verbatim", async () => {
  const pg = { code: "22023", message: "search_funds: 31 funds match, above the anonymous ceiling of 25", details: "d", hint: "narrow p_query" };
  const { res, json } = await get("/v2/search?q=fundo&kind=fund", 400, JSON.stringify(pg));
  assertEquals(res.status, 400);
  assertEquals(json.error.code, "over_limit");
  assertEquals(json.error.message, pg.message);
  assertEquals(json.error.innererror, { sqlstate: "22023", hint: "narrow p_query", details: "d" });
});

Deno.test("PostgREST errors map to the ten codes", () => {
  assertEquals(fromPostgrest(500, '{"code":"57014","message":"canceling statement"}', "x").code, "timeout");
  assertEquals(fromPostgrest(401, '{"code":"PGRST301","message":"JWT expired"}', "x").code, "unauthorized");
  assertEquals(fromPostgrest(403, '{"code":"42501","message":"permission denied"}', "x").code, "forbidden_for_tier");
  assertEquals(fromPostgrest(429, "slow down", "x").code, "rate_limited");
  assertEquals(fromPostgrest(503, "", "x").code, "unavailable");
  assertEquals(fromPostgrest(404, '{"code":"PGRST202","message":"no function"}', "x").code, "internal");
  assertEquals(fromPostgrest(400, '{"code":"22P02","message":"invalid input"}', "x").code, "bad_request");
  assertEquals(ERROR_CODES.length, 10);
});

Deno.test("a network failure is unavailable, never an empty answer", async () => {
  const handler = makeHandler({ fetchImpl: () => Promise.reject(new Error("dns")), env });
  const res = await handler(new Request(`${BASE}/v2/coverage`));
  const body = await res.json();
  assertEquals(res.status, 503);
  assertEquals(body.error.code, "unavailable");
  assert(!("data" in body));
});

// ------------------------------------------------------------ coverage --

Deno.test("coverage freshness renames as_of to data_through and narrows by dataset", async () => {
  const rows = [
    { dataset: "quotes", as_of: "2026-10-30", complete_through: "2026-10-30", landed_at: null, landed_git_sha: null },
    { dataset: "funds_fidc", as_of: "2026-09-01", complete_through: "2026-08-01", landed_at: null, landed_git_sha: null },
  ];
  const all = await get("/v2/coverage", 200, JSON.stringify(rows));
  assertEquals(all.calls[0].url.endsWith("/rpc/coverage"), true);
  assertEquals(all.json.meta.kind, "freshness");
  assertEquals(all.json.meta.request, { kind: "freshness", dataset: "all" });
  assertEquals(all.json.data[0].data_through, "2026-10-30");
  assert(!("as_of" in all.json.data[0]), "as_of is reserved for point in time in v2");
  assertEquals(all.json.data[0].landed_at, null, "null stays null");

  const one = await get("/v2/coverage?dataset=funds_fidc", 200, JSON.stringify(rows));
  assertEquals(one.json.data.map((r: { dataset: string }) => r.dataset), ["funds_fidc"]);
  assertEquals(one.json.meta.request.dataset, ["funds_fidc"]);

  const typo = await get("/v2/coverage?dataset=funds_fdic", 200, JSON.stringify(rows));
  assertEquals(typo.json.error.code, "bad_request");
  assertEquals(typo.json.error.target, "dataset");
  assertStringIncludes(typo.json.error.message, "funds_fidc");
});

Deno.test("coverage metrics and catalog call their endpoints; catalog is data[0]", async () => {
  const metrics = await get("/v2/coverage?kind=metrics&dataset=fidc", 200, JSON.stringify([
    { entity_type: "fidc", metric: "nav" },
    { entity_type: "fi", metric: "nav" },
  ]));
  assertEquals(metrics.calls[0].url.endsWith("/rpc/metric_coverage"), true);
  assertEquals(metrics.json.data, [{ entity_type: "fidc", metric: "nav" }]);

  const catalog = await get("/v2/coverage?kind=catalog", 200, JSON.stringify({ version: 81, metrics: {} }));
  assertEquals(catalog.calls[0].url.endsWith("/rpc/catalog"), true);
  assertEquals(catalog.json.data, [{ version: 81, metrics: {} }]);
  const misplaced = await get("/v2/coverage?kind=catalog&dataset=quotes");
  assertEquals(misplaced.json.error.target, "dataset");
  assertEquals(misplaced.calls.length, 0);
});

// ---------------------------------------------------------------- auth --

Deno.test("a caller's JWT is forwarded; a publishable key is not; a secret key is refused", async () => {
  const jwt = "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoiYXV0aGVudGljYXRlZCJ9.sig";
  const signed = await get("/v2/coverage", 200, "[]", { Authorization: `Bearer ${jwt}` });
  const h = signed.calls[0].init.headers as Record<string, string>;
  assertEquals(h["Authorization"], `Bearer ${jwt}`);
  assertEquals(h["apikey"], "test-anon-key", "apikey is always the gateway's publishable key");

  const cfg = configFromEnv(env);
  assert(!("error" in cfg));
  assertEquals(callerBearer("Bearer sb_publishable_abc", cfg), null);
  assertEquals(callerBearer("Bearer test-anon-key", cfg), null);
  assertEquals(callerBearer(null, cfg), null);

  const secret = await get("/v2/coverage", 200, "[]", { Authorization: "Bearer sb_secret_zzz" });
  assertEquals(secret.res.status, 401);
  assertEquals(secret.json.error.code, "unauthorized");
  assertEquals(secret.calls.length, 0);
});

Deno.test("config refuses a secret key", () => {
  const secret = configFromEnv((n) => ({ SUPABASE_URL: "https://x", SUPABASE_ANON_KEY: "sb_secret_zzz" } as Record<string, string>)[n]);
  assert("error" in secret);
});

Deno.test("every built resource keeps at most 3 main parameters, kind included", () => {
  for (const r of REGISTRY.resources.filter((x) => x.status === "built")) {
    const main = (r.parameters ?? []).filter((p) => p.visibility === "main");
    assert(main.length <= 3, r.name);
    assert(main.some((p) => p.name === "kind"), r.name);
  }
});
