# Architecture

**Analysis Date:** 2026-05-05

## Pattern Overview

**Overall:** Three-stage async pipeline: FETCH → PARSE → STORE

**Key Characteristics:**
- Headless ETL (no API layer — downstream consumers query Supabase directly)
- Async throughout (asyncio + aiohttp for parallelism)
- Dual-source ingestion (CVM + BACEN)
- Incremental updates (daily) + full historical backfill capability
- Data-centric error recovery (audit log for every ingest run)

## Layers

**FETCH Layer:**
- Purpose: Download CSV/ZIP files from Brazilian public sources via HTTP with resilience
- Location: `src/fetchers/`
- Contains: 
  - `cvm_fetcher.CVMFetcher` — async HTTP client with DNS rotation, retry, on-disk caching for CVM (dados.cvm.gov.br)
  - `bacen_fetcher.BacenClient` — async wrapper around python-bcb SDK for BACEN data
  - `cvm_config.DatasetConfig` — URL templates and metadata for all CVM endpoints
- Depends on: asyncio, aiohttp, dns.resolver (CVM); pandas, bcb SDK (BACEN)
- Used by: `CVMIngestor`, `BacenIngestor`

**PARSE Layer:**
- Purpose: Normalize downloaded data, extract/validate key fields (CNPJ, dates, numerics)
- Location: `src/parsers/` + co-located in fetchers (CSV extraction, DataFrame normalization)
- Contains:
  - `validation.DataValidator` — comprehensive field validators (CNPJ, date, currency format checks)
  - CVM parsing: ZIP→CSV extraction and dict normalization in `CVMFetcher._extract_csv_from_zip()` and `._parse_csv()`
  - BACEN parsing: DataFrame→dict flattening in `BacenClient` via `_df_to_records()`
- Depends on: csv module, zipfile, pandas for BACEN conversions
- Used by: Ingestors before `upsert_rows()`

**STORE Layer:**
- Purpose: Persist normalized data to Supabase Postgres with upsert semantics
- Location: `src/store/`
- Contains:
  - `supabase_client.upsert_rows()` — chunked upserts (500-row batches) with ON CONFLICT handling
  - `supabase_client.get_supabase_client()` — singleton client factory
  - `schema.sql` — canonical schema (9 CVM tables + 3 BACEN tables + audit log)
- Depends on: supabase-py client
- Used by: `CVMIngestor`, `BacenIngestor`, schema bootstrap

**ORCHESTRATION Layer:**
- Purpose: Wire FETCH→PARSE→STORE stages; manage entity/doc_type matrix; coordinate parallel runs
- Location: `src/pipeline/`
- Contains:
  - `cvm_pipeline.CVMIngestor` — orchestrates fetch+store for 6 CVM entities (FI, FIDC, FIP, FIAGRO, FII, SECURIT)
  - `bacen_pipeline.BacenIngestor` — orchestrates SGS, PTAX, Expectativas fetches
  - `run_daily.py` — CLI entry point (current month + previous month for CVM; 7-day window for BACEN)
  - `run_backfill.py` — CLI with --start-year, --entity filtering for historical loads
- Depends on: ingestors, asyncio.gather for parallelism
- Used by: GitHub Actions cron, manual operations

## Data Flow

**CVM Daily Update:**

1. User/scheduler invokes `python -m src.pipeline.run_daily`
2. `run_daily.py` instantiates `CVMIngestor()` and `BacenIngestor()`
3. `CVMIngestor.daily_update()` calls entity-specific ingest methods in parallel (e.g., `ingest_fi_diario`, `ingest_fidc_mensal`)
4. Each method:
   - Calls `CVMFetcher.fetch(entity, doc_type, year, month)` → HTTP GET to dados.cvm.gov.br
   - Caching: MD5(url) → check cache_dir for 24-hour-old data
   - On miss: retry up to 3 times with exponential backoff, DNS rotation
   - ZIP extraction: `_extract_csv_from_zip()` finds CSV by name pattern, decompresses
   - CSV parsing: `_parse_csv()` → List[dict] with column name normalization
5. Transformation: `_find_cnpj_field()`, `_normalize_cnpj()`, field mapping (e.g., "TP_FUNDO_CLASSE" → "tp_fundo")
6. Log start: `_log_start(run_id)` inserts row into `cvm_ingest_log` with status='running'
7. Upsert: `upsert_rows(table, records, conflict_columns)` chunks into 500-row batches, executes Supabase upsert
8. Log finish: `_log_finish(run_id)` updates log row with rows_upserted, status='ok' or error details
9. Aggregation: results returned as `Dict[table_name → row_count]`

**BACEN Daily Update:**

1. `BacenIngestor.daily_update()` runs three fetch methods in parallel:
   - `ingest_sgs(start, end)` → `BacenClient.get_sgs_series()` wraps `bcb.sgs.get()`, returns DataFrame
   - `ingest_ptax()` → one task per currency (USD/EUR/GBP/JPY/ARS) via `bcb.PTAX`
   - `ingest_expectativas()` → one task per endpoint/indicator combo via `bcb.Expectativas`
2. Each fetch returns pandas DataFrame
3. `_df_to_records()` normalizes: DatetimeIndex → column, NaN → None, numpy types → Python native
4. Field extraction: date normalization (isoformat()), numeric type casting
5. Upsert: same chunked pattern as CVM

**State Management:**
- Raw CSV: stored in JSONB `raw` column for audit/reprocessing
- Audit trail: `cvm_ingest_log` tracks entity/doc_type/period/status/error_msg for every run
- Idempotence: ON CONFLICT ON (conflict_columns) DO UPDATE ensures re-runs don't duplicate
- Caching: fetcher-level URL cache (24-hour TTL) reduces HTTP load
- No external state: all decisions made per-run based on date logic (daily = current + previous month)

## Key Abstractions

**Entity/DocType Matrix:**
- CVM entities: FI, FIDC, FIP, FIAGRO, FII, SECURIT
- Each entity has 1–N doc_types (e.g., FI has inf_diario, cda, perfil_mensal, balancete)
- Config-driven: `DatasetConfig` defines all valid combos + URL patterns
- Ingestor methods are 1:1 with (entity, doc_type) pair → one table

**Async Concurrency:**
- `asyncio.gather()` with `return_exceptions=True` batches tasks:
  - CVM: 6 tasks at a time for FI (to avoid overwhelming CVM server)
  - BACEN: all currency tasks in parallel (no rate limit concern)
- Backfill mode: years × entities × months → potentially hundreds of tasks queued, batched

**Field Discovery:**
- CVM CSVs have inconsistent column names across years/entities (e.g., "VL_TOTAL" vs "VL_CARTEIRA_TOTAL")
- `_find_field(*candidates)` searches case-insensitively for first non-empty match
- `_find_cnpj_field(prefer_suffix)` prioritizes certain column names (e.g., "CNPJ_FUNDO" before generic "CNPJ")
- Raw dict always preserved in JSONB for manual inspection

**Chunked Upsert:**
- Supabase REST API has practical limit (500 rows/request observed)
- `upsert_rows()` splits into `_CHUNK_SIZE = 500` batches
- Each chunk: one REST call with `on_conflict` parameter naming unique constraint
- Automatic retry on network error (Supabase client handles it)

## Entry Points

**Daily Cron:**
- Location: `.github/workflows/daily_ingest.yml` (GitHub Actions)
- Triggers: `06:00 UTC daily` + `workflow_dispatch`
- Responsibilities: Execute `python -m src.pipeline.run_daily`

**Manual Backfill:**
- Location: `src/pipeline/run_backfill.py`
- Triggers: Local CLI or GitHub Actions workflow_dispatch with parameters
- Responsibilities: 
  - Parse args (--start-year, --end-year, --entity, --bacen-start, --cvm-only, --bacen-only)
  - Filter by entity if specified
  - Call `CVMIngestor.backfill()` and/or `BacenIngestor.backfill()`
  - Log total row count and elapsed time

**Development / Testing:**
- Location: `src/pipeline/run_daily.py` and `run_backfill.py` can be imported for testing
- PYTHONPATH setup: `sys.path.insert(0, os.path.join(...))` allows `from src.pipeline import ...`

## Error Handling

**Strategy:** Log + upsert + continue. No transactional rollback across tables.

**Patterns:**
- HTTP: `CVMFetcher._download()` retries 3 times with exponential backoff; falls back to system DNS if custom resolver fails
- Fetch: 404 → `ValueError`; HTTP errors → `RuntimeError`; caught by ingestor, logged as error
- Parse: malformed CSV → caught during `_parse_csv()` (csv.DictReader handles gracefully); empty rows skipped
- Upsert: Supabase error logged + re-raised (halts that entity/doc_type, not others)
- Ingest log: start/finish always written separately, so partial failures are recorded

**Example:**
```python
# src/pipeline/cvm_pipeline.py:203-206
except Exception as exc:
    logger.warning("ingest_fi_diario %d-%02d failed: %s", year, month, exc)
    self._log_finish(run_id, 0, str(exc))
    return 0
```

Failure in one doc_type doesn't block others running in parallel.

## Cross-Cutting Concerns

**Logging:**
- Module-level loggers: `logger = logging.getLogger(__name__)`
- Format: `%(asctime)s %(name)s %(levelname)s %(message)s`
- Key points logged: fetch URL, row count, elapsed time, errors, backfill start/finish
- Example: `logger.info("CVM parse: %s/%s -> %d rows in %.1fs", entity, doc_type, len(rows), elapsed)`

**Validation:**
- CNPJ normalization: `_normalize_cnpj()` strips non-digits
- Field extraction: `_find_field()` handles case-insensitive, None, empty string
- Date conversion: `_period_to_date()` tries to parse YYYY-MM-DD; falls back to first-of-month
- Numeric: stored as string in Python, Supabase NUMERIC type casts on insert
- Comprehensive validators in `DataValidator` (CNPJ checksum, date patterns, etc.) for future use

**Authentication:**
- Supabase: `SUPABASE_URL` + `SUPABASE_SERVICE_KEY` env vars
- Service role key bypasses RLS (full write access)
- CVM: public data, no auth required
- BACEN: public SDK, no auth required

---

*Architecture analysis: 2026-05-05*
