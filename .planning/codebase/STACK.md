# Technology Stack

**Analysis Date:** 2026-05-05

## Languages

**Primary:**
- Python 3.12 - All application code, data pipeline, tests

## Runtime

**Environment:**
- Python 3.12 (specified in `.python-version`)

**Package Manager:**
- pip
- Lockfile: Present (implied by GitHub Actions cache)

## Frameworks

**Core:**
- (No web framework) — Pure data pipeline application, no REST/GraphQL API

**Data Processing:**
- pandas 2.2.0 - DataFrame operations for financial data normalization
- numpy 1.26.3 - Numerical operations and type conversions

**HTTP/Async:**
- aiohttp 3.13.4 - Async HTTP client for CVM data downloads
- aiofiles 23.2.1 - Async file I/O for ZIP extraction and caching

**Testing:**
- pytest 9.0.3 - Test runner and assertion framework
- pytest-asyncio 0.23.4 - Async test support
- hypothesis 6.98.3 - Property-based testing

**Build/Dev:**
- (No build tool) — Direct Python module execution

## Key Dependencies

**Critical:**
- supabase 2.3.0+ - PostgreSQL client for storing CVM/BACEN data; sole persistence layer
- python-bcb 0.3.0 - Banco Central do Brasil SDK wrapping SGS, PTAX, Expectativas, TaxaJuros APIs
- python-dotenv 1.2.2 - Environment variable loading from `.env`

**HTTP/Network:**
- dnspython 2.6.1 - DNS resolution with custom nameserver rotation (CVM network tuning)
- requests 2.33.0 - Synchronous HTTP (used by python-bcb wrapper)

**Data Parsing:**
- lxml 6.1.0 - XML parsing (backup fallback; primary is CSV)
- python-dateutil 2.8.2 - Date parsing and timezone handling

## Configuration

**Environment:**
- `.env` file (copy from `.env.example`)
- Required variables:
  - `SUPABASE_URL` — Supabase project URL (`https://<project-ref>.supabase.co`)
  - `SUPABASE_SERVICE_KEY` — Service role key (bypasses RLS for batch upserts)
- Optional network tuning:
  - `CVM_DNS_NAMESERVERS` — Comma-separated DNS IPs (default: "1.1.1.1,8.8.8.8,9.9.9.9")
  - `CVM_REQUEST_TIMEOUT` — HTTP timeout in seconds (default: 300)
  - `CVM_MAX_RETRIES` — Retry attempts on HTTP failure (default: 3)
  - `CVM_RETRY_DELAY` — Seconds between retries (default: 2)
- Metadata:
  - `TZ=America/Sao_Paulo` — Brazilian timezone
  - `LOG_LEVEL=INFO` — Logging verbosity

**Build:**
- `pytest.ini` — pytest configuration with `pythonpath = .` and `asyncio_mode = auto`

## Platform Requirements

**Development:**
- Python 3.12+
- macOS / Linux (CI runs on ubuntu-latest)
- Virtual environment: `.venv/`

**Production:**
- Python 3.12+ runtime
- Deployment: GitHub Actions (no Docker, no containers)
- Execution: `python -m src.pipeline.run_daily` or `python -m src.pipeline.run_backfill`

## Module Entry Points

**Daily incremental ingest:**
- `src.pipeline.run_daily` — Runs nightly at 06:00 UTC via cron (`.github/workflows/daily_ingest.yml`)

**Historical backfill:**
- `src.pipeline.run_backfill` — One-shot script for all years; callable via GitHub Actions workflow_dispatch

**Pipeline orchestrators:**
- `src.pipeline.cvm_pipeline.CVMIngestor` — Wires CVM fetch → parse → store
- `src.pipeline.bacen_pipeline.BacenIngestor` — Wires BACEN fetch → parse → store

---

*Stack analysis: 2026-05-05*
