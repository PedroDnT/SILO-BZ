// Offline tests for silo-api. fetch is stubbed: no network, no database.
//
//   deno test supabase/functions/silo-api/
//
// CI runs these with `deno test`; tests/test_api_v2_registry.py checks the
// registry rules offline. This file checks behaviour: routing, the envelope,
// defaults, refusals, the PostgREST bridge, and paging and tiers (#1059).

import { assert, assertEquals, assertStringIncludes } from "@std/assert";

import { TIERS } from "./config.ts";
import { ERROR_CODES, fromPostgrest } from "./errors.ts";
import { minusMonths, todayUtcMinus3 } from "./params.ts";
import { decodeCursor, encodeCursor } from "./paging.ts";
import { callerBearer, configFromEnv, type FetchLike } from "./postgrest.ts";
import { REGISTRY } from "./registry.ts";
import { makeHandler, routeOf } from "./server.ts";
import { clientIp, type Gate, retryAfter, TIER_CACHE_MS } from "./tier.ts";

const ENV: Record<string, string> = {
  SUPABASE_URL: "https://example-ref.supabase.co/",
  SUPABASE_ANON_KEY: "test-anon-key",
};
const env = (name: string) => ENV[name];
const BASE = "https://example-ref.supabase.co/functions/v1/silo-api";
// A user JWT: the signed-in tier (#1059). PostgREST verifies it; the stub does not.
const JWT = "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoiYXV0aGVudGljYXRlZCJ9.sig";
const SIGNED = { Authorization: `Bearer ${JWT}` };
// The resource tests below are about resources, so their gate is #1059's
// rule with no counting: a Bearer is signed_in, every request is the first
// this minute. The Postgres gate (api.my_tier, api.rate_hit) has its own
// tests at the end of the file (#1064).
const OPEN: Gate = {
  tier: (ctx) => Promise.resolve(ctx.bearer ? "signed_in" : "anonymous"),
  hit: () => Promise.resolve(1),
};
/** A next_page_url as a path for get(). */
const pathOf = (url: string) => url.slice(BASE.length);

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
  const handler = makeHandler({ fetchImpl: stub.impl, env, gate: OPEN });
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

Deno.test("GET /v2/ lists the 14 resources, every one built (#1057 built the last), with no upstream call", async () => {
  const { res, json, calls } = await get("/v2/");
  assertEquals(res.status, 200);
  assertEquals(calls.length, 0);
  assertEquals(json.data.length, 14);
  for (const r of json.data as { name: string; status: string }[]) assertEquals(r.status, "built", r.name);
  assertEquals(json.meta.resource, "index");
});

// No resource is planned any more, so the 501 path for a planned one has no
// registry entry to reach it; the unknown-resource refusal is what remains.
Deno.test("an unknown resource is refused with a v2 error body and no upstream call", async () => {
  const unknown = await get("/v2/quotes");
  assertEquals(unknown.res.status, 404);
  assertEquals(unknown.json.error.code, "bad_request");
  assertEquals(unknown.json.error.target, "resource");
  assertEquals(unknown.calls.length, 0);
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
  assertEquals(json.meta.request, { q: "petrobras", kind: "any", family: "all", as_of: null, limit: 10 });
  assertEquals(json.meta.id_known, null);
  assertEquals(json.meta.endpoint, "api.lookup");
  assertEquals(json.meta.tier, "anonymous");
  assertEquals(json.meta.page_size, 10, "limit defaults to the tier's page maximum");
  assert(!("next_page_url" in json), "one row: no next page");
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

Deno.test("search kind=company keeps the company rows; kind=fund maps family, and limit is never p_limit", async () => {
  const rows = [
    { id: "PETR4", id_type: "ticker", asset_class: "equity", name: "PETROBRAS PN", truncated: false },
    { id: "9512", id_type: "cd_cvm", asset_class: "cia", name: "PETROBRAS", truncated: false },
  ];
  const company = await get("/v2/search?q=petrobras&kind=company", 200, JSON.stringify(rows));
  assertEquals(company.json.data.map((r: { id: string }) => r.id), ["9512"]);

  const fund = await get("/v2/search?q=itau&kind=fund&family=fidc&limit=10");
  assertEquals(fund.calls[0].url.endsWith("/rpc/search_funds"), true);
  assertEquals(JSON.parse(String(fund.calls[0].init.body)), { p_query: "itau", p_entity_type: "fidc" }, "limit is the page size: the whole match is asked");
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
  const handler = makeHandler({ fetchImpl: () => Promise.reject(new Error("dns")), env, gate: OPEN });
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
  assertEquals(all.json.meta.request, { kind: "freshness", dataset: "all", limit: 10 });
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

/** A view holding `rows` from the requested offset on: answers at most `limit` of them, as PostgREST does, and never a count (#1098). */
function stubView(rows: unknown[]) {
  const calls: Captured[] = [];
  const impl = (input: string, init: RequestInit): Promise<Response> => {
    calls.push({ url: String(input), init });
    const limit = new URL(String(input)).searchParams.get("limit");
    const out = limit === null ? rows : rows.slice(0, Number(limit));
    return Promise.resolve(new Response(JSON.stringify(out), { status: 200, headers: { "content-type": "application/json" } }));
  };
  return { calls, impl };
}

async function getView(path: string, rows: unknown[], headers: Record<string, string> = {}) {
  const stub = stubView(rows);
  const res = await makeHandler({ fetchImpl: stub.impl, env, gate: OPEN })(new Request(`${BASE}${path}`, { headers }));
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
  assertEquals(body(calls[0]), { p_cnpj: CNPJ, p_from: "2023-09-30", p_to: "2026-09-30", p_entity_type: "fi", p_after: "" }, "a family: fund_nav's own cursor");
  assertEquals(json.meta.request, { kind: "nav", family: "fi", holding: null, status: "all", id: CNPJ, from: "2023-09-30", to: "2026-09-30", limit: 10 });
  assertEquals(json.meta.endpoint, "api.fund_nav");
});

Deno.test("funds kind=nav with no to sends no p_to (the endpoint's latest complete period) and from counted from today", async () => {
  const { calls, json } = await get(`/v2/funds?id=${CNPJ}&kind=nav`);
  const sent = body(calls[0]);
  assertEquals(sent.p_to, undefined);
  assertEquals(sent.p_entity_type, undefined, "family=all is not sent");
  assertEquals(sent.p_after, undefined, "fund_nav pages with p_after only with a family; family=all walks date windows");
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

Deno.test("funds with no id GETs the funds view: eq filters, an order, no count asked", async () => {
  const rows = [{ cnpj: "00000000000191", entity_type: "fidc", fund_name: "A" }];
  const { res, json, calls } = await getView("/v2/funds?family=fidc&status=EM%20FUNCIONAMENTO%20NORMAL", rows);
  assertEquals(res.status, 200);
  assertEquals(calls.length, 1);
  assertEquals(calls[0].init.method, "GET");
  const u = new URL(calls[0].url);
  assertEquals(u.pathname, "/rest/v1/funds");
  assertEquals(u.searchParams.get("entity_type"), "eq.fidc");
  assertEquals(u.searchParams.get("status"), "eq.EM FUNCIONAMENTO NORMAL");
  assertEquals(u.searchParams.get("order"), "cnpj.asc,entity_type.asc");
  assertEquals(u.searchParams.get("limit"), "11", "the anonymous page maximum, plus one row that says whether more remain");
  assertEquals(u.searchParams.get("offset"), null, "the first page");
  const h = calls[0].init.headers as Record<string, string>;
  assertEquals(h["Accept-Profile"], "api");
  assertEquals(h["Prefer"], undefined, "no count=exact: it scans the whole selection (#1098)");
  assertEquals(json.data, rows);
  assertEquals(json.meta.endpoint, "api.funds");
  assertEquals(json.meta.rows_total, null, "no count is asked");
  assert(!("next_page_url" in json), "no extra row came back: every row was served");
});

Deno.test("funds with no id pages the view with limit + offset, and says while rows remain", async () => {
  const page = Array.from({ length: 11 }, (_, i) => ({ cnpj: String(i).padStart(14, "0") }));
  const first = await getView("/v2/funds", page);
  assertEquals(first.res.status, 200);
  assertEquals(first.json.data.length, 10, "the extra row says more remain and is not served");
  assertEquals(first.json.data, page.slice(0, 10));
  assertEquals(first.json.meta.rows_total, null);
  assertEquals(first.json.meta.rows_served, 10);
  assert(first.json.next_page_url.startsWith(`${BASE}/v2/funds?cursor=`));
  const next = await getView(pathOf(first.json.next_page_url), page);
  const u = new URL(next.calls[0].url);
  assertEquals(u.searchParams.get("offset"), "10", "the next page starts after the rows served, not after the extra row");
  assertEquals(u.searchParams.get("limit"), "11");
  assertEquals(next.json.meta.rows_served, 20);

  const exact = await getView("/v2/funds", page.slice(0, 10));
  assertEquals(exact.json.data.length, 10);
  assert(!("next_page_url" in exact.json), "exactly a page and no extra row: nothing remains, no cursor");

  const coerced = await getView("/v2/funds?limit=500", page);
  assertEquals(coerced.res.status, 200, "a limit above the tier maximum is coerced, not refused (AIP-158)");
  assertEquals(coerced.json.meta.request.limit, 10);
  assertEquals(coerced.json.meta.limit_coerced_from, 500);
  const signed = await getView("/v2/funds?limit=500", page, SIGNED);
  assertEquals(new URL(signed.calls[0].url).searchParams.get("limit"), "101", "the signed-in page maximum, plus one");
  const zero = await get("/v2/funds?limit=0");
  assertEquals(zero.json.error.target, "limit");
});

Deno.test("funds holdings and debentures: exactly one of id and holding", async () => {
  const fwd = await get(`/v2/funds?id=${CNPJ}&kind=holdings&from=2025-01-01&to=2025-12-31&limit=50`);
  assert(fwd.calls[0].url.endsWith("/rpc/fund_holdings"));
  assertEquals(body(fwd.calls[0]), { p_cnpj: CNPJ, p_from: "2025-01-01", p_to: "2025-12-31" }, "limit is the page size, never p_limit (a head)");

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
    [`kind=portfolio&item=sector&limit=10`, "fidc_portfolio", { p_cnpj: CNPJ, p_kind: "sector", p_from: "2024-09-30", p_to: "2026-09-30" }],
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
  const { json, calls } = await getView("/v2/fidc?limit=5", Array(4120).fill({ cnpj: CNPJ, entity_type: "fidc" }));
  const u = new URL(calls[0].url);
  assertEquals(u.pathname, "/rest/v1/funds");
  assertEquals(u.searchParams.get("entity_type"), "eq.fidc");
  assertEquals(u.searchParams.get("limit"), "6");
  assertEquals(json.data.length, 5);
  assert(json.next_page_url, "4,120 held and 5 served: the cursor says more remain");
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

// ------------------------------------------------- prices (#1055) --

// The default windows, counted back from today in UTC-3 (window_months 12 and 60).
const Y1 = minusMonths(todayUtcMinus3(), 12);
const Y5 = minusMonths(todayUtcMinus3(), 60);

Deno.test("prices defaults: quote_history, split-adjusted core fields, adjusted true on every row", async () => {
  const rows = [{ ticker: "PETR4", trade_date: "2026-10-30", close_adj: 38.12, isin: "BRPETRACNPR6" }];
  const { res, json, calls } = await get("/v2/prices?id=PETR4", 200, JSON.stringify(rows));
  assertEquals(res.status, 200);
  assertEquals(calls.length, 1);
  assert(calls[0].url.endsWith("/rpc/quote_history"));
  assertEquals(body(calls[0]), { p_ticker: "PETR4", p_from: M3, p_fields: ["close_adj", "isin"], p_after: "" }, "no to: the SQL's default end applies");
  assertEquals(json.data, [{ ...rows[0], adjusted: true }]);
  assertEquals(json.meta.request, {
    kind: "history", freq: "day", adjust: "split", board: null, asset_class: "all", fields: "core", date: null,
    id: "PETR4", from: M3, to: null, limit: 10,
  });
  assertEquals(json.meta.window_narrowed_to_tier, { months: 3, tier: "anonymous" }, "the 1-year default, narrowed to the anonymous daily window");
  assertEquals(json.meta.endpoint, "api.quote_history");
  const signed = await get("/v2/prices?id=PETR4", 200, JSON.stringify(rows), SIGNED);
  assertEquals(body(signed.calls[0]).p_from, Y1, "signed in: the 1-year default fits the 2-year window");
});

Deno.test("prices adjust=none serves the raw close; fields=all never carries an adjusted field with it", async () => {
  const none = await get("/v2/prices?id=PETR4&adjust=none", 200, JSON.stringify([{ ticker: "PETR4", trade_date: "2026-10-30", close: 38.5, isin: "X" }]));
  assertEquals(body(none.calls[0]).p_fields, ["close", "isin"]);
  assertEquals(none.json.data[0].adjusted, false);
  const all = await get("/v2/prices?id=PETR4&adjust=none&fields=all");
  const f: string[] = body(all.calls[0]).p_fields;
  assert(f.includes("close") && f.includes("volume") && f.includes("isin"));
  assert(!f.includes("close_adj") && !f.includes("close_total_return"));
  const split = await get("/v2/prices?id=PETR4&fields=all");
  assert(body(split.calls[0]).p_fields.includes("close_adj"));
});

Deno.test("prices freq=month keeps the last session of each month, never a filled month", async () => {
  const rows = [
    { ticker: "X", trade_date: "2026-01-29", close_adj: 1 },
    { ticker: "X", trade_date: "2026-01-30", close_adj: 2 },
    { ticker: "X", trade_date: "2026-03-02", close_adj: 3 },
    { ticker: "X", trade_date: "2026-03-31", close_adj: 4 },
  ];
  const { json } = await get("/v2/prices?id=X&freq=month", 200, JSON.stringify(rows));
  assertEquals(json.data.map((r: { trade_date: string }) => r.trade_date), ["2026-01-30", "2026-03-31"], "February had no session: no row");
  const idx = await get("/v2/prices?kind=index&id=IBOV&freq=month", 200, JSON.stringify([{ index_code: "IBOV", trade_date: "2026-01-30", level: 1 }]));
  assert(idx.calls[0].url.endsWith("/rpc/index_history"));
  assertEquals(body(idx.calls[0]), { p_index: "IBOV", p_from: M3, p_after: "" });
  assertEquals(idx.json.data[0].adjusted, false);
});

Deno.test("prices with only to counts the 1-year window back from it, and echoes it", async () => {
  const { json, calls } = await get("/v2/prices?id=PETR4&to=2021-06-30", 200, "[]", SIGNED);
  assertEquals(body(calls[0]).p_from, "2020-06-30");
  assertEquals(body(calls[0]).p_to, "2021-06-30");
  assertEquals(json.meta.request.from, "2020-06-30");
  const fwd = await get("/v2/prices?kind=forward&id=IMAB11&from=2026-01-01", 200, "[]", SIGNED);
  assert(fwd.calls[0].url.endsWith("/rpc/trade_consolidated_history"));
  assertEquals(body(fwd.calls[0]), { p_ticker: "IMAB11", p_from: "2026-01-01", p_after: "" });
  const anon = await get("/v2/prices?id=PETR4&to=2021-06-30");
  assertEquals(body(anon.calls[0]).p_from, "2021-03-30", "anonymous: the default window narrowed to 3 months of daily data");
});

Deno.test("prices refuses a value its kind cannot use, before any call", async () => {
  for (const [path, target] of [
    ["/v2/prices?kind=latest&id=PETR4&adjust=none", "adjust"],
    ["/v2/prices?id=PETR4&asset_class=equity", "asset_class"],
    ["/v2/prices?kind=session&freq=month", "freq"],
    ["/v2/prices?kind=index&id=IBOV&board=02", "board"],
    ["/v2/prices?adjust=none", "adjust"],
  ]) {
    const { json, calls } = await get(path);
    assertEquals(json.error.code, "bad_request", path);
    assertEquals(json.error.target, target, path);
    assertEquals(calls.length, 0, path);
  }
});

Deno.test("prices with no id lists the research universe; latest projects core unless fields=all", async () => {
  const none = await get("/v2/prices", 200, JSON.stringify([{ ticker: "AAAA3", isin: "BRAAAAACNOR0" }]));
  assert(none.calls[0].url.endsWith("/rpc/research_universe"));
  assertEquals(none.json.data, [{ ticker: "AAAA3", isin: "BRAAAAACNOR0" }], "no adjusted on a universe row");
  const row = { ticker: "PETR4", trade_date: "2026-10-30", board: "02", close: 38.5, isin: "X", adjusted: false, contract_points_raw: null };
  const latest = await get("/v2/prices?kind=latest&id=PETR4", 200, JSON.stringify([row]));
  assertEquals(body(latest.calls[0]), { p_ticker: "PETR4" });
  assertEquals(latest.json.data, [{ ticker: "PETR4", trade_date: "2026-10-30", board: "02", isin: "X", close: 38.5, adjusted: false }]);
  const all = await get("/v2/prices?kind=latest&id=PETR4&fields=all", 200, JSON.stringify([row]));
  assertEquals(all.json.data, [row], "fields=all drops no column");
});

Deno.test("prices kind=session: the newest session found, pinned, and read a page at a time from the view asset_class picks", async () => {
  const rows = [
    { ticker: "AAAA3", trade_date: "2026-10-30", board: "02", close: 1 },
    { ticker: "BBBB3", trade_date: "2026-10-30", board: "02", close: 2 },
  ];
  const { json, calls } = await getView("/v2/prices?kind=session", rows);
  assertEquals(calls.length, 2, "one GET finds the newest session, one reads it");
  for (const c of calls) assertEquals(c.init.method, "GET");
  const probe = new URL(calls[0].url);
  assertEquals(probe.pathname, "/rest/v1/quotes");
  assert(probe.searchParams.get("trade_date")!.startsWith("gte."));
  assertEquals(probe.searchParams.get("limit"), "1");
  const read = new URL(calls[1].url);
  assertEquals(read.searchParams.get("trade_date"), "eq.2026-10-30");
  assertEquals(read.searchParams.get("order"), "trade_date.desc,ticker.asc");
  assertEquals(read.searchParams.get("limit"), "11");
  assertEquals((calls[1].init.headers as Record<string, string>)["Accept-Profile"], "api");
  assertEquals(json.data.map((r: { ticker: string }) => r.ticker), ["AAAA3", "BBBB3"]);
  assertEquals(json.data[0].adjusted, false);
  assertEquals(json.meta.endpoint, "api.quotes");
  assertEquals(json.meta.session, "2026-10-30");

  const eq = await get("/v2/prices?kind=session&asset_class=auction&date=2026-10-01&id=petr4&board=02", 200, "[]");
  assertEquals(eq.calls.length, 1, "a date asked needs no probe");
  const u = new URL(eq.calls[0].url);
  assertEquals(u.pathname, "/rest/v1/auctions");
  assertEquals(u.searchParams.get("trade_date"), "eq.2026-10-01");
  assertEquals(u.searchParams.get("ticker"), "eq.PETR4");
  assertEquals(u.searchParams.get("board"), "eq.02");
  assertEquals(eq.json.data, [], "a session with no print is an empty answer");
  assertEquals(eq.json.meta.endpoint, "api.auctions");
});

Deno.test("prices kind=session pages a session of any size; the pinned session rides in the cursor", async () => {
  const page = Array.from({ length: 1400 }, (_, i) => ({ ticker: `T${i}`, trade_date: "2026-10-30" }));
  const first = await getView("/v2/prices?kind=session&asset_class=equity", page);
  assertEquals(first.res.status, 200, "1,400 rows: served in pages, never refused, never cut");
  assert(first.calls[1].url.includes("/rest/v1/equities?"));
  assertEquals(first.json.data.length, 10);
  assert(first.json.next_page_url);
  const next = await getView(pathOf(first.json.next_page_url), page);
  assertEquals(next.calls.length, 1, "the pinned session needs no second probe");
  const u = new URL(next.calls[0].url);
  assertEquals(u.searchParams.get("trade_date"), "eq.2026-10-30");
  assertEquals(u.searchParams.get("offset"), "10");
  const whole = await getView("/v2/prices?kind=session&date=2026-10-30", page.slice(0, 3));
  assertEquals(whole.json.data.length, 3);
  assert(!("next_page_url" in whole.json));
  assertEquals((whole.calls[0].init.headers as Record<string, string>)["Prefer"], undefined, "no count=exact (#1098)");
  const empty = await get("/v2/prices?kind=session&id=ZZZZ3", 200, "[]");
  assertEquals(empty.json.error.target, "date", "no session in the lookback: say so, never an empty answer");
});

Deno.test("prices ?help lists kind, freq, adjust as main and the price views as endpoints", async () => {
  const { json } = await get("/v2/prices?help");
  const own = json.data[0].parameters.map((p: { name: string }) => p.name).filter((n: string) => !["id", "from", "to", "limit"].includes(n));
  assertEquals(own, ["kind", "freq", "adjust"]);
  for (const v of ["api.quote_history", "api.quotes", "api.equities", "api.auctions", "api.index_history", "api.trade_consolidated_history"]) {
    assert(json.data[0].endpoints.includes(v), v);
  }
});

// --------------------------------------------- statements (#1055) --

Deno.test("statements defaults: financials, consolidated, every period, 5 years by the SQL default", async () => {
  const rows = [{ id: "9512", doc_type: "itr", statement: "DRE", period_months: 3, value: 1 }];
  const { json, calls } = await get("/v2/statements?id=PETR4", 200, JSON.stringify(rows));
  assert(calls[0].url.endsWith("/rpc/financials"));
  assertEquals(body(calls[0]), { p_id: "PETR4", p_from: Y5, p_scope: "con" });
  assertEquals(json.data, rows, "rows as filed: period_months stays");
  assertEquals(json.meta.request, { kind: "all", period: "both", scope: "consolidated", as_of: null, statement: "DRE", id: "PETR4", from: Y5, to: null, limit: 10 });
});

Deno.test("statements maps period, scope and as_of to the SQL codes", async () => {
  const inc = await get("/v2/statements?id=PETR4&kind=income&period=quarterly&scope=individual&as_of=2024-02-29");
  assert(inc.calls[0].url.endsWith("/rpc/income_statements"));
  assertEquals(body(inc.calls[0]), { p_id: "PETR4", p_doc_type: "itr", p_scope: "ind", p_as_of: "2024-02-29", p_from: Y5 });
  const bal = await get("/v2/statements?id=PETR4&kind=balance&period=annual&to=2022-12-31");
  assert(bal.calls[0].url.endsWith("/rpc/balance_sheets"));
  assertEquals(body(bal.calls[0]), { p_id: "PETR4", p_doc_type: "dfp", p_scope: "con", p_from: "2017-12-31", p_to: "2022-12-31" });
  const cf = await get("/v2/statements?id=PETR4&kind=cashflow");
  assert(cf.calls[0].url.endsWith("/rpc/cash_flow_statements"));
});

Deno.test("statements headline selects period on doc_type; versions reads one statement, no as_of", async () => {
  const rows = [
    { id: "9512", doc_type: "itr", period_months: 3, revenue: 1 },
    { id: "9512", doc_type: "dfp", period_months: 12, revenue: 4 },
  ];
  const head = await get("/v2/statements?id=PETR4&kind=headline&period=annual", 200, JSON.stringify(rows));
  assert(head.calls[0].url.endsWith("/rpc/company_financials"));
  assertEquals(body(head.calls[0]), { p_id: "PETR4", p_from: Y5, p_scope: "con" },"company_financials takes no p_doc_type");
  assertEquals(head.json.data, [rows[1]]);
  const onlyItr = await get("/v2/statements?id=PETR4&kind=headline&period=annual", 200, JSON.stringify([rows[0]]));
  assertEquals(onlyItr.json.data, [], "an enum cannot be mistyped: no annual row is an empty answer");

  const ver = await get("/v2/statements?id=PETR4&kind=versions&statement=BPA");
  assert(ver.calls[0].url.endsWith("/rpc/financial_statement_history"));
  assertEquals(body(ver.calls[0]), { p_id: "PETR4", p_statement: "BPA", p_scope: "con", p_from: Y5 });
  const pit = await get("/v2/statements?id=PETR4&kind=versions&as_of=2024-01-01");
  assertEquals(pit.json.error.target, "as_of");
  assertEquals(pit.calls.length, 0);
  const misplaced = await get("/v2/statements?id=PETR4&statement=BPA");
  assertEquals(misplaced.json.error.target, "statement");
});

Deno.test("statements with no id lists the research universe", async () => {
  const { json, calls } = await get("/v2/statements?kind=income", 200, JSON.stringify([{ ticker: "PETR4", cnpj: "33000167000101" }]));
  assert(calls[0].url.endsWith("/rpc/research_universe"));
  assertEquals(body(calls[0]), {});
  assertEquals(json.data.length, 1);
  const bad = await get("/v2/statements?period=annual");
  assertEquals(bad.json.error.target, "period");
});

// ------------------------- derivatives, curves, macro, positioning (#1057) --

const M3 = minusMonths(todayUtcMinus3(), 3);
// Y3 (36 months back) is declared with the #1058 tests below; a const is hoisted for use at test run time.
const rowsOf = (n: number, f: (i: number) => Record<string, unknown> = (i) => ({ codneg: `PETRK${i}` })) =>
  JSON.stringify(Array.from({ length: n }, (_, i) => f(i)));

Deno.test("derivatives chain: option_chain with the prefix upper case, asked for 1,001 rows, served in pages", async () => {
  const { res, json, calls } = await get("/v2/derivatives?id=petr", 200, rowsOf(40));
  assertEquals(res.status, 200);
  assert(calls[0].url.endsWith("/rpc/option_chain"));
  assertEquals(body(calls[0]), { p_prefix: "PETR", p_limit: 1001 }, "no date: the SQL's latest session; expiry_from: today");
  assertEquals(json.data.length, 10, "the anonymous page of a 40-series chain");
  assert(json.next_page_url);
  assertEquals(json.meta.request, { kind: "chain", date: null, expiry_from: null, id: "PETR", from: null, to: null, limit: 10 });
  const next = await get(pathOf(json.next_page_url), 200, rowsOf(40));
  assertEquals(next.json.data[0].codneg, "PETRK10", "the next slice of the same chain");

  const dated = await get("/v2/derivatives?id=PETR&date=2026-10-30&expiry_from=2026-11-01&limit=50", 200, rowsOf(10));
  assertEquals(body(dated.calls[0]), { p_prefix: "PETR", p_trade_date: "2026-10-30", p_expiry_from: "2026-11-01", p_limit: 1001 });
});

Deno.test("derivatives chain refuses a chain the SQL may have cut, whatever limit asks", async () => {
  for (const n of [200, 1000, 1001]) {
    const r = await get("/v2/derivatives?id=PETR&limit=5", 200, rowsOf(n));
    assertEquals(r.res.status, 400, String(n));
    assertEquals(r.json.error.code, "over_limit");
    assert(!("data" in r.json));
  }
  const ok = await get("/v2/derivatives?id=PETR", 200, rowsOf(199));
  assertEquals(ok.res.status, 200, "199 is no ceiling: the whole chain, in pages");
});

Deno.test("derivatives exercises: asks 1,001; a count the SQL may have cut halves the window, and one day still cut is refused", async () => {
  const ok = await get("/v2/derivatives?kind=exercises&id=VALE&from=2026-01-01", 200, rowsOf(3), SIGNED);
  assert(ok.calls[0].url.endsWith("/rpc/option_exercises"));
  assertEquals(body(ok.calls[0]), { p_prefix: "VALE", p_from: "2026-01-01", p_limit: 1001 });
  assertEquals(ok.json.data.length, 3);
  const day = await get("/v2/derivatives?kind=exercises&id=VALE&from=2026-10-01&to=2026-10-01", 200, rowsOf(500));
  assertEquals(day.json.error.code, "over_limit");
  assertEquals(day.calls.length, 1);
  // The stub cuts every window at 500 (the anonymous ceiling): halved down to one day, then refused.
  const halved = await get("/v2/derivatives?kind=exercises&id=VALE&from=2026-09-01&to=2026-10-30", 200, rowsOf(500));
  assertEquals(body(halved.calls[1]).p_to, "2026-09-30", "60 days, halved to 30");
  assertEquals(halved.json.error.code, "over_limit");
  assert(!("data" in halved.json), "never served cut");
});

Deno.test("derivatives history, termo, futures need an id and take the 1-year window", async () => {
  for (const [kind, fn, arg] of [["history", "option_history", "p_codneg"], ["termo", "termo_history", "p_codneg"], ["futures", "future_series", "p_ticker"]]) {
    const r = await get(`/v2/derivatives?kind=${kind}&id=x1`);
    assert(r.calls[0].url.endsWith(`/rpc/${fn}`), kind);
    assertEquals(body(r.calls[0]), { [arg]: "X1", p_from: M3 }, kind);
    const signed = await get(`/v2/derivatives?kind=${kind}&id=x1`, 200, "[]", SIGNED);
    assertEquals(body(signed.calls[0]).p_from, Y1, kind);
    const none = await get(`/v2/derivatives?kind=${kind}`);
    assertEquals(none.json.error.target, "id");
    assertEquals(none.calls.length, 0);
  }
});

Deno.test("derivatives futures_curve: root default DI1 (not sent), date; di_settlement is a ranged GET", async () => {
  const curve = await get("/v2/derivatives?kind=futures_curve&date=2026-10-30");
  assert(curve.calls[0].url.endsWith("/rpc/future_curve"));
  assertEquals(body(curve.calls[0]), { p_trade_date: "2026-10-30" });
  const misplaced = await get("/v2/derivatives?kind=futures_curve&from=2026-01-01");
  assertEquals(misplaced.json.error.target, "from");

  const di = await getView("/v2/derivatives?kind=di_settlement&id=di1f27&from=2026-01-01&to=2026-06-30", [{ trade_date: "2026-06-30" }], SIGNED);
  assertEquals(di.calls[0].init.method, "GET");
  const u = new URL(di.calls[0].url);
  assertEquals(u.pathname, "/rest/v1/di_settlement");
  assertEquals(u.searchParams.get("ticker"), "eq.DI1F27");
  assertEquals(u.searchParams.get("and"), "(trade_date.gte.2026-01-01,trade_date.lte.2026-06-30)");
  assertEquals(u.searchParams.get("trade_date"), null, "the range is not an eq. filter");
  assertEquals(u.searchParams.get("order"), "trade_date.desc,ticker.asc");
  assertEquals(di.json.meta.endpoint, "api.di_settlement");
  const date = await get("/v2/derivatives?kind=di_settlement&date=2026-10-30");
  assertEquals(date.json.error.target, "date");
  assertEquals(date.calls.length, 0);
  const many = await getView("/v2/derivatives?kind=di_settlement", Array.from({ length: 9000 }, () => ({})));
  assert(many.json.next_page_url, "9,000 held: paged, never refused or cut");
  const wide = await get("/v2/derivatives?kind=di_settlement&from=2026-01-01&to=2026-06-30");
  assertEquals(wide.res.status, 403);
  assertEquals(wide.json.error.code, "forbidden_for_tier", "anonymous: 6 months of daily data is wider than 3");
  assertEquals(wide.json.error.target, "from");
  assertEquals(wide.calls.length, 0);
});

Deno.test("curves snapshot and history map curve, date and tenor; tenor is used by history only", async () => {
  const snap = await get("/v2/curves");
  assert(snap.calls[0].url.endsWith("/rpc/curve"));
  assertEquals(body(snap.calls[0]), { p_curve: "PRE" });
  assertEquals(snap.json.meta.request, { kind: "snapshot", curve: "PRE", tenor: 360, date: null, from: null, to: null, limit: 10 });
  const hist = await get("/v2/curves?kind=history&curve=DPL&tenor=720&to=2026-06-30");
  assert(hist.calls[0].url.endsWith("/rpc/curve_history"));
  assertEquals(body(hist.calls[0]), { p_curve: "DPL", p_tenor_days: 720, p_from: "2026-03-30", p_to: "2026-06-30" }, "anonymous: 3 months of daily data");
  const tenor = await get("/v2/curves?tenor=90");
  assertEquals(tenor.json.error.target, "tenor");
  const curve = await get("/v2/curves?curve=DIC");
  assertEquals(curve.json.error.target, "curve");
  for (const r of [tenor, curve]) assertEquals(r.calls.length, 0);
});

Deno.test("curves vertices: the newest session found and pinned, or the date asked, read from reference_rate", async () => {
  const rows = [
    { trade_date: "2026-10-30", curve: "PRE", calendar_days: 1, rate_pct: 14.9 },
    { trade_date: "2026-10-30", curve: "PRE", calendar_days: 30, rate_pct: 14.8 },
  ];
  const { json, calls } = await get("/v2/curves?kind=vertices&curve=DOC", 200, JSON.stringify(rows));
  assertEquals(calls.length, 2);
  const probe = new URL(calls[0].url);
  assertEquals(probe.pathname, "/rest/v1/reference_rate");
  assertEquals(probe.searchParams.get("curve"), "eq.DOC");
  assert(probe.searchParams.get("trade_date")!.startsWith("gte."));
  assertEquals(probe.searchParams.get("limit"), "1");
  const u = new URL(calls[1].url);
  assertEquals(u.searchParams.get("trade_date"), "eq.2026-10-30");
  assertEquals(u.searchParams.get("order"), "trade_date.desc,calendar_days.asc");
  assertEquals(json.data.length, 2);
  assertEquals(json.meta.endpoint, "api.reference_rate");
  const dated = await get("/v2/curves?kind=vertices&date=2026-10-29", 200, "[]");
  assertEquals(new URL(dated.calls[0].url).searchParams.get("trade_date"), "eq.2026-10-29");
  assertEquals(dated.json.data, []);
  const none = await get("/v2/curves?kind=vertices", 200, "[]");
  assertEquals(none.json.error.target, "date");
  const window = await get("/v2/curves?kind=vertices&from=2026-01-01");
  assertEquals(window.json.error.target, "from");
});

Deno.test("macro series needs an id; inflation takes the 3-year window and family", async () => {
  const s = await get("/v2/macro?id=SELIC_META");
  assert(s.calls[0].url.endsWith("/rpc/macro_series"));
  assertEquals(body(s.calls[0]), { p_series: "SELIC_META", p_from: Y1 });
  const none = await get("/v2/macro");
  assertEquals(none.json.error.target, "id");
  assertEquals(none.calls.length, 0);

  const inf = await get("/v2/macro?kind=inflation&family=core");
  assert(inf.calls[0].url.endsWith("/rpc/inflation"));
  assertEquals(body(inf.calls[0]), { p_family: "core", p_from: Y3 });
  const focusFamily = await get("/v2/macro?kind=inflation&family=selic");
  assertEquals(focusFamily.json.error.target, "family");
  assertEquals(focusFamily.calls.length, 0);
  const misplaced = await get("/v2/macro?id=CDI&family=core");
  assertEquals(misplaced.json.error.target, "family");
});

Deno.test("macro inflation_items: no id reads the groups (SQL default), an id reads every level", async () => {
  const groups = await get("/v2/macro?kind=inflation_items");
  assert(groups.calls[0].url.endsWith("/rpc/inflation_items"));
  assertEquals(body(groups.calls[0]), { p_from: Y3 });
  const item = await get("/v2/macro?kind=inflation_items&id=1101002&from=2025-01-01");
  assertEquals(body(item.calls[0]), { p_item: "1101002", p_from: "2025-01-01", p_level: null });
});

Deno.test("macro fx: ptax for one currency; currency=all reads the ptax_daily view with a range", async () => {
  const usd = await get("/v2/macro?kind=fx");
  assert(usd.calls[0].url.endsWith("/rpc/ptax"));
  assertEquals(body(usd.calls[0]), { p_currency: "USD", p_from: M3 }, "fx is daily: the anonymous window");
  const all = await getView("/v2/macro?kind=fx&currency=all&from=2026-10-01&limit=10", [{ date: "2026-10-30", currency: "EUR" }]);
  const u = new URL(all.calls[0].url);
  assertEquals(u.pathname, "/rest/v1/ptax_daily");
  assertEquals(u.searchParams.get("date"), "gte.2026-10-01");
  assertEquals(u.searchParams.get("limit"), "11");
  assertEquals(u.searchParams.get("currency"), null);
  assertEquals(all.json.meta.endpoint, "api.ptax_daily");
  const limit = await get("/v2/macro?kind=fx&limit=5");
  assertEquals(limit.res.status, 200, "limit is the page size of every kind");
  assertEquals(limit.json.meta.request.limit, 5);
});

Deno.test("macro expectations: family is the Focus survey (annual by default) and horizon defaults to this year", async () => {
  const year = todayUtcMinus3().slice(0, 4);
  const a = await get("/v2/macro?kind=expectations&id=IPCA");
  assert(a.calls[0].url.endsWith("/rpc/focus_expectations"));
  assertEquals(body(a.calls[0]), { p_indicator: "IPCA", p_endpoint: "ExpectativasMercadoAnuais", p_horizon: year, p_from: Y1 });
  assertEquals(a.json.meta.request.family, "annual");
  assertEquals(a.json.meta.request.horizon, year);
  const m = await get("/v2/macro?kind=expectations&family=selic&horizon=R6/2028");
  assertEquals(body(m.calls[0]).p_endpoint, "ExpectativasMercadoSelic");
  assertEquals(body(m.calls[0]).p_horizon, "R6/2028");
  const noHorizon = await get("/v2/macro?kind=expectations&family=monthly");
  assertEquals(noHorizon.json.error.target, "horizon");
  const wrong = await get("/v2/macro?kind=expectations&family=core");
  assertEquals(wrong.json.error.target, "family");
  for (const r of [noHorizon, wrong]) assertEquals(r.calls.length, 0);
});

Deno.test("positioning: each kind GETs its view newest first, with a 3-month range and eq filters", async () => {
  const si = await getView("/v2/positioning?id=petr4", [{ trade_date: "2026-10-30", ticker: "PETR4" }]);
  let u = new URL(si.calls[0].url);
  assertEquals(u.pathname, "/rest/v1/short_interest");
  assertEquals(u.searchParams.get("ticker"), "eq.PETR4");
  assertEquals(u.searchParams.get("trade_date"), `gte.${M3}`);
  assertEquals(u.searchParams.get("order"), "trade_date.desc,ticker.asc");
  assertEquals(si.json.meta.request.from, M3);

  const sector = await getView("/v2/positioning?kind=short_by_sector&sector=Petr%C3%B3leo&to=2026-10-30", []);
  u = new URL(sector.calls[0].url);
  assertEquals(u.pathname, "/rest/v1/short_interest_by_sector");
  assertEquals(u.searchParams.get("sector"), "eq.Petróleo");
  assertEquals(u.searchParams.get("and"), "(trade_date.gte.2026-07-30,trade_date.lte.2026-10-30)");

  for (const [kind, view] of [["lending", "lending_trades"], ["lending_brokers", "lending_participants"]]) {
    const r = await getView(`/v2/positioning?kind=${kind}&id=VALE3`, []);
    assertEquals(new URL(r.calls[0].url).pathname, `/rest/v1/${view}`, kind);
  }
  const flow = await getView("/v2/positioning?kind=investor_flow&investor_type=Estrangeiro", []);
  u = new URL(flow.calls[0].url);
  assertEquals(u.pathname, "/rest/v1/investor_flow");
  assertEquals(u.searchParams.get("investor_type"), "eq.Estrangeiro");
  assertEquals(u.searchParams.get("reference_date"), `gte.${M3}`);
  assertEquals(u.searchParams.get("order"), "reference_date.desc,investor_type.asc");
});

Deno.test("positioning pages a selection over one page and refuses a parameter its kind cannot use", async () => {
  const page = Array.from({ length: 4200 }, (_, i) => ({ ticker: `T${i}` }));
  const many = await getView("/v2/positioning", page);
  assertEquals(many.res.status, 200);
  assert(many.json.next_page_url, "4,200 held: paged, never refused or cut");
  const head = await getView("/v2/positioning?limit=5", page);
  assertEquals(new URL(head.calls[0].url).searchParams.get("limit"), "6");
  assert(head.json.next_page_url);
  const id = await get("/v2/positioning?kind=investor_flow&id=PETR4");
  assertEquals(id.json.error.target, "id");
  const sector = await get("/v2/positioning?kind=lending&sector=Financeiro");
  assertEquals(sector.json.error.target, "sector");
  for (const r of [id, sector]) assertEquals(r.calls.length, 0);
  const help = await get("/v2/positioning?help");
  assert(help.json.data[0].notes.some((n: string) => n.includes("is_total")));
  assert(!help.json.data[0].parameters.some((p: { name: string }) => p.name === "sector"), "sector is hidden");
});

Deno.test("a view resource asks for one row more than the page, never an exact count (#1098)", async () => {
  // positioning kind=lending: count(*) over the 3-month window outran the anon statement_timeout.
  const rows = Array.from({ length: 11 }, (_, i) => ({ trade_date: "2026-10-30", ticker: "VALE3", n: i }));
  const more = await getView("/v2/positioning?kind=lending&id=VALE3", rows);
  assertEquals(more.res.status, 200);
  assertEquals(more.calls.length, 1);
  const h = more.calls[0].init.headers as Record<string, string>;
  assert(!Object.values(h).some((v) => v.includes("count=")), "no Prefer count on a view call");
  assertEquals(new URL(more.calls[0].url).searchParams.get("limit"), "11");
  assertEquals(more.json.data, rows.slice(0, 10), "the extra row is not served");
  assertEquals(more.json.meta.rows_served, 10);
  assertEquals(more.json.meta.rows_total, null);
  assert(more.json.next_page_url, "the extra row came back: more remain");
  const state = decodeCursor(new URL(more.json.next_page_url).searchParams.get("cursor")!, "positioning");
  assertEquals(state.p, { off: 10 });

  const last = await getView(pathOf(more.json.next_page_url), rows.slice(10));
  assertEquals(new URL(last.calls[0].url).searchParams.get("offset"), "10");
  assertEquals(last.json.data, rows.slice(10));
  assertEquals(last.json.meta.rows_served, 11);
  assert(!("next_page_url" in last.json), "no extra row: no more rows, no cursor");

  const none = await getView("/v2/positioning?kind=lending_brokers&id=VALE3", rows.slice(0, 10));
  assertEquals(none.json.data.length, 10);
  assert(!("next_page_url" in none.json), "exactly a page and no extra row: nothing remains");
});

Deno.test("a view page of db-max-rows cannot ask for one more: a full page may have more (#1098)", async () => {
  const stub = stubView(Array.from({ length: 1500 }, (_, i) => ({ ticker: `T${i}` })));
  const pro: Gate = { tier: () => Promise.resolve("pro"), hit: () => Promise.resolve(1) };
  const handler = makeHandler({ fetchImpl: stub.impl, env, gate: pro });
  const res = await handler(new Request(`${BASE}/v2/positioning?limit=1000`, { headers: SIGNED }));
  const json = await res.json();
  assertEquals(res.status, 200);
  assertEquals(new URL(stub.calls[0].url).searchParams.get("limit"), "1000", "1,001 would be cut to 1,000 by db-max-rows");
  assertEquals(json.data.length, 1000);
  assert(json.next_page_url, "a full page of 1,000: more may remain");
});

Deno.test("every built resource keeps at most 3 main parameters, kind included", () => {
  for (const r of REGISTRY.resources.filter((x) => x.status === "built")) {
    const main = (r.parameters ?? []).filter((p) => p.visibility === "main");
    assert(main.length <= 3, r.name);
    // panel has one kind, so it takes no kind parameter (#1058).
    if (r.name === "panel") assert(!(r.parameters ?? []).some((p) => p.name === "kind"));
    else assert(main.some((p) => p.name === "kind"), r.name);
  }
});

// ------------------------------------------ panel, screens, portfolio (#1058) --

const Y3 = minusMonths(todayUtcMinus3(), 36);

// portfolio is served to signed-in callers (#1059), so post() signs in unless told not to.
async function post(path: string, payload: unknown, status = 200, rows = "[]", headers: Record<string, string> = SIGNED) {
  const stub = stubFetch(status, rows);
  const handler = makeHandler({ fetchImpl: stub.impl, env, gate: OPEN });
  const init: RequestInit = { method: "POST", body: typeof payload === "string" ? payload : JSON.stringify(payload), headers };
  const res = await handler(new Request(`${BASE}${path}`, init));
  return { res, json: await res.json(), calls: stub.calls };
}

Deno.test("panel: id is a list, 3 years by default, metric auto sends no p_metrics", async () => {
  const { res, json, calls } = await get("/v2/panel?id=PETR4,%2033000167000101", 200, "[]", SIGNED);
  assertEquals(res.status, 200);
  assert(calls[0].url.endsWith("/rpc/panel"));
  assertEquals(body(calls[0]), { p_ids: ["PETR4", "33000167000101"], p_from: Y3, p_freq: "month", p_after: "" });
  assertEquals(json.meta.kind, "panel");
  assertEquals(json.meta.request.id, ["PETR4", "33000167000101"]);
  const named = await get("/v2/panel?id=PETR4&metric=close,volume&freq=day&family=fi&from=2026-01-02", 200, "[]", SIGNED);
  assertEquals(body(named.calls[0]), { p_ids: ["PETR4"], p_metrics: ["close", "volume"], p_from: "2026-01-02", p_freq: "day", p_entity_type: "fi", p_after: "" });
  const daily = await get("/v2/panel?id=PETR4&freq=day&from=2026-01-02");
  assertEquals(daily.json.error.code, "forbidden_for_tier", "freq=day is daily data: anonymous reads 3 months");
});

Deno.test("panel: an unknown metric is unknown_parameter with the name in target, before any call", async () => {
  const { res, json, calls } = await get("/v2/panel?id=PETR4&metric=close,clsoe");
  assertEquals(res.status, 400);
  assertEquals(json.error.code, "unknown_parameter");
  assertEquals(json.error.target, "clsoe");
  assertEquals(calls.length, 0);
  const kind = await get("/v2/panel?id=PETR4&kind=panel");
  assertEquals(kind.json.error.code, "unknown_parameter");
});

Deno.test("panel: the gateway's id ceiling per tier, then the SQL's refusal verbatim; universe mode is not served yet", async () => {
  const two = await get("/v2/panel?id=A,B");
  assertEquals(two.res.status, 403);
  assertEquals(two.json.error.code, "forbidden_for_tier", "anonymous: 1 id per call");
  assertEquals(two.json.error.target, "id");
  const four = await get("/v2/panel?id=A,B,C,D", 200, "[]", SIGNED);
  assertEquals(four.json.error.code, "forbidden_for_tier", "signed in: 3 ids per call");
  assertStringIncludes(four.json.error.message, "never trimmed");
  for (const r of [two, four]) assertEquals(r.calls.length, 0);

  const pg = { code: "22023", message: "panel accepts at most 3 ids per call for anonymous callers; 4 were given.", hint: null, details: null };
  const over = await get("/v2/panel?id=A,B,C", 400, JSON.stringify(pg), SIGNED);
  assertEquals(over.json.error.code, "over_limit");
  assertEquals(over.json.error.message, pg.message);
  assertEquals(body(over.calls[0]).p_ids, ["A", "B", "C"], "never trimmed");
  const none = await get("/v2/panel");
  assertEquals(none.json.error.target, "id");
  assertEquals(none.calls.length, 0);
  const uni = await get("/v2/panel?family=fidc&min_nav=1000000&metric=delinquency", 200, "[]", SIGNED);
  assertEquals(uni.json.error.code, "forbidden_for_tier", "universe mode is the pro tier's (#1064)");
  assertEquals(uni.calls.length, 0);
  const misplaced = await get("/v2/panel?id=PETR4&min_months=12");
  assertEquals(misplaced.json.error.target, "min_months");
  const daily = await get("/v2/panel?family=fi&freq=day");
  assertEquals(daily.json.error.target, "freq");
});

Deno.test("screens with no kind lists the screens from the catalog, one row each, and says signal, not a verdict", async () => {
  const catalog = { screens: { zombie_growth: { function: "screen_zombie_growth", family: "fidc", params: { p_period: null, p_min_delinq_pct: 5, p_min_aum: 1000000 } } } };
  const { json, calls } = await get("/v2/screens", 200, JSON.stringify(catalog), SIGNED);
  assert(calls[0].url.endsWith("/rpc/catalog"));
  assertEquals(json.data.length, 1);
  assertEquals(json.data[0].kind, "zombie_growth");
  assertEquals(json.data[0].defaults, { date: null, min_delinq_pct: 5, min_aum: 1000000 });
  assertStringIncludes(json.meta.signal, "Signal, not a verdict");
  const anon = await get("/v2/screens", 200, JSON.stringify(catalog));
  assertEquals(anon.res.status, 403);
  assertEquals(anon.json.error.code, "forbidden_for_tier", "screens are signed-in only");
  assertEquals(anon.calls.length, 0);
  assertEquals((await get("/v2/screens?help")).res.status, 200, "?help stays open");
});

Deno.test("screens kinds send the SQL defaults (echoed) and refuse a threshold the screen does not take", async () => {
  const { json, calls } = await get("/v2/screens?kind=captive_vehicles&max_investors=5", 200, "[]", SIGNED);
  assert(calls[0].url.endsWith("/rpc/screen_captive_vehicles"));
  assertEquals(body(calls[0]), { p_lookback_months: 3, p_max_investors: 5, p_min_aum: 50000000 });
  assertEquals(json.meta.request.lookback_months, 3);
  assertStringIncludes(json.meta.signal, "not a verdict");
  const dd = await get("/v2/screens?kind=delinquency_drivers&min_delta_pp=0.5&driver=stable", 200, "[]", SIGNED);
  assertEquals(body(dd.calls[0]), { p_months: 12, p_min_months: 6, p_min_delta_brl: 1000000, p_min_delta_pp: 0.5, p_driver: "stable" });
  const bad = await get("/v2/screens?kind=overdue_securit&min_aum=1", 200, "[]", SIGNED);
  assertEquals(bad.json.error.code, "bad_request");
  assertEquals(bad.json.error.target, "min_aum");
  assertEquals(bad.calls.length, 0);
  const neg = await get("/v2/screens?kind=overdue_securit&min_volume=-1");
  assertEquals(neg.json.error.target, "min_volume");
});

Deno.test("portfolio is POST: kind in the query, lists in the body, one rpc call", async () => {
  const cnpjs = ["33000167000101"];
  const { res, json, calls } = await post("/v2/portfolio?kind=lookthrough&month=2026-08-31", { id: cnpjs });
  assertEquals(res.status, 200);
  assert(calls[0].url.endsWith("/rpc/portfolio_lookthrough"));
  assertEquals(calls[0].init.method, "POST");
  assertEquals(body(calls[0]), { p_cnpjs: cnpjs, p_month: "2026-08-31", p_max_depth: 4 });
  assertEquals(json.meta.body, { id: cnpjs });
  const resolve = await post("/v2/portfolio", { names: ["ITAU RF", null], quotas: [1.5, null] });
  assertEquals(body(resolve.calls[0]), { p_names: ["ITAU RF", null], p_quotas: [1.5, null] });
  const instr = await post("/v2/portfolio?kind=instruments", { id: ["CRA0260025T"] });
  assertEquals(body(instr.calls[0]), { p_codes: ["CRA0260025T"] });
  const anon = await post("/v2/portfolio?kind=fees", { id: cnpjs }, 200, "[]", {});
  assertEquals(anon.json.error.code, "forbidden_for_tier", "portfolio is signed-in only");
  assertEquals(anon.calls.length, 0);
});

Deno.test("portfolio refuses GET, a missing list, a misplaced list, a bad body and a list in the query", async () => {
  const getData = await get("/v2/portfolio?kind=fees");
  assertEquals(getData.res.status, 405);
  const help = await get("/v2/portfolio?help");
  assertEquals(help.res.status, 200);
  assertEquals(help.json.data[0].method, "POST");
  const missing = await post("/v2/portfolio?kind=fees", {});
  assertEquals(missing.json.error.target, "id");
  const misplaced = await post("/v2/portfolio?kind=fees", { id: ["1"], quotas: [1] });
  assertEquals(misplaced.json.error.target, "quotas");
  const unknown = await post("/v2/portfolio?kind=fees", { cnpjs: ["1"] });
  assertEquals(unknown.json.error.code, "unknown_parameter");
  const notJson = await post("/v2/portfolio?kind=fees", "{");
  assertEquals(notJson.json.error.target, "body");
  const badItem = await post("/v2/portfolio", { names: ["X"], quota_dates: ["2026-02-30"] });
  assertEquals(badItem.json.error.target, "quota_dates");
  const inQuery = await post("/v2/portfolio?kind=fees&id=1", { id: ["1"] });
  assertEquals(inQuery.json.error.code, "unknown_parameter");
  const noMonth = await post("/v2/portfolio?kind=debenture_returns", { id: ["VALE18"] });
  assertEquals(noMonth.json.error.target, "month");
  const depth = await post("/v2/portfolio?kind=fees&max_depth=2", { id: ["1"] });
  assertEquals(depth.json.error.target, "max_depth");
  for (const r of [getData, missing, misplaced, unknown, notJson, badItem, inQuery, noMonth, depth]) assertEquals(r.calls.length, 0);
  const other = await post("/v2/search?q=x", {});
  assertEquals(other.res.status, 405);
});

// ------------------------------------------ cursors and tiers (#1059) --

type Row = Record<string, unknown>;

/** Follow next_page_url from `first` to the end; every page must be a 200. */
async function walk(first: string, impl: FetchLike, headers: Record<string, string> = {}) {
  const handler = makeHandler({ fetchImpl: impl, env, gate: OPEN });
  const rows: Row[] = [];
  const pages: { data: Row[]; meta: Record<string, unknown>; next_page_url?: string }[] = [];
  let path: string | null = first;
  while (path !== null && pages.length < 200) {
    const res = await handler(new Request(`${BASE}${path}`, { headers }));
    const j = await res.json();
    assertEquals(res.status, 200, JSON.stringify(j.error ?? null));
    pages.push(j);
    rows.push(...j.data);
    path = j.next_page_url ? pathOf(j.next_page_url) : null;
  }
  return { rows, pages };
}

/** Run fn with one tier limit changed, then put it back. */
async function withLimit<T>(
  tier: "anonymous" | "signed_in",
  key: "rows_per_call" | "daily_window_months",
  value: number | null,
  fn: () => Promise<T>,
): Promise<T> {
  const was = TIERS[tier][key];
  TIERS[tier][key] = value;
  try {
    return await fn();
  } finally {
    TIERS[tier][key] = was;
  }
}

function iso(i: number, start = "2019-01-02"): string {
  const d = new Date(`${start}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + i);
  return d.toISOString().slice(0, 10);
}

const keyOf = (r: Row) => `${r.date}|${r.id}|${r.metric}|${r.asset_class}`;

/** api.panel with a 2,500-row answer, honouring p_after exactly as the SQL does: 1,000 rows after the key. */
function panelSeries(n = 2500) {
  const series: Row[] = Array.from({ length: n }, (_, i) => ({ id: "PETR4", asset_class: "equity", date: iso(i, "1990-01-01"), metric: "close", value: i }));
  const calls: string[] = [];
  const impl: FetchLike = (_url, init) => {
    const after = JSON.parse(String(init.body)).p_after;
    assertEquals(typeof after, "string", "panel is always called in paging mode");
    calls.push(after);
    const rest = after === "" ? series : series.filter((r) => keyOf(r) > after);
    return Promise.resolve(new Response(JSON.stringify(rest.slice(0, 1000)), { status: 200 }));
  };
  return { series, calls, impl };
}

Deno.test("done when (#1059): a 2,500-row series walks to the end through next_page_url, no row lost or repeated", async () => {
  const { series, calls, impl } = panelSeries();
  // Signed in, at its own page size (100). Its rows-per-call cap (1,000) would stop a 2,500-row walk,
  // so the cap is lifted here (as the pro tier's is) to walk to the end; the next test keeps it.
  const { rows, pages } = await withLimit("signed_in", "rows_per_call", null, () => walk("/v2/panel?id=PETR4&from=1990-01-01", impl, SIGNED));
  assertEquals(rows.length, 2500);
  assertEquals(rows.map(keyOf), series.map(keyOf), "every row once, in order");
  assertEquals(pages.length, 25);
  for (const p of pages) assertEquals(p.data.length, 100);
  assert(!("next_page_url" in pages[24]) && !pages[24].meta.tier_cap_reached, "the end: no next page, no cap");
  assertEquals(pages[24].meta.rows_served, 2500);
  assert(calls.includes(keyOf(series[999])), "the SQL's own 1,000-row page boundary was crossed with its cursor");
});

Deno.test("done when (#1059): the tiers' rows-per-call caps stop the walk with tier_cap_reached, never silently", async () => {
  const { series, impl } = panelSeries();
  const signed = await walk("/v2/panel?id=PETR4&from=1990-01-01", impl, SIGNED);
  assertEquals(signed.rows.map(keyOf), series.slice(0, 1000).map(keyOf), "signed in: the first 1,000, each once");
  const lastSigned = signed.pages[signed.pages.length - 1];
  assertEquals(lastSigned.meta.tier_cap_reached, true);
  assert(!("next_page_url" in lastSigned));

  const anon = await walk("/v2/panel?id=PETR4&from=1990-01-01", impl);
  assertEquals(anon.pages.length, 5, "anonymous: pages of 10");
  assertEquals(anon.rows.map(keyOf), series.slice(0, 50).map(keyOf), "anonymous: the first 50, each once");
  const last = anon.pages[4];
  assertEquals(last.meta.tier_cap_reached, true);
  assertStringIncludes(String(last.meta.tier_cap_message), "Sign in");
  assert(!("next_page_url" in last));
  for (const p of anon.pages.slice(0, 4)) assert(p.next_page_url && !p.meta.tier_cap_reached);
});

Deno.test("date-window walk: a function with no cursor is split into windows, a refused window halved, every row once", async () => {
  const series = Array.from({ length: 2500 }, (_, i) => ({ series: "CDI", date: iso(i), value: i }));
  let refused = 0;
  const impl: FetchLike = (url, init) => {
    assert(url.endsWith("/rpc/macro_series"));
    const a = JSON.parse(String(init.body));
    const rows = series.filter((r) => (!a.p_from || r.date >= a.p_from) && (!a.p_to || r.date <= a.p_to));
    if (rows.length > 1000) {
      refused++;
      const pg = { code: "22023", message: "macro_series: refused, this request would return more than 1000 rows. To fix: narrow p_from/p_to.", details: null, hint: null };
      return Promise.resolve(new Response(JSON.stringify(pg), { status: 400 }));
    }
    return Promise.resolve(new Response(JSON.stringify(rows), { status: 200 }));
  };
  const path = `/v2/macro?id=CDI&from=${series[0].date}&to=${series[2499].date}`;
  const { rows } = await withLimit("signed_in", "rows_per_call", null, () => walk(path, impl, SIGNED));
  assertEquals(rows.map((r) => r.date), series.map((r) => r.date), "every row once, oldest first");
  assert(refused >= 2, "the whole window and its first half were refused and halved");
});

Deno.test("date-window walk: a refusal that is not the row cap is returned at once, verbatim", async () => {
  const pg = { code: "22023", message: "macro_series: unknown series ZZZ. Known: CDI, SELIC.", details: null, hint: null };
  const r = await get("/v2/macro?id=ZZZ&from=2020-01-01", 400, JSON.stringify(pg));
  assertEquals(r.json.error.message, pg.message);
  assertEquals(r.calls.length, 1, "no halving on an unknown id");
});

Deno.test("view walk: order + limit + offset with an exact count, every row once", async () => {
  const view = Array.from({ length: 2500 }, (_, i) => ({ trade_date: "2026-10-30", ticker: `T${String(i).padStart(4, "0")}` }));
  const impl: FetchLike = (url) => {
    const u = new URL(url);
    assertEquals(u.pathname, "/rest/v1/short_interest");
    const off = Number(u.searchParams.get("offset") ?? 0);
    const lim = Number(u.searchParams.get("limit"));
    const page = view.slice(off, off + lim);
    return Promise.resolve(
      new Response(JSON.stringify(page), { status: 200, headers: { "content-range": `${off}-${off + page.length - 1}/${view.length}` } }),
    );
  };
  const { rows, pages } = await withLimit("signed_in", "rows_per_call", null, () => walk("/v2/positioning", impl, SIGNED));
  assertEquals(rows.map((r) => r.ticker), view.map((r) => r.ticker));
  assertEquals(pages.length, 25);
});

Deno.test("single_page kinds: one call holds the answer, served in pages of the tier's size", async () => {
  const universe = JSON.stringify(Array.from({ length: 25 }, (_, i) => ({ ticker: `T${i}`, isin: `BR${i}` })));
  const stub = stubFetch(200, universe);
  const { rows, pages } = await walk("/v2/search?kind=universe", stub.impl);
  assertEquals(pages.map((p) => p.data.length), [10, 10, 5]);
  assertEquals(rows.map((r) => r.ticker), Array.from({ length: 25 }, (_, i) => `T${i}`));
  assertEquals(pages[2].meta.rows_served, 25);
});

Deno.test("a cursor fixes every parameter: a different one is bad_request, the same one is fine", async () => {
  const universe = JSON.stringify(Array.from({ length: 25 }, (_, i) => ({ ticker: `T${i}` })));
  const first = await get("/v2/search?kind=universe", 200, universe);
  const next = pathOf(first.json.next_page_url);
  const same = await get(`${next}&kind=universe`, 200, universe);
  assertEquals(same.res.status, 200);
  assertEquals(same.json.data[0].ticker, "T10");
  const other = await get(`${next}&kind=any`, 200, universe);
  assertEquals(other.json.error.code, "bad_request");
  assertEquals(other.json.error.target, "kind");
  const added = await get(`${next}&as_of=2020-01-31`, 200, universe);
  assertEquals(added.json.error.target, "as_of");
  const garbage = await get("/v2/search?cursor=not*base64", 200, universe);
  assertEquals(garbage.json.error.target, "cursor");
  const elsewhere = await get(`/v2/coverage?${next.split("?")[1]}`, 200, universe);
  assertEquals(elsewhere.json.error.target, "cursor", "a search cursor on coverage");
  for (const r of [other, added, garbage, elsewhere]) assertEquals(r.calls.length, 0);
});

Deno.test("an unsigned cursor never widens a tier: its parameters are parsed again and the tier is the caller's", async () => {
  const universe = JSON.stringify(Array.from({ length: 200 }, (_, i) => ({ ticker: `T${i}` })));
  const first = await get("/v2/search?kind=universe&limit=100", 200, universe, SIGNED);
  const token = new URL(first.json.next_page_url).searchParams.get("cursor")!;
  const replay = await get(`/v2/search?cursor=${token}`, 200, universe);
  assertEquals(replay.json.data.length, 0, "anonymous replaying a signed-in cursor past its own cap is served nothing more");
  assertEquals(replay.json.meta.tier_cap_reached, true);

  const state = decodeCursor(token, "search");
  const reset = encodeCursor({ ...state, n: 0, q: { ...state.q, limit: "1000" } });
  const edited = await get(`/v2/search?cursor=${reset}`, 200, universe);
  assertEquals(edited.json.data.length, 10, "limit from an edited cursor is still coerced to the caller's page maximum");
  assertEquals(edited.json.data[0].ticker, "T100", "a position is only a position");

  const badKind = encodeCursor({ ...state, q: { ...state.q, kind: "nope" } });
  assertEquals((await get(`/v2/search?cursor=${badKind}`)).json.error.target, "kind", "validated like a fresh request");
  const badPos = encodeCursor({ ...state, p: { off: -3 } });
  assertEquals((await get(`/v2/search?cursor=${badPos}`)).json.error.target, "cursor");
  const outside = encodeCursor({
    v: 1,
    r: "macro",
    q: { id: "CDI", from: "2020-01-01", to: "2020-12-31" },
    m: "date_window",
    p: { a: "2019-01-01", b: "2020-12-31", span: 30, off: 0 },
    n: 0,
  });
  assertEquals((await get(`/v2/macro?cursor=${outside}`)).json.error.target, "cursor", "a window before from is refused");
});

Deno.test("a walk with a defaulted from keeps its window across midnight (UTC-3): the cursor carries the request day (#1103)", async () => {
  // Exercises with no from: the window is counted back from today. A window wider than a week is "cut"
  // (500 rows, the anonymous ceiling) and halved; a narrower one holds 20 rows, so the first page of 10
  // stops inside the first window and the cursor's position starts at the defaulted from.
  const sent: Record<string, unknown>[] = [];
  const impl: FetchLike = (_url, init) => {
    const b = JSON.parse(String(init.body));
    sent.push(b);
    const days = b.p_to ? (Date.parse(b.p_to) - Date.parse(b.p_from)) / 86_400_000 + 1 : Infinity;
    const n = days > 7 ? 500 : 20;
    return Promise.resolve(new Response(rowsOf(n, (i) => ({ i })), { status: 200 }));
  };
  const clock = { t: Date.parse("2026-11-12T02:30:00Z") }; // 23:30 UTC-3 on 2026-11-11
  const handler = makeHandler({ fetchImpl: impl, env, gate: OPEN, now: () => clock.t });
  const call = async (path: string) => {
    const res = await handler(new Request(`${BASE}${path}`));
    return { res, json: await res.json() };
  };
  const first = await call("/v2/derivatives?kind=exercises&id=VALE");
  assertEquals(first.res.status, 200, JSON.stringify(first.json.error ?? null));
  assertEquals(first.json.meta.request.from, "2026-08-11", "3 anonymous months back from 2026-11-11");
  assertEquals(sent[0].p_from, "2026-08-11");
  const token = new URL(first.json.next_page_url).searchParams.get("cursor")!;
  assertEquals(decodeCursor(token, "derivatives").t, "2026-11-11");

  clock.t = Date.parse("2026-11-12T03:30:00Z"); // 00:30 UTC-3 on 2026-11-12: a new day
  sent.length = 0;
  const next = await call(pathOf(first.json.next_page_url));
  assertEquals(next.res.status, 200, JSON.stringify(next.json.error ?? null));
  assertEquals(next.json.meta.request.from, "2026-08-11", "the window the walk started with, not one counted from the new day");
  assertEquals(sent[0].p_from, "2026-08-11");
  assertEquals(next.json.data.map((r: Row) => r.i), [10, 11, 12, 13, 14, 15, 16, 17, 18, 19], "the rest of the first window");

  // A fresh request on the new day counts from it.
  const fresh = await call("/v2/derivatives?kind=exercises&id=VALE");
  assertEquals(fresh.json.meta.request.from, "2026-08-12");

  // The cursor is unsigned: a request day other than today or yesterday is refused, never trusted.
  const state = decodeCursor(token, "derivatives");
  for (const t of ["2026-11-10", "2026-11-13", "2026-02-30"]) {
    const edited = await call(`/v2/derivatives?cursor=${encodeCursor({ ...state, t })}`);
    assertEquals(edited.res.status, 400, t);
    assertEquals(edited.json.error.target, "cursor", t);
  }
});

Deno.test("a POST cursor needs the same body; the body travels as a digest, not in the URL", async () => {
  const rows = JSON.stringify(Array.from({ length: 30 }, (_, i) => ({ cnpj: String(i).padStart(14, "0") })));
  const first = await post("/v2/portfolio?kind=fund_terms&limit=10", { id: ["33000167000101"] }, 200, rows);
  assertEquals(first.json.data.length, 10);
  const next = pathOf(first.json.next_page_url);
  assert(!next.includes("33000167000101"), "the body is not in the cursor");
  const again = await post(next, { id: ["33000167000101"] }, 200, rows);
  assertEquals(again.json.data[0].cnpj, "00000000000010");
  const changed = await post(next, { id: ["00000000000191"] }, 200, rows);
  assertEquals(changed.json.error.target, "body");
  assertEquals(changed.calls.length, 0);
});

Deno.test("freq=month on a p_after walk never picks a month-end from half a month", async () => {
  // The first 1,000 daily rows end mid-month: that month is read again from the next SQL page.
  const daily = Array.from({ length: 1200 }, (_, i) => ({ ticker: "X", trade_date: iso(i), close_adj: i }));
  const impl: FetchLike = (_url, init) => {
    const after = JSON.parse(String(init.body)).p_after;
    const rest = after === "" ? daily : daily.filter((r) => r.trade_date > after);
    return Promise.resolve(new Response(JSON.stringify(rest.slice(0, 1000)), { status: 200 }));
  };
  const path = `/v2/prices?id=X&freq=month&from=${daily[0].trade_date}&to=${daily[1199].trade_date}`;
  const { rows } = await withLimit("signed_in", "daily_window_months", null, () => walk(path, impl, SIGNED));
  const lastOf = (m: string) => daily.filter((r) => r.trade_date.startsWith(m)).at(-1)!.trade_date;
  const months = [...new Set(daily.map((r) => r.trade_date.slice(0, 7)))];
  assertEquals(rows.map((r) => String(r.trade_date)), months.map(lastOf), "one row per month, each its last session");
});

Deno.test("the tier numbers live in one block in config.ts", () => {
  assertEquals(TIERS.anonymous.page_max, 10);
  assertEquals(TIERS.anonymous.rows_per_call, 50);
  assertEquals(TIERS.signed_in.page_max, 100);
  assertEquals(TIERS.signed_in.rows_per_call, 1000);
  assertEquals(TIERS.pro.rows_per_call, null);
});

// ------------------------------------- tier and rate in Postgres (#1064) --

interface GateCall {
  fn: string;
  body: unknown;
  auth: string | null;
}

/**
 * A PostgREST stub that answers api.my_tier with `tier`, api.rate_hit with
 * the next number of `hits` (or `rateStatus` when set), and every data call
 * with []. It records which function was called, with what and by whom.
 */
function gateStub(opts: { tier?: unknown; tierStatus?: number; hits?: number[]; rateStatus?: number; rateThrows?: boolean }) {
  const calls: GateCall[] = [];
  let n = 0;
  const impl: FetchLike = (input, init) => {
    const url = String(input);
    const fn = url.includes("/rpc/") ? url.slice(url.indexOf("/rpc/") + 5) : url.slice(url.lastIndexOf("/") + 1);
    const headers = (init.headers ?? {}) as Record<string, string>;
    calls.push({ fn, body: init.body ? JSON.parse(String(init.body)) : null, auth: headers["Authorization"] ?? null });
    const reply = (status: number, body: unknown) =>
      Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }));
    if (fn === "my_tier") {
      if (opts.tierStatus) return reply(opts.tierStatus, { code: "PGRST301", message: "JWT expired" });
      return reply(200, opts.tier ?? "signed_in");
    }
    if (fn === "rate_hit") {
      if (opts.rateThrows) return Promise.reject(new Error("connection reset"));
      if (opts.rateStatus) return reply(opts.rateStatus, { code: "PGRST202", message: "Could not find the function api.rate_hit" });
      const hits = opts.hits ?? [1];
      return reply(200, hits[Math.min(n++, hits.length - 1)]);
    }
    return reply(200, []);
  };
  return { calls, impl };
}

/** 2026-11-03 21:30:15 UTC-3 (00:30:15 UTC): 45 s left in the minute. */
const NOW = Date.UTC(2026, 10, 4, 0, 30, 15);

function gated(stub: { impl: FetchLike }, clock: { t: number } = { t: NOW }) {
  return makeHandler({ fetchImpl: stub.impl, env, now: () => clock.t });
}

const fns = (calls: GateCall[]) => calls.map((c) => c.fn);

Deno.test("tier: no Bearer is anonymous with no my_tier call; the bucket is ip:<cf-connecting-ip>", async () => {
  const stub = gateStub({ hits: [1] });
  const res = await gated(stub)(new Request(`${BASE}/v2/coverage`, { headers: { "cf-connecting-ip": "203.0.113.7", "x-forwarded-for": "6.6.6.6, 203.0.113.7" } }));
  assertEquals(res.status, 200);
  assertEquals(fns(stub.calls), ["rate_hit", "coverage"]);
  assertEquals(stub.calls[0].body, { p_bucket: "ip:203.0.113.7" });
  assertEquals(stub.calls[0].auth, null);
  assertEquals(res.headers.get("RateLimit-Limit"), String(TIERS.anonymous.requests_per_minute));
  assertEquals(res.headers.get("RateLimit-Remaining"), String(TIERS.anonymous.requests_per_minute - 1));
});

Deno.test("tier: the publishable key sent as a Bearer is anonymous, never a my_tier call", async () => {
  const stub = gateStub({});
  const res = await gated(stub)(new Request(`${BASE}/v2/coverage`, { headers: { Authorization: "Bearer sb_publishable_abc" } }));
  assertEquals(res.status, 200);
  assertEquals(fns(stub.calls), ["rate_hit", "coverage"]);
});

Deno.test("tier: a Bearer asks api.my_tier with that token; rate_hit sends no bucket (SQL uses auth.uid())", async () => {
  const stub = gateStub({ tier: "signed_in" });
  const res = await gated(stub)(new Request(`${BASE}/v2/coverage`, { headers: SIGNED }));
  assertEquals(res.status, 200);
  assertEquals(fns(stub.calls), ["my_tier", "rate_hit", "coverage"]);
  assertEquals(stub.calls[0].auth, `Bearer ${JWT}`);
  assertEquals(stub.calls[1].body, {});
  assertEquals(stub.calls[1].auth, `Bearer ${JWT}`);
  assertEquals(res.headers.get("RateLimit-Limit"), String(TIERS.signed_in.requests_per_minute));
});

Deno.test("tier: a Bearer my_tier calls anonymous (is_anonymous sign-in) sends its ip bucket and is served (#1101)", async () => {
  // A Supabase anonymous sign-in: a real JWT whose claims carry is_anonymous: true.
  const b64 = (o: unknown) => btoa(JSON.stringify(o)).replace(/=+$/, "").replace(/\+/g, "-").replace(/\//g, "_");
  const anonJwt = `${b64({ alg: "HS256", typ: "JWT" })}.${b64({ sub: "00000000-0000-4000-8000-000000000001", role: "authenticated", is_anonymous: true })}.sig`;
  const stub = gateStub({ tier: "anonymous", hits: [1] });
  const res = await gated(stub)(
    new Request(`${BASE}/v2/coverage`, { headers: { Authorization: `Bearer ${anonJwt}`, "cf-connecting-ip": "198.51.100.4" } }),
  );
  assertEquals(res.status, 200);
  assertEquals(fns(stub.calls), ["my_tier", "rate_hit", "coverage"]);
  assertEquals(stub.calls[1].body, { p_bucket: "ip:198.51.100.4" });
  assertEquals(stub.calls[1].auth, `Bearer ${anonJwt}`);
  assertEquals(res.headers.get("RateLimit-Limit"), String(TIERS.anonymous.requests_per_minute));
});

Deno.test("tier: my_tier is cached per token for 60 s, then asked again", async () => {
  const stub = gateStub({ tier: "signed_in" });
  const clock = { t: NOW };
  const handler = gated(stub, clock);
  const once = () => handler(new Request(`${BASE}/v2/coverage`, { headers: SIGNED }));
  await once();
  clock.t += TIER_CACHE_MS - 1;
  await once();
  assertEquals(fns(stub.calls).filter((f) => f === "my_tier").length, 1);
  clock.t += 2;
  await once();
  assertEquals(fns(stub.calls).filter((f) => f === "my_tier").length, 2);
  // Another token is its own entry.
  await handler(new Request(`${BASE}/v2/coverage`, { headers: { Authorization: "Bearer other.user.jwt" } }));
  assertEquals(fns(stub.calls).filter((f) => f === "my_tier").length, 3);
});

Deno.test("tier: pro is what my_tier says, and replaces 'any Bearer is signed_in'", async () => {
  // Request 31 this minute: over signed_in's 30, within pro's 300.
  const pro = gateStub({ tier: "pro", hits: [TIERS.signed_in.requests_per_minute + 1] });
  const ok = await gated(pro)(new Request(`${BASE}/v2/coverage`, { headers: SIGNED }));
  assertEquals(ok.status, 200);
  assertEquals(ok.headers.get("RateLimit-Limit"), String(TIERS.pro.requests_per_minute));
  const signed = gateStub({ tier: "signed_in", hits: [TIERS.signed_in.requests_per_minute + 1] });
  const refused = await gated(signed)(new Request(`${BASE}/v2/coverage`, { headers: SIGNED }));
  assertEquals(refused.status, 429);
  // A token my_tier calls anonymous (an anonymous sign-in) gets anonymous limits: screens are refused.
  const anon = gateStub({ tier: "anonymous" });
  const screens = await gated(anon)(new Request(`${BASE}/v2/screens`, { headers: SIGNED }));
  assertEquals(screens.status, 403);
  assertEquals((await screens.json()).error.code, "forbidden_for_tier");
  assertEquals(fns(anon.calls), ["my_tier"]);
});

Deno.test("rate: above the tier's requests per minute is 429 rate_limited with Retry-After, and no data is read", async () => {
  const limit = TIERS.anonymous.requests_per_minute;
  const stub = gateStub({ hits: [limit, limit + 1] });
  const handler = gated(stub);
  const at = await handler(new Request(`${BASE}/v2/coverage`, { headers: { "cf-connecting-ip": "198.51.100.2" } }));
  assertEquals(at.status, 200);
  assertEquals(at.headers.get("RateLimit-Remaining"), "0");
  const over = await handler(new Request(`${BASE}/v2/coverage`, { headers: { "cf-connecting-ip": "198.51.100.2" } }));
  const body = await over.json();
  assertEquals(over.status, 429);
  assertEquals(body.error.code, "rate_limited");
  assertEquals(over.headers.get("Retry-After"), "45");
  assertEquals(over.headers.get("RateLimit-Limit"), String(limit));
  assertEquals(over.headers.get("RateLimit-Remaining"), "0");
  assertStringIncludes(body.error.message, `${limit} requests a minute`);
  assertStringIncludes(body.error.message, "Sign in");
  assert(!("data" in body));
  assertEquals(fns(stub.calls), ["rate_hit", "coverage", "rate_hit"]);
});

Deno.test("rate: index and ?help read no data and are not counted", async () => {
  const stub = gateStub({});
  const handler = gated(stub);
  assertEquals((await handler(new Request(`${BASE}/v2/`))).status, 200);
  assertEquals((await handler(new Request(`${BASE}/v2/coverage?help`, { headers: SIGNED }))).status, 200);
  assertEquals(stub.calls.length, 0);
});

Deno.test("rate: a request the parameters refuse is not counted", async () => {
  const stub = gateStub({});
  const res = await gated(stub)(new Request(`${BASE}/v2/search?q=petr&qq=1`));
  assertEquals(res.status, 400);
  assertEquals(stub.calls.length, 0);
});

Deno.test("fail closed: rate_hit unreachable or missing is unavailable, and no data is read", async () => {
  for (const opts of [{ rateThrows: true }, { rateStatus: 404 }]) {
    const stub = gateStub(opts);
    const res = await gated(stub)(new Request(`${BASE}/v2/coverage`));
    const body = await res.json();
    assertEquals(res.status, 503, JSON.stringify(opts));
    assertEquals(body.error.code, "unavailable");
    assertStringIncludes(body.error.message, "fails closed");
    assertEquals(fns(stub.calls), ["rate_hit"]);
  }
});

Deno.test("fail closed: an invalid token is unauthorized (passed on); a bad my_tier answer is internal", async () => {
  const expired = gateStub({ tierStatus: 401 });
  const res = await gated(expired)(new Request(`${BASE}/v2/coverage`, { headers: SIGNED }));
  assertEquals(res.status, 401);
  assertEquals((await res.json()).error.code, "unauthorized");
  assertEquals(fns(expired.calls), ["my_tier"]);
  const odd = gateStub({ tier: "gold" });
  const bad = await gated(odd)(new Request(`${BASE}/v2/coverage`, { headers: SIGNED }));
  assertEquals(bad.status, 500);
  assertEquals((await bad.json()).error.code, "internal");
});

Deno.test("clientIp: cf-connecting-ip, else x-forwarded-for's first hop, else one shared bucket", () => {
  assertEquals(clientIp(new Headers({ "cf-connecting-ip": "2001:db8::1", "x-forwarded-for": "1.1.1.1" })), "2001:db8::1");
  assertEquals(clientIp(new Headers({ "x-forwarded-for": " 192.0.2.4 , 10.0.0.1" })), "192.0.2.4");
  assertEquals(clientIp(new Headers({ "x-forwarded-for": "not-an-ip" })), "0.0.0.0");
  assertEquals(clientIp(new Headers({ "cf-connecting-ip": "evil'; drop" })), "0.0.0.0");
  assertEquals(clientIp(new Headers()), "0.0.0.0");
});

Deno.test("retryAfter: seconds to the next minute, 1..60", () => {
  assertEquals(retryAfter(Date.UTC(2026, 10, 4, 0, 30, 0)), 60);
  assertEquals(retryAfter(Date.UTC(2026, 10, 4, 0, 30, 59, 900)), 1);
  assertEquals(retryAfter(NOW), 45);
});
