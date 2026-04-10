# Architecture

**Analysis Date:** 2026-04-10

## Pattern Overview

**Overall:** Multi-service REST API platform (microservices-lite)

Each data source maps to one independent FastAPI service. Services are stateless at the HTTP layer; disk-level caching and in-memory TTL caching happen inside each service. There is no shared API gateway, message queue, or database — services communicate with upstream public sources only.

**Key Characteristics:**
- Three independent FastAPI services, each owning its own config/models/service/main stack
- No internal service-to-service calls; all data fetched directly from upstream government/exchange sources
- Disk-based file cache (24 h TTL) for CVM; in-memory dict cache (30 min TTL, 64 entries) for B3 CALC
- In-memory pagination: full CSV downloaded first, then sliced per request
- Async everywhere except BACEN (python-bcb is sync; wrapped in `asyncio.to_thread`)

## Services

**CVM Credit API (`src/cvm_api/`):**
- Purpose: Expose fund registry and periodic financial data from `dados.cvm.gov.br`
- Port: 8000
- Entry point: `src/cvm_api/main.py`
- Entities: FIDC, FIP, FIAGRO, SECURIT (each with multiple doc types)
- Upstream: `https://dados.cvm.gov.br/dados/{ENTITY}/DOC/{DOC_TYPE}/DADOS/...`
- Transport: `aiohttp` with rotating DNS resolver for resilience
- Cache: Disk-based (`cache/` dir), 24 h TTL, keyed by MD5 of URL

**BACEN API (`src/bacen_api/`):**
- Purpose: Expose BCB time series, exchange rates, market expectations, and interest rates
- Port: 8002
- Entry point: `src/bacen_api/main.py`
- Upstream: Banco Central APIs via `python-bcb` (SGS, PTAX OData, Expectativas OData, TaxaJuros OData)
- Client: `src/clients/bacen_client.py` — wraps all sync `python-bcb` calls in `asyncio.to_thread`
- Cache: None — upstream is fast enough; python-bcb handles connection pooling

**B3 CALC API (`src/b3_calc_api/`):**
- Purpose: Fixed income pricing (debentures, CRA, CRI) from `calculadorarendafixa.com.br`
- Port: 8001
- Entry point: `src/b3_calc_api/main.py`
- Upstream: `https://calculadorarendafixa.com.br/webservice` (env-configurable via `B3_CALC_BASE_URL`)
- Transport: `httpx.AsyncClient` (initialized at startup, closed at shutdown)
- Cache: In-memory dict with TTL (`CacheManager` in `src/b3_calc_api/services.py`), 30 min TTL, max 64 entries
- Fallback: Hardcoded sample data (`SAMPLE_DEBENTURES`, `SAMPLE_CRAS`, `SAMPLE_CRIS`) used when upstream is unavailable — this is intentional and must be preserved

## Layers (per service)

**Config layer:**
- Purpose: Environment variables, URL patterns, entity/doc-type enums, pagination defaults
- CVM/B3: `BaseConfig` class with class-level constants; `DatasetConfig` for URL pattern maps
- BACEN: Module-level constants (no class), env vars read directly with `os.getenv`
- Examples: `src/cvm_api/config.py`, `src/bacen_api/config.py`, `src/b3_calc_api/config.py`

**Models layer:**
- Purpose: Pydantic v2 request/response contracts
- All models use `ConfigDict`, `model_dump()`, `json_schema_extra` (v2 patterns)
- Generic container: `DataResponse` (entity, doc_type, data: List[Dict], pagination, metadata, timestamp)
- CNPJ cross-entity lookup: `CNPJRegistryResponse` (registrations, periodic_snapshots, emissions)
- Examples: `src/cvm_api/models.py`, `src/bacen_api/models.py`, `src/b3_calc_api/models.py`

**Service layer:**
- Purpose: Upstream I/O, data transformation, caching, validation, pagination
- CVM: `CVMCreditDataService` in `src/cvm_api/services.py`
- BACEN: `BacenClient` in `src/clients/bacen_client.py` (not a service class — a thin async client)
- B3: `B3CalcService` + `CacheManager` in `src/b3_calc_api/services.py`
- Validation: `DataValidator` in `src/validation_utils.py` (CNPJ checksum, CPF, date, currency, security code)

**Routing layer:**
- Purpose: HTTP request handling, FastAPI route declarations, parameter validation
- All files: `src/{service}/main.py`
- Pattern: Single global service instance initialized at module level (CVM/BACEN) or via `@app.on_event("startup")` (B3)
- CORS: `allow_origins=["*"]` on all three services

## Data Flow

**CVM Credit (standard entity/doc request):**

1. HTTP GET `/api/v1/{entity}/{doc_type}?year=&month=&page=&page_size=`
2. `main.py` validates path/query params via FastAPI + enums
3. `CVMCreditDataService.get_data()` normalizes entity/doc_type names and resolves aliases
4. `_validate_parameters()` checks year/month are provided when required by URL pattern
5. `_build_url()` formats URL from `DatasetConfig.{ENTITY}_DATASETS[doc_type]["url_pattern"]`
6. `_download_file()` checks disk cache (24 h TTL); if miss, downloads via `aiohttp` with retry + rotating DNS
7. If ZIP: `_extract_csv_from_zip()` extracts named CSV using `csv_name_pattern`; if plain CSV: decode `latin-1`
8. `_parse_csv_content()` reads `;`-delimited CSV with `csv.DictReader`, strips whitespace, drops empty keys
9. `_validate_data_quality()` runs field-type checks via `DataValidator`
10. `_paginate_data()` slices full in-memory list by `page` and `page_size`
11. Returns `DataResponse` with data slice, `PaginationInfo`, source_url, processing_time, quality report

**CVM CNPJ Cross-Entity Lookup:**

1. HTTP GET `/api/v1/cnpj/{cnpj}?year=&month=`
2. `CVMCreditDataService.get_cnpj_registry()` runs parallel downloads across all entities:
   - Cadastral datasets (FIDC, FIP, FIAGRO) → `CNPJRegistryEntry` list in `registrations`
   - Monthly/periodic datasets (FIDC, FIAGRO) when `month` is provided → `PeriodicSnapshot` list
   - SECURIT emission datasets (CRA, CRI, LCA, LCI) → `EmissionRecord` list in `emissions`
3. Returns `CNPJRegistryResponse` with `found_in` / `not_found_in` entity lists

**BACEN Request:**

1. HTTP GET `/api/v1/bacen/{category}/...`
2. `main.py` handler calls `BacenClient` async method
3. `BacenClient` wraps sync `python-bcb` call in `asyncio.to_thread(_fetch)`
4. `_fetch()` calls `sgs.get()` / `PTAX().get_endpoint(...).query().collect()` etc.
5. `_df_to_records()` converts pandas DataFrame to `List[Dict]`: resets DatetimeIndex, NaN → None, numpy types → Python natives
6. Returns response model with records + timestamp

**B3 CALC Request:**

1. HTTP GET `/api/v1/prices/{symbol}` or `/api/v1/securities/{type}`
2. `B3CalcService` checks in-memory `CacheManager` by composite key (`b3calc:price:{type}:{code}:{date}`)
3. If miss: `_request()` fetches via `httpx.AsyncClient` with retry
4. On connection/timeout error: falls back to `_generate_sample_price()` (random but plausible values with `_sample: True` marker)
5. `_parse_price_response()` extracts fields from multi-alias response (handles Portuguese/English keys)
6. Stores result in cache, returns `SecurityPriceResponse`

## Key Abstractions

**`DatasetConfig` (CVM URL routing):**
- Purpose: Maps `(entity, doc_type)` pairs to URL pattern strings and ZIP/CSV metadata
- Location: `src/cvm_api/config.py`
- Pattern: Static class dicts (`FIDC_DATASETS`, `FIP_DATASETS`, etc.) with `get_dataset_config(entity, doc_type)` factory
- Used by: `CVMCreditDataService._build_url()` and `_validate_parameters()`

**`RotatingDNSResolver` (CVM network resilience):**
- Purpose: Rotates through configurable nameservers (`CVM_DNS_NAMESERVERS` env var) to work around CVM's unreliable DNS
- Location: `src/cvm_api/services.py`
- Pattern: `aiohttp.abc.AbstractResolver` subclass; per-attempt nameserver rotation via `_get_rotated_nameservers(attempt)`

**`CacheManager` (B3 CALC in-memory cache):**
- Purpose: TTL + max-size bounded dict; async-safe via `asyncio.Lock`
- Location: `src/b3_calc_api/services.py`
- Pattern: FIFO eviction on size limit; TTL checked on `get()`, expired entries removed lazily

**`BacenClient` (BACEN async wrapper):**
- Purpose: Bridges FastAPI async event loop with sync `python-bcb` library
- Location: `src/clients/bacen_client.py`
- Pattern: All public methods are `async`, each wraps a sync inner `_fetch()` function via `asyncio.to_thread`
- `_df_to_records()` normalizes pandas/numpy types to JSON-serializable Python primitives

**`DataValidator` (shared validation):**
- Purpose: CNPJ/CPF checksum, date format, numeric, currency, security code validation
- Location: `src/validation_utils.py`
- Pattern: Dispatcher dict (`self.validators`) keyed by type name; called by `CVMCreditDataService._validate_data_quality()`

**Dual-run import guard:**
- Purpose: Allow each `main.py` to be run as `python -m uvicorn src.X.main:app` (package mode) or as a direct script
- Pattern:
  ```python
  if __package__:
      from .config import config
  else:
      from config import config
  ```
- Applies to: `src/cvm_api/main.py`, `src/bacen_api/main.py`, `src/b3_calc_api/main.py`, `src/cvm_api/services.py`, `src/b3_calc_api/services.py`

## Entry Points

**`src/cvm_api/main.py`:**
- Invoked by: `python -m uvicorn src.cvm_api.main:app` or Docker
- Creates: `CVMCreditDataService()` at module load
- Routes: `/api/v1/{fidc,fip,fiagro,securit}/{doc_type}`, `/api/v1/cnpj/{cnpj}`

**`src/bacen_api/main.py`:**
- Invoked by: `python -m uvicorn src.bacen_api.main:app` or Docker
- Creates: `BacenClient()` at module load
- Routes: `/api/v1/bacen/sgs/...`, `/api/v1/bacen/ptax/...`, `/api/v1/bacen/expectativas/...`, `/api/v1/bacen/taxas_juros/...`

**`src/b3_calc_api/main.py`:**
- Invoked by: `python -m uvicorn src.b3_calc_api.main:app` or Docker
- Creates: `B3CalcService()` via `@app.on_event("startup")`; `await service.close()` on shutdown
- Routes: `/api/v1/prices/{symbol}`, `/api/v1/securities/{type}`, `/api/v1/indexes`, `/api/v1/market-data`

**`src/tools/backfill.py`:**
- Invoked by: `python -m src.tools.backfill --entity FIDC --doc-type INF_MENSAL`
- Purpose: CLI bulk historical downloader; uses `ThreadPoolExecutor` (sync `requests`, not aiohttp); tracks progress in `ProgressTracker`; independent from the API services

## Error Handling

**Strategy:** Translate upstream exceptions to HTTP status codes at route level; surface validation errors as 400, upstream failures as 502/500.

**Patterns:**
- `ValueError` → `HTTPException(400)` (validation failures, bad parameters)
- `FileNotFoundError` → `HTTPException(404)` (CVM 404 on unavailable period)
- `Exception` → `HTTPException(500/502)` (network, parse failures)
- BACEN upstream failures → `HTTPException(502, "BCB SGS error: ...")`
- B3 CALC upstream failures → transparent fallback to sample data (no error surfaced to client)
- All services register a catch-all `@app.exception_handler(Exception)` for unhandled errors

## Cross-Cutting Concerns

**Logging:** `logging.basicConfig` at `INFO` level; `logging.getLogger(__name__)` per module; structured as `%(asctime)s - %(name)s - %(levelname)s - %(message)s`

**Validation:** FastAPI query/path param validation for types and ranges; business-rule validation in `DataValidator`; CNPJ/date field validation in `CVMCreditDataService._validate_data_quality()`

**Authentication:** None — all three services use `allow_origins=["*"]` and accept unauthenticated requests

**Caching (CVM):** Disk files under `cache/` dir; `.cache` binary file + `.meta` JSON file (url, size, timestamp) per URL hash; `_is_cache_valid()` checks age in hours against `max_age_hours=24`

---

*Architecture analysis: 2026-04-10*
