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
