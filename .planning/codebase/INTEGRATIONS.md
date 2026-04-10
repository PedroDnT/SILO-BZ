# External Integrations

**Analysis Date:** 2026-04-10

## Official Brazilian Financial Data Sources

This is the core purpose of the codebase: bridging public Brazilian regulatory/market data APIs into structured REST endpoints.

---

### CVM — Comissão de Valores Mobiliários

**What it is:** Brazil's securities regulator (equivalent of SEC). Publishes fund disclosure data as CSV/ZIP files over HTTP.

**Base URL:** `https://dados.cvm.gov.br/dados`

**Integration method:** Direct HTTP file download via `aiohttp` in `src/cvm_api/services.py`. No authentication required. Files are static CSVs and ZIPs at predictable URL patterns.

**Data served:**
- `FIDC` (credit rights funds): mensal ZIP, cadastral CSV, trimestral CSV, anual CSV
- `FIP` (private equity funds): inf_quadrimestral, inf_trimestral, cadastral, dfin — all yearly CSVs
- `FIAGRO` (agro investment funds): mensal ZIP, cadastral CSV, trimestral CSV, anual CSV
- `SECURIT` (securitization companies): cra_mensal, cri_mensal, ots_mensal, lca_mensal, lci_mensal — all yearly ZIPs

**URL pattern examples:**
```
https://dados.cvm.gov.br/dados/FIDC/DOC/INF_MENSAL/DADOS/inf_mensal_fidc_{year}{month:02d}.zip
https://dados.cvm.gov.br/dados/SECURIT/DOC/INF_MENSAL_CRA/DADOS/inf_mensal_cra_{year}.zip
```
Full pattern map in `src/cvm_api/config.py` → `DatasetConfig`

**Parsing details:** latin-1 encoding, `;` delimiter, empty-string normalization. Logic in `src/cvm_api/services.py` → `CVMCreditDataService`.

**Resilience mechanisms:**
- DNS rotation over Cloudflare/Google/Quad9 nameservers (`CVM_DNS_NAMESERVERS` env var, default `1.1.1.1,8.8.8.8,9.9.9.9`)
- Custom `RotatingDNSResolver` (implements `aiohttp.abc.AbstractResolver`) in `src/cvm_api/services.py`
- 3 retries with 2-second delay (`MAX_RETRIES=3`, `RETRY_DELAY=2`)
- 300-second request timeout
- On-disk cache with 24-hour TTL at `./cache/` (MD5-keyed `.cache` + `.meta` JSON files)

**Auth:** None (open public data)

---

### BACEN — Banco Central do Brasil

**What it is:** Brazil's central bank. Publishes macroeconomic time series, exchange rates, Focus market expectations, and interest rates via OData/REST APIs.

**Integration method:** `python-bcb>=0.3.0` (third-party sync library). Wrapped in async via `asyncio.to_thread` in `src/clients/bacen_client.py` → `BacenClient`.

**Data served via `python-bcb`:**
- **SGS** (Sistema Gerenciador de Séries Temporais): time series by numeric code. Well-known codes in `src/bacen_api/config.py`: SELIC_META=432, SELIC_DIARIA=11, CDI=12, IPCA=433, IGPM=189, INPC=188, USDBRL=1, EURBRL=21619, POUPANCA=25, PIB=4380.
- **PTAX** (exchange rates): USD/BRL daily or period, any currency daily or period, currency list. Uses BACEN OData endpoints like `CotacaoDolarDia`, `CotacaoDolarPeriodo`, `CotacaoMoedaDia`, `CotacaoMoedaPeriodo`.
- **Expectativas** (Focus bulletin — market expectations): endpoints include `ExpectativasMercadoAnuais`, `ExpectativasMercadoMensais`, `ExpectativasMercadoTrimestrais`, `ExpectativasMercadoSelic`, `ExpectativasMercadoTop5Anuais`, `ExpectativasMercadoTop5Mensais`, `ExpectativasMercadoInflacao12Meses`, `InstituicoesCreditoras`.
- **TaxaJuros** (interest rates): OData endpoint `TaxasJurosMercadoImobiliario`.

**Auth:** None (open public data accessed via `python-bcb`)

**Client location:** `src/clients/bacen_client.py` — shared async wrapper used by `src/bacen_api/main.py`

---

### B3 CALC — calculadorarendafixa.com.br

**What it is:** B3's fixed income pricing calculator for debentures, CRA, and CRI.

**Base URL:** `https://calculadorarendafixa.com.br/webservice` (env-configurable: `B3_CALC_BASE_URL`)

**Integration method:** `httpx.AsyncClient` in `src/b3_calc_api/services.py` → `B3CalcService`.

**Endpoints called:**
```
GET /debentures          → list debentures
GET /cra                 → list CRAs
GET /cri                 → list CRIs
GET /debentures/price    → price calculation for a debenture
GET /cra/price           → price calculation for CRA
GET /cri/price           → price calculation for CRI
GET /indexes             → current market indexes (CDI, SELIC, IPCA)
```
Full endpoint map in `src/b3_calc_api/config.py` → `B3_CALC_ENDPOINTS`.

**Security type auto-detection by code format:**
- Debenture: `^[A-Z]{4}[0-9]{2}$` (e.g., `VALE12`)
- CRI/CRA: `^[0-9]{2}[A-Z]{1}[0-9]{7}-[0-9]{2}$` (e.g., `22A0001234-11`)

**Fallback behavior:** If the upstream is unavailable (404, network error, timeout), the service returns sample data from `SAMPLE_DEBENTURES`, `SAMPLE_CRAS`, `SAMPLE_CRIS`, `SAMPLE_INDEXES` in `src/b3_calc_api/config.py`. **This fallback is intentional — do not remove.**

**In-memory cache:** 30-minute TTL, max 64 entries, FIFO eviction — `CacheManager` in `src/b3_calc_api/services.py`.

**Auth:** None (public pricing calculator)

---

## Data Storage

**Databases:** None. No SQL or NoSQL database is used anywhere in the codebase.

**File Storage:**
- `./cache/` — CVM on-disk response cache; files named by MD5 hash of URL + `.cache`/`.meta`. 24-hour TTL. Created at service startup.
- `./temp/` — Temporary extraction directory for CVM ZIP files. Created at service startup.
- `./data/` — Created in Docker image but not populated by code.

**Caching:**
- CVM: Disk-based, 24-hour TTL, in `src/cvm_api/services.py`
- B3 CALC: In-memory (process-local), 30-minute TTL, in `src/b3_calc_api/services.py`
- BACEN: No caching layer; `python-bcb` fetches on every call

## Authentication & Identity

**Auth Provider:** None. All three upstream data sources are unauthenticated public APIs.

**CORS:** All services use permissive `allow_origins=["*"]` CORS middleware (FastAPI `CORSMiddleware`).

**ANBIMA:** Not implemented (noted as P3 backlog in `TODO`; requires paid OAuth2 credentials).

## Monitoring & Observability

**Error Tracking:** None configured (no Sentry, Datadog, etc.)

**Logs:**
- Standard Python `logging` module, configured via `LOG_LEVEL` env var (default: `info`)
- `structlog==24.1.0` present in `src/b3_calc_api/requirements.txt` but not confirmed wired
- `rich==13.7.0` used in CLI tools for terminal output

**Health Checks:**
- Each service exposes `GET /health` returning `HealthResponse` (status, timestamp, version)
- Docker healthcheck: `curl -f http://localhost:{port}/health` every 30s

## CI/CD & Deployment

**Hosting:** Docker Compose (bridge network `br_finance`). No cloud-specific deployment config detected.

**CI Pipeline:**
- `.github/workflows/claude.yml` — Claude Code action on `@claude` mentions
- `.github/workflows/claude-code-review.yml` — automated code review
- `.github/workflows/update-docs.yml` — documentation automation
- `.github/workflows/jekyll-gh-pages.yml` — GitHub Pages deployment
- No automated test runner in CI detected

## Environment Configuration

**Required env vars (from `.env.example`):**

| Variable | Default | Purpose |
|---|---|---|
| `CVM_DNS_NAMESERVERS` | `1.1.1.1,8.8.8.8,9.9.9.9` | DNS fallback for CVM downloads |
| `B3_CALC_BASE_URL` | `https://calculadorarendafixa.com.br/webservice` | B3 CALC upstream |
| `BACEN_API_HOST` | `0.0.0.0` | BACEN service bind address |
| `BACEN_API_PORT` | `8002` | BACEN service port |
| `RATE_LIMIT_ENABLED` | `true` | Rate limiting toggle (not yet wired) |
| `RATE_LIMIT_REQUESTS` | `100` | Rate limit request count |
| `RATE_LIMIT_WINDOW` | `60` | Rate limit window (seconds) |
| `CACHE_TTL` | `3600` | Cache TTL (seconds) |
| `TZ` | `America/Sao_Paulo` | Timezone |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

**Secrets location:** `.env` file (gitignored). No secrets manager in use.

## Webhooks & Callbacks

**Incoming:** None

**Outgoing:** None

---

## Data Flow Summary (Source → API)

```
dados.cvm.gov.br (HTTP CSV/ZIP)
    → aiohttp download (RotatingDNSResolver)
    → disk cache (./cache/, 24h TTL)
    → ZIP extraction if needed
    → CSV parse (latin-1, ;-delimited)
    → in-memory pagination
    → FastAPI JSON response (port 8000)

api.bcb.gov.br / webservices PTAX / OData services (via python-bcb)
    → asyncio.to_thread(python-bcb sync call)
    → pandas DataFrame
    → _df_to_records() normalization
    → FastAPI JSON response (port 8002)

calculadorarendafixa.com.br/webservice (HTTP JSON)
    → httpx.AsyncClient
    → in-memory cache (30-min TTL, 64 entries)
    → fallback to SAMPLE_* constants if unavailable
    → FastAPI JSON response (port 8001)
```

---

*Integration audit: 2026-04-10*
