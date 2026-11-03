// silo-api: one opaque cursor on every list kind (#1059).
//
// The cursor is base64url of a JSON state: the resource, every original
// query parameter as sent, a digest of a POST body, the paging method, the
// position, and the rows served so far. It is NOT signed. So the gateway
// never trusts it: the parameters it carries are parsed again exactly like a
// fresh request (parseQuery, then every check), the position is validated by
// the method that reads it, and the page size and the rows-per-call cap come
// from the CURRENT caller's tier, never from the cursor. An edited cursor can
// at most restart the walk at a position a fresh request could reach.
//
// The walkers here are pure over a fetch callback: run.ts gives them the one
// call to make, and they decide the window, the key and the slice.

import { ApiError } from "./errors.ts";
import { MAX_UPSTREAM_CALLS, SQL_PAGE } from "./config.ts";

export type Row = Record<string, unknown>;

export type Method = "p_after" | "date_window" | "view_offset" | "single_page";

export interface CursorState {
  v: 1;
  /** The resource the cursor was issued for. */
  r: string;
  /** Every original query parameter, as the caller sent it (cursor excluded). */
  q: Record<string, string>;
  /** POST only: a digest of the body, which the caller sends again unchanged. */
  b?: string;
  /** The paging method that wrote `p`. */
  m: Method;
  /** The position, read by that method. */
  p: Record<string, unknown>;
  /** Rows served by the pages before this one. */
  n: number;
}

function badCursor(why: string): ApiError {
  return new ApiError(400, "bad_request", `The cursor is not valid: ${why}. Start again without cursor.`, "cursor");
}

function b64urlEncode(text: string): string {
  const bytes = new TextEncoder().encode(text);
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function b64urlDecode(token: string): string {
  const b64 = token.replace(/-/g, "+").replace(/_/g, "/");
  const bin = atob(b64 + "=".repeat((4 - (b64.length % 4)) % 4));
  return new TextDecoder().decode(Uint8Array.from(bin, (c) => c.charCodeAt(0)));
}

export function encodeCursor(state: CursorState): string {
  return b64urlEncode(JSON.stringify(state));
}

const METHODS: Method[] = ["p_after", "date_window", "view_offset", "single_page"];

/** Decode and check the shape. The values inside are checked again where they are used. */
export function decodeCursor(token: string, resource: string): CursorState {
  if (!/^[A-Za-z0-9_-]+$/.test(token)) throw badCursor("it is not base64url");
  let s: unknown;
  try {
    s = JSON.parse(b64urlDecode(token));
  } catch {
    throw badCursor("it does not decode to JSON");
  }
  if (!s || typeof s !== "object" || Array.isArray(s)) throw badCursor("it is not an object");
  const c = s as Record<string, unknown>;
  if (c.v !== 1) throw badCursor("unknown version");
  if (c.r !== resource) throw badCursor(`it was issued for /v2/${String(c.r)}, not /v2/${resource}`);
  if (!c.q || typeof c.q !== "object" || Array.isArray(c.q) || Object.values(c.q).some((v) => typeof v !== "string")) {
    throw badCursor("its parameters are not a map of strings");
  }
  if ("cursor" in (c.q as object)) throw badCursor("it nests a cursor");
  if (c.b !== undefined && typeof c.b !== "string") throw badCursor("its body digest is not a string");
  if (!METHODS.includes(c.m as Method)) throw badCursor("unknown paging method");
  if (!c.p || typeof c.p !== "object" || Array.isArray(c.p)) throw badCursor("its position is not an object");
  if (!Number.isInteger(c.n) || (c.n as number) < 0) throw badCursor("its row count is not a whole number");
  return c as unknown as CursorState;
}

/**
 * The query to parse for a request that sends a cursor: the cursor's own
 * parameters. Any other parameter in the URL must repeat the cursor's value
 * exactly; a new or a different one is bad_request, because the cursor fixes
 * every parameter of the walk.
 */
export function cursorQuery(url: URLSearchParams, state: CursorState): URLSearchParams {
  for (const [k, v] of url.entries()) {
    if (k === "cursor") continue;
    if (state.q[k] !== v) {
      const was = k in state.q ? `\`${state.q[k]}\`` : "not sent";
      throw new ApiError(
        400,
        "bad_request",
        `${k}=${v} differs from the cursor's walk (${k} was ${was}). A cursor fixes every parameter: send cursor alone, or start a new walk without it.`,
        k,
      );
    }
  }
  return new URLSearchParams(state.q);
}

/** FNV-1a over the body text, twice with two seeds: a digest, not a signature. */
export function bodyDigest(text: string): string {
  let a = 0x811c9dc5, b = 0x01000193 ^ 0x5bd1e995;
  for (let i = 0; i < text.length; i++) {
    const c = text.charCodeAt(i);
    a = Math.imul(a ^ c, 0x01000193) >>> 0;
    b = Math.imul(b ^ c, 0x01000193) >>> 0;
  }
  return a.toString(16).padStart(8, "0") + b.toString(16).padStart(8, "0") + text.length.toString(16);
}

// -- positions ----------------------------------------------------------------

function int(p: Record<string, unknown>, k: string, min = 0): number {
  const v = p[k] ?? 0;
  if (!Number.isInteger(v) || (v as number) < min) throw badCursor(`${k} is not a whole number >= ${min}`);
  return v as number;
}

const DATE = /^\d{4}-\d{2}-\d{2}$/;
function realDate(s: string): boolean {
  if (!DATE.test(s)) return false;
  const d = new Date(`${s}T00:00:00Z`);
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === s;
}

function dateOrNull(p: Record<string, unknown>, k: string): string | null {
  const v = p[k] ?? null;
  if (v === null) return null;
  if (typeof v !== "string" || !realDate(v)) throw badCursor(`${k} is not a date`);
  return v;
}

/** single_page and view_offset: an offset, and for a view a pinned session date. */
export function offsetPos(p: Record<string, unknown> | null): { off: number; pin: string | null } {
  if (!p) return { off: 0, pin: null };
  return { off: int(p, "off"), pin: dateOrNull(p, "pin") };
}

export function afterPos(p: Record<string, unknown> | null): string {
  if (!p) return "";
  const a = p.after;
  if (typeof a !== "string" || a.length > 512 || a === "") throw badCursor("after is not a key");
  return a;
}

export interface WindowPos {
  /** The range not yet served: [a, b]. null = as the request gave it (from or to not sent). */
  a: string | null;
  b: string | null;
  /** Days per window; null = the whole range in one call. */
  span: number | null;
  /** Rows of the current window already served. */
  off: number;
}

/**
 * A date-window position, kept inside the request's own from..to: a cursor
 * can move the walk forward, never outside the window the request asked for.
 */
export function windowPos(p: Record<string, unknown> | null, from: string | null, to: string | null): WindowPos {
  if (!p) return { a: from, b: to, span: null, off: 0 };
  const a = dateOrNull(p, "a");
  const b = dateOrNull(p, "b");
  const span = p.span === null || p.span === undefined ? null : int(p, "span", 1);
  if (from !== null && (a === null || a < from)) throw badCursor("its window starts before from");
  if (to !== null && (b === null || b > to)) throw badCursor("its window ends after to");
  if (span !== null && (a === null || b === null)) throw badCursor("a split window needs both ends");
  return { a, b, span, off: int(p, "off") };
}

// -- dates ----------------------------------------------------------------------

export function addDays(iso: string, n: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

function daysBetween(a: string, b: string): number {
  return Math.round((Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / 86_400_000);
}

// -- walkers ----------------------------------------------------------------------

export interface Walked<P> {
  rows: Row[];
  /** Rows remain after this page (or may: an empty window ahead is not known until read). */
  more: boolean;
  pos: P;
}

/**
 * single_page: one call holds the whole answer; this page is rows[off, off+need).
 */
export function slicePage(rows: Row[], off: number, need: number): Walked<{ off: number }> {
  const page = rows.slice(off, off + need);
  return { rows: page, more: off + page.length < rows.length, pos: { off: off + page.length } };
}

/**
 * p_after: the function's own cursor. Each call returns up to SQL_PAGE rows
 * after the key; a shorter page is the last. The rows are selected (the
 * declared selections), then served up to `need`; the next key is the last
 * served row's, or the last row read when the selection kept none of the
 * rest. With freq=month (`holdBackMonth`), a full page's last month may be
 * incomplete, so its rows are read again on the next call rather than
 * selected now: a month-end is never picked from half a month.
 */
export async function walkAfter(o: {
  after: string;
  need: number;
  fetch: (after: string) => Promise<Row[]>;
  select: (rows: Row[]) => Row[];
  key: (row: Row) => string;
  holdBackMonth?: string | null;
  budget?: number;
}): Promise<Walked<{ after: string }>> {
  const out: Row[] = [];
  let after = o.after;
  for (let calls = 0; calls < (o.budget ?? MAX_UPSTREAM_CALLS); calls++) {
    const raw = await o.fetch(after);
    const full = raw.length >= SQL_PAGE;
    let usable = raw;
    if (full && o.holdBackMonth) {
      const col = o.holdBackMonth;
      const month = String(raw[raw.length - 1][col] ?? "").slice(0, 7);
      usable = raw.filter((r) => String(r[col] ?? "").slice(0, 7) !== month);
      if (usable.length === 0) {
        throw new ApiError(500, "internal", `One month holds ${raw.length} rows; freq=month cannot select its last session from one page.`);
      }
    }
    const sel = o.select(usable);
    const take = sel.slice(0, o.need - out.length);
    out.push(...take);
    if (take.length < sel.length) return { rows: out, more: true, pos: { after: o.key(take[take.length - 1]) } };
    if (!full) return { rows: out, more: false, pos: { after } };
    after = o.key(usable[usable.length - 1]);
    if (out.length >= o.need) return { rows: out, more: true, pos: { after } };
  }
  return { rows: out, more: true, pos: { after } };
}

/**
 * date_window: split from..to into windows that fit one call. The first call
 * is the whole range as asked. A window the SQL refuses for its row cap is
 * halved and tried again; a single day that is still refused is over_limit
 * with the SQL's message, verbatim. A position inside a window is an offset
 * into its rows (the function's order is fixed, so the same call gives the
 * same rows). Windows go in the function's own order: asc from `from`, desc
 * from `to`. When a split needs an end the request left open, `to` is today
 * (UTC-3); a missing `from` cannot be split, and the refusal stands.
 */
export async function walkWindows(o: {
  pos: WindowPos;
  order: "asc" | "desc";
  need: number;
  today: string;
  fetch: (lo: string | null, hi: string | null) => Promise<Row[]>;
  budget?: number;
}): Promise<Walked<WindowPos>> {
  const out: Row[] = [];
  let { a, b, span, off } = o.pos;
  for (let calls = 0; calls < (o.budget ?? MAX_UPSTREAM_CALLS); calls++) {
    let lo = a, hi = b;
    if (span !== null) {
      if (o.order === "asc") {
        const end = addDays(a!, span - 1);
        hi = end < b! ? end : b;
      } else {
        const start = addDays(b!, -(span - 1));
        lo = start > a! ? start : a;
      }
    }
    let rows: Row[];
    try {
      rows = await o.fetch(lo, hi);
    } catch (e) {
      if (!(e instanceof ApiError && e.rowCap)) throw e;
      if (off > 0) {
        throw new ApiError(
          400,
          "bad_request",
          "A window this walk already served part of now holds more than one page (new data landed between pages). Start again without cursor.",
          "cursor",
        );
      }
      if (a === null) throw e; // no from: nothing to split
      if (b === null) b = o.today;
      if (hi === null) hi = b;
      const days = daysBetween(lo ?? a, hi) + 1;
      if (days <= 1) throw e; // one day still over one page: refused, verbatim
      span = Math.ceil(days / 2);
      continue;
    }
    const take = rows.slice(off, off + (o.need - out.length));
    out.push(...take);
    if (off + take.length < rows.length) {
      return { rows: out, more: true, pos: { a, b, span, off: off + take.length } };
    }
    // This window is served. Was it the last?
    if (span === null || (o.order === "asc" ? hi! >= b! : lo! <= a!)) {
      return { rows: out, more: false, pos: { a, b, span, off: 0 } };
    }
    if (o.order === "asc") a = addDays(hi!, 1);
    else b = addDays(lo!, -1);
    off = 0;
    if (rows.length < SQL_PAGE / 4) span = span * 2; // sparse: try a wider window next
    if (out.length >= o.need) return { rows: out, more: true, pos: { a, b, span, off } };
  }
  return { rows: out, more: true, pos: { a, b, span, off } };
}
