# Silo API — how we serve the data

Users do not want `cvm_fi_diario` or PostgREST filters. They want **PETR4’s
close**, **this fund’s NAV**, and **whether the numbers are fresh**. Ingest
stays in this repo; the public contract is schema `api` plus a thin HTTP
adapter in `serve/`.

## Who it is for

| Person | Job | Call |
|---|---|---|
| App / quant (brapi-shaped) | Last price and history for a ticker | `GET /v1/quotes/PETR4` |
| Fund analyst | Find a vehicle, then its NAV / flows | `GET /v1/funds?q=alocação` then `/v1/funds/{cnpj}/nav` |
| Agent / LLM | Stable English JSON, provenance, no fake zeros | same routes + `source`, `adjusted: false` |
| Evidence dashboard | Already on `dim_*` / `fact_*` | unchanged — do not force a migration |

The localhost Flask control plane (`app.py`) stays **operator-only** (trigger
ingest). It is not this API.

## Layers

```
client  →  HTTPS /v1/*   (serve/, bind 127.0.0.1 or a gateway)
              ↓  role silo_api: SELECT/EXECUTE on api.* only
         Postgres schema api     (views + functions)
              ↓  owner rights, not GRANT on landing tables
         public landing + dim_/fact_*     (ingest still writes here)
```

1. **`api` schema is the product.** English names, ticker/CNPJ keys, unadjusted
   flag, default cash board `02`. Clients should not query `b3_cotahist`.
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
5. **404 vs empty.** Unknown ticker/CNPJ → 404. Known ticker, no sessions in
   range (holiday window) → `200 { data: [] }`. Never a plausible last-close
   fallback.

## Routes (v1)

| Method | Path | Postgres |
|---|---|---|
| GET | `/v1/health` | `SELECT 1 FROM api.quotes LIMIT 0` |
| GET | `/v1/coverage` | `api.coverage()` |
| GET | `/v1/quotes/{ticker}` | `api.quote_latest(ticker, board)` |
| GET | `/v1/quotes/{ticker}/history?from&to&board` | `api.quote_history(...)` |
| GET | `/v1/funds?q&type&limit` | `api.search_funds(...)` |
| GET | `/v1/funds/{cnpj}` | `api.fund_profile(cnpj)` |
| GET | `/v1/funds/{cnpj}/nav?from&to&type` | `api.fund_nav(...)` |

CNPJ in the path may include punctuation (`12.345.678/0001-90`); it is stripped
to 14 digits. Tickers are uppercased.

Later (same contract, more routes): FIDC delinquency, CIA financials, BACEN
macro — each as `api.*` first, HTTP second.

## Why not the alternatives

| Approach | Why not as the user API |
|---|---|
| Raw PostgREST on `public` | Leaks `cvm_ingest_log`, options tape, Portuguese columns; users must learn the warehouse |
| supabase.rpc only | Fine as a power-user escape hatch; terrible onboarding vs `/v1/quotes/PETR4` |
| Extend the Flask control plane | No auth, ingest triggers, localhost-only — mixing operators and readers |
| Rebuilding FastAPI microservices | Already deleted; duplicates the warehouse |

## Run

```bash
bash scripts/apply_analytical.sh    # creates api.* after ingest
python -m serve.app                 # 127.0.0.1:8080
curl -s localhost:8080/v1/quotes/PETR4
```

Production: put a Vercel / any HTTPS proxy in front, point
`SILO_API_DATABASE_URL` at a **read-only** role (`GRANT USAGE ON SCHEMA api`,
`SELECT` on api views, `EXECUTE` on api functions, nothing else). Transaction
pooler is correct here; ingest keeps the session pooler / direct URL.
