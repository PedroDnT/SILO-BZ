// silo-api: the caller's tier and the requests-per-minute limit (#1064).
//
// Both are counted in Postgres, through PostgREST, with the caller's own token:
//   api.my_tier()          anonymous | signed_in | pro (39_api_tiers.sql)
//   api.rate_hit(p_bucket) one hit in this minute's bucket; returns the count
// The numbers are config.ts TIERS.requests_per_minute; SQL only counts.
//
// Tier: no Bearer (or the publishable key sent as one) is anonymous with no
// call. Any other token asks api.my_tier() once and the answer is cached per
// token for TIER_CACHE_MS in this isolate's memory. An invalid token is
// refused by PostgREST as unauthorized, which is passed on.
//
// Bucket: a signed-in caller's is u:<user id>, chosen by SQL from auth.uid()
// (p_bucket is not sent, and SQL ignores it anyway). An anonymous caller's is
// ip:<address>, from clientIp() below.
//
// Failure: fail closed. When the tier or the count cannot be read (network,
// timeout, a missing function) the request is refused as `unavailable` and no
// data is read. The data call would hit the same database anyway; serving it
// uncounted would make the limit silently optional.

import { HIGHER_TIER, type Tier, TIERS } from "./config.ts";
import { ApiError } from "./errors.ts";
import { callRpc, type CallContext } from "./postgrest.ts";

/** How long a token's tier is trusted without asking api.my_tier() again. */
export const TIER_CACHE_MS = 60_000;
/** Tokens kept in the cache at most; the oldest goes first. */
export const TIER_CACHE_MAX = 1000;

const TIER_NAMES: readonly Tier[] = ["anonymous", "signed_in", "pro"];

/** What the server needs from Postgres. Tests inject one; production uses postgresGate(). */
export interface Gate {
  /** The caller's tier. */
  tier(ctx: CallContext): Promise<Tier>;
  /** Count one request; the bucket's hits this minute, this one included. */
  hit(ctx: CallContext, ipBucket: string | null): Promise<number>;
}

function unavailable(what: string, e: unknown): ApiError {
  const why = e instanceof Error ? e.message : String(e);
  return new ApiError(
    503,
    "unavailable",
    `${what} could not be read (${why}). The gateway fails closed: no data was read. Try again shortly.`,
  );
}

/** Pass on what the caller can fix (an invalid token); everything else is unavailable. */
function failClosed(what: string, e: unknown): never {
  if (e instanceof ApiError && e.code === "unauthorized") throw e;
  throw unavailable(what, e);
}

export function postgresGate(now: () => number = () => Date.now()): Gate {
  const cache = new Map<string, { tier: Tier; at: number }>();
  return {
    async tier(ctx) {
      if (!ctx.bearer) return "anonymous";
      const hit = cache.get(ctx.bearer);
      if (hit && now() - hit.at < TIER_CACHE_MS) return hit.tier;
      let value: unknown;
      try {
        value = await callRpc(ctx, "my_tier", {});
      } catch (e) {
        failClosed("Your tier (api.my_tier)", e);
      }
      if (typeof value !== "string" || !TIER_NAMES.includes(value as Tier)) {
        throw new ApiError(500, "internal", `api.my_tier answered ${JSON.stringify(value)}, not one of ${TIER_NAMES.join(", ")}.`);
      }
      cache.delete(ctx.bearer);
      cache.set(ctx.bearer, { tier: value as Tier, at: now() });
      while (cache.size > TIER_CACHE_MAX) cache.delete(cache.keys().next().value as string);
      return value as Tier;
    },
    async hit(ctx, ipBucket) {
      let value: unknown;
      try {
        value = await callRpc(ctx, "rate_hit", ctx.bearer ? {} : { p_bucket: ipBucket });
      } catch (e) {
        failClosed("The request count (api.rate_hit)", e);
      }
      if (typeof value !== "number" || !Number.isInteger(value) || value < 1) {
        throw unavailable("The request count (api.rate_hit)", new Error(`it answered ${JSON.stringify(value)}`));
      }
      return value;
    },
  };
}

const IP = /^[0-9A-Fa-f:.]{2,45}$/;

/**
 * The headers clientIp() reads. A caller that builds its own Request to the
 * gateway in process (silo-mcp-v2) must copy these from its inbound request,
 * or every anonymous caller lands in the one shared bucket.
 */
export const CLIENT_IP_HEADERS = ["cf-connecting-ip", "x-forwarded-for"] as const;

/**
 * The anonymous caller's address. On hosted Supabase the request crosses
 * Cloudflare, which OVERWRITES cf-connecting-ip with the connecting socket's
 * address, so that is the one header trusted. x-forwarded-for is APPENDED to
 * (a caller's own value survives as its first hop), and x-real-ip is a
 * Supabase proxy, not the caller. So x-forwarded-for's first hop is used only
 * when cf-connecting-ip is missing (a local `supabase functions serve`), and
 * there it is spoofable: behind no proxy, every header is the caller's word.
 * No usable address puts the caller in one shared bucket, ip:0.0.0.0.
 */
export function clientIp(headers: Headers): string {
  const cf = (headers.get("cf-connecting-ip") ?? "").trim();
  if (IP.test(cf)) return cf;
  const first = (headers.get("x-forwarded-for") ?? "").split(",")[0].trim();
  if (IP.test(first)) return first;
  return "0.0.0.0";
}

/** Seconds until the next minute starts, when the count resets (1..60). */
export function retryAfter(nowMs: number): number {
  return 60 - (Math.floor(nowMs / 1000) % 60);
}

export interface RateState {
  limit: number;
  remaining: number;
}

/**
 * Count the request and refuse it above the tier's requests per minute
 * (rate_limited, HTTP 429, Retry-After). A refused request is counted too.
 */
export async function enforceRate(
  gate: Gate,
  ctx: CallContext,
  tier: Tier,
  headers: Headers,
  now: () => number = () => Date.now(),
): Promise<RateState> {
  const limit = TIERS[tier].requests_per_minute;
  const hits = await gate.hit(ctx, ctx.bearer ? null : `ip:${clientIp(headers)}`);
  if (hits > limit) {
    const wait = retryAfter(now());
    const e = new ApiError(
      429,
      "rate_limited",
      `The ${tier} tier is served ${limit} requests a minute; this is request ${hits} this minute. Retry after ${wait} s. ${HIGHER_TIER[tier]}`.trim(),
    );
    e.headers = { "Retry-After": String(wait), "RateLimit-Limit": String(limit), "RateLimit-Remaining": "0" };
    throw e;
  }
  return { limit, remaining: limit - hits };
}
