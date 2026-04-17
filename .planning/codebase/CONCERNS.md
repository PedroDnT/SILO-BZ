# Technical Concerns & Debt

**Analysis Date:** 2026-04-10

## Critical Issues

### datetime.utcnow() Deprecation (P1)
- **Location**: `src/cvm_api/models.py`, `src/bacen_api/models.py`, `src/b3_calc_api/models.py`, all `main.py` files
- **Issue**: `datetime.utcnow()` is deprecated in Python 3.12+; generates ~35 warnings on every test run
- **Impact**: Warnings pollute test output, mask other issues; will break on Python 3.14+
- **Fix**: Replace all instances with `datetime.now(timezone.utc)` (34 call sites total)
- **Effort**: ~30 min; straightforward mechanical replacement

### Hardcoded Absolute Paths (P1)
- **Location**: `.claude/launch.json` (4 entries), `scripts/check_all_endpoints.py` docstring
- **Issue**: Paths hardcoded to `/Users/pedrotodescan/...` — will break on other systems
- **Impact**: Dev tools fail when cloned to different machines; onboarding friction
- **Fix**: Use `${workspaceFolder}` in launch.json, relative paths in docstrings
- **Effort**: ~15 min

## Technical Debt & Fragile Areas

### B3 CALC Fallback Dependency (P2)
- **Location**: `src/b3_calc_api/services.py:B3CalcService._fetch_from_b3()`
- **Issue**: Entire B3 CALC service falls back to hardcoded sample data (`SAMPLE_DEBENTURES`, `SAMPLE_CRAS`, `SAMPLE_CRIS`) when upstream `calculadorarendafixa.com.br` is unavailable
- **Impact**:
  - Real pricing data never requested; users get deterministic sample data indefinitely
  - No metrics on upstream availability — silent failures
  - If upstream adds new securities, service returns outdated samples
- **Risk Level**: Medium — service appears operational but serves stale data
- **Mitigation**: Probe upstream health on startup; log failures; consider cache with revalidation strategy
- **Note**: This is a designed fallback (intentional per CLAUDE.md); do not remove without explicit request

### CVM File Caching with Manual Metadata (P2)
- **Location**: `src/cvm_api/services.py:CVMCreditDataService._load_cache()` and `.meta` files
- **Issue**: Cache invalidation depends on JSON `.meta` files alongside binary `.cache` files; no automated TTL
- **Impact**:
  - Stale CVM data served if `.meta` is corrupted or diverges from `.cache`
  - Manual cache invalidation required for upstream schema changes
  - Network outage = service returns 30-day-old data (default cache lifespan)
- **Mitigation**: Add checksum validation in `.meta`; implement age-based eviction; monitor cache hit rate

### Rate Limiting Defined but Not Wired (P2)
- **Location**: `.env.example` defines `RATE_LIMIT_ENABLED`, `RATE_LIMIT_REQUESTS`, `RATE_LIMIT_WINDOW`
- **Issue**: Environment variables configured but never applied to any FastAPI app
- **Impact**: No protection against request floods; all three services accept unlimited concurrent requests
- **Note**: If rate limiting becomes needed, integrate `slowapi` (already in recommendations)
- **Effort**: ~2 hours to implement across all three services

### DNS Fallback Chain (P2)
- **Location**: `src/cvm_api/config.py:CVM_DNS_NAMESERVERS`
- **Issue**: Hardcoded fallback to `1.1.1.1, 8.8.8.8, 9.9.9.9` if system resolver fails; requires network reachability assumption
- **Impact**:
  - If all three fallback servers are unreachable, CVM downloads fail silently
  - Enterprise environments (VPN, proxies) may not reach public DNS
- **Mitigation**: Log DNS resolution attempts; expose toggle for local DNS only; add observability

### CSV Parsing Assumptions (P2)
- **Location**: `src/cvm_api/services.py:_parse_csv_content()`
- **Issue**: Assumes `latin-1` encoding and `;` delimiter for all CVM sources; no format detection
- **Impact**: If CVM changes encoding or delimiter (migration to UTF-8 for example), parsing fails silently with corrupt data
- **Mitigation**:
  - Add encoding detection (chardet) for robustness
  - Log actual encoding used; monitor for changes
  - Add sample-row validation before full parse

### Import Guard Complexity (P2)
- **Location**: `src/*/main.py` and `src/*/services.py` (5 files)
- **Issue**: Dual-run guards (`if __package__: ... else: ...`) needed for both package and direct script execution
- **Impact**:
  - If guard logic is wrong, imports fail in one execution mode only (discovered late)
  - Difficult to test both paths; CI may miss import errors in worktree mode
  - Worktree deploys are fragile (easy to break with `python uvicorn_direct` vs `python -m uvicorn`)
- **Mitigation**:
  - Test suite should validate both import modes
  - Use `python -m` exclusively in all tooling and documentation
  - Consider removing direct execution path if not used

## Security Considerations

### Open CORS Policy (Design)
- **Location**: All three `main.py` files — `allow_origins=["*"]`
- **Issue**: Unrestricted CORS — any origin can call the API
- **Impact**:
  - Browser-based clients from anywhere can access data
  - No protection against CSRF or cross-site data exfiltration
  - Suitable for public APIs; unsuitable if any data becomes sensitive
- **Status**: Intentional for public Brazilian financial data
- **Action if needed**: Restrict to specific origins or remove CORS in later phases

### No Request Authentication (Design)
- **Location**: All three services are unauthenticated
- **Issue**: Anyone with network access can query the APIs
- **Impact**: Public data accessed without API keys or tokens
- **Status**: Acceptable for public financial data sources; noted for on-chain bridging phase
- **Future**: On-chain bridge may require API key authentication

### Data Validation on Input (Present)
- **Location**: `src/validation_utils.py` + route-level validation (query params)
- **Status**: ✅ CNPJ/CPF checksums, date formats, percentage ranges validated
- **Coverage**: Complete for CVM entity/doc-type constraints; good for query parameters

### Environment Variable Exposure Risk (Low)
- **Location**: `.env.example` committed; `.env` gitignored
- **Status**: ✅ No secrets in examples; API keys are opt-in
- **Note**: Backfill tool may store credentials in `data/` directory (currently not in use)

## Performance & Scalability Concerns

### In-Memory Pagination & Caching (P2)
- **Location**: `src/cvm_api/services.py:_paginate_data()`; `src/b3_calc_api/services.py:CacheManager`
- **Issue**:
  - Full CSV loaded into memory before pagination — no streaming
  - B3 CALC cache limited to 64 entries in-memory (LRU); no persistence
  - Single large FIDC monthly report (~50MB CSV) causes memory spikes
- **Impact**:
  - Memory usage O(dataset_size); exceeds available memory on edge functions
  - Concurrent requests share single service instance (no horizontal scaling)
- **Mitigation**:
  - Stream pagination (fetch N rows from ZIP without full load)
  - Persist cache to Blob/Redis if on Vercel; file-based cache if on Docker

### DNS Resolution on Every Download (P2)
- **Location**: `src/cvm_api/services.py:_download_file()`
- **Issue**: DNS lookup performed on every file download via `aiohttp`
- **Impact**: Extra 10-100ms latency per request; no DNS caching
- **Mitigation**: Connection pooling with DNS TTL; consider custom resolver with caching

### Test Suite Slow Path (P2)
- **Location**: `tests/test_live_endpoints.py` — live CVM API calls
- **Issue**: Tests call real `dados.cvm.gov.br` API; take 5-10 seconds per entity/doc-type combo
- **Impact**: Full test suite takes 2-3 minutes; CI feedback delay
- **Mitigation**: Use VCR or recorded HTTP cassettes; keep live tests separate (`-m integration`)

## Maintenance Concerns

### Pydantic v1 to v2 Migration Incomplete (P2)
- **Status**: Partial migration done; some files still use v1 patterns
- **Locations**:
  - `.schema()` → use `.model_json_schema()` (check all models.py)
  - `schema_extra` → use `json_schema_extra` (ConfigDict)
  - `.dict()` → use `.model_dump()` (check all serialization)
- **Effort**: ~1 hour to complete across all services
- **Risk**: Breaking changes if Pydantic v3 drops v1 compat layer

### Dependency Version Pinning (P2)
- **Location**: `requirements.txt`
- **Issue**: Versions pinned but no version upper bounds; future major releases may break
- **Example**: `fastapi==0.109.0` will become incompatible with FastAPI 1.0 when released
- **Mitigation**: Add upper bounds (`fastapi<1.0`); use `pip-audit` in CI

### Documentation Mint Maintenance (P3)
- **Location**: `docs.json`, `*.mdx` files, `start.mdx`
- **Issue**: Documentation stub only; no API docs auto-generated from code
- **Impact**: API changes require manual documentation updates
- **Mitigation**: Add `FastAPI` auto-doc extraction; sync with code via CI

## Data Quality & Source Concerns

### CVM CSV Encoding Assumption (P2)
- **Location**: Hard-coded `latin-1` in `src/cvm_api/services.py`
- **Issue**: CVM may migrate to UTF-8 (Brazilian government push towards UTF-8)
- **Risk**: Parsing silently produces corrupt data if encoding changes
- **Mitigation**: Auto-detect encoding or request clarification from CVM

### B3 CALC Upstream Volatility (P2)
- **Location**: `calculadorarendafixa.com.br` external dependency
- **Issue**: Third-party website; no SLA, no versioning, UI changes break scraper
- **Status**: Currently disabled (fallback to sample data); not actively maintained
- **Risk**: If re-enabled, service breaks on upstream changes

### BACEN python-bcb Library (P2)
- **Location**: `src/bacen_api/` depends on `python-bcb` library (third-party)
- **Issue**: Async wrapper in `src/clients/bacen_client.py` uses `asyncio.to_thread` to wrap sync calls
- **Impact**: Blocking I/O in thread pool; limits concurrency
- **Better alternative**: Use native async library or fork `python-bcb` to async

## Testing Gaps

### No BACEN API Tests (P2)
- **Location**: `src/bacen_api/` has no dedicated test file
- **Coverage**: Only covered indirectly via `test_live_endpoints.py`
- **Impact**: Regressions in BACEN routes undetected until production

### No B3 CALC Tests (P2)
- **Location**: `src/b3_calc_api/` has no dedicated test file
- **Coverage**: Sample data fallback untested; no unit tests for pricing logic
- **Impact**: Cache behavior and fallback logic are fragile

### No Backfill Tool Tests (P2)
- **Location**: `src/tools/backfill.py` has no unit tests
- **Coverage**: CLI only tested manually
- **Impact**: Resume logic, progress tracking, and directory mapping changes break silently

### Missing Import Mode Tests (P2)
- **Location**: Tests always run with `PYTHONPATH=.` in package mode
- **Issue**: Direct script execution (`python src/cvm_api/main.py`) never tested
- **Impact**: Import guards may be broken in direct mode (discovered only on user deployment)

## Known Fragile Areas

### Zip Extraction Filename Matching (P2)
- **Location**: `src/cvm_api/services.py:_extract_csv_from_zip()`
- **Issue**: Looks for predictable filename (e.g., `inf_mensal_fidc_202502.csv`); falls back to first `.csv` if not found
- **Impact**: If CVM changes filename pattern, fallback picks wrong file
- **Mitigation**: Log which file was extracted; validate row count matches schema

### Pagination Offset Calculation (P2)
- **Location**: `src/cvm_api/services.py:_paginate_data()`
- **Issue**: Assumes contiguous page boundaries; no robust error if `page > total_pages`
- **Impact**: Returns empty page silently instead of 404
- **Better**: Check bounds and raise `ValueError` with hint

### DNS Resolver Initialization (P2)
- **Location**: `src/cvm_api/services.py:__init__()` creates `RotatingDNSResolver`
- **Issue**: Resolver created once per service; if DNS servers change, restart required
- **Impact**: Long-running services won't pick up DNS changes
- **Mitigation**: Periodic re-initialization or config reload

## Opportunities for Improvement

### Observability (P3)
- **Current**: Basic logging to stdout; no structured logs or trace IDs
- **Opportunity**: Add OpenTelemetry integration; export to Datadog/Grafana
- **Value**: Better incident debugging, performance profiling, SLA monitoring

### Caching Strategy (P3)
- **Current**: File cache for CVM; in-memory for B3
- **Opportunity**: Unified cache interface (file/Redis/memory); TTL-based invalidation
- **Value**: Faster response times; easier deployment to edge compute

### Async/Await Patterns (P3)
- **Current**: Mostly async, but `BacenClient` wraps sync library
- **Opportunity**: Use native async libraries; remove `asyncio.to_thread` blocking calls
- **Value**: Better concurrency; reduced latency tail

### Error Handling Consistency (P3)
- **Current**: Mix of `ValueError`, `HTTPException`, and generic `Exception`
- **Opportunity**: Custom exception hierarchy; unified error response format
- **Value**: Better API error messages; easier debugging

---

*Concerns analysis: 2026-04-10*
