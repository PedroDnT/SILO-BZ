// Offline tests for silo-api. fetch is stubbed: no network, no database.
//
//   deno test supabase/functions/silo-api/
//
// CI does not run Deno yet (#1052 child 2/8); tests/test_api_v2_registry.py is
// what CI protects today (the registry rules). This file checks behaviour:
// routing, the envelope, defaults, refusals and the PostgREST bridge.

import { assert, assertEquals, assertStringIncludes } from "@std/assert";

import { ERROR_CODES, fromPostgrest } from "./errors.ts";
import { minusMonths, todayUtcMinus3 } from "./params.ts";
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
  for (const n of ["funds", "fidc", "events"]) assertEquals(byName[n], "built", n);
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

// ------------------------------------------ funds, fidc, events (#1056) --

const CNPJ = "33000167000101";
const body = (c: Captured) => JSON.parse(String(c.init.body));

function stubView(rows: unknown[], contentRange: string | null) {
  const calls: Captured[] = [];
  const impl = (input: string, init: RequestInit): Promise<Response> => {
    calls.push({ url: String(input), init });
    const headers: Record<string, string> = { "content-type": "application/json" };
    if (contentRange !== null) headers["content-range"] = contentRange;
    return Promise.resolve(new Response(JSON.stringify(rows), { status: 200, headers }));
  };
  return { calls, impl };
}

async function getView(path: string, rows: unknown[], contentRange: string | null) {
  const stub = stubView(rows, contentRange);
  const res = await makeHandler({ fetchImpl: stub.impl, env })(new Request(`${BASE}${path}`));
  return { res, json: await res.json(), calls: stub.calls };
}

Deno.test("windows: minusMonths clamps the day, and today is counted in UTC-3", () => {
  assertEquals(minusMonths("2026-10-31", 36), "2023-10-31");
  assertEquals(minusMonths("2024-02-29", 12), "2023-02-28");
  assertEquals(minusMonths("2026-03-31", 1), "2026-02-28");
  assertEquals(minusMonths("2026-01-15", 24), "2024-01-15");
  assertEquals(todayUtcMinus3(new Date("2026-11-04T02:00:00Z")), "2026-11-03");
  assertEquals(todayUtcMinus3(new Date("2026-11-04T03:00:00Z")), "2026-11-04");
});

Deno.test("funds kind=nav: id, the 3-year window back from to, family -> p_entity_type", async () => {
  const { res, json, calls } = await get(`/v2/funds?id=33.000.167/0001-01&kind=nav&to=2026-09-30&family=fi`);
  assertEquals(res.status, 200);
  assertEquals(calls.length, 1);
  assert(calls[0].url.endsWith("/rpc/fund_nav"));
  assertEquals(body(calls[0]), { p_cnpj: CNPJ, p_from: "2023-09-30", p_to: "2026-09-30", p_entity_type: "fi" });
  assertEquals(json.meta.request, { kind: "nav", family: "fi", holding: null, status: "all", id: CNPJ, from: "2023-09-30", to: "2026-09-30", limit: null });
  assertEquals(json.meta.endpoint, "api.fund_nav");
});

Deno.test("funds kind=nav with no to sends no p_to (the endpoint's latest complete period) and from counted from today", async () => {
  const { calls, json } = await get(`/v2/funds?id=${CNPJ}&kind=nav`);
  const sent = body(calls[0]);
  assertEquals(sent.p_to, undefined);
  assertEquals(sent.p_entity_type, undefined, "family=all is not sent");
  assertEquals(sent.p_from, minusMonths(todayUtcMinus3(), 36));
  assertEquals(json.meta.request.from, sent.p_from, "meta.request echoes the window applied");
});

Deno.test("funds kind=profile with an id calls fund_profile and takes no window", async () => {
  const rows = [{ cnpj: CNPJ, entity_type: "fi", fund_name: "X", status: null, latest_aum: null }];
  const { json, calls } = await get(`/v2/funds?id=${CNPJ}`, 200, JSON.stringify(rows));
  assert(calls[0].url.endsWith("/rpc/fund_profile"));
  assertEquals(body(calls[0]), { p_cnpj: CNPJ });
  assertEquals(json.data, rows, "null stays null");
  assertEquals(json.meta.request.from, null);
  const misplaced = await get(`/v2/funds?id=${CNPJ}&from=2024-01-01`);
  assertEquals(misplaced.json.error.code, "bad_request");
  assertEquals(misplaced.json.error.target, "from");
  assertEquals(misplaced.calls.length, 0);
});

Deno.test("funds with no id GETs the funds view: eq filters, an order, Prefer count=exact", async () => {
  const rows = [{ cnpj: "00000000000191", entity_type: "fidc", fund_name: "A" }];
  const { res, json, calls } = await getView("/v2/funds?family=fidc&status=EM%20FUNCIONAMENTO%20NORMAL", rows, "0-0/1");
  assertEquals(res.status, 200);
  assertEquals(calls.length, 1);
  assertEquals(calls[0].init.method, "GET");
  const u = new URL(calls[0].url);
  assertEquals(u.pathname, "/rest/v1/funds");
  assertEquals(u.searchParams.get("entity_type"), "eq.fidc");
  assertEquals(u.searchParams.get("status"), "eq.EM FUNCIONAMENTO NORMAL");
  assertEquals(u.searchParams.get("order"), "cnpj.asc,entity_type.asc");
  assertEquals(u.searchParams.get("limit"), "1000");
  const h = calls[0].init.headers as Record<string, string>;
  assertEquals(h["Accept-Profile"], "api");
  assertEquals(h["Prefer"], "count=exact");
  assertEquals(json.data, rows);
  assertEquals(json.meta.endpoint, "api.funds");
  assertEquals(json.meta.rows_total, 1);
  assertEquals(json.meta.truncated, false);
});

Deno.test("funds with no id refuses a cut page rather than trim; limit asks for the first N, and says so", async () => {
  const page = Array.from({ length: 1000 }, (_, i) => ({ cnpj: String(i).padStart(14, "0") }));
  const over = await getView("/v2/funds", page, "0-999/84211");
  assertEquals(over.res.status, 400);
  assertEquals(over.json.error.code, "over_limit");
  assertEquals(over.json.error.target, "limit");
  assertStringIncludes(over.json.error.message, "84211");
  assertStringIncludes(over.json.error.message, "family or status");
  assert(!("data" in over.json));

  const noCount = await getView("/v2/funds", page, null);
  assertEquals(noCount.json.error.code, "over_limit", "no count and a full page is ambiguous: refused");

  const head = await getView("/v2/funds?limit=2", page.slice(0, 2), "0-1/84211");
  assertEquals(head.res.status, 200);
  assertEquals(new URL(head.calls[0].url).searchParams.get("limit"), "2");
  assertEquals(head.json.data.length, 2);
  assertEquals(head.json.meta.rows_total, 84211);
  assertEquals(head.json.meta.truncated, true);

  const shortPage = await getView("/v2/funds?limit=500", page.slice(0, 100), "0-99/84211");
  assertEquals(shortPage.json.error.code, "over_limit", "a server cut below the asked N is refused too");
});

Deno.test("funds holdings and debentures: exactly one of id and holding", async () => {
  const fwd = await get(`/v2/funds?id=${CNPJ}&kind=holdings&from=2025-01-01&to=2025-12-31&limit=50`);
  assert(fwd.calls[0].url.endsWith("/rpc/fund_holdings"));
  assertEquals(body(fwd.calls[0]), { p_cnpj: CNPJ, p_from: "2025-01-01", p_to: "2025-12-31", p_limit: 50 });

  const rev = await get("/v2/funds?kind=holdings&holding=PETR4&from=2025-01-01");
  assertEquals(body(rev.calls[0]), { p_ticker: "PETR4", p_from: "2025-01-01" });
  const deb = await get("/v2/funds?kind=debentures&holding=PETR&from=2025-01-01");
  assert(deb.calls[0].url.endsWith("/rpc/fund_debentures"));
  assertEquals(body(deb.calls[0]), { p_issuer: "PETR", p_from: "2025-01-01" });

  const both = await get(`/v2/funds?id=${CNPJ}&kind=holdings&holding=PETR4`);
  assertEquals(both.json.error.code, "bad_request");
  assertEquals(both.json.error.target, "holding");
  assertEquals(both.calls.length, 0);
  const none = await get("/v2/funds?kind=holdings");
  assertEquals(none.json.error.code, "bad_request");
  assertEquals(none.json.error.target, "id");
  assertEquals(none.calls.length, 0);
});

Deno.test("funds refuses a missing id, a non-CNPJ id and a misplaced hidden parameter before any call", async () => {
  const nav = await get("/v2/funds?kind=nav");
  assertEquals(nav.json.error.target, "id");
  assertStringIncludes(nav.json.error.message, "needs id");
  const ticker = await get("/v2/funds?id=PETR4&kind=nav");
  assertEquals(ticker.json.error.code, "bad_request");
  assertEquals(ticker.json.error.target, "id");
  assertStringIncludes(ticker.json.error.message, "CNPJ");
  const holding = await get(`/v2/funds?id=${CNPJ}&kind=nav&holding=PETR4`);
  assertEquals(holding.json.error.target, "holding");
  const status = await get(`/v2/funds?id=${CNPJ}&status=CANCELADA`);
  assertEquals(status.json.error.target, "status");
  const family = await get(`/v2/funds?id=${CNPJ}&kind=properties&family=fii`);
  assertEquals(family.json.error.target, "family");
  const window = await get(`/v2/funds?id=${CNPJ}&kind=nav&from=2026-01-01&to=2025-01-01`);
  assertEquals(window.json.error.target, "from");
  for (const r of [nav, ticker, holding, status, family, window]) assertEquals(r.calls.length, 0);

  const props = await get(`/v2/funds?id=${CNPJ}&kind=properties&from=2020-01-01`);
  assert(props.calls[0].url.endsWith("/rpc/fii_property_history"));
  assertEquals(body(props.calls[0]), { p_cnpj: CNPJ, p_from: "2020-01-01" });
});

Deno.test("fidc maps one kind per fidc_* function with a 2-year window, and hidden params to their p_ args", async () => {
  const cases: [string, string, Record<string, unknown>][] = [
    [`kind=portfolio&item=sector&limit=10`, "fidc_portfolio", { p_cnpj: CNPJ, p_kind: "sector", p_from: "2024-09-30", p_to: "2026-09-30", p_limit: 10 }],
    [`kind=tranches&series=SENIOR%201`, "fidc_tranches", { p_cnpj: CNPJ, p_from: "2024-09-30", p_to: "2026-09-30", p_series: "SENIOR 1" }],
    [`kind=aging`, "fidc_aging", { p_cnpj: CNPJ, p_from: "2024-09-30", p_to: "2026-09-30" }],
    [`kind=cedentes`, "fidc_cedentes", { p_cnpj: CNPJ, p_from: "2024-09-30", p_to: "2026-09-30" }],
    [`kind=sacados`, "fidc_sacados", { p_cnpj: CNPJ, p_from: "2024-09-30", p_to: "2026-09-30" }],
  ];
  for (const [qs, fn, args] of cases) {
    const { calls, json } = await get(`/v2/fidc?id=${CNPJ}&to=2026-09-30&${qs}`);
    assertEquals(calls.length, 1, qs);
    assert(calls[0].url.endsWith(`/rpc/${fn}`), qs);
    assertEquals(body(calls[0]), args, qs);
    assertEquals(json.meta.endpoint, `api.${fn}`);
  }
  const portfolioDefault = await get(`/v2/fidc?id=${CNPJ}&to=2026-09-30`);
  assertEquals(body(portfolioDefault.calls[0]), { p_cnpj: CNPJ, p_from: "2024-09-30", p_to: "2026-09-30" }, "item=all is not sent");

  const rev = await get("/v2/fidc?kind=cedentes&cedente=12345678000199&from=2025-01-01");
  assertEquals(body(rev.calls[0]), { p_cedente: "12345678000199", p_from: "2025-01-01" });
  const series = await get(`/v2/fidc?id=${CNPJ}&kind=aging&series=SENIOR`);
  assertEquals(series.json.error.target, "series");
  assertEquals(series.calls.length, 0);
  const noId = await get("/v2/fidc?kind=tranches");
  assertEquals(noId.json.error.target, "id");
  assertEquals(noId.calls.length, 0);
  const item = await get(`/v2/fidc?id=${CNPJ}&item=loans`);
  assertEquals(item.json.error.target, "item");
});

Deno.test("fidc with no id lists the FIDC registry from the funds view", async () => {
  const { json, calls } = await getView("/v2/fidc?limit=5", Array(5).fill({ cnpj: CNPJ, entity_type: "fidc" }), "0-4/4120");
  const u = new URL(calls[0].url);
  assertEquals(u.pathname, "/rest/v1/funds");
  assertEquals(u.searchParams.get("entity_type"), "eq.fidc");
  assertEquals(u.searchParams.get("limit"), "5");
  assertEquals(json.meta.truncated, true);
  const item = await get("/v2/fidc?item=sector");
  assertEquals(item.json.error.target, "item", "item needs an id: it applies to the portfolio function only");
});

Deno.test("fidc ?help carries the 2020-11 delinquency regime break and the hidden params only at help=all", async () => {
  const main = await get("/v2/fidc?help");
  const help = main.json.data[0];
  assert(help.notes.some((n: string) => n.includes("2020-11")), "regime break note");
  assertEquals(help.default_window_months, 24);
  assertEquals(help.parameters.map((p: { name: string }) => p.name), ["kind", "id", "from", "to", "limit"]);
  const all = await get("/v2/fidc?help=all");
  const names = all.json.data[0].parameters.map((p: { name: string }) => p.name);
  for (const n of ["series", "cedente", "item"]) assert(names.includes(n), n);
  const funds = await get("/v2/funds?help");
  assert(funds.json.data[0].endpoints.includes("api.funds"));
});

Deno.test("events maps each kind, with a 12-month window and category to the source label", async () => {
  const cases: [string, string, Record<string, unknown>][] = [
    [`id=PETR4&category=Fato%20Relevante`, "company_events", { p_id: "PETR4", p_from: "2025-09-30", p_to: "2026-09-30", p_category: "Fato Relevante" }],
    [`id=${CNPJ}&kind=fund&category=Informe%20Mensal`, "fund_documents", { p_cnpj: CNPJ, p_from: "2025-09-30", p_to: "2026-09-30", p_tipo: "Informe Mensal" }],
    [`kind=restatements&family=fidc`, "fund_restatements", { p_from: "2025-09-30", p_to: "2026-09-30", p_tipo_fundo: "fidc" }],
    [`id=${CNPJ}&kind=restatement_diff`, "fund_restatement_diff", { p_cnpj: CNPJ, p_from: "2025-09-30", p_to: "2026-09-30" }],
    [`kind=judicial_recovery`, "rj_listed_documents", { p_from: "2025-09-30", p_to: "2026-09-30" }],
  ];
  for (const [qs, fn, args] of cases) {
    const { calls } = await get(`/v2/events?to=2026-09-30&${qs}`);
    assertEquals(calls.length, 1, qs);
    assert(calls[0].url.endsWith(`/rpc/${fn}`), qs);
    assertEquals(body(calls[0]), args, qs);
  }
});

Deno.test("events refuses what a kind cannot use, and a fund kind takes a CNPJ", async () => {
  const company = await get("/v2/events");
  assertEquals(company.json.error.target, "id");
  const cat = await get("/v2/events?kind=restatements&category=Informe%20Mensal");
  assertEquals(cat.json.error.code, "bad_request");
  assertEquals(cat.json.error.target, "category");
  const fam = await get("/v2/events?id=PETR4&family=fii");
  assertEquals(fam.json.error.target, "family");
  const ticker = await get("/v2/events?id=PETR4&kind=fund");
  assertEquals(ticker.json.error.target, "id");
  for (const r of [company, cat, fam, ticker]) assertEquals(r.calls.length, 0);
});

Deno.test("a SQL refusal on a new resource still comes back verbatim as over_limit", async () => {
  const pg = { code: "22023", message: "fidc_portfolio: 1001 rows, above one page", hint: "pin p_kind", details: null };
  const { res, json } = await get(`/v2/fidc?id=${CNPJ}`, 400, JSON.stringify(pg));
  assertEquals(res.status, 400);
  assertEquals(json.error.code, "over_limit");
  assertEquals(json.error.message, pg.message);
});

Deno.test("every built resource keeps at most 3 main parameters, kind included", () => {
  for (const r of REGISTRY.resources.filter((x) => x.status === "built")) {
    const main = (r.parameters ?? []).filter((p) => p.visibility === "main");
    assert(main.length <= 3, r.name);
    assert(main.some((p) => p.name === "kind"), r.name);
  }
});
