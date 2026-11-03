// silo-api: the success envelope and the JSON response helpers.
//
//   { "data": [...], "meta": { "resource", "kind", "request", "id_known", "endpoint" }, "next_page_url"? }
//
// meta.request echoes every parameter the resource takes, with the default
// that was applied, so a request can be pasted into a methods section and
// replayed. next_page_url is present only when more rows remain; it carries
// one opaque cursor, set by resources/run.ts (#1059). Rows are passed
// through as PostgREST returned them: nothing filled, null stays null.

import type { ApiError } from "./errors.ts";
import type { Value } from "./params.ts";

export interface Meta {
  resource: string;
  kind: string | null;
  request: Record<string, Value>;
  /** Whether the id is one SILO holds; null when the call names no id. */
  id_known: boolean | null;
  /** The api.* endpoint that answered (provenance). */
  endpoint?: string;
  [key: string]: unknown;
}

export interface Envelope {
  data: unknown[];
  meta: Meta;
  next_page_url?: string;
}

export function envelope(data: unknown[], meta: Meta, nextPageUrl?: string): Envelope {
  const out: Envelope = { data, meta };
  if (nextPageUrl) out.next_page_url = nextPageUrl;
  return out;
}

export const CORS: Record<string, string> = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS", // POST: portfolio only (#1058)
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type, accept",
};

export function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...CORS, "Content-Type": "application/json; charset=utf-8" },
  });
}

export function errorResponse(e: ApiError): Response {
  return json(e.status, e.body());
}
