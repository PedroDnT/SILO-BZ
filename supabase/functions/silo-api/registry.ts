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
export type ParamType = "string" | "enum" | "date" | "list" | "integer" | "number";

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
  /** v2 value -> the value the endpoint takes, e.g. period quarterly -> itr. */
  sql_values?: Record<string, string>;
}

export interface FilterSpec {
  /** The v2 parameter the selection reads. */
  parameter: string;
  /** in: row[column] is one of the values. between: row[low] <= value <= row[high]. */
  op: "in" | "between" | "month_last";
  column?: string;
  low?: string;
  high?: string;
  /** The parameter value that means "no selection". */
  all?: string;
  /** in only: v2 value -> column value. The parameter is an enum, so a value no row carries is no row, not a typo. */
  map?: Record<string, string>;
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
  // -- funds, fidc, events (#1056) --
  /**
   * The endpoint is a GET view, not a function. args then map a v2 parameter
   * to a view column (an eq. filter applied by PostgREST, before its row cap),
   * `limit` maps to the page size, and `where` is sent as eq. filters too.
   */
  view?: boolean;
  /** view only: the PostgREST order, so a page is a defined sequence. */
  order?: string;
  /** Exactly one of these parameters must be given (one name = it is required). */
  require_one_of?: string[];
  // -- prices, statements (#1055) --
  /** view only: the view is chosen by this parameter's value (endpoint is the default view). */
  view_by?: { parameter: string; views: Record<string, string> };
  /** Parameters the resource module reads itself (e.g. prices' adjust and fields). */
  uses?: string[];
  // -- screens (#1058) --
  /** The SQL function's own default for a v2 parameter left null: sent, so meta.request echoes it (pinned to the SQL by a test). */
  sql_defaults?: Record<string, number>;
}

/** portfolio (#1058): one field of a POST body, always a JSON list. Its entries may be null. */
export interface BodySpec {
  name: string;
  items: "string" | "number" | "date";
  default: null;
  default_doc: string;
  doc: string;
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
  /** Default window: with no `from`, a kind that takes one gets `to` (or today, UTC-3) minus this. */
  window_months?: number;
  /** Shown in ?help: what a reader must know before using the rows (regime breaks). */
  notes?: string[];
  // -- portfolio (#1058) --
  /** POST: a data call is a POST with a JSON body of lists (`body`); ?help stays a GET. Default GET. */
  method?: "GET" | "POST";
  body?: BodySpec[];
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
      "status": "built",
      "summary": "What did it trade at? Daily history (split-adjusted by default), latest quote, sessions, indices, B3 FORWARD prints.",
      "example": "/v2/prices?id=PETR4",
      "shared": ["id", "from", "to"],
      "window_months": 12,
      "parameters": [
        {
          "name": "kind",
          "visibility": "main",
          "type": "enum",
          "values": ["history", "latest", "session", "index", "forward"],
          "default": "history",
          "doc": "history: one ticker's daily series. latest: its newest session. session: every quote of one session (the seven price views in one). index: a B3 index's daily levels. forward: B3 FORWARD-segment prints (fixed-income ETFs COTAHIST does not carry)."
        },
        {
          "name": "freq",
          "visibility": "main",
          "type": "enum",
          "values": ["day", "month"],
          "default": "day",
          "doc": "kind history, index, forward. month: the last session of each month, selected from the daily rows (no interpolation; a month with no session has no row). The daily rows still count toward the 1,000-row cap."
        },
        {
          "name": "adjust",
          "visibility": "main",
          "type": "enum",
          "values": ["split", "none"],
          "default": "split",
          "doc": "kind history. split: close_adj (splits, groupings, bonus shares; no dividends). none: the raw close as traded. Every row carries adjusted (true or false); the other kinds are never adjusted."
        },
        {
          "name": "board",
          "visibility": "hidden",
          "type": "string",
          "default": null,
          "default_doc": "all boards: the series follows the ISIN across boards",
          "doc": "kind history, latest, session. A BDI board code (02 is the standard lot)."
        },
        {
          "name": "asset_class",
          "visibility": "hidden",
          "type": "enum",
          "values": ["all", "equity", "bdr", "unit", "fund_quota", "cash_security", "auction"],
          "default": "all",
          "doc": "kind session. all: api.quotes (standard lot, tpmerc 010). Each class reads its own view (equities, bdrs, units, fund_quotas, cash_securities: standard, odd and block lots, with lot on the row; auctions: tpmerc 017), with every column it publishes."
        },
        {
          "name": "fields",
          "visibility": "hidden",
          "type": "enum",
          "values": ["core", "all"],
          "default": "core",
          "doc": "core: a short set (history: ticker, trade_date, close_adj or close, isin). all: every column the endpoint publishes. index and forward publish few columns, so core is all of them."
        },
        {
          "name": "date",
          "visibility": "hidden",
          "type": "date",
          "default": null,
          "default_doc": "the latest session in the 14 days to today that matches the other filters",
          "doc": "kind session. The session date, YYYY-MM-DD."
        }
      ],
      "kinds": {
        "history": {
          "doc": "api.quote_history: one ticker, oldest first, 1 year to the latest session by default. Refuses (over_limit) above 1,000 daily rows: narrow from/to. With no id: the research universe (the tickers held).",
          "endpoint": "quote_history",
          "args": { "id": "p_ticker", "from": "p_from", "to": "p_to", "board": "p_board" },
          "filters": [{ "parameter": "freq", "op": "month_last", "column": "trade_date", "all": "day" }],
          "uses": ["adjust", "fields"],
          "when_empty": { "parameter": "id", "plan": { "endpoint": "research_universe", "args": {} } }
        },
        "latest": {
          "doc": "api.quote_latest: the ticker's newest session (raw, adjusted false). With no id: the research universe.",
          "endpoint": "quote_latest",
          "args": { "id": "p_ticker", "board": "p_board" },
          "uses": ["fields"],
          "when_empty": { "parameter": "id", "plan": { "endpoint": "research_universe", "args": {} } }
        },
        "session": {
          "doc": "One session's quotes from one price view (raw, adjusted false). A view answer is cut at 1,000 rows, so 1,000 rows or more is refused (over_limit): narrow with asset_class, board or id.",
          "endpoint": "quotes",
          "view": true,
          "order": "trade_date.desc,ticker.asc",
          "view_by": {
            "parameter": "asset_class",
            "views": { "all": "quotes", "equity": "equities", "bdr": "bdrs", "unit": "units", "fund_quota": "fund_quotas", "cash_security": "cash_securities", "auction": "auctions" }
          },
          "args": { "id": "ticker", "board": "board", "date": "trade_date" },
          "uses": ["fields"]
        },
        "index": {
          "doc": "api.index_history: one B3 index code (IBOV, IFIX, ...), levels as published (total-return indices, not adjusted). With no id the SQL refusal names the codes held.",
          "endpoint": "index_history",
          "args": { "id": "p_index", "from": "p_from", "to": "p_to" },
          "filters": [{ "parameter": "freq", "op": "month_last", "column": "trade_date", "all": "day" }],
          "uses": ["fields"]
        },
        "forward": {
          "doc": "api.trade_consolidated_history: one FORWARD-segment ticker; last_price is the close, ref_price is never a trade.",
          "endpoint": "trade_consolidated_history",
          "args": { "id": "p_ticker", "from": "p_from", "to": "p_to" },
          "filters": [{ "parameter": "freq", "op": "month_last", "column": "trade_date", "all": "day" }],
          "uses": ["fields"]
        }
      }
    },
    {
      "name": "statements",
      "status": "built",
      "summary": "What did the company file? Income, balance sheet, cash flow, headline figures and every stored version.",
      "example": "/v2/statements?id=PETR4&kind=income",
      "shared": ["id", "from", "to"],
      "window_months": 60,
      "parameters": [
        {
          "name": "kind",
          "visibility": "main",
          "type": "enum",
          "values": ["all", "income", "balance", "cashflow", "headline", "versions"],
          "default": "all",
          "doc": "all: every filed line, long (api.financials). income, balance, cashflow: the standard lines, wide. headline: revenue, net income, assets, equity, margins (api.company_financials). versions: every stored version of one statement (api.financial_statement_history)."
        },
        {
          "name": "period",
          "visibility": "main",
          "type": "enum",
          "values": ["both", "quarterly", "annual"],
          "default": "both",
          "null_value": "both",
          "sql_values": { "quarterly": "itr", "annual": "dfp" },
          "doc": "quarterly: ITR filings. annual: DFP filings. A quarterly filing holds the 3-month and the year-to-date figure; period_months on the row says which. Never add the two."
        },
        {
          "name": "scope",
          "visibility": "main",
          "type": "enum",
          "values": ["consolidated", "individual"],
          "default": "consolidated",
          "sql_values": { "consolidated": "con", "individual": "ind" },
          "doc": "Consolidated and individual are separate filings of the same period; they are never merged."
        },
        {
          "name": "as_of",
          "visibility": "hidden",
          "type": "date",
          "default": null,
          "default_doc": "none: the latest stored version of every document, which is NOT point in time",
          "doc": "Point in time: only documents CVM received before this date, at the highest version known then. Not for kind versions."
        },
        {
          "name": "statement",
          "visibility": "hidden",
          "type": "enum",
          "values": ["DRE", "BPA", "BPP", "DFC_MD", "DFC_MI", "DMPL", "DRA", "DVA"],
          "default": "DRE",
          "doc": "kind versions: the one statement to read (DRE income, BPA assets, BPP liabilities and equity, DFC_MD or DFC_MI cash flow, DMPL, DRA, DVA)."
        }
      ],
      "kinds": {
        "all": {
          "doc": "api.financials: every line, one row per account, latest stored version. Refuses above 1,000 rows (over_limit): narrow from/to or period. With no id (every kind): the research universe, whose cnpj links a ticker to its filer.",
          "endpoint": "financials",
          "args": { "id": "p_id", "from": "p_from", "to": "p_to", "period": "p_doc_type", "scope": "p_scope", "as_of": "p_as_of" },
          "when_empty": { "parameter": "id", "plan": { "endpoint": "research_universe", "args": {} } }
        },
        "income": {
          "doc": "api.income_statements: one row per filed period, with period_months.",
          "endpoint": "income_statements",
          "args": { "id": "p_id", "from": "p_from", "to": "p_to", "period": "p_doc_type", "scope": "p_scope", "as_of": "p_as_of" },
          "when_empty": { "parameter": "id", "plan": { "endpoint": "research_universe", "args": {} } }
        },
        "balance": {
          "doc": "api.balance_sheets: one row per filed date. A balance sheet is a point in time, so the source has no period_months.",
          "endpoint": "balance_sheets",
          "args": { "id": "p_id", "from": "p_from", "to": "p_to", "period": "p_doc_type", "scope": "p_scope", "as_of": "p_as_of" },
          "when_empty": { "parameter": "id", "plan": { "endpoint": "research_universe", "args": {} } }
        },
        "cashflow": {
          "doc": "api.cash_flow_statements: one row per filed period, with period_months.",
          "endpoint": "cash_flow_statements",
          "args": { "id": "p_id", "from": "p_from", "to": "p_to", "period": "p_doc_type", "scope": "p_scope", "as_of": "p_as_of" },
          "when_empty": { "parameter": "id", "plan": { "endpoint": "research_universe", "args": {} } }
        },
        "headline": {
          "doc": "api.company_financials: headline figures per filed period. The function takes no p_doc_type, so period is a selection on the rows' doc_type.",
          "endpoint": "company_financials",
          "args": { "id": "p_id", "from": "p_from", "to": "p_to", "scope": "p_scope", "as_of": "p_as_of" },
          "filters": [{ "parameter": "period", "op": "in", "column": "doc_type", "all": "both", "map": { "quarterly": "itr", "annual": "dfp" } }],
          "when_empty": { "parameter": "id", "plan": { "endpoint": "research_universe", "args": {} } }
        },
        "versions": {
          "doc": "api.financial_statement_history: every stored version of one statement (hidden statement, default DRE), with filing metadata. No as_of: it already shows every version.",
          "endpoint": "financial_statement_history",
          "args": { "id": "p_id", "statement": "p_statement", "from": "p_from", "to": "p_to", "period": "p_doc_type", "scope": "p_scope" },
          "when_empty": { "parameter": "id", "plan": { "endpoint": "research_universe", "args": {} } }
        }
      }
    },
    {
      "name": "funds",
      "status": "built",
      "summary": "What is this fund and how is it doing? Profile, NAV, holdings, debentures, FII properties.",
      "example": "/v2/funds?id=33000167000101&kind=nav",
      "shared": [
        "id",
        "from",
        "to",
        "limit"
      ],
      "window_months": 36,
      "notes": [
        "id is a fund CNPJ: 14 digits, punctuation allowed. Find one with /v2/search?kind=fund&q=<name>.",
        "kind=nav columns are per family: a null outside the family's list is not applicable, not missing (coverage?kind=catalog, applicability).",
        "FIDC delinquency (api.fund_nav, panel) starts 2013-01 and is on every row only from 2020-11 (regime break; coverage?kind=catalog lists it under regime_breaks). Through 2020-10-31 a fund with no tab VI row that month is null, not zero and not clean books; from 2020-11-30 it is filed on every row (a fund with none files 0). Never read a pre-2020-11 null as zero or fill it, and never compare a count of reporting funds across 2020-10 -> 2020-11."
      ],
      "parameters": [
        {
          "name": "kind",
          "visibility": "main",
          "type": "enum",
          "values": [
            "profile",
            "nav",
            "holdings",
            "debentures",
            "properties"
          ],
          "default": "profile",
          "doc": "profile: one fund's registry row and AUM (with no id: the fund registry). nav: the monthly NAV and flows series. holdings: the listed equities it holds (CDA). debentures: the debentures it holds. properties: an FII's real estate."
        },
        {
          "name": "family",
          "visibility": "main",
          "type": "enum",
          "values": [
            "all",
            "fi",
            "fidc",
            "fii",
            "fip",
            "fiagro"
          ],
          "default": "all",
          "null_value": "all",
          "doc": "One fund family. kind=nav: the series filed under that family (one CNPJ can file under two). With no id: the registry rows of that family."
        },
        {
          "name": "holding",
          "visibility": "hidden",
          "type": "string",
          "default": null,
          "default_doc": "none: what the fund in id holds",
          "doc": "Reverse lookup, instead of id. kind=holdings: the funds that hold this ticker. kind=debentures: the funds that hold this issuer's debentures (ticker, CVM code or CNPJ)."
        },
        {
          "name": "status",
          "visibility": "hidden",
          "type": "string",
          "default": "all",
          "null_value": "all",
          "doc": "With no id: only registry rows whose status is this, exactly as CVM publishes it (e.g. EM FUNCIONAMENTO NORMAL)."
        }
      ],
      "kinds": {
        "profile": {
          "doc": "api.fund_profile: one row per family the CNPJ files under. With no id: the api.funds registry view, ordered by cnpj, refused (over_limit) when the selection holds more than one page unless limit asks for the first N.",
          "endpoint": "fund_profile",
          "args": {
            "id": "p_cnpj"
          },
          "when_empty": {
            "parameter": "id",
            "plan": {
              "endpoint": "funds",
              "view": true,
              "order": "cnpj.asc,entity_type.asc",
              "args": {
                "family": "entity_type",
                "status": "status",
                "limit": "limit"
              }
            }
          }
        },
        "nav": {
          "doc": "api.fund_nav: monthly NAV, quota, quotaholders and flows, oldest first. With no to, the series ends at the family's latest complete period. Refuses above 1000 rows: narrow from, or pin family.",
          "endpoint": "fund_nav",
          "args": {
            "id": "p_cnpj",
            "from": "p_from",
            "to": "p_to",
            "family": "p_entity_type"
          },
          "require_one_of": [
            "id"
          ]
        },
        "holdings": {
          "doc": "api.fund_holdings: the listed equities a fund holds (CDA), or with holding the funds that hold a ticker. limit asks for the newest N rows.",
          "endpoint": "fund_holdings",
          "args": {
            "id": "p_cnpj",
            "holding": "p_ticker",
            "from": "p_from",
            "to": "p_to",
            "limit": "p_limit"
          },
          "require_one_of": [
            "id",
            "holding"
          ]
        },
        "debentures": {
          "doc": "api.fund_debentures: the debentures a fund holds, or with holding the funds that hold an issuer's paper. limit asks for the newest N rows.",
          "endpoint": "fund_debentures",
          "args": {
            "id": "p_cnpj",
            "holding": "p_issuer",
            "from": "p_from",
            "to": "p_to",
            "limit": "p_limit"
          },
          "require_one_of": [
            "id",
            "holding"
          ]
        },
        "properties": {
          "doc": "api.fii_property_history: an FII's properties, every filed version, newest first.",
          "endpoint": "fii_property_history",
          "args": {
            "id": "p_cnpj",
            "from": "p_from",
            "to": "p_to"
          },
          "require_one_of": [
            "id"
          ]
        }
      }
    },
    {
      "name": "fidc",
      "status": "built",
      "summary": "What is inside this FIDC? Portfolio, tranches, aging, cedentes, sacados.",
      "example": "/v2/fidc?id=<cnpj>&kind=tranches",
      "shared": [
        "id",
        "from",
        "to",
        "limit"
      ],
      "window_months": 24,
      "notes": [
        "id is a FIDC CNPJ: 14 digits, punctuation allowed. With no id, kind=portfolio lists the FIDC registry (api.funds, entity_type fidc).",
        "FIDC delinquency (api.fund_nav, panel) starts 2013-01 and is on every row only from 2020-11 (regime break; coverage?kind=catalog lists it under regime_breaks). Through 2020-10-31 a fund with no tab VI row that month is null, not zero and not clean books; from 2020-11-30 it is filed on every row (a fund with none files 0). Never read a pre-2020-11 null as zero or fill it, and never compare a count of reporting funds across 2020-10 -> 2020-11.",
        "Tab X (the SCR grade ladders of kind=portfolio) is filed from 2023-10: earlier months have no scr rows, not zero-graded ones. Values are as filed."
      ],
      "parameters": [
        {
          "name": "kind",
          "visibility": "main",
          "type": "enum",
          "values": [
            "portfolio",
            "tranches",
            "aging",
            "cedentes",
            "sacados"
          ],
          "default": "portfolio",
          "doc": "portfolio: the receivables book, long (tab II sectors, tab X SCR ladders, tax debt). tranches: each senior and subordinated series. aging: the to-maturity and overdue ladders. cedentes: the originators it buys from. sacados: its largest debtors, as anonymized ranks."
        },
        {
          "name": "series",
          "visibility": "hidden",
          "type": "string",
          "default": "all",
          "null_value": "all",
          "doc": "kind=tranches: one TAB_X_CLASSE_SERIE, matched exactly as filed."
        },
        {
          "name": "cedente",
          "visibility": "hidden",
          "type": "string",
          "default": "all",
          "null_value": "all",
          "doc": "kind=cedentes, instead of id: the funds that buy from this originator (CPF or CNPJ, or a listed ticker or CVM code)."
        },
        {
          "name": "item",
          "visibility": "hidden",
          "type": "enum",
          "values": [
            "all",
            "sector",
            "scr_debtor",
            "scr_operation",
            "tax_debt"
          ],
          "default": "all",
          "null_value": "all",
          "doc": "kind=portfolio: one part of the book, matched against the row's kind column: sector (tab II), scr_debtor or scr_operation (tab X ladders), tax_debt."
        }
      ],
      "kinds": {
        "portfolio": {
          "doc": "api.fidc_portfolio, newest first. Refuses above 1000 rows: narrow from, pin item, or ask for the newest N with limit. With no id: the FIDC registry, ordered by cnpj.",
          "endpoint": "fidc_portfolio",
          "args": {
            "id": "p_cnpj",
            "item": "p_kind",
            "from": "p_from",
            "to": "p_to",
            "limit": "p_limit"
          },
          "when_empty": {
            "parameter": "id",
            "plan": {
              "endpoint": "funds",
              "view": true,
              "order": "cnpj.asc",
              "where": {
                "entity_type": "fidc"
              },
              "args": {
                "limit": "limit"
              }
            }
          }
        },
        "tranches": {
          "doc": "api.fidc_tranches: per series, quota value, quotaholders and returns. Refuses above 1000 rows (no cursor): narrow from.",
          "endpoint": "fidc_tranches",
          "args": {
            "id": "p_cnpj",
            "from": "p_from",
            "to": "p_to",
            "series": "p_series"
          },
          "require_one_of": [
            "id"
          ]
        },
        "aging": {
          "doc": "api.fidc_aging: the to_maturity, overdue and overdue_total ladders. Refuses above 1000 rows (no cursor): narrow from.",
          "endpoint": "fidc_aging",
          "args": {
            "id": "p_cnpj",
            "from": "p_from",
            "to": "p_to"
          },
          "require_one_of": [
            "id"
          ]
        },
        "cedentes": {
          "doc": "api.fidc_cedentes: the originators a fund buys from, or with cedente the funds that buy from one. limit asks for the newest N rows.",
          "endpoint": "fidc_cedentes",
          "args": {
            "id": "p_cnpj",
            "cedente": "p_cedente",
            "from": "p_from",
            "to": "p_to",
            "limit": "p_limit"
          },
          "require_one_of": [
            "id",
            "cedente"
          ]
        },
        "sacados": {
          "doc": "api.fidc_sacados: the largest debtors, as anonymized ranks (there is no debtor-side lookup). limit asks for the newest N rows.",
          "endpoint": "fidc_sacados",
          "args": {
            "id": "p_cnpj",
            "from": "p_from",
            "to": "p_to",
            "limit": "p_limit"
          },
          "require_one_of": [
            "id"
          ]
        }
      }
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
      "status": "built",
      "summary": "What was filed or restated? Company IPE filings, fund documents, restatements, judicial recovery.",
      "example": "/v2/events?id=PETR4",
      "shared": [
        "id",
        "from",
        "to"
      ],
      "window_months": 12,
      "notes": [
        "id is a ticker, 14-digit CNPJ or CVM code for kind company and judicial_recovery, and a fund CNPJ for kind fund, restatements and restatement_diff.",
        "Dates are delivery days. With no to, company and judicial_recovery end today and the fund kinds have no upper bound."
      ],
      "parameters": [
        {
          "name": "kind",
          "visibility": "main",
          "type": "enum",
          "values": [
            "company",
            "fund",
            "restatements",
            "restatement_diff",
            "judicial_recovery"
          ],
          "default": "company",
          "doc": "company: a listed company's IPE filings (fatos relevantes, comunicados, ...). fund: a fund's FNET documents. restatements: FNET documents re-filed as a new version (with no id: every fund's). restatement_diff: field by field, what changed in a fund's restated documents. judicial_recovery: listed companies' judicial recovery filings (with no id: every company's)."
        },
        {
          "name": "category",
          "visibility": "main",
          "type": "string",
          "default": "all",
          "null_value": "all",
          "doc": "One label, matched exactly as the source labels it. kind=company: the IPE categoria (e.g. Fato Relevante). kind=fund and restatement_diff: the FNET tipo_documento. kind=judicial_recovery: the CVM Tipo (accented as published)."
        },
        {
          "name": "family",
          "visibility": "hidden",
          "type": "enum",
          "values": [
            "all",
            "fii",
            "fidc",
            "etf"
          ],
          "default": "all",
          "null_value": "all",
          "doc": "kind=restatements: the FNET fund type link (FII, FIDC or ETF). all includes documents not linked to a fund type yet."
        }
      ],
      "kinds": {
        "company": {
          "doc": "api.company_events: IPE filings, newest first. Refuses above 1000 rows (no cursor): narrow from or pin category.",
          "endpoint": "company_events",
          "args": {
            "id": "p_id",
            "from": "p_from",
            "to": "p_to",
            "category": "p_category"
          },
          "require_one_of": [
            "id"
          ]
        },
        "fund": {
          "doc": "api.fund_documents: FNET documents, newest first, each version its own fnet_id. Refuses above 1000 rows: narrow from or pin category.",
          "endpoint": "fund_documents",
          "args": {
            "id": "p_cnpj",
            "from": "p_from",
            "to": "p_to",
            "category": "p_tipo"
          },
          "require_one_of": [
            "id"
          ]
        },
        "restatements": {
          "doc": "api.fund_restatements: one row per document with versao > 1, with the version it most plausibly replaced and whether SILO diffed the pair.",
          "endpoint": "fund_restatements",
          "args": {
            "id": "p_cnpj",
            "from": "p_from",
            "to": "p_to",
            "family": "p_tipo_fundo"
          }
        },
        "restatement_diff": {
          "doc": "api.fund_restatement_diff: one row per field that changed between a restated document and its predecessor (the FIDC informe mensal for now).",
          "endpoint": "fund_restatement_diff",
          "args": {
            "id": "p_cnpj",
            "from": "p_from",
            "to": "p_to",
            "category": "p_tipo"
          },
          "require_one_of": [
            "id"
          ]
        },
        "judicial_recovery": {
          "doc": "api.rj_listed_documents: judicial recovery (recuperacao judicial) filings of listed companies, newest first.",
          "endpoint": "rj_listed_documents",
          "args": {
            "id": "p_id",
            "from": "p_from",
            "to": "p_to",
            "category": "p_doc_type"
          }
        }
      }
    },
    {
      "name": "screens",
      "status": "built",
      "summary": "Which funds look odd? Forensic screens: signals, not verdicts.",
      "example": "/v2/screens",
      "shared": [],
      "notes": [
        "Signal, not a verdict: a screen lists a pattern worth a look. Legal funds match every screen (exclusive vehicles, wind-downs, distressed mandates, routine corrections). Every response repeats this in meta.signal.",
        "Each threshold is hidden and defaults to the SQL function's own default; meta.request echoes the value applied. A threshold the chosen screen does not take is bad_request."
      ],
      "parameters": [
        {
          "name": "kind",
          "visibility": "main",
          "type": "enum",
          "values": ["list", "captive_vehicles", "delinquency_drivers", "dormant_funds", "dormant_trend", "evergreen_aging", "late_filers", "overdue_securit", "restatements", "silent_filers", "zombie_growth"],
          "default": "list",
          "doc": "list (the default, no kind given): the screens, one line each, with their defaults. Any other value runs that screen (api.screen_<kind>)."
        },
        { "name": "date", "visibility": "hidden", "type": "date", "default": null, "default_doc": "the screen's own: zombie_growth the latest aging month; delinquency_drivers the latest complete FIDC month; restatements today; late_filers the newest month whose deadline has passed", "doc": "zombie_growth: the aging month-end (p_period). delinquency_drivers, restatements, late_filers: the window end (p_end)." },
        { "name": "months", "visibility": "hidden", "type": "integer", "default": null, "default_doc": "the screen's SQL default (12)", "doc": "delinquency_drivers (2..24), restatements, late_filers (1..36): the window length in months." },
        { "name": "lookback_months", "visibility": "hidden", "type": "integer", "default": null, "default_doc": "the screen's SQL default: captive_vehicles 3, evergreen_aging 12, dormant_funds 3, dormant_trend 3", "doc": "captive_vehicles, evergreen_aging, dormant_funds, dormant_trend: the trailing window in months." },
        { "name": "history_months", "visibility": "hidden", "type": "integer", "default": null, "default_doc": "the SQL default (36)", "doc": "dormant_trend: month-ends emitted, 1..60." },
        { "name": "min_months", "visibility": "hidden", "type": "integer", "default": null, "default_doc": "the SQL default (6)", "doc": "delinquency_drivers: observations a fund needs, 2..months." },
        { "name": "min_aum", "visibility": "hidden", "type": "number", "default": null, "default_doc": "the screen's SQL default: zombie_growth 1000000, captive_vehicles 50000000 (BRL)", "doc": "zombie_growth, captive_vehicles: the NAV floor, BRL." },
        { "name": "min_nav", "visibility": "hidden", "type": "number", "default": null, "default_doc": "none: no floor", "doc": "dormant_funds: keep rows whose last NAV is at least this, BRL (an output filter)." },
        { "name": "min_delinq_pct", "visibility": "hidden", "type": "number", "default": null, "default_doc": "the SQL default (5)", "doc": "zombie_growth: delinquency floor, percent of NAV, 0..100." },
        { "name": "max_investors", "visibility": "hidden", "type": "integer", "default": null, "default_doc": "the SQL default (10)", "doc": "captive_vehicles: flagged when the window minimum quotaholder count is below this, 1..1000." },
        { "name": "min_longtail_pct", "visibility": "hidden", "type": "number", "default": null, "default_doc": "the SQL default (70)", "doc": "evergreen_aging: share of delinquency overdue more than 1080 days, 0..100." },
        { "name": "max_variation_pp", "visibility": "hidden", "type": "number", "default": null, "default_doc": "the SQL default (10)", "doc": "evergreen_aging: largest move of that share across the window, percentage points." },
        { "name": "min_volume", "visibility": "hidden", "type": "number", "default": null, "default_doc": "the SQL default (100000)", "doc": "overdue_securit: paid-in volume floor, BRL." },
        { "name": "min_delta_brl", "visibility": "hidden", "type": "number", "default": null, "default_doc": "the SQL default (1000000)", "doc": "delinquency_drivers: the up/down threshold on delinquency, BRL." },
        { "name": "min_delta_pp", "visibility": "hidden", "type": "number", "default": null, "default_doc": "the SQL default (1.0)", "doc": "delinquency_drivers: the up/down threshold on the rate, percentage points." },
        { "name": "min_restatements", "visibility": "hidden", "type": "integer", "default": null, "default_doc": "the SQL default (3)", "doc": "restatements: re-filings (versao > 1) in the window, 1..1000." },
        { "name": "min_rate_pct", "visibility": "hidden", "type": "number", "default": null, "default_doc": "the SQL default (20)", "doc": "restatements: re-filings as percent of the fund's documents in the window, 0..100." },
        { "name": "min_days_late", "visibility": "hidden", "type": "integer", "default": null, "default_doc": "the SQL default (5)", "doc": "late_filers: days past the cited deadline that count as late, 1..90." },
        { "name": "min_late", "visibility": "hidden", "type": "integer", "default": null, "default_doc": "the SQL default (2)", "doc": "late_filers: late months a fund needs in the window." },
        { "name": "min_silent_months", "visibility": "hidden", "type": "integer", "default": null, "default_doc": "the SQL default (3)", "doc": "silent_filers: complete months with no filing, 1..120." },
        { "name": "max_silent_months", "visibility": "hidden", "type": "integer", "default": null, "default_doc": "the SQL default (24)", "doc": "silent_filers: and at most this many, up to 240." },
        { "name": "dormancy", "visibility": "hidden", "type": "enum", "values": ["all", "empty_shell", "parked_capital"], "default": "all", "null_value": "all", "doc": "dormant_funds: keep one dormancy (an output filter). empty_shell: no quotaholder. parked_capital: quotaholders, no flow." },
        { "name": "driver", "visibility": "hidden", "type": "enum", "values": ["all", "consistent_worsening", "value_up_rate_masked", "denominator_only", "improvement", "stable"], "default": "all", "null_value": "all", "doc": "delinquency_drivers: keep one class of move (an output filter)." },
        { "name": "modality", "visibility": "hidden", "type": "enum", "values": ["all", "RE", "RC"], "default": "all", "null_value": "all", "doc": "restatements: count only one FNET modalidade. RE: voluntary. RC: required by CVM." },
        { "name": "family", "visibility": "hidden", "type": "enum", "values": ["all", "fi", "fidc", "fii", "fiagro"], "default": "all", "null_value": "all", "doc": "late_filers (fii, fidc) and silent_filers (fi, fidc, fii, fiagro): keep one family (an output filter)." }
      ],
      "kinds": {
        "list": {
          "doc": "The screens, one line each, with the family each reads and its SQL defaults (from api.catalog().screens).",
          "endpoint": "catalog",
          "args": {},
          "single": true
        },
        "captive_vehicles": {
          "doc": "FIIs whose NAV peaked above min_aum while the quotaholder count never reached max_investors.",
          "endpoint": "screen_captive_vehicles",
          "args": { "lookback_months": "p_lookback_months", "max_investors": "p_max_investors", "min_aum": "p_min_aum" },
          "sql_defaults": { "lookback_months": 3, "max_investors": 10, "min_aum": 50000000 }
        },
        "delinquency_drivers": {
          "doc": "FIDC delinquency, first vs last observation in BRL and in points of NAV, the move classified (driver). No window before 2025-01.",
          "endpoint": "screen_delinquency_drivers",
          "args": { "date": "p_end", "months": "p_months", "min_months": "p_min_months", "min_delta_brl": "p_min_delta_brl", "min_delta_pp": "p_min_delta_pp", "driver": "p_driver" },
          "sql_defaults": { "months": 12, "min_months": 6, "min_delta_brl": 1000000, "min_delta_pp": 1.0 }
        },
        "dormant_funds": {
          "doc": "FI classes that filed every month of the window with zero subscriptions and zero redemptions (empty_shell, parked_capital).",
          "endpoint": "screen_dormant_funds",
          "args": { "lookback_months": "p_lookback_months", "dormancy": "p_dormancy", "min_nav": "p_min_nav" },
          "sql_defaults": { "lookback_months": 3 }
        },
        "dormant_trend": {
          "doc": "dormant_funds counted at every month-end: funds filing, empty shells, parked capital and its NAV.",
          "endpoint": "screen_dormant_trend",
          "args": { "lookback_months": "p_lookback_months", "history_months": "p_history_months" },
          "sql_defaults": { "lookback_months": 3, "history_months": 36 }
        },
        "evergreen_aging": {
          "doc": "FIDCs whose receivables overdue more than 1080 days stay a large, nearly constant share of delinquency.",
          "endpoint": "screen_evergreen_aging",
          "args": { "lookback_months": "p_lookback_months", "min_longtail_pct": "p_min_longtail_pct", "max_variation_pp": "p_max_variation_pp" },
          "sql_defaults": { "lookback_months": 12, "min_longtail_pct": 70, "max_variation_pp": 10 }
        },
        "late_filers": {
          "doc": "FIIs and FIDCs whose monthly informe reached FNET at least min_days_late days after the cited deadline, in at least min_late months.",
          "endpoint": "screen_late_filers",
          "args": { "months": "p_months", "date": "p_end", "min_days_late": "p_min_days_late", "min_late": "p_min_late", "family": "p_family" },
          "sql_defaults": { "months": 12, "min_days_late": 5, "min_late": 2 }
        },
        "overdue_securit": {
          "doc": "CRI, CRA and other series past their filed maturity whose newest filing still reports a non-terminal status.",
          "endpoint": "screen_overdue_securit",
          "args": { "min_volume": "p_min_volume" },
          "sql_defaults": { "min_volume": 100000 }
        },
        "restatements": {
          "doc": "Funds whose FNET re-filings (versao > 1) in the window reach min_restatements and min_rate_pct of their documents.",
          "endpoint": "screen_restatements",
          "args": { "months": "p_months", "date": "p_end", "min_restatements": "p_min_restatements", "min_rate_pct": "p_min_rate_pct", "modality": "p_modalidade" },
          "sql_defaults": { "months": 12, "min_restatements": 3, "min_rate_pct": 20 }
        },
        "silent_filers": {
          "doc": "Funds CVM still lists as active whose last periodic informe is min_silent_months to max_silent_months behind their family.",
          "endpoint": "screen_silent_filers",
          "args": { "min_silent_months": "p_min_silent_months", "max_silent_months": "p_max_silent_months", "family": "p_family" },
          "sql_defaults": { "min_silent_months": 3, "max_silent_months": 24 }
        },
        "zombie_growth": {
          "doc": "FIDCs with delinquency above min_delinq_pct of NAV while NAV stays above min_aum, in one aging month.",
          "endpoint": "screen_zombie_growth",
          "args": { "date": "p_period", "min_delinq_pct": "p_min_delinq_pct", "min_aum": "p_min_aum" },
          "sql_defaults": { "min_delinq_pct": 5, "min_aum": 1000000 }
        }
      }
    },
    {
      "name": "panel",
      "status": "built",
      "summary": "A clean (id, date, metric, value) table across families.",
      "example": "/v2/panel?id=PETR4,VALE3&metric=close_return",
      "shared": ["id", "from", "to"],
      "window_months": 36,
      "notes": [
        "panel has one kind, so it takes no kind parameter. id is a comma-separated list of tickers, fund CNPJs, option or termo tickers and futures codes. The tier ceiling applies (3 ids anonymous, 50 signed in) and is refused above it (over_limit), never trimmed.",
        "Missing months stay absent: no fill, no return across a gap. Metric names are catalog().metrics (coverage?kind=catalog); an unknown name is unknown_parameter.",
        "With no id and a family, panel walks the family (universe mode, monthly, signed-in callers only); min_nav and min_months narrow it."
      ],
      "parameters": [
        {
          "name": "metric",
          "visibility": "main",
          "type": "list",
          "default": "auto",
          "null_value": "auto",
          "doc": "Comma-separated catalog metric names (close, close_adj, close_return, volume, nav, delinquency, ...). auto: each id's family default, as api.panel with no p_metrics (close_adj for shares and units, close for other tickers, settlement_rate for futures, nav for funds)."
        },
        {
          "name": "freq",
          "visibility": "main",
          "type": "enum",
          "values": ["month", "day"],
          "default": "month",
          "doc": "month: the last session of each month for tickers, the filed month for funds. day: tickers and futures only (funds file monthly)."
        },
        {
          "name": "family",
          "visibility": "main",
          "type": "enum",
          "values": ["auto", "fi", "fidc", "fii", "fip", "fiagro"],
          "default": "auto",
          "null_value": "auto",
          "doc": "auto: every family a CNPJ files under (a CNPJ filing as fi and fidc yields one row per family). One family narrows the fund rows to it; with no id it walks that family (universe mode)."
        },
        { "name": "min_nav", "visibility": "hidden", "type": "number", "default": null, "default_doc": "none: no floor", "doc": "Universe mode only: keep funds whose latest NAV in the window is at least this, BRL." },
        { "name": "min_months", "visibility": "hidden", "type": "integer", "default": null, "default_doc": "none: no floor", "doc": "Universe mode only: keep funds with at least this many observations of the first metric." }
      ],
      "kinds": {
        "panel": {
          "doc": "api.panel: long rows (id, id_type, asset_class, date, metric, value, source), 3 years back from to by default. Refuses above 1,000 rows (over_limit): narrow from/to, ids or metrics.",
          "endpoint": "panel",
          "args": { "id": "p_ids", "metric": "p_metrics", "from": "p_from", "to": "p_to", "freq": "p_freq", "family": "p_entity_type", "min_nav": "p_min_nav", "min_months": "p_min_months" }
        }
      }
    },
    {
      "name": "portfolio",
      "status": "built",
      "summary": "Diagnose a portfolio: resolve statement lines, fees, look-through, movement (POST).",
      "example": "POST /v2/portfolio?kind=resolve {\"names\": [\"ITAU RF DI\"]}",
      "method": "POST",
      "shared": [],
      "notes": [
        "A data call is a POST: kind, month and the hidden parameters go in the query string, the lists go in a JSON body (see body). ?help stays a GET. Read-only: every kind is one api.portfolio_* function.",
        "Each list is capped by its function (200 entries, 70 for debenture_returns, 50 classes for equivalents) and refused above it, never trimmed.",
        "Not served: portfolio_credit_returns (held back with the ANBIMA-linked endpoints). The class in fees, fee_peers, movement and equivalents is the ANBIMA class label as filed in the CVM Extrato; no ANBIMA table is read."
      ],
      "parameters": [
        {
          "name": "kind",
          "visibility": "main",
          "type": "enum",
          "values": ["resolve", "fees", "fee_peers", "lookthrough", "movement", "instruments", "fund_terms", "equivalents", "debenture_returns"],
          "default": "resolve",
          "doc": "resolve: statement lines to candidate funds. fees: estimated and disclosed fees. fee_peers: the admin fee against its filed class. lookthrough: holdings through fund quotas. movement: the month's quota return against its class. instruments: CRA, CRI and debenture codes. fund_terms: manager, administrator, redemption terms. equivalents: the ETFs that track a class's index. debenture_returns: 13 month-ends of debenture marks."
        },
        {
          "name": "month",
          "visibility": "main",
          "type": "date",
          "default": null,
          "default_doc": "the latest complete month, as each function defines it (fees: each fund's newest balancete; lookthrough: the last complete CDA month; movement: the last complete FI month). debenture_returns has no default month and needs one.",
          "doc": "Any day of the month. fees, lookthrough, movement: the month read. debenture_returns: the window's last month."
        },
        { "name": "max_depth", "visibility": "hidden", "type": "integer", "default": 4, "doc": "lookthrough: fund-quota levels looked through, 1..6 (the SQL default is 4)." },
        { "name": "as_of", "visibility": "hidden", "type": "date", "default": null, "default_doc": "today (the SQL default)", "doc": "fee_peers: dates the comparison and excludes later documents; it reads the latest Extrato, so it is not a historical backtest. equivalents: snapshots dated after it are not read." },
        { "name": "max_monthly_drop_pct", "visibility": "hidden", "type": "number", "default": null, "default_doc": "none: every decrease is flagged limite_pendente (the threshold is the owner's to set)", "doc": "debenture_returns: a monthly PU drop beyond this is flagged queda_pu_possivel_evento." }
      ],
      "body": [
        { "name": "id", "items": "string", "default": null, "default_doc": "none: required by every kind except resolve", "doc": "The list: fund CNPJs (fees, fee_peers, lookthrough, movement, fund_terms; resolve: the CNPJ each line prints, parallel to names), instrument codes (instruments), filed ANBIMA class labels (equivalents) or debenture tickers (debenture_returns). Null entries are allowed where the function takes them." },
        { "name": "names", "items": "string", "default": null, "default_doc": "none: required by resolve", "doc": "resolve: one statement line each, the fund name as printed." },
        { "name": "quotas", "items": "number", "default": null, "default_doc": "none", "doc": "resolve: the quota value each line prints, parallel to names, for the tie-break." },
        { "name": "quota_dates", "items": "date", "default": null, "default_doc": "none", "doc": "resolve: the date each quota refers to, parallel to names." }
      ],
      "kinds": {
        "resolve": {
          "doc": "api.portfolio_resolve: up to 5 ranked candidate funds per statement line (a printed CNPJ wins, then an ETF ticker, an exact name, a trigram match).",
          "endpoint": "portfolio_resolve",
          "args": { "names": "p_names", "id": "p_cnpjs", "quotas": "p_quotas", "quota_dates": "p_quota_dates" }
        },
        "fees": {
          "doc": "api.portfolio_fees: the disclosed fee and the fee estimated from the balancete, never mixed.",
          "endpoint": "portfolio_fees",
          "args": { "id": "p_cnpjs", "month": "p_month" }
        },
        "fee_peers": {
          "doc": "api.portfolio_fee_peers: the admin fee against funds and ETFs of the same filed class, one row per CNPJ.",
          "endpoint": "portfolio_fee_peers",
          "args": { "id": "p_cnpjs", "as_of": "p_as_of" }
        },
        "lookthrough": {
          "doc": "api.portfolio_lookthrough: one CDA month, holdings followed through fund quotas up to max_depth levels.",
          "endpoint": "portfolio_lookthrough",
          "args": { "id": "p_cnpjs", "month": "p_month", "max_depth": "p_max_depth" }
        },
        "movement": {
          "doc": "api.portfolio_movement: the fund's monthly quota return against its filed class (movimento incomum).",
          "endpoint": "portfolio_movement",
          "args": { "id": "p_cnpjs", "month": "p_month" }
        },
        "instruments": {
          "doc": "api.portfolio_instruments: CRA, CRI and debenture codes matched to their series, one line per code.",
          "endpoint": "portfolio_instruments",
          "args": { "id": "p_codes" }
        },
        "fund_terms": {
          "doc": "api.portfolio_fund_terms: manager, administrator and redemption terms as filed, one line per CNPJ.",
          "endpoint": "portfolio_fund_terms",
          "args": { "id": "p_cnpjs" }
        },
        "equivalents": {
          "doc": "api.portfolio_equivalents: the active ETFs tracking an index the owner-reviewed list maps to each filed class.",
          "endpoint": "portfolio_equivalents",
          "args": { "id": "p_classes", "as_of": "p_as_of" }
        },
        "debenture_returns": {
          "doc": "api.portfolio_debenture_returns: 13 month-ends of median fund marks (CDA block 4) per debenture ticker; marks, not trades. Needs month.",
          "endpoint": "portfolio_debenture_returns",
          "args": { "id": "p_tickers", "month": "p_end_month", "max_monthly_drop_pct": "p_max_monthly_drop_pct" },
          "require_one_of": ["month"]
        }
      }
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
