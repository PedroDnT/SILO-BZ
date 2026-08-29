# Silo API — how we serve the data

The main user is a **researcher**: correlation tests, factor models, and
relationships across asset classes, mixing market prints with CVM fundamentals.
They need a **panel** — `(id, date, metric, value)` — not a quote widget.

Ingest stays in this repo; the contract is schema `api` plus `serve/`.

## Researcher workflow

```
0. GET /v1/catalog                             → metrics, grains, constraints (agents: cache this)
1. GET /v1/funds?type=fidc&limit=200           → pick vehicles (search_funds; to enumerate
                                                 a whole family, page the api.funds VIEW on
                                                 PostgREST — limit/offset work on views only)
2. GET /v1/lookup?q=PETR4                     → ticker / ISIN (no invented CNPJ match)
3. GET /v1/panel?ids=PETR4,VALE3,<cnpj>
     &metrics=close,close_return,nav,delinquency
     &freq=month&from=2019-01-01&format=wide
4. In the notebook: corrcoef on the matrix, pairwise complete (nulls stay null)
```

There is no `POST /v1/query` and no server-side `corr`/`rank`. The catalog lists
those as `notebook_reducers`. Agents load `GET /v1/tools` (OpenAI-style specs)
and call the same HTTP routes. Roadmap: [docs/planning/SERVING.md](planning/SERVING.md).

`format=wide` is the correlation input: `dates × columns` (`PETR4.close`,
`{cnpj}.delinquency`). Missing cells are JSON `null`. We never ffill, interpolate,
or carry last-observation. Mixing daily equity with monthly NAV on a **daily**
calendar would require filling — that is your notebook. Mix them on `freq=month`
(equity close = last session in the month, a real print).

`close_return` is `p_t / p_{t-1} - 1` from stored **unadjusted** closes. A
2:1 split reports roughly −50% — the arithmetic is faithful to B3's published
prices, not a total return. Daily: previous session. Monthly: previous
calendar month, else null (a missing month does not become a two-month
return).

Ticker↔listed-company (`cia_*`) join is **not** invented here. Lookup returns
CIA by CNPJ/`cd_cvm`/name separately until that match exists.

## Who else

| Person             | Job                                  | Call                        |
| ------------------ | ------------------------------------ | --------------------------- |
| Researcher         | Panel across equity + funds + credit | `/v1/panel`                 |
| Chart / app        | One ticker series                    | `/v1/quotes/PETR4?range=1y` |
| Fund analyst       | One vehicle NAV                      | `/v1/funds/{cnpj}/nav`      |
| Evidence dashboard | Already on `dim_*` / `fact_*`        | unchanged                   |

Ingest is GitHub Actions cron and the pipeline CLI (`run_daily` /
`run_backfill`). There is no ingest HTTP server. `serve/` is read-only.

## Layers

```
client  →  HTTPS /v1/*   (serve/, bind 127.0.0.1 or a gateway)
              ↓  role silo_api: SELECT/EXECUTE on api.* only
         Postgres schema api     (views + functions)
              ↓  owner rights, not GRANT on landing tables
         public landing + dim_/fact_*     (ingest still writes here)
```

1. **`api` schema is the product.** English names, ticker/CNPJ keys, unadjusted
   flag, and automatic selection of each ticker's published BDI board. Clients
   should not query `b3_cotahist`.
2. **HTTP is an adapter**, not a second database. Every handler is a single
   `SELECT` / `api.*()` call. No business logic that can invent a price.
3. **Do not turn on PostgREST on `public`.** Today some landing tables are
   GRANTed to `anon`. The end state is: expose schema `api` only, revoke `anon`
   from `cvm_*` / `b3_cotahist` / `cvm_ingest_log`. Existing SECURITY INVOKER
   RPCs in `public` still need those grants until they are wrapped — wrap first,
   then revoke.
4. **Cache at the edge.** History whose `to` is in the past is immutable
   (`max-age=86400`). Latest quote is short (`max-age=300`). Header
   `X-Silo-Adjusted: false` so nobody assumes brapi-style split adjustment.
5. **404 vs empty.** On `serve/`, unknown ticker/CNPJ → 404. Known ticker,
   no sessions in range (holiday window) → `200 { kind: "series", series: [] }`.
   On PostgREST (`api.*`) there is no adapter to shape the error: unknown
   ticker and empty window both return `200 []`. A caller that treats empty
   as 404 will silently mis-read a miss. Never a plausible last-close
   fallback.

## Point vs series

The same URL is a **point** until the caller asks for a window. Then it is a
**series** — dated observations at the grain we actually store (day for B3,
month for fund NAV). We do not invent weekly/monthly bars.

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

## Routes (v1)

| Method | Path                                        | Postgres                                              |
| ------ | ------------------------------------------- | ----------------------------------------------------- |
| GET    | `/v1/catalog`                               | static metric map + constraints (no DB)               |
| GET    | `/v1/tools`                                 | OpenAI/AI-SDK tool specs pointing at these routes     |
| GET    | `/v1/health`                                | `SELECT 1 FROM api.quotes LIMIT 0`                    |
| GET    | `/v1/coverage`                              | `api.coverage()`                                      |
| GET    | `/v1/panel?ids&metrics&freq&from&to`        | `api.panel(...)` long or wide                         |
| GET    | `/v1/lookup?q=`                             | `api.lookup(...)`                                     |
| GET    | `/v1/quotes/{ticker}`                       | `api.quote_latest` or `api.quote_history` if windowed |
| GET    | `/v1/quotes/{ticker}/history?from&to&range` | `api.quote_history(...)`                              |
| GET    | `/v1/funds?q&type&limit`                    | `api.search_funds(...)`                               |
| GET    | `/v1/funds/{cnpj}`                          | `api.fund_profile(cnpj)`                              |
| GET    | `/v1/funds/{cnpj}/nav?from&to&range`        | `api.fund_nav(...)`                                   |

PostgREST-only resources (Supabase Data API, no `/v1` twin — `serve/`'s catalog lists
them under a separate `postgrest` section):

| Method | Resource                                                                              | Backing                                                                                                           |
| ------ | ------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| GET    | `/rest/v1/equities` (+ `bdrs`, `units`, `fund_quotas`, `cash_securities`)             | typed cash views, `lot` grain; `equities` adds `share_class`/`governance_segment`, `fund_quotas` adds `fund_type` |
| GET    | `/rest/v1/auctions`                                                                   | tpmerc 017 auction prints                                                                                         |
| POST   | `/rest/v1/rpc/option_chain` / `option_history` / `option_exercises` / `termo_history` | option/termo functions; option rows carry `underlying_ticker`                                                     |

CNPJ in the path may include punctuation (`12.345.678/0001-90`); it is stripped
to 14 digits. Tickers are uppercased.

Later: CIA line items and BACEN macro as extra `api.panel` metrics once identifiers
are matched — same long grain, not a new API style.

## Why not the alternatives

| Approach                                            | Why not as the user API                                                                  |
| --------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| Raw PostgREST on `public`                           | Leaks `cvm_ingest_log`, options tape, Portuguese columns; users must learn the warehouse |
| supabase.rpc only                                   | Fine as a power-user escape hatch; terrible onboarding vs `/v1/quotes/PETR4`             |
| Revive the old ingest Flask (`app.py` / `src/api/`) | No auth, ingest triggers, localhost-only — mixing operators and readers                  |
| Rebuilding FastAPI microservices                    | Already deleted; duplicates the warehouse                                                |

## Run

```bash
bash scripts/apply_analytical.sh    # creates api.* after ingest
python -m serve.app                 # 127.0.0.1:8080
curl -s localhost:8080/v1/quotes/PETR4
```

Production: the public path is **Supabase-native** (decided 2026-08-26) —
schema `api` is exposed through the Supabase Data API (PostgREST), so there is
no gateway, no TLS to terminate, and no serve/ host to run. The live base URL is
`https://zcjbtpxuhdekpwcxmepn.supabase.co/rest/v1/` with the anon key. To enable
it on a fresh project: Supabase Dashboard → Settings → API → add `api` to
**Exposed schemas**. The generic form is `https://<project-ref>.supabase.co/rest/v1/`;
views are read as `/rest/v1/quotes?select=...`, functions are called as
`POST /rest/v1/rpc/<name>` with named arguments in the JSON body. The grants
in `19_api_contract.sql` (anon/authenticated: `USAGE` on schema `api`,
`SELECT` on the api views, `EXECUTE` on the api functions — and nothing on
the `public` landing tables) are exactly the surface this exposes.

### Two platform limits bound every call, and neither is in the SQL

Both were found by an independent audit of the live deployment (2026-08-27) and
reproduced against production on 2026-08-28. Both surprise callers, so read them
before writing a client.

**1. PostgREST truncates every response at 1000 rows, oldest first, silently.**
This is `db-max-rows` on the Supabase project — not the in-function caps, which
LIMIT at cap+1 (panel 100001, series 5001). Behind a 1000-row ceiling those
sentinels can never fire, so the old advice to "check for exactly 100001 rows"
detected nothing. Measured:

```
POST /rest/v1/rpc/panel  p_ids=[PETR4] p_metrics=[close] p_freq=day p_to=2026-08-26
  p_from=2019-01-01  -> 1000 rows, 2019-01-02 .. 2023-01-09   TRUNCATED, HTTP 200
  p_from=2022-01-01  -> 1000 rows, 2022-01-03 .. 2026-01-02   TRUNCATED, HTTP 200
  p_from=2024-01-01  ->  664 rows, 2024-01-02 .. 2026-08-26   complete
```

A caller charting "PETR4 since 2019" gets a plausible line that simply stops in
January 2023. **The only signal is the `Content-Range` response header**:
`0-999/*` means truncated, and adding `Prefer: count=exact` turns it into
`0-999/1906` so you also learn the true total. A range ending below 999 is
complete.

**`Range` paging does not work on RPC.** Sending `Range: 1000-1999` to
`/rest/v1/rpc/panel` returns the _same first page_ again — verified, same
`Content-Range: 0-999/1906`. So a panel cannot be paged: narrow `p_from`/`p_to`,
ids, or metrics until the header comes back under 1000. `GET` views on the
`api` schema do page with `Range` normally.

Raising `db-max-rows` (Dashboard → Settings → API → Max rows) is an operator
decision, not a code change.

**2. The `statement_timeout` that applies is `anon`'s 3s, not `silo_api`'s 15s.**
`12_grants_and_rls.sql` sets 15s on `silo_api` — but that role serves only the
local `serve/` adapter. The deployed PostgREST surface runs as `anon`, which
carries Supabase's default 3s (`authenticated` gets 8s). Anything over ~3s
returns `57014 canceling statement due to statement timeout`.

Cold calls are the practical consequence: on a warehouse this size the first
call after idle can take 16–43s and is cancelled at the ceiling, so a
first-time caller meets an API that looks comprehensively down. Warm, the same
calls return in 0.3–1.9s. Warming the endpoints, or raising the `anon` timeout,
is an operator decision.

`serve/` remains the local adapter for notebooks and development. If it is
ever hosted, point `SILO_API_DATABASE_URL` at a login member of the
**read-only** `silo_api` role (created by `12_grants_and_rls.sql`; see the
operator comment there). Transaction pooler is correct here; ingest keeps
the session pooler / direct URL.
