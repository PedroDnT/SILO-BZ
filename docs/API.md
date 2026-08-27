# Silo API — how we serve the data

The main user is a **researcher**: correlation tests, factor models, and
relationships across asset classes, mixing market prints with CVM fundamentals.
They need a **panel** — `(id, date, metric, value)` — not a quote widget.

Ingest stays in this repo; the contract is schema `api` plus `serve/`.

## Researcher workflow

```
0. GET /v1/catalog                             → metrics, grains, constraints (agents: cache this)
1. GET /v1/universe?asset_class=fidc          → pick vehicles
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
| GET    | `/v1/universe?asset_class&limit`            | `api.universe(...)`                                   |
| GET    | `/v1/lookup?q=`                             | `api.lookup(...)`                                     |
| GET    | `/v1/quotes/{ticker}`                       | `api.quote_latest` or `api.quote_history` if windowed |
| GET    | `/v1/quotes/{ticker}/history?from&to&range` | `api.quote_history(...)`                              |
| GET    | `/v1/funds?q&type&limit`                    | `api.search_funds(...)`                               |
| GET    | `/v1/funds/{cnpj}`                          | `api.fund_profile(cnpj)`                              |
| GET    | `/v1/funds/{cnpj}/nav?from&to&range`        | `api.fund_nav(...)`                                   |

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
the `public` landing tables) are exactly the surface this exposes; the
in-function row caps and Supabase's platform `statement_timeout` on the API
roles bound each call.

`serve/` remains the local adapter for notebooks and development. If it is
ever hosted, point `SILO_API_DATABASE_URL` at a login member of the
**read-only** `silo_api` role (created by `12_grants_and_rls.sql`; see the
operator comment there). Transaction pooler is correct here; ingest keeps
the session pooler / direct URL.
