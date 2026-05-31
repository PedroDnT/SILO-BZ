# iliquid — Brazilian Fund Accountability Pipeline

Headless ingestion pipeline for Brazilian public financial data. Maintains continuous, verifiable accountability of the fund industry — tracking NAV, delinquency, tranche performance, issuer financials, and structural health of every entity type CVM publishes.

## Data sources

| Source | What | Tables |
| ------ | ---- | ------ |
| **CVM** — `dados.cvm.gov.br` | Fund disclosures: FI, FIDC, FIP, FIAGRO, FII, SECURIT (CRA/CRI/OTS) | `cvm_fi_diario`, `cvm_fidc_mensal`, `cvm_fidc_aging`, `cvm_fii_mensal`, `cvm_securit_serie`, `cvm_fip_quad`, `cvm_fiagro_mensal` |
| **CVM** — CIA Aberta | Publicly listed companies: registry, events, ITR/DFP financial statements | `cia_company`, `cia_event`, `cia_filing`, `cia_account` |
| **BACEN** | SGS time series (SELIC, CDI, IPCA, IGP-M), PTAX exchange rates, Focus bulletin | `bacen_series`, `bacen_ptax`, `bacen_expectativas` |

Data is downloaded, parsed, validated, and upserted into a Supabase Postgres database via psycopg2. There is no public API — downstream consumers query Supabase directly.

A small **local Flask control plane** (`app.py` + `src/api/`) wraps the pipeline so operators can trigger partial fills one `(entity, doc_type, year, month)` slice at a time and watch jobs progress via a polling endpoint.

> A previous version exposed three FastAPI services + a gateway + a Mintlify docs site. Those layers and a Solana "Delos Oracle" experiment were removed in the consolidation; only fetch/parse/store remains. The Flask app is **localhost-only**.

## CVM ZIP structure

Each CVM entity distributes data as ZIP files containing multiple CSVs. The pipeline reads specific CSVs from each ZIP:

| Entity | CSVs per ZIP | Pipeline reads | Pending |
| ------ | ------------ | -------------- | ------- |
| FI | 1 CSV | `inf_diario` (NAV, flows) | — |
| FIDC | **17 CSVs** (tab_I–tab_XIV) | `tab_IV` (fund-level NAV), `tab_X` (tranches), `tab_VI` (aging) | — |
| FII | 3 CSVs | `geral`, `ativo_passivo`, `complemento` (NAV + yield) | — |
| SECURIT (CRA/CRI/OTS) | **8 CSVs** | `ativo_passivo` (emissão totals), `*_classe` (series status) | `fluxo_caixa` |
| FIP | 1 CSV | `inf_quadrimestral` (PL) | — |
| FIAGRO | 1 CSV | `mensal` (PL) — available from May 2025 | — |
| CIA Aberta | Multiple CSVs + ZIP per filing | Company registry, events (IPE), ITR/DFP account data | — |

## Pipeline stages

```
  ┌───── FETCH ─────┐    ┌───── PARSE ────┐    ┌───── STORE ────┐
  │ src/fetchers/   │ →  │ src/parsers/   │ →  │ src/store/     │
  │  cvm_fetcher    │    │  validation    │    │  pg_client.py  │
  │  cia_fetcher    │    │  field_maps/   │    │  schema.sql    │
  │  bacen_fetcher  │    │                │    │  migrations/   │
  └─────────────────┘    └────────────────┘    └────────────────┘
                                                      ▲
                          ┌───── ORCHESTRATE ──────────┘
                          │ src/pipeline/
                          │   cvm_pipeline.py     (CVMIngestor)
                          │   bacen_pipeline.py   (BacenIngestor)
                          │   ingest_cia.py        (CIA Aberta)
                          │   ingest_fi/fidc/fii/securit/misc.py
                          │   run_backfill.py     (one-shot, all years)
                          │   run_daily.py        (cron, current month)
                          └──────────────────────────────────────
```

| Package | Role | Key modules |
| ------- | ---- | ----------- |
| `src/fetchers/` | HTTP/SDK calls only. CVM downloads ZIP/CSV with retry, DNS rotation, and on-disk cache. BACEN wraps `python-bcb`. CIA Aberta downloads company/event/filing ZIPs. | `cvm_fetcher`, `cvm_config`, `cia_fetcher`, `bacen_fetcher` |
| `src/parsers/` | Shared field/CNPJ/date validation. Per-dataset typed column → CSV header mappings in `field_maps/`. | `validation.DataValidator`, `mapping.apply_map`, `field_maps/` |
| `src/store/` | psycopg2 Supabase client, chunked upserts, canonical schema, and incremental migrations. Analytical views live in `analytical/`. | `pg_client`, `schema.sql`, `migrations/`, `analytical/` |
| `src/pipeline/` | Wires the three stages, writes audit log rows. Per-entity ingest modules for clean separation. | `cvm_pipeline`, `bacen_pipeline`, `ingest_cia`, `ingest_fi`, `ingest_fidc`, `ingest_fii`, `ingest_securit`, `run_backfill`, `run_daily` |

## Repository layout

```text
.
├── src/
│   ├── fetchers/
│   │   ├── cvm_fetcher.py      # CVMFetcher.fetch(entity, doc_type, year, month)
│   │   ├── cvm_config.py       # URL templates + dataset configs (entity × doc_type matrix)
│   │   ├── cia_fetcher.py      # CIAFetcher — company/event/filing/account downloads
│   │   └── bacen_fetcher.py    # BacenClient (SGS / PTAX / Expectativas / TaxaJuros)
│   ├── parsers/
│   │   ├── validation.py       # CNPJ / date / numeric / record validators
│   │   ├── mapping.py          # apply_map() — typed field map → row dicts
│   │   └── field_maps/         # Per-dataset column → CSV header mappings
│   ├── store/
│   │   ├── pg_client.py        # get_pg_client(), upsert_rows() — psycopg2/Supabase
│   │   ├── schema.sql          # base CREATE TABLE IF NOT EXISTS for all domains
│   │   ├── migrations/         # numbered ALTER TABLE / ADD COLUMN scripts
│   │   └── analytical/         # dim/fact/view/function/index SQL + smoke.sql
│   ├── pipeline/
│   │   ├── cvm_pipeline.py     # CVMIngestor — orchestrates CVM fetch+store
│   │   ├── bacen_pipeline.py   # BacenIngestor — orchestrates BACEN fetch+store
│   │   ├── ingest_cia.py       # CIA Aberta — company, event, filing, account
│   │   ├── ingest_fi.py        # FI inf_diario ingestor
│   │   ├── ingest_fidc.py      # FIDC mensal + aging + tranche ingestors
│   │   ├── ingest_fii.py       # FII mensal ingestor
│   │   ├── ingest_securit.py   # SECURIT ativo_passivo + serie ingestors
│   │   ├── ingest_misc.py      # FIP, FIAGRO ingestors
│   │   ├── run_backfill.py     # CLI: full historical backfill
│   │   └── run_daily.py        # CLI: incremental daily update
│   └── api/                    # Flask control plane (local-only)
│       ├── __init__.py         # create_app() factory
│       ├── routes.py           # HTTP endpoints (ingest, status, jobs, verify)
│       ├── jobs.py             # in-process job registry (UUID → state)
│       ├── dispatch.py         # (entity, doc_type) → ingestor method
│       └── hooks.py            # post-job error classifier + inefficiency detector
├── app.py                      # Flask entry point — `flask --app app run`
├── dashboard/                  # Evidence.dev analytics dashboard (Supabase data source)
│   └── pages/
│       ├── index.md            # Overview: AUM by entity, FIDC delinquency, row counts
│       ├── fidc.md             # FIDC credit monitor: aging buckets, top delinquents
│       ├── fii.md              # FII market: AUM, yield distribution, top funds
│       └── suspicious.md       # Forensic screens: zombie growth, evergreen aging
├── webapp/                     # Evidence.dev (newer build — CIA financials in progress)
├── tests/                      # Offline pytest suite
├── scripts/
│   ├── apply_schema.py         # Apply schema.sql + migrations/ against Supabase (idempotent)
│   ├── seed_local_db.py        # Fetch real CVM data → local DuckDB for offline testing
│   ├── run_analysis_local.py   # Run verification queries against local DuckDB
│   ├── verify_pipeline.py      # Run verification queries against live Supabase DB
│   ├── explore_cvm_output.py   # Inspect raw CVM ZIP/CSV field names and sample rows
│   ├── _check_conn.py          # Quick Supabase connectivity test
│   └── queries/                # Analytical queries (call functions from analytical/ layer)
├── .github/workflows/
│   ├── daily_ingest.yml        # cron @ 06:00 UTC + workflow_dispatch
│   └── backfill.yml            # manual backfill workflow
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

The Flask app exposes each ingestor method as a background job, so backfill work can proceed one slice at a time. Bind to `127.0.0.1`; there is no auth.

```bash
flask --app app run     # or: python app.py
```

Requires `POSTGRES_URL` set to the Supabase connection string.

### Endpoint reference

| Method | Path | Body / Query | Purpose |
| ------ | ---- | ------------ | ------- |
| GET | `/healthz` | — | Liveness + Supabase DB reachability |
| GET | `/api/status` | — | Row counts per table + last 5 `cvm_ingest_log` entries |
| GET | `/api/dispatch` | — | List every valid `(entity, doc_type)` pair |
| POST | `/api/ingest` | `{entity, doc_type, year, month?}` | Fire one slice. Returns `{job_id}` |
| POST | `/api/ingest/range` | `{entity, doc_type, year_start, year_end, months?}` | Spawn N sequential child jobs |
| POST | `/api/daily` | — | Run `CVMIngestor.daily_update()` as one background job |
| GET | `/api/jobs` | `?limit=50` | List recent jobs, newest first |
| GET | `/api/jobs/<id>` | — | Full job state: status, rows, error, warnings, children |
| POST | `/api/verify` | — | Run the quality-gate subset of `verify_pipeline.py` synchronously |

`month` is required for monthly conventions (`fi`, `fidc`, `fiagro mensal`). Yearly conventions (`fii`, `fip`, `securit *_classe / *_fluxo / dfin_*`) take only `year`.

### Error classification

Failed jobs include an `error.type`:

- `network` — HTTP / DNS / timeout failures
- `csv_parse` — CSV parsing, encoding, or missing CVM column
- `db_write` — psycopg2 error, constraint violation
- `schema_mismatch` — column missing on the target table (apply `schema.sql` + migrations)
- `unknown` — fallback with full traceback in `error.traceback`

Successful jobs may still emit `warnings`:

- `no_data_published` — 0 rows + no exception (CVM hasn't published that period yet)
- `slow_ingest` — >300s for <1000 rows (likely DNS rotation / upstream slowness)
- `audit_log_error` — surfaced from `cvm_ingest_log.error_msg` for the same slice

Hooks classify only — they do **not** auto-retry. Re-POST the same payload to retry.

## Evidence dashboards

Two Evidence.dev instances connect to Supabase Postgres via `@evidence-dev/postgres`:

| Dir | Status | Pages |
| --- | ------ | ----- |
| `dashboard/` | Live — fund analytics | Overview, FIDC credit, FII market, Suspicious screens |
| `webapp/` | In progress — CIA financials | |

```bash
# Run either dashboard locally
cd dashboard   # or: cd webapp
npm install
npm run sources
npm run dev
```

## Tests

```bash
PYTHONPATH=. pytest tests/ -v
```

All tests are offline (Supabase DB and HTTP are mocked).

## Deploy

Single deploy target: **GitHub Actions cron writing to Supabase Postgres**.

- `.github/workflows/daily_ingest.yml` — runs `run_daily` at 06:00 UTC with `workflow_dispatch` for ad-hoc backfills.
- `.github/workflows/backfill.yml` — manual backfill trigger.
- Required GitHub secret: `POSTGRES_URL`.

Schema changes: commit `src/store/schema.sql` and any new `src/store/migrations/*.sql`, then apply against Supabase. Schema uses `CREATE TABLE IF NOT EXISTS` and named UNIQUE constraints — re-applying is idempotent.

## What's intentionally not here

- **No public REST/GraphQL API.** Pipeline only writes to Supabase Postgres. Build consumers against Supabase directly.
- **No B3.** The previous `b3_calc_api` pointed at a non-B3 domain; removed. Add `src/fetchers/b3_fetcher.py` when real B3 endpoints are validated.
- **No local Postgres / Docker / Alembic.** Supabase Postgres is the single source of truth. Use `scripts/seed_local_db.py` with a local Postgres for offline testing.
- **No Solana oracle.** The Delos Oracle experiment is out of scope.
