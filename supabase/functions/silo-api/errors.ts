// silo-api: the one error object and the PostgREST-to-v2 error mapping.
//
// Shape (docs/planning/API_V2.md, section 5):
//   { "error": { "code", "message", "target", "innererror": { "sqlstate", "hint", "details" } } }
// A PostgREST 22023 (SILO refused rather than trimmed) maps to over_limit and
// keeps its message, details and hint VERBATIM: a SILO refusal is information.

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

export interface InnerError {
  sqlstate: string | null;
  hint: string | null;
  details?: string | null;
}

export interface ErrorBody {
  error: {
    code: ErrorCode;
    message: string;
    target: string | null;
    innererror: InnerError;
  };
}

/** A v2 error with its HTTP status. Thrown inside the gateway, rendered once. */
export class ApiError extends Error {
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
    return { error: { code: this.code, message: this.message, target: this.target, innererror: this.inner } };
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

  if (sqlstate === "22023") return new ApiError(400, "over_limit", message, null, inner);
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
