// silo-api: the resource registry. One entry per v2 resource.
//
// This is a declaration, not behaviour: which resources exist, which
// parameters each takes and the default of every one, which `api.*` endpoint
// each kind calls, and how a v2 name maps to a `p_` argument or to a selection
// the gateway applies to the rows the endpoint returned.
//
// The object between the BEGIN and END markers is STRICT JSON (double quotes,
// no trailing commas, no comments), because tests/test_api_v2_registry.py
// parses it offline and checks the rules of docs/planning/API_V2.md against
// it: at most 3 main parameters per resource with `kind` counted, a default on
// every parameter, every endpoint present and granted in serve/endpoint_manifest.py,
// every `p_` argument one the SQL declares. Edit the JSON, keep it JSON.

export type Visibility = "main" | "hidden";
export type ParamType = "string" | "enum" | "date" | "list" | "integer";

export interface ParamSpec {
  name: string;
  visibility: Visibility;
  type: ParamType;
  /** The value applied when the caller sends none. null = "none" (see default_doc). */
  default: string | number | null;
  /** What the default means, in words. Required when default is null or "". */
  default_doc?: string;
  doc: string;
  /** enum only: the accepted values. */
  values?: string[];
  /** A value sent to the endpoint as SQL NULL (no narrowing), e.g. family=all. */
  null_value?: string;
}

export interface FilterSpec {
  /** The v2 parameter the selection reads. */
  parameter: string;
  /** in: row[column] is one of the values. between: row[low] <= value <= row[high]. */
  op: "in" | "between";
  column?: string;
  low?: string;
  high?: string;
  /** The parameter value that means "no selection". */
  all?: string;
}

export interface Plan {
  /** The api.* function this plan calls (one POST /rpc/<endpoint>). */
  endpoint: string;
  /** v2 parameter name -> the endpoint's `p_` argument. */
  args: Record<string, string>;
  /** Selections applied by the gateway to the returned rows, never a fill. */
  filters?: FilterSpec[];
  /** A fixed selection of the kind itself: row[column] === value. */
  where?: Record<string, string>;
  /** Source column -> v2 column, e.g. coverage's as_of -> data_through. */
  rename?: Record<string, string>;
  /** The endpoint returns one JSON value (not rows); data is [value]. */
  single?: boolean;
}

export interface KindSpec extends Plan {
  doc: string;
  /** When `parameter` is empty, this plan runs instead (with no id, list what is held). */
  when_empty?: { parameter: string; plan: Plan };
}

export interface ResourceSpec {
  name: string;
  status: "built" | "planned";
  summary: string;
  example: string;
  /** Which of the shared parameters this resource takes. */
  shared?: string[];
  parameters?: ParamSpec[];
  kinds?: Record<string, KindSpec>;
}

export interface SharedSpec {
  default: string | number | null;
  default_doc: string;
  doc: string;
}

export interface Registry {
  version: string;
  shared_parameters: Record<string, SharedSpec>;
  resources: ResourceSpec[];
}

// BEGIN REGISTRY
export const REGISTRY: Registry = {
  "version": "v2",
  "shared_parameters": {
    "id": {
      "default": null,
      "default_doc": "none: the resource lists the ids it holds",
      "doc": "The thing you want: a ticker, a 14-digit CNPJ, a CVM code or a series code. The gateway detects which."
    },
    "from": {
      "default": null,
      "default_doc": "the resource's default window, counted back from to",
      "doc": "First date of the window, YYYY-MM-DD."
    },
    "to": {
      "default": null,
      "default_doc": "the latest complete period, from coverage",
      "doc": "Last date of the window, YYYY-MM-DD."
    },
    "limit": {
      "default": null,
      "default_doc": "none: the endpoint's own ceiling applies, and the endpoint refuses above it rather than trim (page size and cursors arrive in #1052 child 6/8)",
      "doc": "Rows wanted. Passed through to the endpoint where it takes one."
    },
    "cursor": {
      "default": null,
      "default_doc": "none: the first page",
      "doc": "The opaque cursor from a previous next_page_url. No resource takes one yet."
    }
  },
  "resources": [
    {
      "name": "search",
      "status": "built",
      "summary": "What is this name or id? Companies, funds and listed shares, with their stable ids (CNPJ, ISIN).",
      "example": "/v2/search?q=petrobras",
      "shared": ["limit"],
      "parameters": [
        {
          "name": "q",
          "visibility": "main",
          "type": "string",
          "default": "",
          "default_doc": "empty: list the research universe (kind any or company) or every fund (kind fund, which refuses above its tier ceiling)",
          "doc": "A ticker, ISIN, CNPJ, CVM code, or words of a company or fund name (every word must match, accents and case ignored)."
        },
        {
          "name": "kind",
          "visibility": "main",
          "type": "enum",
          "values": ["any", "company", "fund", "universe"],
          "default": "any",
          "doc": "any: exact ids, then companies, then funds (at most 20 rows). company: the company rows of that answer. fund: fund search, largest latest NAV first. universe: every listed share and unit since 2019-01-02."
        },
        {
          "name": "family",
          "visibility": "main",
          "type": "enum",
          "values": ["all", "fi", "fidc", "fii", "fip", "fiagro"],
          "default": "all",
          "null_value": "all",
          "doc": "Narrows kind=fund to one fund family."
        },
        {
          "name": "as_of",
          "visibility": "hidden",
          "type": "date",
          "default": null,
          "default_doc": "none: every pair the tape has seen",
          "doc": "kind=universe (or an empty q): only the ticker+ISIN pairs whose first_observed <= as_of <= last_observed, dead names included. Survivorship-free."
        }
      ],
      "kinds": {
        "any": {
          "doc": "Resolve a name or id across companies, funds and tickers.",
          "endpoint": "lookup",
          "args": { "q": "p_query" },
          "when_empty": {
            "parameter": "q",
            "plan": {
              "endpoint": "research_universe",
              "args": {},
              "filters": [{ "parameter": "as_of", "op": "between", "low": "first_observed", "high": "last_observed" }]
            }
          }
        },
        "company": {
          "doc": "The company rows (id_type cd_cvm) of the lookup answer; truncated still says when more than 20 entries matched.",
          "endpoint": "lookup",
          "args": { "q": "p_query" },
          "where": { "id_type": "cd_cvm" },
          "when_empty": {
            "parameter": "q",
            "plan": {
              "endpoint": "research_universe",
              "args": {},
              "filters": [{ "parameter": "as_of", "op": "between", "low": "first_observed", "high": "last_observed" }]
            }
          }
        },
        "fund": {
          "doc": "Fund name or CNPJ search, largest latest NAV first. Refuses (over_limit) when more match than the tier ceiling: narrow q, or ask for the first N with limit.",
          "endpoint": "search_funds",
          "args": { "q": "p_query", "family": "p_entity_type", "limit": "p_limit" }
        },
        "universe": {
          "doc": "The research universe: one row per ticker+ISIN pair of listed shares and units.",
          "endpoint": "research_universe",
          "args": {},
          "filters": [{ "parameter": "as_of", "op": "between", "low": "first_observed", "high": "last_observed" }]
        }
      }
    },
    {
      "name": "prices",
      "status": "planned",
      "summary": "What did it trade at? Daily history (split-adjusted by default), latest quote, sessions, indices, B3 FORWARD prints.",
      "example": "/v2/prices?id=PETR4"
    },
    {
      "name": "statements",
      "status": "planned",
      "summary": "What did the company file? Income, balance sheet, cash flow, headline figures and every stored version.",
      "example": "/v2/statements?id=PETR4&kind=income"
    },
    {
      "name": "funds",
      "status": "planned",
      "summary": "What is this fund and how is it doing? Profile, NAV, holdings, debentures, FII properties.",
      "example": "/v2/funds?id=33000167000101&kind=nav"
    },
    {
      "name": "fidc",
      "status": "planned",
      "summary": "What is inside this FIDC? Portfolio, tranches, aging, cedentes, sacados.",
      "example": "/v2/fidc?id=<cnpj>&kind=tranches"
    },
    {
      "name": "derivatives",
      "status": "planned",
      "summary": "Options, termo and futures: chains, histories, exercises, the DI1 settlement.",
      "example": "/v2/derivatives?id=PETR&kind=chain"
    },
    {
      "name": "curves",
      "status": "planned",
      "summary": "What does the rate curve look like? B3 reference curves, their history and vertices.",
      "example": "/v2/curves?curve=PRE"
    },
    {
      "name": "macro",
      "status": "planned",
      "summary": "Macro series, inflation and its item tree, PTAX, Focus expectations.",
      "example": "/v2/macro?kind=inflation"
    },
    {
      "name": "positioning",
      "status": "planned",
      "summary": "Who is short, lending or flowing in? Short interest, lending trades and brokers, investor flow.",
      "example": "/v2/positioning?id=PETR4"
    },
    {
      "name": "events",
      "status": "planned",
      "summary": "What was filed or restated? Company IPE filings, fund documents, restatements, judicial recovery.",
      "example": "/v2/events?id=PETR4"
    },
    {
      "name": "screens",
      "status": "planned",
      "summary": "Which funds look odd? Forensic screens: signals, not verdicts.",
      "example": "/v2/screens"
    },
    {
      "name": "panel",
      "status": "planned",
      "summary": "A clean (id, date, metric, value) table across families.",
      "example": "/v2/panel?id=PETR4&metric=close"
    },
    {
      "name": "portfolio",
      "status": "planned",
      "summary": "Diagnose a portfolio: resolve statement lines, fees, look-through, movement (POST).",
      "example": "POST /v2/portfolio?kind=resolve"
    },
    {
      "name": "coverage",
      "status": "built",
      "summary": "How fresh is each dataset, which metrics each family files, and the whole read contract.",
      "example": "/v2/coverage",
      "shared": [],
      "parameters": [
        {
          "name": "kind",
          "visibility": "main",
          "type": "enum",
          "values": ["freshness", "metrics", "catalog"],
          "default": "freshness",
          "doc": "freshness: per dataset, data_through (newest elapsed period), complete_through, landed_at, landed_git_sha. metrics: filed span per (family, metric). catalog: the read contract as one JSON object."
        },
        {
          "name": "dataset",
          "visibility": "main",
          "type": "list",
          "default": "all",
          "doc": "Comma-separated. kind=freshness: dataset names (funds_fidc, quotes, ...). kind=metrics: fund families (fi, fidc, ...). A name no row carries is refused, with the known names."
        }
      ],
      "kinds": {
        "freshness": {
          "doc": "api.coverage(); the source's as_of is returned as data_through (in v2, as_of means point in time).",
          "endpoint": "coverage",
          "args": {},
          "filters": [{ "parameter": "dataset", "op": "in", "column": "dataset", "all": "all" }],
          "rename": { "as_of": "data_through" }
        },
        "metrics": {
          "doc": "api.metric_coverage(): a (family, metric) pair absent here is one the family never files, not late data.",
          "endpoint": "metric_coverage",
          "args": {},
          "filters": [{ "parameter": "dataset", "op": "in", "column": "entity_type", "all": "all" }]
        },
        "catalog": {
          "doc": "api.catalog(): metrics, constraints, limits, applicability, regime breaks, screens. Cache it.",
          "endpoint": "catalog",
          "args": {},
          "single": true
        }
      }
    }
  ]
};
// END REGISTRY

export const SHARED_NAMES: string[] = Object.keys(REGISTRY.shared_parameters);

export const RESOURCES_BY_NAME: Map<string, ResourceSpec> = new Map(
  REGISTRY.resources.map((r) => [r.name, r]),
);
