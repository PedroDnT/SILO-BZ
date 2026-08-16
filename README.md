# Brazilian Financial Data Scrapper and handler

Headless ingestion pipeline for Brazilian public financial data. The goal is to maintain
continuous, verifiable accountability of the fund industry — tracking NAV, delinquency,
tranche performance, and structural health of every entity type CVM publishes.

Data sources:

- **CVM** (Comissão de Valores Mobiliários) — fund disclosures: FI, FIDC, FIP, FIAGRO, FII, SECURIT.
- **BACEN** (Banco Central do Brasil) — SGS time series (SELIC, CDI, IPCA, IGP-M), PTAX exchange rates,
  Expectativas (Focus bulletin).
- **B3** — public COTAHIST daily/yearly quotation zips (unadjusted OHLC, volume, ticker, ISIN).
  Landed in `b3_cotahist`; not yet joined to `cia_*` / fund tables.

Data is downloaded, parsed, validated, and upserted into a Supabase Postgres database via psycopg2.
Dashboards query Supabase directly. Apps should use schema `api` and `serve/`
([docs/API.md](docs/API.md)) — not landing tables. Ingest is GitHub Actions plus
the pipeline CLI (`run_daily` / `run_backfill`); there is no ingest HTTP server.
How we get from “ingested” to “a researcher can pull a panel”:
[docs/planning/SERVING.md](docs/planning/SERVING.md).

> A previous version exposed three FastAPI services + a gateway, a Solana "Delos Oracle"
> experiment, and a localhost ingest Flask control plane (`app.py` / `src/api/`); those
> layers were removed. Only fetch/parse/store remains for ingest. The remaining Flask
> app is `serve/` — a read-only adapter over schema `api`, not an ingest trigger.

## CVM ZIP structure (important)

Each CVM entity distributes data as ZIP files containing multiple CSVs. The pipeline
reads the specific CSVs listed below from each ZIP; the "Pending" column tracks CSVs
that exist in the source but are not yet ingested. (Source of truth for what is
actually wired is `src/store/schema.sql` + `src/pipeline/` (`CVMIngestor.daily_update` /
`backfill`), not this table.)

| Entity                | CSVs per ZIP                | Pipeline reads                                                       | Pending (in plan) |
| --------------------- | --------------------------- | -------------------------------------------------------------------- | ----------------- |
| FI                    | 4 docs                      | inf_diario (NAV, flows), cda (portfolio), perfil, **balancete**      | —                 |
| FIDC                  | **17 CSVs** (tab_I–tab_XIV) | tab_IV (fund-level NAV), **tab_X (tranches)**, **tab_VI (aging)**    | —                 |
| FII                   | 3 CSVs                      | geral, ativo_passivo, **complemento** (NAV + yield)                  | —                 |
| SECURIT (CRA/CRI/OTS) | **8 CSVs**                  | ativo_passivo (emissão), **classe (series status)**, **fluxo_caixa** | —                 |
| FIP                   | 1 CSV                       | inf_quadrimestral (PL)                                               | —                 |
| FIAGRO                | 1 CSV                       | mensal (PL) — available from May 2025                                | —                 |

Tranche (FIDC tab_X), aging (FIDC tab_VI), and SECURIT series/fluxo ingestion are now
wired (see `cvm_fidc_tranche`, `cvm_fidc_aging`, `cvm_securit_serie`, `cvm_securit_fluxo`).

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

| Package         | Role                                                                                                                                                                           |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `src/fetchers/` | **FETCH** — HTTP/SDK calls only. CVM downloads ZIP/CSV from `dados.cvm.gov.br` with retry, DNS rotation, and on-disk cache. BACEN wraps `python-bcb`.                          |
| `src/parsers/`  | **PARSE** — shared field/CNPJ/date validation. CVM CSV extraction is co-located with `CVMFetcher.fetch()` because it needs the URL/filename context. BACEN DataFrame normaliza |
| `src/store/`    | **STORE** — psycopg2 Supabase client and chunked upserts; canonical schema.                                                                                                    |
| `src/pipeline/` | **ORCHESTRATE** — wires the three stages, writes audit log rows, runs daily/backfill.                                                                                          |

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
├── serve/                      # read-only HTTP over schema api (`python -m serve.app`)
├── dashboard/                  # Evidence.dev analytics dashboard
│   ├── pages/                  # Markdown-based pages + embedded SQL queries
│   ├── sources/
│   │   └── supabase/           # Supabase Postgres connection config
│   └── README.md               # Dashboard-specific setup
├── webapp/                     # Evidence.dev CIA Aberta (listed-company) analytics
│   ├── pages/                  # Listed-company financials & events
│   └── README.md               # Webapp-specific setup
├── tests/                      # offline pytest suite
├── scripts/
│   ├── seed_local_db.py        # Fetch real CVM data → local Postgres for offline testing
│   ├── run_analysis_local.py   # Run 11 verification queries against local DB
│   ├── verify_pipeline.py      # Run verification queries against live Supabase DB
│   ├── analysis_queries.sql    # 11 SQL queries: data presence, null rates, business metrics
│   └── explore_cvm_output.py   # Utility for inspecting raw CVM ZIP/CSV structure
├── docs/
│   ├── supabase_operations.md  # Supabase project / connection / ops notes
│   └── planning/
│       └── CHANGELOG.md        # Workstream history (W0-W2)
├── .github/workflows/
│   ├── test.yml                # pytest on PR/push (pip + .pytest_cache); api-smoke on dispatch
│   ├── daily_ingest.yml        # cron @ 06:00 UTC + workflow_dispatch
│   ├── watchdog.yml            # cron @ 08:00 UTC — self-healing staleness re-run
│   └── backfill.yml            # on-demand full historical backfill
├── requirements.txt
└── .env.example
```

## ETL Schema

The pipeline writes to **16 tables** across **two logical domains**: CVM fund data and BACEN macroeconomic context.

### CVM Fund Data (12 core tables)

Each CVM entity gets one or more tables per data release frequency:

| Table                    | Entity  | Data                                             | Rows             | Cadence          | Key                                                                                    |
| ------------------------ | ------- | ------------------------------------------------ | ---------------- | ---------------- | -------------------------------------------------------------------------------------- |
| `cvm_fi_diario`          | FI      | Daily NAV, flows                                 | ~400k/mo, ~5M/yr | Daily            | `(cnpj, dt_comptc)`                                                                    |
| `cvm_fi_cda`             | FI      | Portfolio composition                            | ~50k/mo          | Monthly          | `(cnpj, period, tp_aplic, tp_ativo)`                                                   |
| `cvm_fi_perfil`          | FI      | Investor profile                                 | ~5k/mo           | Monthly          | `(cnpj, period)`                                                                       |
| `cvm_fi_balancete`       | FI      | Balance sheet (chart of accounts)                | ~2M/mo           | Monthly          | `(cnpj, dt_comptc, cd_conta_balcte)`                                                   |
| `cvm_fidc_mensal`        | FIDC    | Fund-level NAV, delinquency                      | ~300/mo          | Monthly          | `(cnpj, period)`                                                                       |
| `cvm_fidc_tranche`       | FIDC    | Tranche-level returns & performance              | ~2k/mo           | Monthly          | `(cnpj, period, classe_serie)`                                                         |
| `cvm_fidc_tranche_flows` | FIDC    | Tranche-level subscriptions/redemptions          | ~3k/mo           | Monthly          | `(cnpj, period, classe_serie, tp_oper)`                                                |
| `cvm_fidc_aging`         | FIDC    | Delinquency aging buckets (30–1080+ day bands)   | ~200/mo          | Monthly          | `(cnpj, period)`                                                                       |
| `cvm_fii_mensal`         | FII     | Fund-level NAV, yield, holding counts            | ~1k/mo           | Monthly          | `(cnpj, period, doc_subtype)`                                                          |
| `cvm_fii_periodic`       | FII     | Annual/quarterly property-level detail           | ~500/yr          | Yearly/Quarterly | `(cnpj, doc_type, period_year)`                                                        |
| `cvm_fip_periodic`       | FIP     | Quadrimestral patrimony (`inf_quadrimestral`)    | ~50/yr           | 4x/year          | `(cnpj, doc_type, period_year)`                                                        |
| `cvm_fiagro_mensal`      | FIAGRO  | Fund-level NAV, delinquency (from May 2025)      | ~500/mo          | Monthly          | `(cnpj, period)`                                                                       |
| `cvm_securit_mensal`     | SECURIT | Monthly emissions (CRA/CRI/OTS)                  | ~500/mo          | Monthly          | `(instrument_type, period_year, cnpj_securit, dt_emissao, dt_vencto, vl_emissao)`      |
| `cvm_securit_serie`      | SECURIT | Per-series status, rating, yield                 | ~2k/yr           | Yearly           | `(instrument_type, cnpj_securit, codigo_identificacao, data_referencia, numero_serie)` |
| `cvm_securit_fluxo`      | SECURIT | Monthly cash flows by tranche                    | ~300/yr          | Monthly          | `(instrument_type, cnpj_securit, codigo_identificacao, data_referencia)`               |
| `cvm_securit_dfin`       | SECURIT | Annual financial statements (dfin_cra, dfin_cri) | ~100/yr          | Yearly           | `(instrument_type, period_year, cnpj_securit)`                                         |

**Fund Registry (shared)**

| Table               | Purpose                             | Rows | Key                   |
| ------------------- | ----------------------------------- | ---- | --------------------- |
| `cvm_fund_registry` | CNPJ → name, status, admin, manager | ~2k  | `(cnpj, entity_type)` |

### BACEN Macroeconomic Context (3 tables)

| Table                | Data                                                                  | Cadence       | Key                                          | Rows                               |
| -------------------- | --------------------------------------------------------------------- | ------------- | -------------------------------------------- | ---------------------------------- |
| `bacen_sgs`          | Time series: SELIC, CDI, IPCA, IGP-M, USD/BRL                         | Daily         | `(series_code, reference_date)`              | ~3M (10 yrs × 365 × 10 series)     |
| `bacen_ptax`         | PTAX exchange rates (USD/BRL, EUR/BRL, etc.)                          | Business days | `(currency, reference_date)`                 | ~10k (10 yrs × 250 × 4 currencies) |
| `bacen_expectativas` | Market consensus (Focus bulletin): SELIC expectations, inflation, GDP | Daily         | `(endpoint_name, indicador, reference_date)` | ~50k                               |

### Audit & Market Data

| Table                 | Purpose                                                                     | Key                                                       |
| --------------------- | --------------------------------------------------------------------------- | --------------------------------------------------------- |
| `cvm_ingest_log`      | Ingest run audit trail (entity, doc_type, period, rows_upserted, error_msg) | `(run_id)`, index: `(entity, doc_type, period_year DESC)` |
| `etf_market_snapshot` | ETF scraped snapshots (nav, price, yields, volatility, drawdown)            | `(ticker, snapshot_date)`                                 |
| `b3_cotahist`         | B3 COTAHIST quotes (unadjusted OHLC, volume, ticker, ISIN). Serve cash via `vw_b3_quote_vista` (`tpmerc = '010'`). | `(codneg, trade_date, tpmerc, codbdi, prazot)`            |

**Total: 20 tables across 11 logical domains (FI, FIDC, FII, FIP, FIAGRO, SECURIT, Registry, BACEN, Audit, ETF, B3).**

### Design Principles

- **Proper types**: DATE and NUMERIC (not text) for all date and money columns.
- **JSONB audit column**: Every row preserves the original CSV (`raw` field) for re-processing.
- **Partitioning**: `cvm_fi_diario` is partitioned by year (monotonic append, ~5M rows/yr).
- **Indexes**: BRIN on date columns, unique constraints on natural keys (idempotent ON CONFLICT upserts).
- **No soft deletes**: Deletion is physical; canceled funds drop out of `cvm_fund_registry.status`.

---

## Frontend Architecture

The frontend consists of **two Evidence.dev instances** sharing the same Supabase Postgres backend:

### 1. **Dashboard** (`dashboard/`)

**Purpose**: Industry-wide accountability & surveillance.

| Page                    | Route         | Key Tables                                              | What It Shows                                                                                                                                      |
| ----------------------- | ------------- | ------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Overview**            | `/`           | `cvm_fi_diario`, `cvm_fidc_mensal`, `cvm_fii_mensal`    | AUM by entity type (12-month trend), FIDC sector delinquency (%), live row counts per table                                                        |
| **FIDC Credit Monitor** | `/fidc`       | `cvm_fidc_mensal`, `cvm_fidc_aging`, `cvm_fidc_tranche` | Sector delinquency trend (24mo), aging bucket distribution (30–1080+ day overdue), top 10 delinquent funds, red flags (sudden delinquency spikes)  |
| **FII Market**          | `/fii`        | `cvm_fii_mensal`                                        | FII vs FIAGRO AUM comparison, yield distribution (p10–p90), top 20 funds by dividend yield, NAV trend                                              |
| **Suspicious Screens**  | `/suspicious` | `cvm_fi_diario`, `cvm_fidc_mensal`, `cvm_fii_mensal`    | Zombie growth (AUM growth + zero inflows), captive vehicles (same admin & manager), evergreen aging (stagnant delinquency), overdue SECURIT series |

**Tech Stack**:

- Evidence.dev (SQL → Markdown → Charts)
- Supabase Postgres datasource (`sources/supabase/connection.yaml`)
- Static build to `build/` directory
- Deploy: Vercel (primary) or any static host

**How to run**:

```bash
cd dashboard
npm install
npm run sources  # Pull schema from Supabase
npm run dev      # localhost:3000
npm run build    # Static site → build/
```

---

### 2. **Webapp** (`webapp/`)

**Purpose**: Listed-company (CIA Aberta) financials and events (parallel universe).

| Page           | Route         | Key Tables                 | What It Shows                                                                     |
| -------------- | ------------- | -------------------------- | --------------------------------------------------------------------------------- |
| **Overview**   | `/`           | `cia_company`, `cia_event` | Company registry, top 20 by revenue, latest Fatos Relevantes (10)                 |
| **Financials** | `/financials` | `cia_account` (ITR/DFP)    | Consolidated revenue, net income, margins, ROE; 5-year trend by company           |
| **Events**     | `/events`     | `cia_event` (IPE filings)  | Fato Relevante volume by category, cumulative event count, event feed (latest 50) |

**Data Model** (CIA Aberta is separate; sourced from CVM's listed-company filings):

- `cia_company` — registry (CNPJ, name, sector, listing date)
- `cia_account` — DRE + BPA/BPP (income statement + balance sheets): revenue, EBIT, net income, equity, etc.
  - Conventions: `escopo = 'con'` (consolidated), `ordem_exerc = 'ÚLTIMO'` (accented), net income = account 3.11 (or 3.09 for banks)
- `cia_event` — IPE filings (Fatos Relevantes, announcements, etc.)

**Tech Stack**:

- Evidence.dev (same as Dashboard)
- Same Supabase Postgres datasource
- Static build
- Deploy: Vercel (primary) or static host

**How to run**:

```bash
cd webapp
npm install
export EVIDENCE_SOURCE__supabase__connectionString='postgresql://...'  # same as dashboard/
npm run sources
npm run dev      # localhost:3000
npm run build    # static site → build/
```

---

### Shared Frontend Logic

Both instances use Evidence.dev **embedded SQL queries** in Markdown, which:

1. Query Supabase Postgres directly at build time.
2. Render as interactive charts (ECharts, maps, tables).
3. Support parameterization (date ranges, entity filters).

No ORMs, no GraphQL — pure SQL. This keeps the frontend lean and deployable as static HTML.

---

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
bash scripts/install_hooks.sh   # fail-safe pre-commit guards (secrets, syntax)
cp .env.example .env   # fill in POSTGRES_URL (Supabase connection string)

# 1. Apply schema + migrations (one-time, against your Supabase Postgres)
python scripts/apply_schema.py

# 2. Run an incremental update
python -m src.pipeline.run_daily

# 3. Run a one-shot historical backfill (e.g. 2019 onward)
python -m src.pipeline.run_backfill --start-year 2019

# 3c. Optional: B3 COTAHIST yearly quotation zips (large; daily run already
#     picks up the last 7 calendar days)
python -m src.pipeline.run_backfill --b3-only --b3-start-year 2019

# 3b. Build the analytical layer (views/functions) — AFTER data is ingested
bash scripts/apply_analytical.sh

# 4. Verify the pipeline (local DuckDB, ~2 min, skips FI inf_diario)
python scripts/seed_local_db.py --skip-fi
python scripts/run_analysis_local.py

# 5. Verify against live Supabase DB
python scripts/verify_pipeline.py
```

## Partial fills (CLI)

Ingest is GitHub Actions plus the pipeline CLI. There is no localhost HTTP
control plane. One entity or year:

```bash
python -m src.pipeline.run_backfill --cvm-only --entity fidc --start-year 2024 --end-year 2024
python -m src.pipeline.run_backfill --cvm-only --entity fidc --start-year 2019
python -m src.pipeline.run_daily
```

One month of one dataset — call the ingestor method (needs `POSTGRES_URL`):

```python
import asyncio
from src.pipeline.cvm_pipeline import CVMIngestor

asyncio.run(CVMIngestor().ingest_fidc_tranche(2024, 5))
```

Failed fetches raise and write `cvm_ingest_log`; they are not auto-retried.
Re-run the same command. Quality gate: `python scripts/verify_pipeline.py`.

The read-only HTTP adapter is separate: `python -m serve.app` (see
[docs/API.md](docs/API.md)).

## Tests

```bash
PYTHONPATH=. pytest tests/ -v
```

All tests are offline (Supabase DB and HTTP are mocked). The read API is covered by
`tests/test_serve_api.py` — also fully offline; Postgres is stubbed.

CI: `.github/workflows/test.yml` runs this suite on every PR and push to `main`
(pip cache + `.pytest_cache`). **Actions → Tests → Run workflow** also runs a
read-only `api.*` smoke against Silo (`POSTGRES_URL`); SQL errors fail, zero
rows do not.

## Deploy

> Day-to-day database upkeep — what to check and how often, reading `cvm_ingest_log`,
> healing gaps, the yearly partition rollover, and a symptom→fix index — lives in
> [`docs/DATABASE_MAINTENANCE.md`](docs/DATABASE_MAINTENANCE.md).

**Ingestion** deploys to a single target: **GitHub Actions cron writing to Supabase Postgres**
(no container registry, no Docker stack).

- `.github/workflows/test.yml` — pytest on PR/push; dispatch also smokes `api.*` read-only.
- `.github/workflows/daily_ingest.yml` — runs `run_daily` at 06:00 UTC and exposes a `workflow_dispatch`
  for ad-hoc runs (`mode=daily|backfill|analytics-only|b3-backfill`). `b3-backfill` loads yearly
  COTAHIST zips (`--b3-only`); set `start_year` (try `2025` first).
- Required GitHub secret: `POSTGRES_URL` (Supabase connection string with `sslmode=require`).

The read-only **Evidence.dev dashboard** (`dashboard/`) deploys separately to **Vercel**
(project `iliquid-nightly`, primary live target); it can also be served as a static build on
any static host. It only reads from Supabase.

To roll out schema changes, commit `src/store/schema.sql` and any new
`src/store/migrations/*.sql`, then run `python scripts/apply_schema.py` against
the Supabase project (it applies the base schema and every migration in order).
The DDL uses `CREATE TABLE IF NOT EXISTS` and named UNIQUE constraints, so re-applying is idempotent.

## Execution roadmap

The original build-out phases are complete — see `docs/planning/CHANGELOG.md` for the
workstream history.

| Phase | What                                                               | Status  |
| ----- | ------------------------------------------------------------------ | ------- |
| **0** | Fix SECURIT csv_name_pattern bug; add FII complemento yield fields | ✅ done |
| **1** | FIDC tranche tables (tab_X, tab_VI) + accountability rules         | ✅ done |
| **2** | SECURIT series + cash-flow tables + accountability rules           | ✅ done |
| **3** | Supabase DB backfill (FIDC + FII + SECURIT re-ingest)              | ✅ done |
| **4** | BACEN macro context (CDI spread rule)                              | ✅ done |

Since then: FI `balancete` wired, a self-healing ingest watchdog (`watchdog.yml`),
and an analytical layer (`src/store/analytical/`, applied via `scripts/apply_analytical.sh`)
— conformed dimensions (`dim_fund` is a **materialized view**) + asset-class /
administrator-gestor classification (13), fraud screens (15), and per-asset-class +
ETF performance ranking functions (16–17) — plus the Evidence `dashboard/` (on Vercel)
with Performance and ETF pages.

## What's intentionally not here

- **No ingest REST API, and no PostgREST dump of landing tables.** The pipeline writes to Supabase via GitHub Actions and the CLI. Apps read schema `api` via `serve/` ([docs/API.md](docs/API.md)). The old localhost ingest Flask (`app.py` / `src/api/`) is deleted.
- **No fabricated quotes.** The old `b3_calc_api` (non-B3 domain + hard-coded sample dicts) stays deleted. Historical quotations come from B3's public COTAHIST zips (`src/fetchers/b3_fetcher.py` → `b3_cotahist` → `api.quotes`). Missing tickers are 404, never a guessed last close.
- **No local Postgres / Docker / Alembic.** Supabase Postgres is the single source of truth. Use `scripts/seed_local_db.py`
  with a local Postgres for offline testing.
- **No Solana oracle.** The Delos Oracle experiment is out of scope.
