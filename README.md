# Brazilian Financial Data — industry accountability pipeline

Headless ingestion pipeline for Brazilian public financial data. The goal is to maintain
continuous, verifiable accountability of the fund industry — tracking NAV, delinquency,
tranche performance, and structural health of every entity type CVM publishes.

Data sources:

- **CVM** (Comissão de Valores Mobiliários) — fund disclosures: FI, FIDC, FIP, FIAGRO, FII, SECURIT.
- **BACEN** (Banco Central do Brasil) — SGS time series (SELIC, CDI, IPCA, IGP-M), PTAX exchange rates,
  Expectativas (Focus bulletin).

Data is downloaded, parsed, validated, and upserted into a Supabase Postgres database via psycopg2.
There is no public API — downstream consumers query Supabase directly.

A small **local Flask control plane** (`app.py` + `src/api/`) wraps the pipeline so
operators can trigger partial fills one (entity, doc_type, year, month) slice at a
time and watch jobs progress via a polling endpoint. See
[Flask control plane](#flask-control-plane-local).

> A previous version exposed three FastAPI services + a gateway + a Mintlify docs site.
> Those layers and a Solana "Delos Oracle" experiment were removed in the consolidation;
> only fetch/parse/store remains. The Flask app here is **localhost-only** — it does
> not reintroduce a public API surface.

## CVM ZIP structure (important)

Each CVM entity distributes data as ZIP files containing multiple CSVs. The pipeline
only reads specific CSVs from each ZIP — the rest contain tranche-level and structural
data not yet ingested:

| Entity                | CSVs per ZIP                | Pipeline reads                                      | Pending (in plan)                   |
| --------------------- | --------------------------- | --------------------------------------------------- | ----------------------------------- |
| FI                    | 1 CSV                       | inf_diario (NAV, flows)                             | —                                   |
| FIDC                  | **17 CSVs** (tab_I–tab_XIV) | tab_IV (fund-level NAV)                             | tab_X (tranches), tab_VI (aging)    |
| FII                   | 3 CSVs                      | geral, ativo_passivo, **complemento** (NAV + yield) | —                                   |
| SECURIT (CRA/CRI/OTS) | **8 CSVs**                  | ativo_passivo (emissão totals)                      | classe (series status), fluxo_caixa |
| FIP                   | 1 CSV                       | inf_quadrimestral (PL)                              | —                                   |
| FIAGRO                | 1 CSV                       | mensal (PL) — available from May 2025               | —                                   |

The tranche and series-level ingestion is the subject of Phases 1–2 in `docs/pipeline-plan.md`.

## Pipeline stages

```
  ┌───── FETCH ─────┐    ┌───── PARSE ────┐    ┌───── STORE ────┐
  │ src/fetchers/   │ →  │ src/parsers/   │ →  │ src/store/     │
  │  cvm_fetcher    │    │  validation    │    │  pg_client.py  │
  │  bacen_fetcher  │    │  (CVM zip→csv  │    │  schema.sql    │
  │                 │    │   and BACEN df │    │                │
  │                 │    │   normalization│    │                │
  │                 │    │   live in the  │    │                │
  │                 │    │   fetchers)    │    │                │
  └─────────────────┘    └────────────────┘    └────────────────┘
                                                      ▲
                          ┌───── ORCHESTRATE ──────────┘
                          │ src/pipeline/
                          │   cvm_pipeline.CVMIngestor
                          │   bacen_pipeline.BacenIngestor
                          │   run_backfill.py  (one-shot, all years)
                          │   run_daily.py     (cron, current month + 7-day window)
                          └─────────────────────────────────────
```

| Package         | Role                                                                                                                                                                                                                 | Key modules                                                                             |
| --------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| `src/fetchers/` | **FETCH** — HTTP/SDK calls only. CVM downloads ZIP/CSV from `dados.cvm.gov.br` with retry, DNS rotation, and on-disk cache. BACEN wraps `python-bcb`.                                                                | `cvm_fetcher.CVMFetcher`, `cvm_config.DatasetConfig`, `bacen_fetcher.BacenClient`       |
| `src/parsers/`  | **PARSE** — shared field/CNPJ/date validation. CVM CSV extraction is co-located with `CVMFetcher.fetch()` because it needs the URL/filename context. BACEN DataFrame normalization is co-located with `BacenClient`. | `validation.DataValidator`                                                              |
| `src/store/`    | **STORE** — psycopg2 Supabase client and chunked upserts; canonical schema.                                                                                                                                              | `pg_client.upsert_rows`, `pg_client.get_pg_client`, `schema.sql`                        |
| `src/pipeline/` | **ORCHESTRATE** — wires the three stages, writes audit log rows, runs daily/backfill.                                                                                                                                | `cvm_pipeline.CVMIngestor`, `bacen_pipeline.BacenIngestor`, `run_backfill`, `run_daily` |

## Repository layout

```text
.
├── src/
│   ├── fetchers/
│   │   ├── cvm_fetcher.py      # CVMFetcher.fetch(entity, doc_type, year, month)
│   │   ├── cvm_config.py       # URL templates + dataset configs (entity × doc_type matrix)
│   │   └── bacen_fetcher.py    # BacenClient (SGS/PTAX/Expectativas/TaxaJuros)
│   ├── parsers/
│   │   ├── validation.py       # CNPJ / date / numeric / record validators
│   │   └── field_maps/         # Per-dataset typed column → CSV header mappings
│   ├── store/
│   │   ├── pg_client.py        # get_pg_client(), upsert_rows() — psycopg2/Supabase
│   │   └── schema.sql          # canonical CVM + BACEN schema (tables + audit log)
│   ├── pipeline/
│   │   ├── cvm_pipeline.py     # CVMIngestor — orchestrates fetch+store for CVM
│   │   ├── bacen_pipeline.py   # BacenIngestor — orchestrates fetch+store for BACEN
│   │   ├── run_backfill.py     # CLI: full historical backfill
│   │   └── run_daily.py        # CLI: incremental daily update
│   └── api/                    # Flask control plane (local-only)
│       ├── __init__.py         # create_app() factory
│       ├── routes.py           # HTTP endpoints (ingest, status, jobs, verify)
│       ├── jobs.py             # in-process job registry (UUID → state)
│       ├── dispatch.py         # (entity, doc_type) → ingestor method
│       └── hooks.py            # post-job error classifier + inefficiency detector
├── app.py                      # Flask entry point — `flask --app app run`
├── tests/                      # offline pytest suite
├── scripts/
│   ├── seed_local_db.py        # Fetch real CVM data → local Postgres for offline testing
│   ├── run_analysis_local.py   # Run 11 verification queries against local DB
│   ├── verify_pipeline.py      # Run verification queries against live Supabase DB
│   ├── analysis_queries.sql    # 11 SQL queries: data presence, null rates, business metrics
│   └── explore_cvm_output.py   # Utility for inspecting raw CVM ZIP/CSV structure
├── docs/
│   ├── pipeline-plan.md        # Master plan: data inventory, accountability rules, execution phases
│   └── planning/               # Workstream tracker, architecture conventions, changelog
├── .github/workflows/
│   └── daily_ingest.yml        # cron @ 06:00 UTC + workflow_dispatch
├── requirements.txt
└── .env.example
```

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in POSTGRES_URL (Supabase connection string)

# 1. Apply schema (one-time, against your Supabase Postgres)
psql "$POSTGRES_URL" -f src/store/schema.sql

# 2. Run an incremental update
python -m src.pipeline.run_daily

# 3. Run a one-shot historical backfill (e.g. 2019 onward)
python -m src.pipeline.run_backfill --start-year 2019

# 4. Verify the pipeline (local DuckDB, ~2 min, skips FI inf_diario)
python scripts/seed_local_db.py --skip-fi
python scripts/run_analysis_local.py

# 5. Verify against live Supabase DB
python scripts/verify_pipeline.py
```

## Flask control plane (local)

The Flask app exposes each `CVMIngestor.ingest_*` method as a background job, so
backfill work can proceed one slice at a time instead of a single all-or-nothing
run. Bind it to `127.0.0.1`; there is no auth.

```bash
flask --app app run                # or: python app.py
```

It needs `POSTGRES_URL` set to the Supabase connection string. The pipeline writes to
16 tables via psycopg2 direct connection — no PostgREST or RLS involved.

### Endpoint reference

| Method | Path                | Body / Query                                        | Purpose                                                           |
| ------ | ------------------- | --------------------------------------------------- | ----------------------------------------------------------------- |
| GET    | `/healthz`          | —                                                   | Liveness + Supabase DB reachability                                   |
| GET    | `/api/status`       | —                                                   | Row counts per table + last 5 entries in `cvm_ingest_log`         |
| GET    | `/api/dispatch`     | —                                                   | List every valid `(entity, doc_type)` pair                        |
| POST   | `/api/ingest`       | `{entity, doc_type, year, month?}`                  | Fire one slice. Returns `{job_id}`                                |
| POST   | `/api/ingest/range` | `{entity, doc_type, year_start, year_end, months?}` | Spawn N sequential child jobs                                     |
| POST   | `/api/daily`        | —                                                   | Run `CVMIngestor.daily_update()` as one background job            |
| GET    | `/api/jobs`         | `?limit=50`                                         | List recent jobs, newest first                                    |
| GET    | `/api/jobs/<id>`    | —                                                   | Full job state: status, rows, error, warnings, children           |
| POST   | `/api/verify`       | —                                                   | Run the quality-gate subset of `verify_pipeline.py` synchronously |

`month` is required for monthly conventions (`fi`, `fidc`, `fiagro mensal`).
Yearly conventions (`fii`, `fip`, `securit *_classe / *_fluxo / dfin_*`) take only `year`.

### Example: drive the remaining FIDC backfill

```bash
# 1. start the server
flask --app app run

# 2. fill one month at a time and watch it
curl -XPOST localhost:5000/api/ingest \
    -H 'content-type: application/json' \
    -d '{"entity":"fidc","doc_type":"tranche","year":2024,"month":5}'
# → {"job_id":"abcd-...","status":"queued","table":"cvm_fidc_tranche"}

curl localhost:5000/api/jobs/abcd-...
# → {... "status":"done","rows_inserted":12345,"warnings":[]}

# 3. when you're confident, batch a year range
curl -XPOST localhost:5000/api/ingest/range \
    -H 'content-type: application/json' \
    -d '{"entity":"fidc","doc_type":"tranche","year_start":2019,"year_end":2023}'
```

### Error hooks

Failed jobs include a `error.type` classified as one of:

- `network` — `aiohttp` / DNS / timeout / socket failures
- `csv_parse` — CSV parsing, encoding, or missing CVM column
- `db_write` — psycopg2 error, constraint violation, duplicate key
- `schema_mismatch` — column missing on the target table (apply `schema.sql`)
- `unknown` — fallback with full traceback in `error.traceback`

Successful jobs may still emit `warnings`:

- `no_data_published` — 0 rows + no exception (CVM hasn't published that period yet)
- `slow_ingest` — >300s for <1000 rows (likely DNS rotation / upstream slowness)
- `audit_log_error` — surfaced from `cvm_ingest_log.error_msg` for the same slice

Hooks classify only — they do **not** auto-retry. Re-POST the same payload to retry.

## Tests

```bash
PYTHONPATH=. pytest tests/ -v
```

All tests are offline (Supabase DB and HTTP are mocked). The Flask layer is covered by
`tests/test_api.py` (21 tests) — also fully offline; `CVMIngestor` is stubbed.

## Deploy

Single deploy target: **GitHub Actions cron writing to Supabase Postgres**. No container registry, no Vercel, no Docker stack.

- `.github/workflows/daily_ingest.yml` — runs `run_daily` at 06:00 UTC and exposes a `workflow_dispatch`
  for ad-hoc backfills (`mode=backfill`, `start_year=YYYY`, `entity=fidc`).
- Required GitHub secret: `POSTGRES_URL` (Supabase connection string with `sslmode=require`).

To roll out schema changes, commit `src/store/schema.sql` and run
`psql "$POSTGRES_URL" -f src/store/schema.sql` against the Supabase project.
The schema uses `CREATE TABLE IF NOT EXISTS` and named UNIQUE constraints, so re-applying is idempotent.

## Execution roadmap

See `docs/pipeline-plan.md` for the full plan. Summary:

| Phase | What                                                               | Est.     |
| ----- | ------------------------------------------------------------------ | -------- |
| **0** | Fix SECURIT csv_name_pattern bug; add FII complemento yield fields | 1h       |
| **1** | FIDC tranche tables (tab_X, tab_VI) + 4 accountability rules       | half day |
| **2** | SECURIT series + cash-flow tables + 2 accountability rules         | half day |
| **3** | Supabase DB backfill (FIDC + FII + SECURIT re-ingest)                  | 2–3h     |
| **4** | BACEN macro context (CDI spread rule)                              | 1h       |

## What's intentionally not here

- **No public REST/GraphQL API.** The pipeline only writes to Supabase Postgres. Build consumers against Supabase directly.
- **No B3.** The previous `b3_calc_api` pointed at a non-B3 domain and fell back to four hard-coded sample dicts;
  it has been removed. Add a `src/fetchers/b3_fetcher.py` + `src/store/schema.sql` extension when real B3 endpoints
  are validated.
- **No local Postgres / Docker / Alembic.** Supabase Postgres is the single source of truth. Use `scripts/seed_local_db.py`
  with a local Postgres for offline testing.
- **No Solana oracle.** The Delos Oracle experiment is out of scope.
