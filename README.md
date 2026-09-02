# Brazilian Financial Data Scrapper and handler

> **Read API:** [https://zcjbtpxuhdekpwcxmepn.supabase.co/rest/v1/](https://zcjbtpxuhdekpwcxmepn.supabase.co/rest/v1/)
> — schema `api`, anon key, open read. Caller docs: [https://octo-98895abd.mintlify.site](https://octo-98895abd.mintlify.site)
> (source: [`api-docs/`](api-docs/quickstart.mdx)).
> **Dashboard:** [https://iliquid-nightly.vercel.app/](https://iliquid-nightly.vercel.app/)
> — Evidence static snapshot. **SILO** is this repo: GitHub Actions ingest into Supabase,
> plus schema `api`. See [What's next](#whats-next) for remaining ops.

Headless ingestion pipeline for Brazilian public financial data. The goal is to maintain
continuous, verifiable accountability of the fund industry — tracking NAV, delinquency,
tranche performance, and structural health of every entity type CVM publishes.

Data sources:

- **CVM** (Comissão de Valores Mobiliários) — fund disclosures: FI, FIDC, FIP, FIAGRO, FII, SECURIT.
- **BACEN** (Banco Central do Brasil) — SGS time series (SELIC, CDI, IPCA, IGP-M), PTAX exchange rates,
  Expectativas (Focus bulletin).
- **B3** — public COTAHIST daily/yearly quotation zips (unadjusted OHLC, volume, ticker, ISIN)
  in `b3_cotahist`, plus published corporate actions (splits, groupings, bonuses,
  dividends) per ISIN in `b3_corporate_event`.

Data is downloaded, parsed, validated, and upserted into a Supabase Postgres database via psycopg2.
Ingest is GitHub Actions plus the pipeline CLI (`run_daily` / `run_backfill`); there is no
ingest HTTP server.

**Reading the data.** Three surfaces, one warehouse — schema `api` / landing tables in
Supabase. SILO (this repo) writes and serves; the dashboard only reads at build time:

| Surface                     | What it is                                                        | Status                                                          |
| --------------------------- | ----------------------------------------------------------------- | --------------------------------------------------------------- |
| **Supabase Data API**       | PostgREST over schema `api` at [https://zcjbtpxuhdekpwcxmepn.supabase.co/rest/v1/](https://zcjbtpxuhdekpwcxmepn.supabase.co/rest/v1/), anon key, public read | live public path |
| **`serve/`**                | local read-only Flask adapter (`python -m serve.app`)             | for notebooks and development                                   |
| **Dashboard**               | Evidence.dev at [https://iliquid-nightly.vercel.app/](https://iliquid-nightly.vercel.app/) (`dashboard/` in this repo) | static snapshot; `webapp/` is CIA Aberta |

Docs: [https://octo-98895abd.mintlify.site](https://octo-98895abd.mintlify.site)
(Mintlify, source in [`api-docs/`](api-docs/quickstart.mdx); agents: [`api-docs/agents.mdx`](api-docs/agents.mdx)) for callers,
[docs/API.md](docs/API.md) for the contract and its edge cases,
[docs/DATA_INVENTORY.md](docs/DATA_INVENTORY.md) for what we ingest, what we
could ingest and don't, what we ingest and don't serve, and the serving grain
per family, and
[docs/planning/SERVING.md](docs/planning/SERVING.md) for how "ingested" becomes
"a researcher pulls a panel" (steps 0–7; 3 and 6 gate public HTTP).

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
│   ├── fetchers/               # HTTP/SDK calls only — no parsing, no storage
│   │   ├── cvm_fetcher.py      # CVMFetcher.fetch(entity, doc_type, year, month)
│   │   ├── cvm_config.py       # URL templates + dataset configs (entity × doc_type matrix)
│   │   ├── bacen_fetcher.py    # BacenClient (SGS/PTAX/Expectativas/TaxaJuros)
│   │   ├── b3_fetcher.py       # public COTAHIST daily/yearly quotation zips
│   │   ├── cia_fetcher.py      # listed-company (CIA Aberta) filings
│   │   └── apify_etf_fetcher.py# ETF market scrape (gated on APIFY_TOKEN)
│   ├── parsers/
│   │   ├── mapping.py          # the declarative FIELD_MAP engine + coercions
│   │   ├── validation.py       # CNPJ / date / numeric / record validators
│   │   └── field_maps/         # per-dataset CSV header → typed DB column
│   ├── store/
│   │   ├── pg_client.py        # get_pg_client(), upsert_rows() — the ONLY DB door
│   │   ├── schema.sql          # canonical schema (tables + audit log)
│   │   ├── migrations/         # NNN_*.sql, append-only — never edit a historical one
│   │   └── analytical/         # 01–19: dims, fact matviews, screens, rankings, schema api
│   ├── pipeline/               # wires fetch→parse→store, writes cvm_ingest_log
│   │   ├── cvm_pipeline.py     # CVMIngestor — the (entity, doc_type) orchestrator
│   │   ├── bacen_pipeline.py   # BacenIngestor
│   │   ├── b3_pipeline.py      # B3Ingestor (COTAHIST)
│   │   ├── anbima_pipeline.py  # ANBIMA boletim
│   │   ├── ingest_<entity>.py  # per-entity ingest_* methods (fi, fidc, fii, securit, cia…)
│   │   ├── run_daily.py        # CLI: incremental daily update
│   │   └── run_backfill.py     # CLI: full historical backfill
├── serve/                      # read-only local adapter over schema api
│   ├── app.py                  # `python -m serve.app` — 127.0.0.1:8080, NOT an ingest trigger
│   ├── pool.py                 # one pooled client per process
│   └── catalog.py              # machine-readable metric catalog (CATALOG_VERSION)
├── dashboard/                  # Evidence.dev analytics dashboard
│   ├── pages/                  # Markdown-based pages + embedded SQL queries
│   ├── sources/
│   │   └── supabase/           # Supabase Postgres connection config
│   └── README.md               # Dashboard-specific setup
├── webapp/                     # Evidence.dev CIA Aberta (listed-company) analytics
│   ├── pages/                  # Listed-company financials & events
│   └── README.md               # Webapp-specific setup
├── tests/                      # offline pytest suite (DB + HTTP mocked)
├── scripts/                    # operator + dev tooling — see scripts/README.md
│   ├── apply_analytical.sh     # build the analytical layer (01–19) after ingest
│   ├── verify_pipeline.py      # quality gate against live Supabase
│   ├── seed_local_db.py        # offline: real CVM data → local DuckDB
│   ├── vercel_should_build.sh  # Vercel ignoreCommand (0 SKIPS, 1 BUILDS)
│   └── queries/                # 13 numbered read-only SQL files
├── docs/                       # prose docs (NOT published; see .mintignore)
│   ├── API.md                  # the read contract, and the Supabase-native decision
│   ├── DATABASE_MAINTENANCE.md # upkeep runbook: checks, cadence, partition rollover
│   ├── DATA_MODELING.md        # read before adding a new CLASS of data
│   ├── ETF_AND_PERFORMANCE.md  # why etf_daily is empty post-CVM-175
│   ├── supabase_operations.md  # connection / pooler / ops notes
│   └── planning/
│       ├── CHANGELOG.md        # workstream history
│       └── SERVING.md          # ingested → researcher pulls a panel (steps 0–7)
├── api-docs/                   # PUBLISHED Mintlify pages (quickstart + reference)
├── index.mdx                   # published docs landing page
├── docs.json                   # Mintlify config: theme + navigation
├── .mintignore                 # keeps Evidence template markdown out of the MDX parser
├── vercel.json                 # dashboard build config + ignoreCommand
├── .githooks/                  # pre-commit: blocks credentialed URLs, bad syntax
├── apify/                      # ETF market scrape actor (gated on APIFY_TOKEN)
├── .github/
│   ├── actions/apply-schema/   # composite action: schema + migrations, lock-guarded
│   └── workflows/
│       ├── test.yml            # pytest on PR/push; api-smoke on dispatch
│       ├── daily_ingest.yml    # cron @ 06:00 UTC + workflow_dispatch
│       ├── watchdog.yml        # cron @ 08:00 UTC — self-healing staleness re-run
│       └── backfill.yml        # on-demand full historical backfill
├── requirements.txt
└── .env.example
```

## ETL Schema

The pipeline writes to **34 tables** across **two logical domains**: CVM fund data and BACEN macroeconomic context.

### CVM Fund Data (18 core tables)

Each CVM entity gets one or more tables per data release frequency:

| Table                    | Entity  | Data                                             | Rows             | Cadence          | Key                                                                                    |
| ------------------------ | ------- | ------------------------------------------------ | ---------------- | ---------------- | -------------------------------------------------------------------------------------- |
| `cvm_fi_diario`          | FI      | Daily NAV, flows                                 | ~400k/mo, ~5M/yr | Daily            | `(cnpj, dt_comptc)`                                                                    |
| `cvm_fi_cda`             | FI      | Portfolio composition                            | ~50k/mo          | Monthly          | `(cnpj, period, tp_aplic, tp_ativo)`                                                   |
| `cvm_fi_cda_acoes`       | FI      | Equity holdings (CDA blk 4, carries B3 ticker)   | ~166k/mo         | Monthly          | `(cnpj, period, tp_fundo, tp_aplic, tp_ativo, cd_ativo, tp_negoc)`                     |
| `cvm_fi_cda_cotas`       | FI      | Fund-of-fund holdings (CDA blk 2)                | ~82k/mo          | Monthly          | `(cnpj, period, tp_fundo, cnpj_cota, tp_aplic, tp_negoc)`                              |
| `cvm_fi_cda_debentures`  | FI      | Debenture holdings (CDA blk 6, carries issuer)   | ~3k/mo           | Monthly          | `(cnpj, period, tp_fundo, tp_aplic, tp_ativo, cpf_cnpj_emissor, dt_venc, tp_negoc, row_hash)` |
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

| Table                 | Purpose                                                                                                            | Key                                                       |
| --------------------- | ------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------- |
| `cvm_ingest_log`      | Ingest run audit trail (entity, doc_type, period, rows_upserted, error_msg)                                        | `(run_id)`, index: `(entity, doc_type, period_year DESC)` |
| `etf_market_snapshot` | ETF scraped snapshots (nav, price, yields, volatility, drawdown)                                                   | `(ticker, snapshot_date)`                                 |
| `b3_cotahist`         | B3 COTAHIST quotes (unadjusted OHLC, volume, ticker, ISIN). `vw_b3_instrument_typed` classifies published instrument types; `api.quotes` serves typed cash rows. | `(codneg, trade_date, tpmerc, codbdi, prazot)`            |

**Total: 35 base tables across 12 logical domains (FI, FIDC, FII, FIP, FIAGRO, SECURIT, CIA Aberta, Registry, BACEN, Audit, ETF, B3)** — counted from a database with `schema.sql` plus every migration applied, excluding partition children. The authoritative list is `src/store/schema.sql` plus `migrations/`; `docs/DATA_INVENTORY.md` maps every table to its source, grain and coverage, and says which are ingested but not served.

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

# Repair only the months missing from one FI document's table (not the audit log)
python -m src.pipeline.run_backfill --cvm-only --entity fi --doc-type balancete --repair-gaps
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
  for ad-hoc runs (`mode=daily|analytics-only|b3-backfill`). CVM history is
  **CVM Historical Backfill** (`backfill.yml`), not a mode here. `b3-backfill` loads yearly
  COTAHIST zips (`--b3-only`); set an exact `start_year` / `end_year` range.
- `.github/workflows/backfill.yml` — choose one entity plus `start_year`/`end_year`.
  Matrix jobs are serialized, FI skips years already complete in `cvm_ingest_log`,
  and the run prints current coverage before writing. For an FI-only repair, choose
  `fi_doc_type` (for example `balancete`) so unrelated sources are not re-fetched.
  Choose `all` only deliberately.
- Required GitHub secret: `POSTGRES_URL` (Supabase connection string with `sslmode=require`).

The read-only **Evidence.dev dashboard** lives at
[https://iliquid-nightly.vercel.app/](https://iliquid-nightly.vercel.app/).
Source is `dashboard/` in this repo; it only reads from Supabase. **SILO** is the
ingest + store + schema `api` serve: GitHub Actions (`daily_ingest.yml` /
`backfill.yml`) write Postgres. The Vercel *project* in the Deloslabs team is
named `silo` (that is the GitHub integration and the deploy-hook target) — the
URL people open is `iliquid-nightly.vercel.app`. It can also be served as a
static build on any static host.

The dashboard is a **static snapshot, not a live view**. `npm run sources` extracts
Supabase into parquet at build time, and the browser then queries that parquet through
DuckDB-WASM. So fresh rows reach the site only when a build runs — which has two
consequences worth knowing:

- **Not every commit builds.** `vercel.json`'s `ignoreCommand` runs
  `scripts/vercel_should_build.sh`, which builds only when `dashboard/`, `vercel.json`,
  or that script changed. A build fires ~90 queries at production Supabase and takes
  25–45 minutes, so rebuilding for a tests-only commit burned that for a byte-identical
  site — and concurrent builds were slow enough to block the schema apply's `ALTER TABLE`
  until Postgres killed it.
- **Data refreshes are explicit.** Scheduled ingest and historical fills never POST the
  Vercel hook. Dispatch **Daily CVM Ingest** with `rebuild_dashboard=true` after the
  database is ready for a 25–45 minute Evidence extraction; otherwise the published
  snapshot remains unchanged.

Schema applies run with `lock_timeout` and retries (`.github/actions/apply-schema`): a
blocked `ALTER TABLE` gives up in seconds instead of queueing and blocking every reader
behind it. `statement_timeout` stays unbounded so a genuinely slow migration is never
killed mid-flight.

To roll out schema changes, commit `src/store/schema.sql` and any new
`src/store/migrations/*.sql`. Every daily/backfill/watchdog ingest applies them
automatically; use `python scripts/apply_schema.py` only for an intentional standalone
rollout.
The DDL uses `CREATE TABLE IF NOT EXISTS` and named UNIQUE constraints, so re-applying is idempotent.

## What's next

The pipeline is production-grade and runs unattended; **serving is the open front**.
Everything below is either an operator action or a known defect — none of it is
speculative roadmap.

### The API is live

```
https://zcjbtpxuhdekpwcxmepn.supabase.co/rest/v1/
```

Schema `api` is applied and exposed, the row caps and landing-table REVOKEs are
in place, and `health.yml` verifies both on every run — the anon probe asserts
`rpc/coverage`, `rpc/catalog`, `quotes` and `funds` answer 200 while
`cvm_fi_diario`, `b3_cotahist`, `cia_account` and `bacen_sgs` under
`Accept-Profile: public` do **not**.

Sign-in is live too: GitHub OAuth, with the page at
`dashboard/static/signin.html`. A user token raises `panel` ids 3 → 50,
`search_funds` 25 → 200, `option_chain` 200 → 2,000 and the query budget
3s → 8s. It does not raise PostgREST's server-wide 1,000-row cap, which is the
same for everyone. Google is configured but not yet enabled.

### Known defects

- **`etf_daily` / `etf_latest` can be absent from production.** Migration 06
  recreates them when missing, so a run whose schema step failed leaves them
  gone and the backfill's "Refresh ETF metrics" job then fails on an assertion
  that is really reporting the earlier failure. The ETF dashboard page depends
  on these views.
- **Dashboard builds are slow** (~25 min). The remaining cost is `fi_investor_mix`
  (4m19) and `fi_investor_split` (3m13), which scan `cvm_fi_perfil` across 24 months.
  Optimizing them needs `EXPLAIN ANALYZE` against real data.
- **`cvm_fip_periodic` holds a pre-fix remnant.** Rows stored before the key was
  corrected carry `row_hash = 'pre-migration-34:<id>'` and are the survivors of
  a key that discarded 72–77% of each file. A backfill of `entity=fip` writes
  the real rows alongside them.

### Deferred by design

- **Historical backfills** for `securit` and `fidc` — the daily window only heals the
  trailing months, so deep history for the recently-fixed field maps needs `backfill.yml`.
- **`VERCEL_DEPLOY_HOOK_URL`** — set. Used only when a manual Daily Ingest dispatch
  sets `rebuild_dashboard=true`; scheduled ingest and fills leave Vercel alone.
- **`APIFY_TOKEN`** — set. The ETF market scrape self-skips without it, and also
  skips (does not fail the daily run) when Apify returns
  `full-permission-actor-not-approved`. Default actor is `apify/playwright-scraper`.
- **Company ↔ ticker** comes from CVM's published FCA valores-mobiliários filing
  (`cia_ticker` → `vw_company_ticker`), never from name matching.
- **Fund → company** now exists as data but is not served. `cvm_fi_cda_acoes.cd_ativo`
  is the published B3 ticker a fund holds, so fund → ticker → `cia_ticker` → company
  is a real join over ingested rows. No `api.*` object exposes it yet, and no edge
  is ever inferred from a name.
- **Prices are not corporate-action adjusted.** `close_unit` (= `close / quotation_factor`,
  both published) makes levels comparable across papers quoted per lot, but a split still
  reads as a jump and `adjusted` is `false` on every row. `b3_corporate_event` holds the
  published events; the adjustment ships once B3's per-label factor convention is verified
  against the tape (`vw_b3_share_count_event`), not before.

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

Current work is **serving**, tracked in `docs/planning/SERVING.md`. Steps 0–2 (the `api`
contract, the agent catalog, the SQL applied) and steps 3 + 6 (row caps inside the `api`
functions, the `silo_api` role, `SET search_path = ''` on every SECURITY DEFINER function,
and REVOKEs on the landing tables) are done in the repo. **Step 7 no longer applies**:
serving is Supabase-native, so there is no gateway to stand up.

What remains is operational, not code: run `analytics-only` to apply the serving SQL to
production, then add `api` to Supabase's Exposed Schemas. Until that apply succeeds,
production's `api` schema is the pre-caps version — see `docs/planning/SERVING.md`.

## What's intentionally not here

- **No ingest REST API, and no PostgREST dump of landing tables.** The pipeline writes to Supabase via GitHub Actions and the CLI. Callers read schema `api` at `https://zcjbtpxuhdekpwcxmepn.supabase.co/rest/v1/` ([api-docs/quickstart.mdx](api-docs/quickstart.mdx), [docs/API.md](docs/API.md)). `serve/` is the local adapter. The old localhost ingest Flask (`app.py` / `src/api/`) is deleted.
- **No fabricated quotes.** The old `b3_calc_api` (non-B3 domain + hard-coded sample dicts) stays deleted. Historical quotations come from B3's public COTAHIST zips (`src/fetchers/b3_fetcher.py` → `b3_cotahist` → `api.quotes`). An unknown ticker returns an empty result, never a guessed last close — `404` from `serve/`, `200 []` from PostgREST, which has no adapter to shape the error. Same contract, different status code.
- **No local Postgres / Docker / Alembic.** Supabase Postgres is the single source of truth. Use `scripts/seed_local_db.py`
  with a local Postgres for offline testing.
- **No Solana oracle.** The Delos Oracle experiment is out of scope.
