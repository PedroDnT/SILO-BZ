# External Integrations

**Analysis Date:** 2026-05-05

## APIs & External Services

**CVM (Comissão de Valores Mobiliários):**
- Brazilian Securities Commission public fund data repository
- Endpoint: `https://dados.cvm.gov.br/` (HTTP ZIP/CSV downloads)
- Data: FI, FIDC, FIP, FIAGRO, FII, SECURIT fund disclosures
- SDK/Client: Custom `src/fetchers/cvm_fetcher.CVMFetcher` (aiohttp-based)
- Features: 
  - DNS nameserver rotation via `RotatingDNSResolver` (`src/fetchers/cvm_fetcher.py`)
  - Configurable retry + exponential backoff
  - On-disk ZIP caching in `cache/` directory (persistent across runs)

**BACEN (Banco Central do Brasil):**
- Brazilian Central Bank economic time series and exchange rates
- Endpoints: SGS (Sistema Gerenciador de Séries), PTAX, Expectativas (Focus bulletin), TaxaJuros
- SDK/Client: `python-bcb 0.3.0` (`bcb`, `sgs`, `PTAX`, `Expectativas`, `TaxaJuros`)
- Implementation: `src/fetchers/bacen_fetcher.BacenClient` wraps python-bcb in asyncio
- Data: 
  - SGS: SELIC, CDI, IPCA, IGPM, USD/BRL, EUR/BRL, POUPANCA, PIB
  - PTAX: USD, EUR, GBP, JPY, ARS exchange rates
  - Expectativas: Market consensus for inflation, Selic, GDP

## Data Storage

**Databases:**
- PostgreSQL 14+ (via Supabase)
  - Connection: `SUPABASE_URL` (https URL) + `SUPABASE_SERVICE_KEY` (service role token)
  - Client: `supabase-py 2.3.0+` (`src/store/supabase_client.get_supabase_client()`)
  - Schema: `src/store/schema.sql` (idempotent, uses `CREATE TABLE IF NOT EXISTS`)
  - Tables (existing):
    - **CVM data**: `cvm_fi_diario` (partitioned by year), `cvm_fi_cda`, `cvm_fi_perfil`,
      `cvm_fidc_mensal`, `cvm_fiagro_mensal`, `cvm_fip_periodic`,
      `cvm_fii_mensal`, `cvm_fii_periodic`, `cvm_securit_mensal`, `cvm_securit_dfin`
    - **BACEN data**: `bacen_sgs` (SELIC/CDI/IPCA/IGP-M), `bacen_ptax` (USD/EUR/GBP/JPY/ARS), `bacen_expectativas`
    - **Audit log**: `cvm_ingest_log` (entity/doc_type/period/status/rows_upserted per run)
  - Tables (planned — Phases 1–2):
    - `cvm_fidc_tranche` — one row per FIDC fund × tranche class × period (tab_X_2)
    - `cvm_fidc_tranche_flows` — series-level cash flows per month (tab_X_4)
    - `cvm_fidc_aging` — delinquency aging buckets (tab_VI)
    - `cvm_securit_serie` — one row per CRA/CRI/OTS series with status and rating (classe CSV)
    - `cvm_securit_fluxo` — monthly payments by tranche class (fluxo_caixa CSV)
  - Upsert strategy: Chunked (500-row batches) with `ON CONFLICT` on named UNIQUE constraints
  - Rate limiting: None (Supabase handles automatically)

**File Storage:**
- Local filesystem only (`cache/` directory)
  - CVM ZIP files cached on disk with SHA256 hash for deduplication
  - No cloud storage (S3, GCS, etc.)

**Caching:**
- In-memory: None (stateless)
- On-disk: CVM ZIP/CSV files in `cache/` with filename-based deduplication

## Authentication & Identity

**Auth Provider:**
- Custom (API keys only, no OAuth/OIDC)

**Implementation:**
- Supabase service role key (`SUPABASE_SERVICE_KEY`) — direct database access, bypasses RLS
- No user authentication; pipeline runs as service account
- CVM/BACEN are public endpoints (no auth required)

## Monitoring & Observability

**Error Tracking:**
- None (no Sentry, Rollbar, etc.)

**Logs:**
- Standard Python logging to stdout
  - Level: Configurable via `LOG_LEVEL` env var (default: INFO)
  - Loggers instantiated per module: `logging.getLogger(__name__)`
  - No log aggregation (local to execution environment)

**Audit Trail:**
- Database-backed: `cvm_ingest_log` table records every run
  - `run_id` (UUID)
  - `entity`, `doc_type`, `period_year`, `period_month`
  - `rows_upserted`, `status` (ok | error | skipped), `error_msg`
  - `started_at`, `finished_at` (TIMESTAMPTZ)

## CI/CD & Deployment

**Hosting:**
- GitHub Actions (no Vercel, no Docker, no external platform)
- Runs on `ubuntu-latest`
- Python 3.11 configured in workflow (note: source specifies 3.12, workflow uses 3.11)

**CI Pipeline:**
- `.github/workflows/daily_ingest.yml`
  - Scheduled: `0 6 * * *` (06:00 UTC = 03:00 BRT)
  - Manual trigger: `workflow_dispatch` with optional inputs
    - `mode`: daily | backfill
    - `start_year`: for backfill mode
    - `entity`: filter to single CVM entity (optional)
  - Steps:
    1. Checkout code
    2. Install Python 3.11
    3. Cache pip dependencies
    4. Run `python -m src.pipeline.run_daily` (scheduled) or `python -m src.pipeline.run_backfill` (manual)
  - Secrets passed: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`

**Deployment:**
- No containerization (direct Python execution)
- No code signing or artifact registry
- Git-based: Latest main branch code runs in workflow

## Environment Configuration

**Required env vars:**
- `SUPABASE_URL` — PostgreSQL connection (Supabase format)
- `SUPABASE_SERVICE_KEY` — Service role API key

**Optional env vars:**
- `CVM_DNS_NAMESERVERS` — Comma-separated list of DNS IPs
- `CVM_REQUEST_TIMEOUT` — HTTP timeout (seconds)
- `CVM_MAX_RETRIES` — Retry count
- `CVM_RETRY_DELAY` — Retry backoff (seconds)
- `TZ` — Timezone (default: America/Sao_Paulo)
- `LOG_LEVEL` — Python logging level (default: INFO)

**Secrets location:**
- GitHub Actions repository secrets (`.github/workflows/daily_ingest.yml` references `${{ secrets.SUPABASE_URL }}` and `${{ secrets.SUPABASE_SERVICE_KEY }}`)

**Local development:**
- `.env` file (git-ignored, copy from `.env.example`)

## Webhooks & Callbacks

**Incoming:**
- None (pipeline is pull-only: fetches CVM/BACEN, writes to Supabase)

**Outgoing:**
- None (no downstream integrations, no pub/sub)

**Design:**
- Downstream consumers query Supabase directly (no API gateway)
- Historical note: Previous FastAPI services were removed in consolidation

---

*Integration audit: 2026-05-06*
