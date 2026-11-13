import { assert, assertEquals } from "@std/assert";
import { OPERATIONS, operationQuery, operationBody } from "./operations.ts";
import { REGISTRY } from "./registry.ts";
import { acceptedParams } from "./params.ts";
import { makeHandler } from "./server.ts";
const base = "https://test.supabase.co/functions/v1/silo-api/v2";
const env = (n: string) => ({SUPABASE_URL:"https://test.supabase.co", SUPABASE_ANON_KEY:"test"}[n]);
const gate = {tier: () => Promise.resolve("pro" as const), hit: () => Promise.resolve(1)};
Deno.test("all 74 operation mappings reference real resource inputs and body fields", () => {
  assertEquals(OPERATIONS.length, 74);
  assertEquals(new Set(OPERATIONS.map(o => o.path)).size, 74);
  for (const op of OPERATIONS) {
    const r = REGISTRY.resources.find(r => r.name === op.resource)!;
    assert(r.kinds?.[op.kind]);
    const names = new Set([...acceptedParams(r).map(p => p.name), "cursor"]);
    for (const p of op.parameters) assert(names.has(p.target), `${op.path}: ${p.target}`);
    assert(!op.parameters.some(p => p.name === "kind" || p.name === "id"));
    for (const b of op.body) assert(r.body?.some(p => p.name === b.target));
    const input = new URLSearchParams(op.parameters.map(p => [p.name, "value"]));
    const output = operationQuery(op, input);
    for (const p of op.parameters) assertEquals(output.get(p.target), "value");
    if (op.body.length) {
      const body = Object.fromEntries(op.body.map(p => [p.name, ["x"]]));
      const translated = JSON.parse(operationBody(op, JSON.stringify(body)));
      for (const p of op.body) assertEquals(translated[p.target], ["x"]);
    }
  }
});
Deno.test("explicit macro route preserves rows and Pro, omits only diagnostics", async () => {
  const rows = [{series:"CDI",date:"2026-11-12",value:null,unit:"pct_day"}];
  const h = makeHandler({env, gate, fetchImpl: () => Promise.resolve(Response.json(rows))});
  for (const suffix of ["", "&details=true"]) {
    const res = await h(new Request(base + "/macro/series?series=CDI&from=2026-11-12&to=2026-11-12" + suffix));
    const b = await res.json();
    assertEquals(res.status,200); assertEquals(b.data,rows); assertEquals(b.meta.tier,"pro");
    assertEquals("request" in b.meta, !!suffix);
  }
  const legacy = await h(new Request(base + "/macro?kind=series&id=CDI&from=2026-11-12&to=2026-11-12"));
  assert("request" in (await legacy.json()).meta);
});
Deno.test("explicit routes refuse redundant, duplicate and invalid input", async () => {
  const h=makeHandler({env,gate,fetchImpl:()=>{throw new Error("must not fetch");}});
  for(const q of ["kind=series", "id=CDI", "series=CDI&series=IGPM", "details=yes", "series=CDI&from=bad"]) {
    assertEquals((await h(new Request(base+"/macro/series?"+q))).status,400,q);
  }
  assertEquals((await h(new Request(base+"/macro/nonexistent"))).status,404);
});
Deno.test("new route pagination stays on the same operation and rejects a different kind", async () => {
  const rows = [{series:"CDI",date:"2026-11-11",value:1},{series:"CDI",date:"2026-11-12",value:2}];
  const h=makeHandler({env,gate,fetchImpl:()=>Promise.resolve(Response.json(rows))});
  const first=await (await h(new Request(base+"/macro/series?series=CDI&from=2026-11-11&to=2026-11-12&limit=1&details=true"))).json();
  assert(first.next_page_url.startsWith(base+"/macro/series?cursor="));
  const second=await (await h(new Request(first.next_page_url))).json();
  assertEquals(second.data.length,1); assertEquals(second.meta.tier,"pro"); assert("request" in second.meta);
  const wrong=await h(new Request(first.next_page_url.replace("/macro/series?", "/macro/inflation?")));
  assertEquals(wrong.status,400);
});
Deno.test("explicit routes keep tier gates and errors", async () => {
  const anon={tier:()=>Promise.resolve("anonymous" as const),hit:()=>Promise.resolve(1)};
  const h=makeHandler({env,gate:anon,fetchImpl:()=>Promise.resolve(Response.json([]))});
  const res=await h(new Request(base+"/macro/series?series=CDI"));
  assertEquals((await res.json()).meta.tier,"anonymous");
  assertEquals((await h(new Request(base+"/screens/list"))).status,403);
  const failure=makeHandler({env,gate,fetchImpl:()=>Promise.resolve(Response.json({message:"bad token"},{status:401}))});
  assertEquals((await failure(new Request(base+"/macro/series?series=CDI"))).status,401);
});
Deno.test("hosted internal HTTP paths produce public HTTPS operation continuations", async () => {
  const rows=[{date:"2026-11-11",series:"CDI"},{date:"2026-11-12",series:"CDI"}];
  const h=makeHandler({env,gate,fetchImpl:()=>Promise.resolve(Response.json(rows))});
  const r=await h(new Request("http://test.supabase.co/silo-api/v2/macro/series?series=CDI&from=2026-11-11&to=2026-11-12&limit=1"));
  const b=await r.json();
  assert(b.next_page_url.startsWith(base+"/macro/series?cursor="));
  assertEquals((await h(new Request(b.next_page_url))).status,200);
});
