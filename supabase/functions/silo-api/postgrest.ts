// silo-api: the bridge to PostgREST on schema `api`. One request per call.
//
// The same rules as silo-mcp (supabase/functions/silo-mcp/tools.ts):
//   * read-only: POST /rpc/<fn> on schema `api`, or GET /<view> on schema
//     `api` for a registry plan marked view (callView), nothing else;
//   * one v2 call = one PostgREST request, never retried; a paged kind makes
//     at most MAX_UPSTREAM_CALLS (config.ts), each a new window or page, never
//     the same request again (paging.ts, #1059);
//   * the only key is the public anon / publishable key, never a secret one;
//   * an error comes back verbatim (errors.ts maps it to a v2 code).
// One difference: a caller's own `Authorization: Bearer <JWT>` is forwarded,
// so a signed-in caller keeps the signed-in tier. The apikey header is always
// the gateway's publishable key; a caller's apikey header is never forwarded.

import type { Tier } from "./config.ts";
import { ApiError, fromPostgrest } from "./errors.ts";

export interface BridgeConfig {
  /** e.g. https://<ref>.supabase.co/rest/v1, no trailing slash. */
  restUrl: string;
  /** The public anon / publishable key. Never a secret key. */
  anonKey: string;
}

type EnvGetter = (name: string) => string | undefined;

/**
 * SUPABASE_URL and SUPABASE_ANON_KEY are provided by the Edge Runtime. When a
 * project has moved to the new API keys, SUPABASE_PUBLISHABLE_KEYS (a JSON
 * dictionary) carries the publishable key instead; its `default` entry (or
 * the only entry) is used. A secret / service_role key is never read.
 */
export function configFromEnv(get: EnvGetter): BridgeConfig | { error: string } {
  const base = (get("SUPABASE_URL") ?? "").trim().replace(/\/+$/, "");
  if (!base) return { error: "SUPABASE_URL is not set in the function environment." };
  let key = (get("SUPABASE_ANON_KEY") ?? "").trim();
  if (!key) {
    const raw = get("SUPABASE_PUBLISHABLE_KEYS");
    if (raw) {
      try {
        const dict = JSON.parse(raw) as Record<string, string>;
        key = (dict["default"] ?? Object.values(dict)[0] ?? "").trim();
      } catch {
        return { error: "SUPABASE_PUBLISHABLE_KEYS is not valid JSON." };
      }
    }
  }
  if (!key) return { error: "Neither SUPABASE_ANON_KEY nor SUPABASE_PUBLISHABLE_KEYS is set in the function environment." };
  if (key.startsWith("sb_secret_")) return { error: "Refusing to call the API with a secret key; only the public key is allowed." };
  return { restUrl: `${base}/rest/v1`, anonKey: key };
}

/**
 * The caller's token to forward, or null for the anonymous tier. A publishable
 * key (or the gateway's own key) sent as a Bearer is not a sign-in, so it is
 * not forwarded. A secret key is refused outright: it must never travel.
 */
export function callerBearer(header: string | null, cfg: BridgeConfig): string | null {
  if (header === null || header.trim() === "") return null;
  const m = /^Bearer\s+(\S+)\s*$/i.exec(header);
  if (!m) throw new ApiError(401, "unauthorized", "Authorization must be `Bearer <token>`.", "Authorization");
  const token = m[1];
  if (token.startsWith("sb_secret_")) {
    throw new ApiError(401, "unauthorized", "A secret key was sent. Never send a secret key to a public API; rotate it.", "Authorization");
  }
  if (token.startsWith("sb_publishable_") || token === cfg.anonKey) return null;
  return token;
}

export type FetchLike = (input: string, init: RequestInit) => Promise<Response>;

export interface CallContext {
  cfg: BridgeConfig;
  fetchImpl: FetchLike;
  bearer: string | null;
  /**
   * The caller's tier: api.my_tier() for a bearer, anonymous without one
   * (#1064, tier.ts). PostgREST verifies the token on every call (an invalid
   * one is refused as unauthorized); the gateway does not decode it.
   */
  tier?: Tier;
}

/** POST /rpc/<endpoint> on schema api. Returns the parsed JSON, or throws ApiError. */
export async function callRpc(ctx: CallContext, endpoint: string, args: Record<string, unknown>): Promise<unknown> {
  const headers: Record<string, string> = {
    apikey: ctx.cfg.anonKey,
    Accept: "application/json",
    "Accept-Profile": "api",
    "Content-Profile": "api",
    "Content-Type": "application/json",
  };
  if (ctx.bearer) headers["Authorization"] = `Bearer ${ctx.bearer}`;
  const path = `/rpc/${endpoint}`;

  let res: Response;
  try {
    res = await ctx.fetchImpl(`${ctx.cfg.restUrl}${path}`, { method: "POST", headers, body: JSON.stringify(args) });
  } catch (e) {
    throw new ApiError(
      503,
      "unavailable",
      `Network error calling api.${endpoint}: ${e instanceof Error ? e.message : String(e)}. No data was returned.`,
    );
  }
  const text = await res.text();
  if (!res.ok) throw fromPostgrest(res.status, text, `api.${endpoint}`);
  try {
    return text === "" ? null : JSON.parse(text);
  } catch {
    throw new ApiError(500, "internal", `api.${endpoint} answered HTTP ${res.status} with a body that is not JSON.`);
  }
}

// -- GET on a view (funds and fidc with no id: #1056) -----------------------

export interface ViewPage {
  rows: Record<string, unknown>[];
  /** Every row the selection holds, from Content-Range (Prefer: count=exact); null if not sent. */
  total: number | null;
}

/**
 * GET /<view> on schema api: eq. filters, an order, a page size and an
 * offset, with `Prefer: count=exact` so the rows left are known. PostgREST
 * cuts a view at db-max-rows and cannot refuse; the gateway pages it with
 * order + limit + offset and says through next_page_url that rows remain
 * (run.ts, #1059).
 */
export async function callView(
  ctx: CallContext,
  view: string,
  eq: Record<string, unknown>,
  order: string | undefined,
  limit: number,
  /** Other PostgREST filters, operator included: column -> e.g. "gte.2026-10-20" (prices kind=session, #1055). */
  filters: Record<string, string> = {},
  /** Rows of the ordered selection to skip (the view cursor, #1059). */
  offset = 0,
): Promise<ViewPage> {
  const qs = new URLSearchParams({ select: "*" });
  for (const [col, v] of Object.entries(eq)) qs.set(col, `eq.${String(v)}`);
  for (const [col, f] of Object.entries(filters)) qs.set(col, f);
  if (order) qs.set("order", order);
  qs.set("limit", String(limit));
  if (offset > 0) qs.set("offset", String(offset));
  const headers: Record<string, string> = {
    apikey: ctx.cfg.anonKey,
    Accept: "application/json",
    "Accept-Profile": "api",
    Prefer: "count=exact",
  };
  if (ctx.bearer) headers["Authorization"] = `Bearer ${ctx.bearer}`;

  let res: Response;
  try {
    res = await ctx.fetchImpl(`${ctx.cfg.restUrl}/${view}?${qs.toString()}`, { method: "GET", headers });
  } catch (e) {
    throw new ApiError(
      503,
      "unavailable",
      `Network error reading api.${view}: ${e instanceof Error ? e.message : String(e)}. No data was returned.`,
    );
  }
  const text = await res.text();
  if (!res.ok) throw fromPostgrest(res.status, text, `api.${view}`);
  let rows: unknown;
  try {
    rows = text === "" ? [] : JSON.parse(text);
  } catch {
    throw new ApiError(500, "internal", `api.${view} answered HTTP ${res.status} with a body that is not JSON.`);
  }
  if (!Array.isArray(rows)) throw new ApiError(500, "internal", `api.${view} did not answer with rows.`);
  const m = /\/(\d+)\s*$/.exec(res.headers.get("content-range") ?? "");
  return { rows: rows as Record<string, unknown>[], total: m ? Number(m[1]) : null };
}
