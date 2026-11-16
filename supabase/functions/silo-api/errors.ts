// silo-api: the one error object and the PostgREST-to-v2 error mapping.
//
// Shape (docs/planning/API_V2.md, section 5):
//   { "error": { "code", "reason", "message", "target", "innererror": { "sqlstate", "hint", "details" } } }
// A PostgREST 22023 (SILO refused rather than trimmed) maps to over_limit and
// keeps its message, details and hint VERBATIM: a SILO refusal is information.
// An unknown id (DETAIL reason=unknown_...) maps to unknown_id instead.

/** The top-level codes. Ten, and only ten. */
export const ERROR_CODES = [
  "bad_request",
  "unknown_parameter",
  "unknown_id",
  "unauthorized",
  "forbidden_for_tier",
  "over_limit",
  "rate_limited",
  "timeout",
  "unavailable",
  "internal",
] as const;

export type ErrorCode = typeof ERROR_CODES[number];

/**
 * The stable reasons of over_limit, so an agent branches on a code and not on
 * the message text: row_cap (the answer is over one 1,000-row page: narrow or
 * page) and tier_cap (over the caller's tier ceiling: narrow or sign in).
 * Every other error, and an over_limit that is neither, has reason null.
 */
export const ERROR_REASONS = ["row_cap", "tier_cap"] as const;

export type ErrorReason = typeof ERROR_REASONS[number];

export interface InnerError {
  sqlstate: string | null;
  hint: string | null;
  details?: string | null;
}

export interface ErrorBody {
  error: {
    code: ErrorCode;
    reason: ErrorReason | null;
    message: string;
    target: string | null;
    innererror: InnerError;
  };
}

/** A v2 error with its HTTP status. Thrown inside the gateway, rendered once. */
export class ApiError extends Error {
  /** The stable reason of an over_limit; null otherwise. */
  reason: ErrorReason | null = null;

  /**
   * The refusal is a row cap (the window holds more than one page), so a
   * date-window walk may halve the window and try again (paging.ts, #1059).
   * Any other refusal (an unknown id, a bad tenor) is returned at once.
   */
  get rowCap(): boolean {
    return this.reason === "row_cap";
  }

  /** Response headers this error adds, e.g. Retry-After on rate_limited (#1064). */
  headers: Record<string, string> = {};

  constructor(
    public status: number,
    public code: ErrorCode,
    message: string,
    public target: string | null = null,
    public inner: InnerError = { sqlstate: null, hint: null },
  ) {
    super(message);
  }

  body(): ErrorBody {
    return { error: { code: this.code, reason: this.reason, message: this.message, target: this.target, innererror: this.inner } };
  }
}

interface PostgrestErrorJson {
  code?: unknown;
  message?: unknown;
  details?: unknown;
  hint?: unknown;
}

function str(v: unknown): string | null {
  return v === undefined || v === null ? null : String(v);
}

/**
 * The reason of a SQL 22023 refusal, read from phrases the SQL's own messages
 * fix: api.assert_row_cap's "more than 1000 rows" (load-bearing, the SDK's
 * SiloOverCap matches it too), and the tier ceilings of search_funds and panel.
 */
function overLimitReason(message: string): ErrorReason | null {
  // Tier first, so a ceiling message that also says "more than N rows" never reads as the page cap.
  if (/tier ceiling|ids per call for anonymous callers|is available to signed-in callers only/.test(message)) return "tier_cap";
  if (message.includes("more than 1000 rows")) return "row_cap";
  return null;
}

/**
 * Map a non-2xx PostgREST response to a v2 error. The PostgREST message is the
 * v2 message, unchanged; its code, hint and details go in innererror.
 */
export function fromPostgrest(status: number, bodyText: string, endpoint: string): ApiError {
  let parsed: PostgrestErrorJson = {};
  try {
    const j = JSON.parse(bodyText);
    if (j && typeof j === "object" && !Array.isArray(j)) parsed = j as PostgrestErrorJson;
  } catch {
    // Not JSON: the raw text is still returned, verbatim, as the message.
  }
  const sqlstate = str(parsed.code);
  const message = str(parsed.message) ?? (bodyText || `HTTP ${status} from ${endpoint}`);
  const inner: InnerError = { sqlstate, hint: str(parsed.hint), details: str(parsed.details) };

  if (sqlstate === "22023") {
    // quote_history's DETAIL reason=unknown_ticker (#1118): the id is not one SILO holds.
    if (inner.details?.startsWith("reason=unknown_")) return new ApiError(404, "unknown_id", message, "id", inner);
    const e = new ApiError(400, "over_limit", message, null, inner);
    e.reason = overLimitReason(message);
    return e;
  }
  if (sqlstate === "57014") return new ApiError(504, "timeout", message, null, inner);
  if (sqlstate === "42501") return new ApiError(403, "forbidden_for_tier", message, null, inner);
  if (status === 401 || sqlstate === "PGRST301" || sqlstate === "PGRST302") {
    return new ApiError(401, "unauthorized", message, null, inner);
  }
  if (status === 403) return new ApiError(403, "forbidden_for_tier", message, null, inner);
  if (status === 429) return new ApiError(429, "rate_limited", message, null, inner);
  if (status === 503 || status === 502 || status === 520) return new ApiError(503, "unavailable", message, null, inner);
  // PGRST2xx: PostgREST found no function or column for the call. The gateway
  // built that call from its registry, so this is the gateway's fault.
  if (sqlstate?.startsWith("PGRST2")) return new ApiError(500, "internal", message, null, inner);
  if (status >= 400 && status < 500) return new ApiError(400, "bad_request", message, null, inner);
  return new ApiError(500, "internal", message, null, inner);
}
