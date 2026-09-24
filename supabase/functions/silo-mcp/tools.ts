// silo-mcp: the tool registry and the one-request-per-call PostgREST bridge.
//
// No npm imports here on purpose: this module is the whole behaviour of the
// server (which tools exist, what each call sends, what each result says) and
// it is tested offline with a stubbed fetch. index.ts only wires it into the
// MCP SDK's streamable-HTTP handler.
//
// Rules this file enforces, from CLAUDE.md and docs/planning/SERVING.md:
//   * read-only: POST /rpc/<fn> and GET /<view> on schema `api`, nothing else;
//   * one tool call = exactly one PostgREST request, never retried;
//   * a PostgREST error is returned VERBATIM as an MCP tool error (isError),
//     because a SILO error is information (22023 = narrow the query);
//   * nothing is trimmed: every row PostgREST returned is in the result, with
//     the row count and a provenance line (endpoint + parameters);
//   * the only credential is the public anon / publishable key.

import { CONTRACT, CONTRACT_VERSION, type ContractEntry } from "./contract.generated.ts";

// ---------------------------------------------------------------------------
// The tool list. One line per tool; the input schema and the contract prose
// come from contract.generated.ts (openapi.json, itself generated from the
// SQL). tests/test_mcp_contract.py pins this list to serve/catalog.py's
// `postgrest` section, so adding an endpoint there without adding it here (or
// the reverse) fails CI. When catalog v33 publishes fund_documents /
// fund_restatements: regenerate openapi.json + contract.generated.ts, then add
// `t("fund_documents")` / `t("fund_restatements")` below.
// ---------------------------------------------------------------------------

export interface ToolSpec {
  name: string;
  title: string;
  /** Prepended to the contract prose: how an agent should use this tool. */
  lead?: string;
}

function t(name: string, title: string, lead?: string): ToolSpec {
  return { name, title, lead };
}

export const TOOL_SPECS: ToolSpec[] = [
  // Orientation — call these first.
  t("catalog", "Catalog (the contract)", "CALL FIRST AND CACHE. The whole read contract as JSON: metrics, constraints, limits, applicability, regime_breaks, screens, examples. When anything here disagrees with memory, the catalog wins."),
  t("coverage", "Coverage and freshness", "Call before claiming freshness or reading a null as a gap."),
  t("metric_coverage", "Metric coverage", "Call before reading a missing metric as late data."),
  t("lookup", "Lookup ids", "Resolve names to ids before any panel call; never guess a ticker or CNPJ."),
  // The primitive.
  t("panel", "Panel (id, date, metric, value)"),
  // Quotes and derivatives.
  t("quote_latest", "Latest quote"),
  t("quote_history", "Quote history"),
  t("option_chain", "Option chain"),
  t("option_history", "Option history"),
  t("option_exercises", "Option exercises"),
  t("termo_history", "Termo history"),
  // Funds.
  t("search_funds", "Search funds"),
  t("fund_profile", "Fund profile"),
  t("fund_nav", "Fund NAV series"),
  t("fund_holdings", "Fund holdings (CDA)"),
  t("fund_debentures", "Fund debentures (CDA block 6)"),
  // FIDC structure and concentration.
  t("fidc_cedentes", "FIDC cedentes"),
  t("fidc_sacados", "FIDC sacados (anonymized)"),
  t("fidc_portfolio", "FIDC portfolio ladders"),
  t("fidc_tranches", "FIDC tranches"),
  t("fidc_aging", "FIDC aging ladder"),
  // Forensic screens — signals, not verdicts.
  t("screen_zombie_growth", "Screen: zombie growth", SCREEN_LEAD()),
  t("screen_captive_vehicles", "Screen: captive vehicles", SCREEN_LEAD()),
  t("screen_evergreen_aging", "Screen: evergreen aging", SCREEN_LEAD()),
  t("screen_overdue_securit", "Screen: overdue securitizations", SCREEN_LEAD()),
  t("screen_dormant_funds", "Screen: dormant funds", SCREEN_LEAD()),
  t("screen_dormant_trend", "Screen: dormant trend", SCREEN_LEAD()),
  t("screen_delinquency_drivers", "Screen: delinquency drivers", SCREEN_LEAD()),
  // Listed companies.
  t("financials", "Financial statement lines"),
  t("company_financials", "Company headline financials"),
  t("income_statements", "Income statements"),
  // Industry and macro.
  t("anbima_classes", "ANBIMA class aggregates"),
  t("inflation", "Inflation (BACEN SGS)"),
  t("inflation_items", "IPCA item tree (IBGE SIDRA)"),
  // Views (GET, PostgREST filters). The B3 lending / flow group is a RATCHET.
  t("funds", "Fund registry (view)"),
  t("quotes", "Cash quotes (view)"),
  t("equities", "Equities (view)"),
  t("bdrs", "BDRs (view)"),
  t("units", "Units (view)"),
  t("fund_quotas", "Listed fund quotas (view)"),
  t("cash_securities", "Other cash securities (view)"),
  t("auctions", "Auction prints (view)"),
  t("short_interest", "Short interest (view)", RATCHET_LEAD()),
  t("short_interest_by_sector", "Short interest by sector (view)", RATCHET_LEAD()),
  t("lending_trades", "Lending trades (view)", RATCHET_LEAD()),
  t("lending_participants", "Lending participants (view)", RATCHET_LEAD()),
  t("investor_flow", "Investor flow (view)", RATCHET_LEAD()),
];

function SCREEN_LEAD(): string {
  return "A SIGNAL, NOT A VERDICT: rows crossed a stated threshold in public filings; each carries `screen` and `params`. Read catalog().screens.<name>.meaning for what else produces the same pattern before repeating any row.";
}

function RATCHET_LEAD(): string {
  return "RATCHET: B3 keeps ~21 business days and publishes no archive, so history starts at SILO's first capture — a short window is not a gap. Check coverage() for the real span.";
}

/** Appended to every tool description: SILO's refusal semantics, compactly. */
export const SEMANTICS =
  "Read-only; one PostgREST request per call, never retried. Errors are information and come back verbatim (isError): SQLSTATE 22023 means the request crossed a stated ceiling (the 1000-row page, the anonymous tier, a threshold range) — narrow the window, or page with p_after where the function offers it; do not retry expecting a different answer. NULL means not declared at source (or not applicable to that family): never fill, ffill or read it as zero. Freshness: coverage().as_of is the newest elapsed period, complete_through what the source has fully published — the source's filing calendar, not an outage. Every result states its row count and the exact endpoint + parameters.";

const VIEW_SEMANTICS =
  "A GET view: filter with PostgREST operators, page with order + limit/offset. The server cuts every response at 1000 rows; the result states the Content-Range and says so explicitly when the page is partial.";

export const SERVER_INSTRUCTIONS =
  `SILO — Brazilian public financial data (CVM funds and FIDC internals, listed-company filings, B3 quotes, options, securities lending and investor flow, BACEN / IBGE inflation), read-only over schema \`api\` (contract v${CONTRACT_VERSION}). ` +
  "Procedure: (1) call `catalog` once and cache it; (2) call `coverage` before claiming freshness; (3) resolve names with `lookup` / `search_funds`; (4) fetch a `panel` (id, asset_class, date, metric, value) and reduce it yourself — there is no server-side correlation, ranking or regression. " +
  "Refusal semantics: every function REFUSES (SQLSTATE 22023) rather than trims a result over 1000 rows or over the anonymous ceilings (3 panel ids, 25 search rows); the error text is returned verbatim — narrow the query or page with p_after (panel, quote_history, fund_nav). Never fabricate a price, NAV, fill or ticker↔CNPJ match; null stays null. " +
  "This server calls the API anonymously with the public key; it has no write path and no SQL passthrough.";

// ---------------------------------------------------------------------------
// Resolved tools.
// ---------------------------------------------------------------------------

export interface ToolAnnotations {
  readOnlyHint: true;
  openWorldHint: false;
  destructiveHint: false;
  idempotentHint: true;
}

export interface ResolvedTool {
  name: string;
  title: string;
  description: string;
  kind: "rpc" | "view";
  path: string;
  columns: string[];
  inputSchema: Record<string, unknown>;
  annotations: ToolAnnotations;
}

export const ANNOTATIONS: ToolAnnotations = Object.freeze({
  readOnlyHint: true,
  openWorldHint: false,
  destructiveHint: false,
  idempotentHint: true,
}) as ToolAnnotations;

function resolve(spec: ToolSpec): ResolvedTool {
  const entry: ContractEntry | undefined = CONTRACT[spec.name];
  if (!entry) {
    // Fail at load, loudly: a listed tool with no contract entry would be a
    // tool whose parameters nobody published.
    throw new Error(`silo-mcp: tool ${spec.name} is not in contract.generated.ts (regenerate from openapi.json)`);
  }
  const parts = [spec.lead, entry.description, entry.kind === "view" ? VIEW_SEMANTICS : undefined, SEMANTICS]
    .filter((s): s is string => Boolean(s && s.trim()));
  return {
    name: spec.name,
    title: spec.title,
    description: parts.join("\n\n"),
    kind: entry.kind,
    path: entry.path,
    columns: entry.columns ?? [],
    inputSchema: entry.inputSchema,
    annotations: ANNOTATIONS,
  };
}

export const TOOLS: ResolvedTool[] = TOOL_SPECS.map(resolve);
export const TOOLS_BY_NAME: Map<string, ResolvedTool> = new Map(TOOLS.map((tool) => [tool.name, tool]));

// ---------------------------------------------------------------------------
// Configuration: the REST base and the public key, from the edge runtime env.
// ---------------------------------------------------------------------------

export interface BridgeConfig {
  /** e.g. https://<ref>.supabase.co/rest/v1 — no trailing slash. */
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

// ---------------------------------------------------------------------------
// Request construction. Pure: tested without a network.
// ---------------------------------------------------------------------------

export interface PlannedRequest {
  method: "GET" | "POST";
  url: string;
  headers: Record<string, string>;
  body?: string;
  /** Human-readable endpoint for the provenance line. */
  endpoint: string;
  /** The parameters exactly as sent (RPC body, or view query). */
  params: Record<string, unknown>;
}

export class ArgumentError extends Error {}

const IDENT = /^[a-z_][a-z0-9_]*$/;
const ORDER_TERM = /^([a-z_][a-z0-9_]*)(\.(asc|desc))?(\.(nullsfirst|nullslast))?$/;
const FILTER_VALUE = /^(eq|neq|gt|gte|lt|lte|in|is)\./;

function asObject(args: unknown): Record<string, unknown> {
  if (args === undefined || args === null) return {};
  if (typeof args !== "object" || Array.isArray(args)) throw new ArgumentError("arguments must be a JSON object");
  return args as Record<string, unknown>;
}

export function planRequest(tool: ResolvedTool, rawArgs: unknown, cfg: BridgeConfig): PlannedRequest {
  const args = asObject(rawArgs);
  const baseHeaders: Record<string, string> = {
    apikey: cfg.anonKey,
    Accept: "application/json",
    "Accept-Profile": "api",
  };

  if (tool.kind === "rpc") {
    const props = Object.keys((tool.inputSchema.properties ?? {}) as Record<string, unknown>);
    const body: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(args)) {
      if (!props.includes(k)) {
        throw new ArgumentError(`${tool.name} takes no argument \`${k}\`; its arguments are: ${props.join(", ") || "(none)"}`);
      }
      if (v !== undefined) body[k] = v;
    }
    return {
      method: "POST",
      url: `${cfg.restUrl}${tool.path}`,
      headers: { ...baseHeaders, "Content-Profile": "api", "Content-Type": "application/json" },
      body: JSON.stringify(body),
      endpoint: `POST /rest/v1${tool.path}`,
      params: body,
    };
  }

  // View: GET with PostgREST's own query syntax, restricted to column filters
  // and the four control parameters. The parameters are URL-encoded one by
  // one, so a value can never become a second parameter.
  const allowed = new Set(["filters", "select", "order", "limit", "offset"]);
  for (const k of Object.keys(args)) {
    if (!allowed.has(k)) throw new ArgumentError(`${tool.name} takes filters, select, order, limit, offset — not \`${k}\``);
  }
  const query = new URLSearchParams();
  const params: Record<string, unknown> = {};
  const filters = args.filters === undefined ? {} : asObject(args.filters);
  for (const [col, expr] of Object.entries(filters)) {
    if (!tool.columns.includes(col)) {
      throw new ArgumentError(`${tool.name} has no column \`${col}\`; filterable columns: ${tool.columns.join(", ")}`);
    }
    if (typeof expr !== "string" || !FILTER_VALUE.test(expr)) {
      throw new ArgumentError(`filter on \`${col}\` must be '<op>.<value>' with op in eq, neq, gt, gte, lt, lte, in, is`);
    }
    query.append(col, expr);
    params[col] = expr;
  }
  if (args.select !== undefined) {
    const sel = String(args.select);
    for (const col of sel.split(",")) {
      if (!IDENT.test(col) || !tool.columns.includes(col)) throw new ArgumentError(`select: unknown column \`${col}\``);
    }
    query.set("select", sel);
    params.select = sel;
  }
  if (args.order !== undefined) {
    const ord = String(args.order);
    for (const term of ord.split(",")) {
      const m = ORDER_TERM.exec(term);
      if (!m || !tool.columns.includes(m[1])) throw new ArgumentError(`order: bad term \`${term}\``);
    }
    query.set("order", ord);
    params.order = ord;
  }
  for (const key of ["limit", "offset"] as const) {
    if (args[key] === undefined) continue;
    const n = args[key];
    if (typeof n !== "number" || !Number.isInteger(n) || n < 0 || (key === "limit" && (n < 1 || n > 1000))) {
      throw new ArgumentError(`${key} must be an integer${key === "limit" ? " in 1..1000" : " >= 0"}`);
    }
    query.set(key, String(n));
    params[key] = n;
  }
  const qs = query.toString();
  return {
    method: "GET",
    url: `${cfg.restUrl}${tool.path}${qs ? `?${qs}` : ""}`,
    // count=estimated: exact up to the page, planner estimate beyond it, so
    // Content-Range can say how much a cut page left out without a full
    // count(*) over the quote tape under the anonymous 3s timeout.
    headers: { ...baseHeaders, Prefer: "count=estimated" },
    endpoint: `GET /rest/v1${tool.path}${qs ? `?${decodeURIComponent(qs)}` : ""}`,
    params,
  };
}

// ---------------------------------------------------------------------------
// The call: one fetch, verbatim errors, provenance on success.
// ---------------------------------------------------------------------------

export interface TextContent {
  type: "text";
  text: string;
}

export interface ToolResult {
  content: TextContent[];
  isError?: boolean;
  [key: string]: unknown;
}

export type FetchLike = (input: string, init: RequestInit) => Promise<Response>;

function errorResult(text: string): ToolResult {
  return { content: [{ type: "text", text }], isError: true };
}

function provenance(plan: PlannedRequest): string {
  return `provenance: ${plan.endpoint} · schema api · params ${JSON.stringify(plan.params)}`;
}

function guidance(body: string): string {
  let code = "";
  try {
    code = String((JSON.parse(body) as { code?: unknown }).code ?? "");
  } catch {
    // Not JSON: nothing to classify; the body is still returned verbatim.
  }
  if (code === "22023") {
    return "SILO refused rather than trimmed (22023): the request crossed a stated ceiling. Narrow the window or ids, raise the screen threshold, or page with p_after where offered. Do not retry the same call expecting a different answer.";
  }
  if (code === "57014") {
    return "The query hit the anonymous tier's statement timeout (57014). This is not an empty answer: narrow the window or ids. The server does not retry on your behalf.";
  }
  if (code.startsWith("PGRST2")) {
    return "PostgREST could not match the call to a published function/column; check the argument names against `catalog`.";
  }
  return "Returned verbatim from PostgREST; do not substitute an answer from memory.";
}

export async function callTool(
  name: string,
  rawArgs: unknown,
  cfg: BridgeConfig | { error: string },
  fetchImpl: FetchLike = fetch,
): Promise<ToolResult> {
  const tool = TOOLS_BY_NAME.get(name);
  if (!tool) return errorResult(`Unknown tool \`${name}\`. Tools: ${TOOLS.map((x) => x.name).join(", ")}`);
  if ("error" in cfg) return errorResult(`silo-mcp is misconfigured: ${cfg.error}`);

  let plan: PlannedRequest;
  try {
    plan = planRequest(tool, rawArgs, cfg);
  } catch (e) {
    if (e instanceof ArgumentError) return errorResult(`Invalid arguments for ${name}: ${e.message}. No request was sent.`);
    throw e;
  }

  let res: Response;
  try {
    res = await fetchImpl(plan.url, { method: plan.method, headers: plan.headers, body: plan.body });
  } catch (e) {
    return errorResult(
      `Network error calling ${plan.endpoint}: ${e instanceof Error ? e.message : String(e)}. No data was returned; do not substitute any.\n${provenance(plan)}`,
    );
  }
  const text = await res.text();
  const contentRange = res.headers.get("content-range");

  if (!res.ok) {
    return errorResult(
      `PostgREST error HTTP ${res.status} from ${plan.endpoint}\n${provenance(plan)}\n${guidance(text)}\n--- verbatim response body ---\n${text}`,
    );
  }

  let data: unknown;
  try {
    data = text === "" ? null : JSON.parse(text);
  } catch {
    return errorResult(`HTTP ${res.status} from ${plan.endpoint} was not JSON; returned verbatim:\n${provenance(plan)}\n${text}`);
  }

  const rows = Array.isArray(data) ? data.length : data === null ? 0 : 1;
  const lines = [
    Array.isArray(data) ? `rows: ${rows}` : `rows: ${rows} (a single JSON value)`,
    provenance(plan),
  ];
  if (tool.kind === "view") {
    lines.push(`content-range: ${contentRange ?? "(absent)"}`);
    const total = contentRange?.split("/")[1];
    const totalN = total && total !== "*" ? Number(total) : NaN;
    const offset = typeof plan.params.offset === "number" ? plan.params.offset : 0;
    if (Number.isFinite(totalN) && offset + rows < totalN) {
      lines.push(
        `PARTIAL PAGE: rows ${offset}..${offset + rows - 1} of about ${totalN} matching rows (PostgREST caps each response at 1000). Page with order + offset, or narrow the filters; do not treat this page as the whole series.`,
      );
    } else if (rows >= 1000 && !Number.isFinite(totalN)) {
      lines.push("PAGE MAY BE CUT: 1000 rows is the server cap and no total was reported. Page with order + offset.");
    }
  }
  return { content: [{ type: "text", text: `${lines.join("\n")}\n${JSON.stringify(data)}` }] };
}
