import { ApiError } from "./errors.ts";
import type { BridgeConfig, FetchLike } from "./postgrest.ts";

type EnvGetter = (name: string) => string | undefined;
const PREFIX = "silo_int_";
const MAX_LIFETIME = 60 * 24 * 60 * 60 * 1000;

export function integrationKey(token: string | null): token is string {
  return token !== null && token.startsWith(PREFIX);
}

export function integrationSession(env: EnvGetter, fetchImpl: FetchLike, now: () => number) {
  let session: { token: string; until: number; hash: string } | undefined;
  let pending: { hash: string; result: Promise<string> } | undefined;

  return async (key: string, cfg: BridgeConfig): Promise<string> => {
    const unauthorized = new ApiError(401, "unauthorized", "Integration key is invalid, expired or revoked.", "Authorization");
    const unavailable = new ApiError(503, "unavailable", "Integration authentication is unavailable. Try again shortly.");
    const expected = env("SILO_INTEGRATION_KEY_SHA256");
    const expires = Date.parse(env("SILO_INTEGRATION_KEY_EXPIRES_AT") ?? "");
    const remaining = expires - now();
    if (!expected || !/^[0-9a-f]{64}$/.test(expected) ||
        !Number.isFinite(remaining) || remaining <= 0 || remaining > MAX_LIFETIME ||
        !/^silo_int_[0-9a-f]{64}$/.test(key)) throw unauthorized;

    const actual = new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(key)));
    let difference = 0;
    for (let i = 0; i < actual.length; i++) difference |= actual[i] ^ parseInt(expected.slice(i * 2, i * 2 + 2), 16);
    if (difference !== 0) throw unauthorized;

    const email = env("SILO_INTEGRATION_AUTH_EMAIL");
    const password = env("SILO_INTEGRATION_AUTH_PASSWORD");
    const userId = env("SILO_INTEGRATION_AUTH_USER_ID");
    if (!email || !password || !userId) throw unavailable;
    const identity = expected + userId;
    if (session?.hash === identity && session.until > now()) return session.token;

    if (pending?.hash !== identity) {
      const result = (async () => {
        try {
          const authUrl = new URL("/auth/v1/token?grant_type=password", cfg.restUrl);
          const response = await fetchImpl(authUrl.href, {
            method: "POST",
            redirect: "error",
            headers: { apikey: cfg.anonKey, "Content-Type": "application/json" },
            body: JSON.stringify({ email, password }),
            signal: AbortSignal.timeout(10_000),
          });
          if (!response.ok) throw unavailable;
          const body = await response.json();
          if (body.user?.id !== userId || typeof body.access_token !== "string" || !body.access_token ||
              !Number.isFinite(body.expires_in) || body.expires_in <= 30) throw unavailable;
          session = { token: body.access_token, until: now() + Math.min(60, body.expires_in - 30) * 1000, hash: identity };
          return session.token;
        } catch {
          throw unavailable;
        }
      })();
      pending = { hash: identity, result };
    }
    const request = pending;
    try {
      const token = await request.result;
      if (now() >= expires || env("SILO_INTEGRATION_KEY_SHA256") !== expected) throw unauthorized;
      return token;
    } finally {
      if (pending === request) pending = undefined;
    }
  };
}
