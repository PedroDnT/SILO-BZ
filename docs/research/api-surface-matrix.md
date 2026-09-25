# SILO-BZ researcher API surface matrix

Snapshot inspected 2026-09-23 from `src/store/analytical/*.sql`,
`openapi.json`, `serve/catalog.py`, `sdk/silo_client/client.py`, and
`serve/app.py`. The object parity tests in `tests/test_openapi_spec.py` compare
public SQL grants with OpenAPI in both directions; the SQL/SDK parameter tests
guard RPC argument compatibility. This table distinguishes the full direct
PostgREST contract from the smaller Flask adapter.

## Surface coverage

| Surface | Current coverage | Shape and limits | Evidence |
| --- | --- | --- | --- |
| SQL grants → PostgREST/OpenAPI | 28 RPC functions + 13 views; all 41 granted objects appear in OpenAPI | RPC arguments and result schemas are documented from database introspection; row caps and permissions are applied in SQL | `tests/test_openapi_spec.py`; local isolated Postgres smoke |
| Discovery catalog | 14 panel metrics, 40 constraints, 11 examples; `catalog`, `coverage`, and `metric_coverage` are RPCs | Catalog explains grains, IDs, date/units caveats, caps and examples. It is not an exhaustive endpoint directory; OpenAPI and API docs enumerate the broader contract. | catalog payload tests and exact SQL `$json$` parity test |
| Python SDK | All 28 public RPCs have direct SDK methods; generic `view`, `view_all`, and iterators support the 13 view resources | SDK omits optional `None` RPC values, normalizes inputs, and exposes paging helpers where SQL has a cursor | `tests/test_sdk_rpc_params_match_sql.py`, `tests/test_sdk_client.py` |
| Flask `serve/` adapter | 12 GET routes | Purposefully narrower convenience API. It does not proxy every PostgREST object. Direct PostgREST/SDK is the access path for specialized RPCs and views outside these routes. | Flask route contract tests; `.claude/skills/run-silo-bz/smoke.sh` |

## Public PostgREST objects

The 28 RPCs in `openapi.json` are:

```text
anbima_classes, catalog, company_financials, coverage, fidc_cedentes,
fidc_portfolio, fidc_sacados, fii_property_history,
financial_statement_history, financials, focus_expectations, fund_debentures,
fund_holdings, fund_nav, fund_profile, income_statements, inflation,
inflation_items, lookup, metric_coverage, option_chain, option_exercises,
option_history, panel, quote_history, quote_latest, search_funds, termo_history
```

The 13 granted views are:

```text
auctions, bdrs, cash_securities, equities, fund_quotas, funds, investor_flow,
lending_participants, lending_trades, quotes, short_interest,
short_interest_by_sector, units
```

The three latest held-data additions are discoverable through the catalog's
metadata and docs and callable through the SDK. Their contract tests pin their
required identifiers, dates, and bounded results:

| RPC | Required resolution | SDK method | Flask route |
| --- | --- | --- | --- |
| `financial_statement_history` | Company/CVM identity + required statement; period and filing version retained | `financial_statement_history()` | None; use direct PostgREST or SDK |
| `fii_property_history` | Exact fund CNPJ + reporting-date window; source row identity only | `fii_property_history()` | None; use direct PostgREST or SDK |
| `focus_expectations` | Exact endpoint + horizon; optional indicator and survey-date window | `focus_expectations()` | None; use direct PostgREST or SDK |

## Flask convenience routes

| Route | Function | Purpose |
| --- | --- | --- |
| `GET /v1/catalog` | `catalog` | Discovery metadata |
| `GET /v1/tools` | `tools` | Tool descriptions |
| `GET /v1/health` | `health` | Process/database readiness |
| `GET /v1/coverage` | `coverage` | Dataset freshness and row coverage |
| `GET /v1/metric-coverage` | `metric_coverage` | Panel metric coverage |
| `GET /v1/quotes/<ticker>` | `quote_resource` | Latest quote |
| `GET /v1/quotes/<ticker>/history` | `quote_history` | Bounded quote history |
| `GET /v1/funds` | `funds_search` | Fund lookup |
| `GET /v1/funds/<cnpj>` | `fund_profile` | Fund metadata |
| `GET /v1/funds/<cnpj>/nav` | `fund_nav` | Fund NAV series |
| `GET /v1/panel` | `panel` | Metric panel |
| `GET /v1/lookup` | `lookup` | Identifier resolution |

## Agent discovery contract

Research prompts contain only the professional question. They do not include
expected datasets, joins, or answers. The agent should inspect the catalog,
read the relevant dataset docs and coverage metadata, resolve identifiers, then
decide whether the available grain and date ranges support an answer. Examples
are discoverability aids, not a dataset allow-list. Expected datasets, valid
joins, date rules, and reference results remain evaluator-private in
`evaluator-cases.json`.

## Maintenance and known gaps

- SQL-grant/OpenAPI drift fails offline tests in either direction.
- SDK argument/signature drift is checked for RPC methods; view access is
  intentionally generic and permits only API schema resources.
- The Flask adapter's smaller scope is intentional. Do not describe a missing
  Flask route as a missing public API if the PostgREST function/view, OpenAPI,
  and SDK contract are present.
- This is static contract coverage, not a live populated-warehouse freshness
  check. The local smoke uses empty tables; representative row semantics and
  source reconciliation need an authorized populated environment.
