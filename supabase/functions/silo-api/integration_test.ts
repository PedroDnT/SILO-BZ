import { assertEquals, assertRejects } from "@std/assert";
import { ApiError } from "./errors.ts";
import { integrationSession } from "./integration.ts";
import { makeHandler } from "./server.ts";

Deno.test("integration authenticates via a dedicated account and refuses expiry, revocation and outage", async () => {
  const key = "silo_int_" + "ab".repeat(32);
  const hash = new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(key)));
  const expected = Array.from(hash, (byte) => byte.toString(16).padStart(2, "0")).join("");
  let now = Date.parse("2026-11-13T12:00:00Z");
  const expires = new Date(now + 60 * 24 * 60 * 60 * 1000).toISOString();
  const vars: Record<string, string> = {
    SILO_INTEGRATION_KEY_SHA256: expected,
    SILO_INTEGRATION_KEY_EXPIRES_AT: expires,
    SILO_INTEGRATION_AUTH_EMAIL: "integration@example.test",
    SILO_INTEGRATION_AUTH_PASSWORD: "test-password",
    SILO_INTEGRATION_AUTH_USER_ID: "dedicated",
    SUPABASE_URL: "https://example.test",
    SUPABASE_ANON_KEY: "public-key",
  };
  const env = (name: string) => vars[name];
  let logins = 0;
  let fail = false;
  const fetchImpl = (input: string, init: RequestInit) => {
    if (input.endsWith("/auth/v1/token?grant_type=password")) {
      logins++;
      assertEquals(new Headers(init.headers).get("authorization"), null);
      return Promise.resolve(fail ? new Response(null, { status: 503 }) :
        Response.json({ access_token: "upstream-jwt", expires_in: 3600, user: { id: "dedicated" } }));
    }
    assertEquals(new Headers(init.headers).get("authorization"), "Bearer upstream-jwt");
    return Promise.resolve(Response.json([]));
  };
  const cfg = { restUrl: "https://example.test/rest/v1", anonKey: "public-key" };
  const resolve = integrationSession(env, fetchImpl, () => now);
  assertEquals(await Promise.all([resolve(key, cfg), resolve(key, cfg)]), ["upstream-jwt", "upstream-jwt"]);
  assertEquals(logins, 1);
  await assertRejects(() => resolve("silo_int_" + "cd".repeat(32), cfg), ApiError, "invalid");
  delete vars.SILO_INTEGRATION_KEY_SHA256;
  await assertRejects(() => resolve(key, cfg), ApiError, "revoked");
  vars.SILO_INTEGRATION_KEY_SHA256 = expected;
  now = Date.parse(expires);
  await assertRejects(() => resolve(key, cfg), ApiError, "expired");
  now -= 1000;
  fail = true;
  await assertRejects(() => resolve(key, cfg), ApiError, "unavailable");
  fail = false;
  const request = () => new Request("https://example.test/v2/search?q=PETR4", {
    headers: { Authorization: `Bearer ${key}` },
  });
  const handler = makeHandler({
    env,
    fetchImpl,
    now: () => now,
    gate: { tier: ({ bearer }) => Promise.resolve(bearer === "upstream-jwt" ? "pro" : "anonymous"),
            hit: () => Promise.resolve(1) },
  });
  assertEquals((await (await handler(request())).json()).meta.tier, "pro");
  const denied = makeHandler({
    env,
    fetchImpl,
    now: () => now,
    gate: { tier: () => Promise.resolve("signed_in"), hit: () => Promise.reject("unexpected data request") },
  });
  assertEquals((await denied(request())).status, 403);
});
