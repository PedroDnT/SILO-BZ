# Codebase Structure

**Analysis Date:** 2026-05-05

## Directory Layout

```
iliquid_nightly/
├── .github/
│   └── workflows/
│       └── daily_ingest.yml         # GitHub Actions cron (06:00 UTC daily)
├── .planning/
│   └── codebase/                    # This directory — GSD docs
├── cache/                           # On-disk fetcher cache (24-hour TTL)
├── temp/                            # Temporary files during ZIP extraction
├── src/
│   ├── __init__.py
│   ├── fetchers/
│   │   ├── __init__.py
│   │   ├── cvm_fetcher.py           # HTTP download + ZIP extraction + CSV parse
│   │   ├── cvm_config.py            # URL templates + dataset metadata
│   │   └── bacen_fetcher.py         # Async wrapper around python-bcb
│   ├── parsers/
│   │   ├── __init__.py
│   │   └── validation.py            # Field validators (CNPJ, date, numeric)
│   ├── store/
│   │   ├── __init__.py
│   │   ├── supabase_client.py       # Upsert client + chunking logic
│   │   └── schema.sql               # Canonical Postgres schema
│   └── pipeline/
│       ├── __init__.py
│       ├── cvm_pipeline.py          # CVMIngestor orchestration
│       ├── bacen_pipeline.py        # BacenIngestor orchestration
│       ├── run_daily.py             # Daily incremental update entry point
│       └── run_backfill.py          # Historical backfill CLI
├── tests/
│   ├── conftest.py                  # pytest fixtures + mocks
│   ├── test_cvm_fetch_parse.py      # CVMFetcher offline tests
│   ├── test_data_validation.py      # DataValidator unit tests
│   └── test_ingestor.py             # Ingestor logic tests (no Supabase)
├── scripts/
│   └── explore_cvm_output.py        # Utility for inspecting raw CVM data
├── .env.example                     # Template: SUPABASE_URL, SUPABASE_SERVICE_KEY
├── .gitignore
├── .python-version                  # Python 3.12
├── pytest.ini
├── requirements.txt                 # Dependencies
├── README.md                        # Project overview
└── TODO                             # Backlog items
```

## Directory Purposes

**`.github/workflows/`:**
- Purpose: GitHub Actions orchestration
- Contains: Daily cron, manual workflow_dispatch
- Key files: `daily_ingest.yml` schedules `run_daily.py` at 06:00 UTC
- Committed: Yes

**`cache/` and `temp/`:**
- Purpose: Runtime state (not source code)
- Generated: Yes (created by CVMFetcher on first run)
- Committed: No (in .gitignore)

**`src/fetchers/`:**
- Purpose: Data source connectors — HTTP + SDK calls only
- Contains: CVM (HTTP + DNS rotation + retry), BACEN (python-bcb wrapper)
- Key files:
  - `cvm_fetcher.py`: CVMFetcher class with URL validation, caching, ZIP extraction
  - `cvm_config.py`: FetcherConfig + DatasetConfig with 6 entity × N doc_types
  - `bacen_fetcher.py`: BacenClient wraps SGS, PTAX, Expectativas

**`src/parsers/`:**
- Purpose: Data normalization and validation rules
- Contains: Field validators (CNPJ checksum, date format, numeric ranges)
- Key files:
  - `validation.py`: DataValidator with regex patterns and rule functions
- Note: CSV extraction is co-located in `cvm_fetcher.py` (needs ZIP filename context)

**`src/store/`:**
- Purpose: Database abstraction and schema management
- Contains: Supabase upsert client, chunking logic, canonical schema
- Key files:
  - `supabase_client.py`: `get_supabase_client()` factory, `upsert_rows()` chunked upsert
  - `schema.sql`: 9 CVM tables (FI/FIDC/FIP/FIAGRO/FII/SECURIT) + 3 BACEN tables + audit log
- Bootstrap: `psql "$SUPABASE_DB_URL" -f src/store/schema.sql` (idempotent, CREATE TABLE IF NOT EXISTS)

**`src/pipeline/`:**
- Purpose: Orchestration — wires FETCH→PARSE→STORE stages
- Contains: Entity-specific ingestors, CLI entry points
- Key files:
  - `cvm_pipeline.py`: CVMIngestor with 8 async ingest methods (one per table)
  - `bacen_pipeline.py`: BacenIngestor with 3 async ingest methods (SGS, PTAX, Expectativas)
  - `run_daily.py`: asyncio.run() wrapper, parallel CVM + BACEN daily updates
  - `run_backfill.py`: argparse CLI for --start-year, --entity filtering

**`tests/`:**
- Purpose: Offline pytest suite (no Supabase, no HTTP)
- Contains: Fixture data, mocking strategy, test ingestors
- Key files:
  - `conftest.py`: Mocks for CVMFetcher, BacenClient, supabase_client
  - `test_cvm_fetch_parse.py`: CVMFetcher._parse_csv(), alias resolution
  - `test_data_validation.py`: DataValidator field rules
  - `test_ingestor.py`: CVMIngestor logic with mocked fetcher + store

**`scripts/`:**
- Purpose: Development utilities (not part of production pipeline)
- Contains: One-off exploratory scripts
- Key files:
  - `explore_cvm_output.py`: Inspect raw CVM data structure

## Key File Locations

**Entry Points:**
- `src/pipeline/run_daily.py`: CLI for daily incremental update (async main())
- `src/pipeline/run_backfill.py`: CLI for historical backfill with argparse
- `.github/workflows/daily_ingest.yml`: GitHub Actions trigger

**Configuration:**
- `src/fetchers/cvm_config.py`: FetcherConfig (URLs, timeouts, DNS) + DatasetConfig (entity/doc_type matrix)
- `.env` (git-ignored): SUPABASE_URL, SUPABASE_SERVICE_KEY
- `.env.example`: Template
- `.python-version`: Python 3.12 specifier

**Core Logic:**
- `src/pipeline/cvm_pipeline.py`: CVMIngestor (8 ingest methods)
- `src/pipeline/bacen_pipeline.py`: BacenIngestor (3 ingest methods)
- `src/fetchers/cvm_fetcher.py`: CVMFetcher (HTTP + ZIP + CSV + cache)
- `src/fetchers/bacen_fetcher.py`: BacenClient (python-bcb wrapper)
- `src/store/supabase_client.py`: upsert_rows() chunking + client factory

**Database Schema:**
- `src/store/schema.sql`: Canonical schema (12 tables + indices)

**Testing:**
- `tests/conftest.py`: pytest fixtures + mocks
- `tests/test_cvm_fetch_parse.py`: Fetch/parse tests
- `tests/test_data_validation.py`: Validator tests
- `tests/test_ingestor.py`: Ingestor orchestration tests

## Naming Conventions

**Files:**
- Underscores: `cvm_fetcher.py`, `bacen_pipeline.py`
- Match module/class names: file `cvm_fetcher.py` → class `CVMFetcher`
- Config: `*_config.py` for constants/templates
- Tests: `test_*.py` for pytest discovery

**Directories:**
- Lowercase with underscores: `src/fetchers/`, `src/parsers/`, `src/pipeline/`
- Match package purpose: `fetchers` = HTTP clients, `parsers` = validation, `pipeline` = orchestration

**Python Classes:**
- PascalCase: `CVMFetcher`, `CVMIngestor`, `BacenClient`, `BacenIngestor`, `DataValidator`, `RotatingDNSResolver`
- Enum: `EntityType`, `FetcherConfig`, `DatasetConfig`

**Python Functions/Methods:**
- snake_case: `upsert_rows()`, `_parse_csv()`, `_normalize_cnpj()`, `_find_cnpj_field()`
- Prefix `_` for internal: `_download()`, `_extract_csv_from_zip()`, `_validate_params()`

**Variables:**
- snake_case: `entity`, `doc_type`, `year`, `month`, `run_id`, `conflict_columns`
- Constants (module-level, UPPERCASE): `_PAGE_SIZE = 5000`, `_CHUNK_SIZE = 500`
- Dict keys: lowercase with underscores: `"cnpj"`, `"dt_comptc"`, `"vl_total"`

**Tables:**
- Prefix + entity + doc_type: `cvm_fi_diario`, `cvm_fidc_mensal`, `bacen_sgs`, `cvm_ingest_log`
- Columns: lowercase, descriptive: `cnpj`, `dt_comptc`, `vl_patrim_liq`, `reference_date`

## Where to Add New Code

**New Entity/DocType (e.g., add B3 data source):**
1. Create `src/fetchers/b3_fetcher.py` with `B3Fetcher` class matching `CVMFetcher` interface
2. Add config to `src/fetchers/b3_config.py` (EntityType, DatasetConfig)
3. Extend `src/store/schema.sql` with new tables
4. Create `src/pipeline/b3_pipeline.py` with `B3Ingestor` (match CVMIngestor pattern)
5. Update `run_daily.py` and `run_backfill.py` to instantiate new ingestor
6. Add tests: `tests/test_b3_fetch_parse.py`, `tests/test_b3_ingestor.py`

**New Validation Rule (e.g., validate a new field type):**
1. Add regex pattern to `DataValidator.field_patterns` dict
2. Add method `_validate_<fieldtype>()` returning `Tuple[bool, str]`
3. Register in `self.validators` dict
4. Add tests: `tests/test_data_validation.py`
5. Use in ingestor: `DataValidator().validate_field(...)`

**New CVM DocType (e.g., new CVM endpoint released):**
1. Add entry to appropriate `*_DATASETS` dict in `src/fetchers/cvm_config.py`
2. Add ingest method to `CVMIngestor` in `src/pipeline/cvm_pipeline.py`
3. Add table(s) to `src/store/schema.sql` with unique constraints
4. Update `cvm_pipeline.backfill()` and `daily_update()` to call new method
5. Add tests: `tests/test_ingestor.py`

**New Table / Schema Change:**
1. Edit `src/store/schema.sql` — use `CREATE TABLE IF NOT EXISTS` and named UNIQUE constraints
2. Run: `psql "$SUPABASE_DB_URL" -f src/store/schema.sql` (idempotent)
3. Commit schema change + new ingestor code together

**Unit Test for New Feature:**
1. Test file: `tests/test_*.py`
2. Use fixtures from `conftest.py` (mock Supabase, mock HTTP)
3. Run: `PYTHONPATH=. pytest tests/ -v`
4. Coverage: unit (fetch, parse, validate) + integration (ingestor with mocks)

## Special Directories

**`.claude/`:**
- Purpose: Claude-specific metadata
- Generated: Yes
- Committed: Yes

**`.planning/codebase/`:**
- Purpose: GSD codebase documentation
- Generated: Yes (via /gsd:map-codebase)
- Committed: Yes
- Files: ARCHITECTURE.md, STRUCTURE.md (this), CONVENTIONS.md, TESTING.md, CONCERNS.md

**`.pytest_cache/` and `__pycache__/`:**
- Purpose: pytest and Python bytecode cache
- Generated: Yes
- Committed: No (in .gitignore)

**`.vscode/`:**
- Purpose: IDE settings
- Generated: Yes (user-created)
- Committed: Yes

---

*Structure analysis: 2026-05-05*
