# Brazilian Financial Data — fetch / parse / store pipeline

Headless ingestion pipeline for two Brazilian public financial data sources:

- **CVM** (Comissão de Valores Mobiliários) — fund disclosures: FI, FIDC, FIP, FIAGRO, FII, SECURIT.
- **BACEN** (Banco Central do Brasil) — SGS time series, PTAX exchange rates, Expectativas (Focus bulletin), TaxaJuros.

Data is downloaded, parsed, validated, and upserted into a Supabase Postgres
database. There is no public API — downstream consumers query Supabase directly.

> A previous version exposed three FastAPI services + a gateway + a Mintlify
> docs site. Those layers and a Solana "Delos Oracle" experiment were removed
> in the consolidation; only fetch/parse/store remains.

## Pipeline stages

```
   ┌───── FETCH ─────┐    ┌───── PARSE ────┐    ┌───── STORE ────┐
   │ src/fetchers/   │ →  │ src/parsers/   │ →  │ src/store/     │
   │  cvm_fetcher    │    │  validation    │    │  supabase_client
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

| Package | Role | Key modules |
| --- | --- | --- |
| `src/fetchers/` | **FETCH** — HTTP/SDK calls only. CVM downloads ZIP/CSV from `dados.cvm.gov.br` with retry, DNS rotation, and on-disk cache. BACEN wraps `python-bcb`. | `cvm_fetcher.CVMFetcher`, `cvm_config.DatasetConfig`, `bacen_fetcher.BacenClient` |
| `src/parsers/` | **PARSE** — shared field/CNPJ/date validation. CVM CSV extraction is co-located with `CVMFetcher.fetch()` because it needs the URL/filename context. BACEN DataFrame normalization is co-located with `BacenClient`. | `validation.DataValidator`, `validator` |
| `src/store/` | **STORE** — Supabase client and chunked upserts; canonical schema. | `supabase_client.upsert_rows`, `supabase_client.get_supabase_client`, `schema.sql` |
| `src/pipeline/` | **ORCHESTRATE** — wires the three stages, writes audit log rows, runs daily/backfill. | `cvm_pipeline.CVMIngestor`, `bacen_pipeline.BacenIngestor`, `run_backfill`, `run_daily` |

## Repository layout

```text
.
├── src/
│   ├── fetchers/
│   │   ├── cvm_fetcher.py      # CVMFetcher.fetch(entity, doc_type, year, month)
│   │   ├── cvm_config.py       # URL templates + dataset configs
│   │   └── bacen_fetcher.py    # BacenClient (SGS/PTAX/Expectativas/TaxaJuros)
│   ├── parsers/
│   │   └── validation.py       # CNPJ / date / numeric / record validators
│   ├── store/
│   │   ├── supabase_client.py  # get_supabase_client(), upsert_rows()
│   │   └── schema.sql          # canonical CVM + BACEN schema
│   └── pipeline/
│       ├── cvm_pipeline.py     # CVMIngestor — orchestrates fetch+store for CVM
│       ├── bacen_pipeline.py   # BacenIngestor — orchestrates fetch+store for BACEN
│       ├── run_backfill.py     # CLI: full historical backfill
│       └── run_daily.py        # CLI: incremental daily update
├── tests/                      # offline pytest suite
├── .github/workflows/
│   └── daily_ingest.yml        # cron @ 06:00 UTC + workflow_dispatch
├── requirements.txt
└── .env.example
```

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in SUPABASE_URL and SUPABASE_SERVICE_KEY

# 1. Apply schema (one-time, against your Supabase Postgres)
psql "$SUPABASE_DB_URL" -f src/store/schema.sql

# 2. Run an incremental update
python -m src.pipeline.run_daily

# 3. Run a one-shot historical backfill (e.g. 2019 onward)
python -m src.pipeline.run_backfill --start-year 2019
```

## Tests

```bash
PYTHONPATH=. pytest tests/ -v
```

All tests are offline (Supabase and HTTP are mocked).

## Deploy

Single deploy target: **GitHub Actions cron writing to Supabase**. No
container registry, no Vercel, no Docker stack.

- `.github/workflows/daily_ingest.yml` — runs `run_daily` at 06:00 UTC and
  exposes a `workflow_dispatch` for ad-hoc backfills (`mode=backfill`,
  `start_year=YYYY`, `entity=fidc`).
- Required GitHub secrets: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`.

To roll out schema changes, commit `src/store/schema.sql` and run
`psql "$SUPABASE_DB_URL" -f src/store/schema.sql` against the target project.
The schema uses `CREATE TABLE IF NOT EXISTS` and named UNIQUE constraints, so
re-applying is idempotent.

## What's intentionally not here

- **No public REST/GraphQL API.** The pipeline only writes to Supabase. Build
  consumers against Supabase directly.
- **No B3.** The previous `b3_calc_api` pointed at a non-B3 domain and
  fell back to four hard-coded sample dicts; it has been removed. Add a
  `src/fetchers/b3_fetcher.py` + `src/store/schema.sql` extension when real B3
  endpoints are validated.
- **No local Postgres / Docker / Alembic.** Supabase is the single source of
  truth. The Postgres + Alembic + 4-service docker-compose stack was deleted.
- **No Solana oracle.** The Delos Oracle experiment is out of scope.
