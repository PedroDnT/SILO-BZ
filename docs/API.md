# `serve/` — the local adapter (this is **not** the public API)

> **If you are looking for the read contract, you are in the wrong file.**
>
> The public surface is **`POST /rest/v1/rpc/<name>`** and **`GET /rest/v1/<view>`**
> on Supabase PostgREST:
>
> ```
> https://zcjbtpxuhdekpwcxmepn.supabase.co/rest/v1/
> ```
>
> Its documentation is the published site — **[Conventions &
> limits](https://octo-98895abd.mintlify.site/api-docs/conventions)** is the single
> source of truth for auth tiers, row caps, null semantics and regime breaks, and
> **`POST /rpc/catalog`** is the same contract as JSON. Start at
> [llms.txt](https://octo-98895abd.mintlify.site/llms.txt) or
> [Quickstart](https://octo-98895abd.mintlify.site/api-docs/quickstart).
>
> **Nothing in this file is normative for a caller.** It documents `serve/app.py`,
> a read-only Flask adapter you can run on your own machine. It is not
> necessarily deployed anywhere, and its `/v1/*` routes, query-string arguments
> and `format=wide` envelope exist **only** there.

`api.catalog()` says the same thing in its `agent` field: prefer the `postgrest`
section; the `/v1/*` routes in `endpoints` are this adapter's.

## Why the adapter exists

The design premise, which the public API inherited: the main user is a
**researcher** doing correlation tests, factor models and cross-asset
relationships, mixing market prints with CVM fundamentals. They need a **panel**
— `(id, date, metric, value)` — not a quote widget. Analysis (corr, OLS, event
studies) is a _reduction_ of a panel, computed in a notebook. There is no
`POST /query` and no server-side `corr` on either surface; `api.catalog()` lists
those as `notebook_reducers`.

`serve/` predates the decision (2026-08-26) to expose schema `api` through
Supabase's own PostgREST. It survives for three things:

1. **Local development and notebooks** against a database you control, without a
   Supabase project or a network round trip.
2. **A shaped 404.** PostgREST has no adapter layer, so an unknown ticker and an
   empty window both return `200 []`. `serve/` distinguishes them (see
   [404 vs empty](#404-vs-empty)).
3. **A different envelope.** `format=wide` and `format=columnar` are chart- and
   correlation-shaped responses that PostgREST does not produce.

It is **not** an ingest trigger, and there is no ingest HTTP server anywhere in
this repository. Ingest is GitHub Actions cron plus `python -m src.pipeline.run_daily`
/ `run_backfill`.

## Layers

```
client  →  HTTP /v1/*   (serve/, bind 127.0.0.1 or a gateway)
              ↓  role silo_api: SELECT/EXECUTE on api.* only
         Postgres schema api     (views + functions)
              ↓  owner rights, not GRANT on landing tables
         public landing + dim_/fact_*     (ingest still writes here)
```

The deployed path skips the top box entirely: the browser or agent talks to
PostgREST as `anon` or `authenticated`, and the same schema `api` answers.

1. **`api` schema is the product.** English names, ticker/CNPJ keys, an explicit
   unadjusted flag, and automatic selection of each ticker's published BDI board.
   Clients never query `b3_cotahist`.
2. **HTTP is an adapter**, not a second database. Every handler is a single
   `SELECT` / `api.*()` call. No business logic that can invent a price.
3. **Do not turn on PostgREST for schema `public`.** Schema `api` is the whole
   public surface; landing tables are revoked from `anon` and `authenticated`, and
   `health.yml` asserts it on every run.
4. **Cache at the edge.** History whose `to` is in the past is immutable
   (`max-age=86400`). Latest quote is short (`max-age=300`). `serve/` also sends
   `X-Silo-Adjusted: false` so nobody assumes brapi-style split adjustment.

### 404 vs empty

On `serve/`, an unknown ticker or CNPJ is a `404`; a known ticker with no sessions
in the range is `200 { kind: "series", series: [] }`.

On PostgREST both are `200 []`, because there is no adapter to shape the error. A
caller that treats empty as 404 will silently mis-read a miss. Never a plausible
last-close fallback, on either surface.

## Point vs series

The same URL is a **point** until the caller asks for a window. Then it is a
**series** — dated observations at the grain actually stored (day for B3, month for
fund NAV). No invented weekly/monthly bars.

```
GET /v1/quotes/PETR4                         → one object (latest session)
GET /v1/quotes/PETR4?range=1y                → { kind: "series", series: [...] }
GET /v1/quotes/PETR4?from=2024-01-01&to=...  → same envelope
GET /v1/quotes/PETR4?range=1y&format=columnar
GET /v1/quotes/PETR4?range=1y&fields=close,volume
GET /v1/quotes/PETR4/history                 → alias (defaults to 1y)
GET /v1/funds/{cnpj}/nav                     → monthly series, same envelope
```

`range`: `5d` `1mo` `3mo` `6mo` `1y` `2y` `5y` `ytd` `max`.

Row envelope (default):

```json
{
  "ticker": "PETR4",
  "kind": "series",
  "grain": "day",
  "adjusted": false,
  "source": "b3_cotahist",
  "board": "02",
  "from": "2025-08-15",
  "to": "2026-08-14",
  "count": 248,
  "series": [
    {
      "date": "2025-08-15",
      "open": 41.1,
      "high": 41.5,
      "low": 40.9,
      "close": 41.2,
      "volume": 1.2e9,
      "trades": 40000
    }
  ]
}
```

Columnar (`format=columnar`) is for charts: `dates` plus one array per field,
aligned by index. Cap is 5000 points — over that is `400`, not a silent trim.

`format=wide` is the correlation input: `dates × columns` (`PETR4.close`,
`{cnpj}.delinquency`). Missing cells are JSON `null`; nothing is filled. **This
envelope exists only on `serve/`** — on PostgREST, `api.panel` returns long rows
and you pivot locally (the Python SDK's `panel(wide=True)` does it for you).

## Routes (v1) — adapter only

| Method | Path                                        | Postgres                                              |
| ------ | ------------------------------------------- | ----------------------------------------------------- |
| GET    | `/v1/catalog`                               | static metric map + constraints (no DB)               |
| GET    | `/v1/tools`                                 | OpenAI/AI-SDK tool specs pointing at these routes     |
| GET    | `/v1/health`                                | `SELECT 1 FROM api.quotes LIMIT 0`                    |
| GET    | `/v1/coverage`                              | `api.coverage()`                                      |
| GET    | `/v1/metric-coverage`                       | `api.metric_coverage()`                               |
| GET    | `/v1/panel?ids&metrics&freq&from&to`        | `api.panel(...)` long or wide                         |
| GET    | `/v1/lookup?q=`                             | `api.lookup(...)`                                     |
| GET    | `/v1/quotes/{ticker}`                       | `api.quote_latest` or `api.quote_history` if windowed |
| GET    | `/v1/quotes/{ticker}/history?from&to&range` | `api.quote_history(...)`                              |
| GET    | `/v1/funds?q&type&limit`                    | `api.search_funds(...)`                               |
| GET    | `/v1/funds/{cnpj}`                          | `api.fund_profile(cnpj)`                              |
| GET    | `/v1/funds/{cnpj}/nav?from&to&range`        | `api.fund_nav(...)`                                   |

CNPJ in the path may include punctuation (`12.345.678/0001-90`); it is stripped to
14 digits. Tickers are uppercased.

The adapter wraps a **subset** of schema `api`. Everything else — the typed cash
views, options, termo, holdings, debentures, FIDC concentration, ANBIMA classes,
company financials, and the B3 lending and investor-flow views — has no `/v1`
twin and is reachable only over PostgREST. Read those on the published site.

### The B3 lending and investor-flow views

Five public views — `short_interest`, `short_interest_by_sector`,
`investor_flow`, `lending_trades` and `lending_participants` — have no `/v1`
twin either. They are documented on the published site: [Securities
lending](https://octo-98895abd.mintlify.site/api-docs/lending) and [Investor
flow](https://octo-98895abd.mintlify.site/api-docs/flows), with first-class SDK
methods since catalog v27.

They were parked in this file while nothing else covered them. That is no longer
true, so the caveats live with the pages that own them rather than here.

## Run

```bash
bash scripts/apply_analytical.sh    # creates api.* after ingest
python -m serve.app                 # 127.0.0.1:8080
curl -s localhost:8080/v1/quotes/PETR4
```

`serve/` needs `POSTGRES_URL` or `SILO_API_DATABASE_URL`. If it is ever hosted,
point `SILO_API_DATABASE_URL` at a login member of the **read-only** `silo_api`
role (created by `12_grants_and_rls.sql`; see the operator comment there).
Transaction pooler is correct here; ingest keeps the session pooler / direct URL.

---

## Operator notes on the deployed surface

Caller-facing versions of everything below live on
[Conventions & limits](https://octo-98895abd.mintlify.site/api-docs/conventions#row-caps).
What is kept here is the operator half: the decision, the measurement, and the
levers that are a dashboard setting rather than a code change.

### Enabling it on a fresh project

Supabase Dashboard → Settings → API → add `api` to **Exposed schemas**. The
generic form is `https://<project-ref>.supabase.co/rest/v1/`; views are read as
`/rest/v1/quotes?select=...`, functions called as `POST /rest/v1/rpc/<name>` with
named arguments in the JSON body. The grants in `19_api_contract.sql`
(`anon`/`authenticated`: `USAGE` on schema `api`, `SELECT` on the api views,
`EXECUTE` on the api functions — and nothing on the `public` landing tables) are
exactly the surface this exposes.

### 1. PostgREST caps every response at 1,000 rows (`db-max-rows`)

Found by an independent audit of the live deployment (2026-08-27) and reproduced
against production on 2026-08-28. The measurement that forced the current design:

```
POST /rest/v1/rpc/panel  p_ids=[PETR4] p_metrics=[close] p_freq=day p_to=2026-08-26
  p_from=2019-01-01  -> 1000 rows, 2019-01-02 .. 2023-01-09   TRUNCATED, HTTP 200
  p_from=2022-01-01  -> 1000 rows, 2022-01-03 .. 2026-01-02   TRUNCATED, HTTP 200
  p_from=2024-01-01  ->  664 rows, 2024-01-02 .. 2026-08-26   complete
```

A caller charting "PETR4 since 2019" got a plausible line that simply stopped in
January 2023.

The in-function caps used to `LIMIT` at cap+1 (panel 100001, series 5001) so a
caller could detect truncation by counting one extra row; behind a 1,000-row
ceiling those sentinels could never fire, so the advice to "check for exactly
100001 rows" detected nothing. Both sentinels are gone — panel in catalog v24, the
series and statement functions in v25/v26.

**Current behaviour, and the correction to what this file used to say:** every
set-returning function now fetches one page plus one row and **raises `22023`**
rather than returning a trimmed result. This file previously stated that "a panel
cannot be paged" — that stopped being true two catalog versions ago. **`panel`,
`quote_history` and `fund_nav` page with a `p_after` cursor**; the others
(`option_history`, `termo_history`, `financials`, `company_financials`,
`anbima_classes`, `inflation`, `inflation_items`) have no cursor and ask you to
narrow the window. `fund_nav` also
requires `p_entity_type` to page, because its cursor is a bare period and 385
CNPJs file under two families in the same month.

`Range` paging genuinely does not work on RPC — `Range: 1000-1999` on
`/rest/v1/rpc/panel` returns the _same first page_, verified, same
`Content-Range: 0-999/1906`. `Range` / `limit` / `offset` remain the **view**
cursor, and `GET` views on schema `api` still truncate silently, so
`Content-Range` is still the only signal there.

Raising `db-max-rows` (Dashboard → Settings → API → Max rows) is an operator
decision, not a code change.

### 2. The `statement_timeout` that applies is `anon`'s 3s, not `silo_api`'s 15s

`12_grants_and_rls.sql` sets 15s on `silo_api` — but that role serves only this
local adapter. The deployed PostgREST surface runs as `anon`, which carries
Supabase's default 3s (`authenticated` gets 8s). Anything over ~3s returns
`57014 canceling statement due to statement timeout`.

Cold calls are the practical consequence: on a warehouse this size the first call
after idle can take 16–43s and is cancelled at the ceiling, so a first-time caller
meets an API that looks comprehensively down. Warm, the same calls return in
0.3–1.9s. Warming the endpoints, or raising the `anon` timeout, is an operator
decision.

## Why not the alternatives

| Approach                                            | Why not as the user API                                                                  |
| --------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| Raw PostgREST on `public`                           | Leaks `cvm_ingest_log`, options tape, Portuguese columns; users must learn the warehouse |
| `supabase.rpc` only, undocumented                   | Fine as a power-user escape hatch; terrible onboarding without the pages and the catalog |
| Revive the old ingest Flask (`app.py` / `src/api/`) | No auth, ingest triggers, localhost-only — mixing operators and readers                  |
| Rebuilding FastAPI microservices                    | Already deleted; duplicates the warehouse                                                |

Roadmap for how "ingested" became "a researcher pulls a panel":
[docs/planning/SERVING.md](planning/SERVING.md).
