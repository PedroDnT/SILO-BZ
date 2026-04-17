# Codebase Structure

**Analysis Date:** 2026-04-10

## Directory Layout

```
iliquid_nightly/
├── src/
│   ├── cvm_api/              # CVM Credit Market API service (port 8000)
│   │   ├── config.py         # BaseConfig class, DatasetConfig, entity/doc-type enums
│   │   ├── models.py         # Pydantic v2 response models
│   │   ├── services.py       # CVMCreditDataService (download, parse, cache, paginate)
│   │   ├── main.py           # FastAPI app + route handlers
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── README.md
│   ├── bacen_api/            # BACEN Public Data API service (port 8002)
│   │   ├── config.py         # Module-level constants (no BaseConfig class)
│   │   ├── models.py         # Pydantic v2 response models
│   │   ├── main.py           # FastAPI app + route handlers
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── README.md
│   ├── b3_calc_api/          # B3 CALC Fixed Income Pricing API service (port 8001)
│   │   ├── config.py         # BaseConfig class, SecurityType enum, sample data constants
│   │   ├── models.py         # Pydantic v2 response models
│   │   ├── services.py       # B3CalcService + CacheManager
│   │   ├── main.py           # FastAPI app + route handlers
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── README.md
│   ├── clients/
│   │   └── bacen_client.py   # Async wrapper around python-bcb
│   ├── tools/
│   │   ├── backfill.py            # CLI bulk historical CVM downloader
│   │   ├── backfill_config.py     # Entity/period/URL configs for backfill
│   │   ├── progress_tracker.py    # Resume-capable download progress state
│   │   └── cvm_dir_mapper.py      # Maps CVM directory structure
│   └── validation_utils.py        # Shared CNPJ/CPF/date/currency validators
├── tests/
│   ├── conftest.py                # Shared pytest fixtures (CSV samples, mock sessions, temp dirs)
│   ├── test_csv_parsing.py
│   ├── test_cvm_url_patterns.py
│   ├── test_data_validation.py
│   └── test_live_endpoints.py
├── scripts/
│   └── check_all_endpoints.py    # Dev tool: hit all live CVM endpoints and report status
├── docs/                         # Static API documentation service (port 8080)
│   ├── docs_server.py
│   ├── static/index.html
│   ├── Dockerfile
│   └── requirements.txt
├── backfill-tool/                # Standalone backfill tool package (mirrors src/tools)
├── memory-bank/                  # AI assistant context files (activeContext, decisionLog, etc.)
├── planning/                     # Specification/planning docs (read-only reference)
├── .planning/                    # GSD codebase maps (this file's directory)
│   └── codebase/
├── docker-compose.yml            # Orchestrates cvm_api:8000, b3_calc_api:8001, bacen_api:8002, docs:8080
├── requirements.txt              # Aggregate dev dependencies (not per-service)
├── docs.json                     # Mintlify documentation site config
├── *.mdx                         # Mintlify documentation pages (start, overview, cvm-api, etc.)
├── TODO                          # Tracked P1/P2/P3 backlog
└── .env.example                  # Environment variable template
```

## Directory Purposes

**`src/cvm_api/`:**
- Purpose: Self-contained FastAPI service for CVM credit market data
- Contains: config, models, service logic, route handlers, Dockerfile
- Key files: `src/cvm_api/services.py` (core ingestion logic), `src/cvm_api/config.py` (URL pattern registry)

**`src/bacen_api/`:**
- Purpose: Self-contained FastAPI service for BACEN public data
- Contains: config (module constants), models, route handlers, Dockerfile
- Key files: `src/bacen_api/main.py` (all routes), `src/bacen_api/config.py` (series codes, endpoint names)
- Note: No `services.py` — route handlers call `BacenClient` directly

**`src/b3_calc_api/`:**
- Purpose: Self-contained FastAPI service for B3 CALC fixed income pricing
- Contains: config, models, service with in-memory cache, route handlers, Dockerfile
- Key files: `src/b3_calc_api/services.py` (B3CalcService + CacheManager)

**`src/clients/`:**
- Purpose: Reusable async client wrappers for external libraries
- Contains: `bacen_client.py` — used by `src/bacen_api/main.py`
- Convention: Clients wrap blocking libraries with `asyncio.to_thread`; return `List[Dict]` not DataFrames

**`src/tools/`:**
- Purpose: CLI utilities for offline bulk operations
- Contains: Backfill CLI (`backfill.py`), config (`backfill_config.py`), progress tracking (`progress_tracker.py`), directory mapper (`cvm_dir_mapper.py`)
- Run: `python -m src.tools.backfill --entity FIDC --doc-type INF_MENSAL` from repo root

**`src/validation_utils.py`:**
- Purpose: Shared validators imported by `src/cvm_api/services.py`
- Provides: `DataValidator` (class), `validator` (singleton instance), `ValidationError`, `ValidationWarning`
- Validators: CNPJ checksum, CPF checksum, date formats, numeric, percentage, currency, security code, email, phone

**`tests/`:**
- Purpose: Pytest test suite; run from repo root with `PYTHONPATH=. pytest tests/ -v`
- 58 tests, 100% passing
- Markers: `unit`, `integration`, `slow`, `cvm`, `validation`, `parsing`

**`cache/` and `temp/` (runtime-generated, gitignored):**
- `cache/`: CVM disk cache; `.cache` (binary) + `.meta` (JSON) per URL hash
- `temp/`: Temporary extraction staging area

**`data/` (runtime-generated, gitignored):**
- Created by `CVMBackfiller`; organized as `data/cvm_backfill/{ENTITY}/{DOC_TYPE}/{period}.csv`

## Key File Locations

**Entry Points:**
- `src/cvm_api/main.py`: CVM API app, route handlers, service initialization
- `src/bacen_api/main.py`: BACEN API app, all route handlers
- `src/b3_calc_api/main.py`: B3 CALC API app, startup/shutdown lifecycle
- `src/tools/backfill.py`: CLI entry point for bulk historical downloads

**Configuration:**
- `src/cvm_api/config.py`: URL pattern registry, entity/doc-type enums, request settings
- `src/bacen_api/config.py`: Module constants — WELL_KNOWN_SGS, EXPECTATIVAS_ENDPOINTS, COMMON_CURRENCIES
- `src/b3_calc_api/config.py`: BaseConfig class, SecurityType enum, SAMPLE_* data, B3_CALC_ENDPOINTS
- `.env.example`: All configurable environment variables with defaults
- `docker-compose.yml`: Service orchestration, port mapping

**Core Logic:**
- `src/cvm_api/services.py`: Full CVM ingestion pipeline (download → extract → parse → validate → paginate)
- `src/clients/bacen_client.py`: All BACEN data access, DataFrame-to-dict conversion
- `src/b3_calc_api/services.py`: B3 pricing, fallback logic, in-memory cache
- `src/validation_utils.py`: Brazilian financial data validators

**Models:**
- `src/cvm_api/models.py`: `DataResponse`, `PaginationInfo`, `CNPJRegistryResponse`, `PeriodicSnapshot`, `EmissionRecord`
- `src/bacen_api/models.py`: `SGSSeriesResponse`, `PTAXRateResponse`, `ExpectativasResponse`, `TaxaJurosResponse`
- `src/b3_calc_api/models.py`: `SecurityPriceResponse`, `SecurityListResponse`, `PriceCalculationResult`

**Testing:**
- `tests/conftest.py`: Fixtures for CSV content, mock HTTP sessions, temp dirs
- `tests/test_csv_parsing.py`: CSV ingestion behavior
- `tests/test_cvm_url_patterns.py`: URL pattern generation for all entity/doc-type combinations
- `tests/test_data_validation.py`: DataValidator rules and edge cases
- `tests/test_live_endpoints.py`: Integration tests against live CVM endpoints

## Naming Conventions

**Files:**
- Service modules: `snake_case.py` matching their role (`config.py`, `models.py`, `services.py`, `main.py`)
- Test files: `test_{subject}.py`
- Tool files: `snake_case.py` describing the operation (`backfill.py`, `progress_tracker.py`)

**Classes:**
- `PascalCase`: `CVMCreditDataService`, `BacenClient`, `B3CalcService`, `CacheManager`, `DataValidator`, `RotatingDNSResolver`
- Enums: `PascalCase` with descriptive value strings: `EntityType.FIDC = "fidc"`, `SECURITDocType.CRA_MENSAL = "cra_mensal"`

**Functions/methods:**
- `snake_case` throughout
- Private helpers prefixed with `_`: `_download_file()`, `_parse_csv_content()`, `_build_url()`
- Async methods named identically to sync intent: `get_data()`, `get_security_price()`

**Constants:**
- `UPPER_SNAKE_CASE` for module-level constants: `WELL_KNOWN_SGS`, `SAMPLE_DEBENTURES`, `B3_CALC_ENDPOINTS`
- Config class attributes: `UPPER_SNAKE_CASE` on class body: `DEFAULT_PAGE_SIZE = 100`

**URL routes:**
- Pattern: `/api/v1/{entity}/{doc_type}` (CVM), `/api/v1/bacen/{category}/...` (BACEN), `/api/v1/{resource}` (B3)
- All lowercase, hyphens for multi-word segments (e.g., `/api/v1/bacen/taxas_juros/`)

## Where to Add New Code

**New CVM entity or doc type:**
- Add enum value to `EntityType`, `FIDCDocType`, etc. in `src/cvm_api/config.py`
- Add dataset dict entry in `DatasetConfig.{ENTITY}_DATASETS` in `src/cvm_api/config.py`
- Add route handler in `src/cvm_api/main.py` following existing handler pattern
- Extend validation config in `CVMCreditDataService._get_validation_config()` in `src/cvm_api/services.py`

**New BACEN data source:**
- Add endpoint constant to `src/bacen_api/config.py`
- Add async method to `BacenClient` in `src/clients/bacen_client.py` (wrap sync call in `asyncio.to_thread`)
- Add response model to `src/bacen_api/models.py`
- Add route handler to `src/bacen_api/main.py`

**New B3 CALC security type:**
- Add value to `SecurityType` enum in `src/b3_calc_api/config.py`
- Add endpoint mapping and sample data constants in `src/b3_calc_api/config.py`
- Add code pattern to `B3CalcService.CODE_PATTERNS` in `src/b3_calc_api/services.py`

**New shared validator:**
- Add method to `DataValidator` in `src/validation_utils.py`
- Register in `self.validators` dict in `DataValidator.__init__()`

**New CLI tool:**
- Add to `src/tools/`; run via `python -m src.tools.{name}` from repo root

**New tests:**
- Unit/integration: `tests/test_{subject}.py`
- Fixtures: add to `tests/conftest.py`
- Run with: `PYTHONPATH=. pytest tests/test_{subject}.py -v`

## Special Directories

**`cache/`:**
- Purpose: Disk cache for CVM downloaded files
- Generated: Yes (at runtime by `CVMCreditDataService.__init__`)
- Committed: No (gitignored)
- Structure: `{md5_of_url}.cache` + `{md5_of_url}.meta` pairs

**`temp/`:**
- Purpose: Temporary staging for ZIP extraction (cleared between requests conceptually)
- Generated: Yes (at runtime)
- Committed: No (gitignored)

**`data/cvm_backfill/`:**
- Purpose: Local storage for backfill downloads organized by entity/doc-type
- Generated: Yes (by `CVMBackfiller`)
- Committed: No (gitignored)
- Structure: `data/cvm_backfill/{ENTITY}/{DOC_TYPE}/{YYYYMM}.csv`

**`memory-bank/`:**
- Purpose: Persistent AI assistant context (activeContext, decisions, progress, patterns)
- Generated: No (maintained manually)
- Committed: Yes — update `progress.md` and `decisionLog.md` after significant changes

**`.planning/codebase/`:**
- Purpose: GSD codebase maps (this file's directory)
- Generated: By GSD map-codebase command
- Committed: Yes

---

*Structure analysis: 2026-04-10*
