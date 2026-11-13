# API documentation reference map

Inspected 2026-11-13 (Brasília). Owner request tracked in #1150.

Sources: [complete page index](https://docs.financialdatasets.ai/llms.txt),
[introduction](https://docs.financialdatasets.ai/introduction),
[prices](https://docs.financialdatasets.ai/api/prices/historical),
[income statements](https://docs.financialdatasets.ai/api/financials/income-statements),
[coverage](https://docs.financialdatasets.ai/market-coverage).
Exa extracted these pages; browser inspection confirmed the prices page's Try it,
editable query fields, authorization field, language selection and response tabs.
No authenticated Financial Datasets request was executed.

| Reference capability | SILO equivalent | Decision |
| --- | --- | --- |
| Task-specific endpoint pages | 74 kinds within 14 v2 resources | Generate 74 named pages and request-schema projections; retain real HTTP paths |
| Historical prices and snapshot | prices history/latest/session/index/forward | Separate navigation; latest is a closing price, not realtime |
| Income, balance, cash flow, as-reported | statements income/balance/cashflow/all/versions/headline | Separate pages; preserve accounting and filing semantics |
| Tickers and company lookup | search any/company/universe | Expose discovery before data reads |
| Holdings and ownership | funds holdings/debentures/properties; positioning | Partial conceptual overlap, not US institutional or insider ownership parity |
| Inflation, rates and macro | macro, curves and derivatives | Expose all existing variants; geography and methodology differ |
| Filing discovery | events company/fund/restatements/restatement_diff | Metadata and existing diffs; do not advertise arbitrary full-text document extraction |
| Screener | screens fixed research screens | Not an arbitrary financial-ratio screener |
| Try it, editable params, generated code | Mintlify OpenAPI playground | Prefill verified request examples, expand optional inputs, offer cURL/Python/JavaScript |
| Coverage and provenance | coverage freshness/metrics/catalog and response metadata | Surface through operation navigation; no copied coverage counts |
| Agent onboarding | v2 MCP, skill.md, llms.txt | Keep existing connection guide and add operation directory |
| IPOs, activist stakes, beneficial ownership | No equivalent v2 resource | Coverage gap; no fabricated equivalent |
| GPU rental prices, US labor and GDP product bundles | Generic Brazilian macro series only | No equivalent dataset or coverage claim |
| News and market-news feeds | No corresponding v2 resource | Product/data gap; requires a separate source and delivery contract |
| Webhooks and event subscriptions | No corresponding v2 resource | Requires delivery infrastructure, retry and signature contracts |
| Realtime prices | Closing prices and observed market history | Requires a realtime feed; page layout cannot provide this |
| Self-service agent billing and x402 | Issued keys and user sessions | No payment/onboarding equivalent implemented |
| US-specific insider, congressional and institutional filings | No equivalent v2 resource | Different coverage domain; no invented Brazilian substitute |
| Earnings guidance, company KPIs, normalized metrics and segments | Not equivalent to current statements API | Requires field coverage and accounting contracts before implementation |

The live reference index contains more products than the previous comparison.
This map covers its page families, not commercial API conformance or data accuracy.
This delivery reproduces discovery and native request interactivity. Remaining
data and service gaps above stay explicit; they are not hidden behind empty endpoints.

## Generation and acceptance

Run `python -m scripts.gen_v2_operation_docs` after the base OpenAPI generator.
The projection specs are documentation-only subsets: same server, route, method,
security and response contract; one kind pinned per page. No new runtime endpoint.
Offline checks reject drift and navigation omissions. Browser checks must verify
kind prefill, code sample changes, actual response, and mobile layout before release.

## Verification

- 74 offline registry/OpenAPI tests pass, including drift, preserved routes/security and kind-specific examples.
- Mintlify full build validation passes. An isolated copy containing only published docs has no broken links.
- Desktop and 390px mobile: the latest-price playground selects `latest`; editing id changes the generated cURL; Send returns HTTP 200, one PETR4 row, `meta.kind: latest` and `meta.tier: anonymous`.
- Direct browser CORS preflight accepts GET and Authorization. No credential was entered in the browser.
- Public production publication and all-operation live execution remain unverified. No paid evaluation was run.
- The native response schema still has generic row types for many resources. Dataset-specific response contracts remain a documented gap; generated placeholders are not observed data.

## Existing v1 functions without a v2 registry mapping

Static comparison against the committed v1 OpenAPI also found five data functions
not named in the v2 registry: `anbima_classes`, `class_return_distribution`,
`credit_market_history`, `credit_implied_rate`, and `portfolio_credit_returns`.
This establishes a contract migration gap, not current production availability.
`my_tier` and `rate_hit` are internal authentication/rate-limit helpers, not missing
user data operations. The five functions need bounded request/pagination adapters
and live coverage checks before being advertised as v2 operations.
