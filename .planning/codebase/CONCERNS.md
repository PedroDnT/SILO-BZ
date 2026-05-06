# Codebase Concerns

**Analysis Date:** 2026-05-05

## Tech Debt

**Silent exception handling in `_period_to_date`:**
- Issue: `_period_to_date()` at `src/pipeline/cvm_pipeline.py:102-112` has a bare `except Exception: pass` that silently swallows parsing errors. If CVM changes date format, failures go unlogged.
- Files: `src/pipeline/cvm_pipeline.py:110-111`
- Impact: Incorrect date normalization cascades silently; audit trail shows wrong periods in ingest_log. Makes debugging CVM schema changes harder.
- Fix approach: Replace bare `except` with specific exception type and `logger.warning()`, return fallback date only after logging.

**Silent DNS resolution fallback in CVMFetcher:**
- Issue: `_build_session()` at `src/fetchers/cvm_fetcher.py:161-163` catches all exceptions during custom DNS resolver setup and falls back to system resolver with only a warning. Network resilience is reduced if custom DNS fails unpredictably.
- Files: `src/fetchers/cvm_fetcher.py:161-163`
- Impact: Intermittent DNS failures invisible in logs; inconsistent network behavior across runs.
- Fix approach: Log resolver initialization failures as errors, not warnings. Add metrics to detect pattern of fallback usage.

**Cache invalidation without validation:**
- Issue: `_is_cache_valid()` at `src/fetchers/cvm_fetcher.py:173-184` catches all exceptions and returns `False`, but doesn't distinguish between corrupted metadata (should retry) vs. timezone parsing failure (should fail loudly).
- Files: `src/fetchers/cvm_fetcher.py:183-184`
- Impact: Corrupted cache metadata silently triggers re-download on every run, wasting bandwidth and time. No visibility into why cache fails.
- Fix approach: Log cache read failures by type. Consider cache TTL extension for metadata parsing errors to prefer stale cache over corruption.

**Bare exception in CSV ZIP extraction:**
- Issue: `_extract_csv_from_zip()` at `src/fetchers/cvm_fetcher.py:268-286` has fallback logic but no logging when expected CSV pattern doesn't match. If CVM changes ZIP contents, the "next CSV in ZIP" fallback hides schema changes.
- Files: `src/fetchers/cvm_fetcher.py:283-284`
- Impact: Silent adoption of wrong CSV file if CVM structure changes; wrong data ingested without alerting.
- Fix approach: Log when fallback CSV selection is used. Include file list in warning so schema drift is visible in logs.

**Validation module incomplete error handling:**
- Issue: `DataValidator._validate_date()` at `src/parsers/validation.py:157` catches `ValueError` but `_validate_datetime()` at line 171 catches generic `Exception`. Inconsistent specificity masks real parsing bugs.
- Files: `src/parsers/validation.py:157-222`
- Impact: Different validators fail differently; hard to reason about validation robustness.
- Fix approach: Standardize on specific exceptions (`ValueError`, `TypeError`) for all validators. Remove generic `Exception` catches.

**Ingest log swallows own failures:**
- Issue: `_log_start()` and `_log_finish()` at `src/pipeline/cvm_pipeline.py:130-155` catch all exceptions and only warn if logging to `cvm_ingest_log` table fails. If Supabase is down, audit trail is lost silently.
- Files: `src/pipeline/cvm_pipeline.py:142-143, 154-155`
- Impact: Failed ingests not recorded in audit log. Operators can't tell if a run succeeded or was silently lost.
- Fix approach: Treat ingest_log failures as critical. Raise exception instead of swallowing; let orchestrator decide retry strategy.

## Known Bugs

**FIDC mensal CSV name pattern mismatch (FIXED IN STAGED CHANGES):**
- Symptoms: FIDC data ingestion silently uses wrong CSV filename pattern.
- Files: `src/fetchers/cvm_config.py:105` (staged fix in git diff shows pattern changed from `inf_mensal_fidc_{year}{month:02d}.csv` to `inf_mensal_fidc_tab_IV_{year}{month:02d}.csv`)
- Trigger: Any FIDC monthly ingest since schema redesign.
- Workaround: Current staged change fixes this — needs to be committed.

**FII mensal_complemento dataset not configured (FIXED IN STAGED CHANGES):**
- Symptoms: Cannot ingest FII mensal_complemento data; endpoint exists but not in config.
- Files: `src/fetchers/cvm_config.py:63-99` (staged addition of mensal_complemento config)
- Trigger: Attempting to call `ingest_fii_mensal("mensal_complemento", 2025)`.
- Workaround: Staged config addition already present in git diff — needs commit.

**Month boundary logic in daily_update:**
- Symptoms: When run on the 1st of month, fetches previous month only if month > 1, skipping December carryover from November of previous year.
- Files: `src/pipeline/cvm_pipeline.py:655`
- Trigger: Run on January 1st after December data published.
- Workaround: Manual run with explicit year/month during month boundaries.
- Root cause: Line 655 uses `([month - 1, month] if month > 1 else [month])` which doesn't handle year rollover.

## Security Considerations

**Service key in environment without rotation:**
- Risk: `SUPABASE_SERVICE_KEY` is service_role (bypasses RLS). If GitHub Actions secrets are compromised, database write access is exposed until manual key rotation.
- Files: `src/store/supabase_client.py:28`, `.github/workflows/daily_ingest.yml:48-50`
- Current mitigation: GitHub organization-level secret encryption; key rotation is manual process.
- Recommendations: 
  - Implement automated key rotation every 90 days.
  - Add GitHub secret audit logging.
  - Consider using Supabase JWT with time-limited tokens instead of service_role.

**DNS nameserver hardcoded in config:**
- Risk: Cloudflare (1.1.1.1), Google (8.8.8.8), and Quad9 (9.9.9.9) are public nameservers. In MITM or DNS poisoning scenario, no fallback to private/trusted resolvers.
- Files: `src/fetchers/cvm_config.py:20`, `.github/workflows/daily_ingest.yml:56`
- Current mitigation: Uses rotation to detect failures, but doesn't detect successful poisoning.
- Recommendations: Add DNSSEC validation for CVM domain. Log resolver response times to detect anomalies.

**No request signing or integrity check:**
- Risk: CVM ZIP/CSV files downloaded over HTTPS but not signed. Man-in-the-middle could inject rows into CSV without detection.
- Files: `src/fetchers/cvm_fetcher.py:250-258`
- Current mitigation: HTTPS TLS only.
- Recommendations: Verify CVM publishes SHA256 checksums for released datasets and validate before ingestion.

## Performance Bottlenecks

**Supabase chunk size hardcoded:**
- Problem: `_CHUNK_SIZE = 500` at `src/store/supabase_client.py:15` assumes safe batch size, but not optimized for large rows (many columns, large JSONB `raw` field).
- Files: `src/store/supabase_client.py:15, 60`
- Cause: No profiling of actual chunk sizes or response times; fixed value works but not tuned.
- Improvement path: Monitor upsert latency; adjust chunk size based on row size and network RTT. Consider dynamic batching.

**CSV parsing done synchronously in async context:**
- Problem: `_parse_csv()` at `src/fetchers/cvm_fetcher.py:288-299` is CPU-bound (CSV parsing) called in async fetch. For large datasets (10K+ rows), blocks event loop.
- Files: `src/fetchers/cvm_fetcher.py:327`
- Cause: CSV parsing happens on main thread in `fetch()` method.
- Improvement path: Move parsing to `asyncio.to_thread()` like BACEN does for python-bcb calls.

**No pagination or streaming for large CVM datasets:**
- Problem: `_fetch_all_pages()` at `src/pipeline/cvm_pipeline.py:161-171` collects entire dataset into memory before storing. For large FIDC/FII datasets (100K+ rows), memory spike is significant.
- Files: `src/pipeline/cvm_pipeline.py:161-171, 199-202`
- Cause: CVMFetcher returns full list; pipeline upserts all at once.
- Improvement path: Implement generator-based streaming; upsert in batches as pages arrive.

**Concurrent ingest tasks not bounded:**
- Problem: Backfill spawns up to 100+ async tasks concurrently (all FIP years, all FII doc types) without concurrency limiting. Can overwhelm Supabase or CVM server.
- Files: `src/pipeline/cvm_pipeline.py:556-636` (backfill method)
- Cause: No semaphore or task pool; naive `asyncio.gather()` with all tasks.
- Improvement path: Use `asyncio.Semaphore(10)` to limit concurrent requests to 10-20 based on CVM rate limits.

**Redundant field lookups in pipeline:**
- Problem: `_find_field()` at `src/pipeline/cvm_pipeline.py:71-77` is called per-row with candidate list; does case-insensitive dict key lookup every time.
- Files: `src/pipeline/cvm_pipeline.py:71-77, 184-196`
- Cause: No schema caching; repeated case-insensitive matching.
- Improvement path: Build field index once per dataset (lowercase → original key mapping) and reuse for all rows in dataset.

## Fragile Areas

**CVM schema discovery via field name variations:**
- Files: `src/pipeline/cvm_pipeline.py:71-87` (all `_find_*` helpers)
- Why fragile: Logic assumes CVM will always include one of several candidate field names (e.g., "VL_QUOTA" or "VL_QUOTA_ACTUAL"). If CVM adds new documents with different naming, silent NULL values result.
- Safe modification: Add schema version tracking to config; log warnings when fallback fields are used. Document expected field names per entity/doc_type in `cvm_config.py`.
- Test coverage: Tests mock fixed field names; don't test against real CVM datasets with schema variations.

**CNPJ normalization and fallback logic:**
- Files: `src/pipeline/cvm_pipeline.py:80-87` (_find_cnpj_field), lines 185-186, 223-224, etc.
- Why fragile: `_find_cnpj_field()` tries suffix-based match first (e.g., "CNPJ_FUNDO") then any CNPJ field. If CVM dataset has multiple CNPJ columns, wrong one silently picked.
- Safe modification: Require explicit field mapping in config per entity/doc_type. Log which CNPJ field is selected.
- Test coverage: Tests use single-CNPJ fixtures; no test of multi-CNPJ schema.

**Period date extraction with fallbacks:**
- Files: `src/pipeline/cvm_pipeline.py:102-112` (_period_to_date), used in lines 225, 288, 325, 404, 474
- Why fragile: Falls back to first-of-month if parsing fails or field missing. Silent date normalization can bias time series analysis.
- Safe modification: Log fallback usage with entity/doc_type/row. Make fallback behavior configurable per entity.
- Test coverage: Tests don't cover parsing failures or missing fields.

**Async error handling with `return_exceptions=True`:**
- Files: `src/pipeline/cvm_pipeline.py:567, 580, 593, 604, 618, 632, 683` (asyncio.gather with return_exceptions)
- Why fragile: Exceptions are returned in results list but not always logged. Line 687-688 in daily_update logs errors, but backfill loops at 567-570, 580-583 don't log non-int results.
- Safe modification: Always log exceptions returned from gather(). Add wrapper to distinguish transient failures (retry) vs. permanent (skip).
- Test coverage: No tests of exception handling in gather loops.

## Scaling Limits

**Single GitHub Actions runner:**
- Current capacity: Single `ubuntu-latest` runner processes entire backfill linearly or with limited parallelism.
- Limit: 2-hour timeout per workflow. Large backfills (2019–2026 for all entities) may exceed timeout.
- Scaling path: Matrix strategy in GitHub Actions to split by entity (FI, FIDC, FIP, etc.) and run in parallel. Requires coordinating Supabase write contention.

**Supabase concurrent write limit:**
- Current capacity: Upserts are chunked (500 rows) and sequential per entity.
- Limit: If all CVM entities ingest simultaneously, Supabase REST API may queue requests. No back-pressure handling.
- Scaling path: Add connection pooling, retry with exponential backoff, or use Supabase RLS + direct Postgres connection instead of REST API.

**Local filesystem cache**:
- Current capacity: Cache stored in `cache/` directory with file-per-URL. No cleanup.
- Limit: Cache can grow unbounded; multi-GB in production after years of daily runs.
- Scaling path: Implement cache expiration (TTL beyond 24 hours), periodic cleanup, or migrate to S3/GCS.

## Dependencies at Risk

**python-bcb (0.3.0):**
- Risk: Last release was 2022. Banco Central may have changed PTAX/Expectativas endpoints. No recent updates suggest abandoned maintenance.
- Impact: BACEN pipelines (SGS, PTAX, Expectativas, TaxaJuros) may fail silently if endpoints change.
- Migration plan: Monitor BACEN API responses for 404/changes. Fork python-bcb if unmaintained and endpoints shift.

**aiohttp (3.13.4):**
- Risk: Large dependency with async complexity. Versions < 3.9 have security advisories (AIOHTTP_CONNECTOR_SSL_ERROR).
- Impact: Potential SSL/TLS bypass on older versions.
- Migration plan: Pin to >= 3.9.5. Add dependabot alerts for aiohttp.

**pandas (2.2.0), numpy (1.26.3):**
- Risk: BACEN dataframes depend on pandas/numpy. Large ecosystem; upgrades can be breaking.
- Impact: BACEN ingestor may fail on major version upgrades.
- Migration plan: Pin minor versions. Test major version upgrades before deploying.

**supabase (>= 2.3.0):**
- Risk: Loose version constraint. New major version may change API.
- Impact: Upsert calls may fail on upgrade.
- Migration plan: Pin to specific version (e.g., `>=2.3.0,<3.0`). Test upgrades in staging.

## Missing Critical Features

**No data validation pipeline:**
- Problem: Data is fetched and ingested without schema validation. CNPJ format, date ranges, numeric bounds are not validated before upsert.
- Blocks: Can't detect CVM data quality issues early; bad data reaches database.
- Mitigation needed: Add `DataValidator` calls in ingest methods. Reject rows with invalid CNPJ, future dates, negative values where unexpected.

**No retry strategy for failed ingests:**
- Problem: If an ingest fails midway (after 5 successful tables, 1 fails), no automatic retry. Operator must manually run backfill for that entity.
- Blocks: Operational resilience; transient network failures cascade.
- Mitigation needed: Implement retry decorator with exponential backoff. Track failed entity/doc_type/period for replay.

**No alerting on pipeline failures:**
- Problem: GitHub Actions logs pipeline errors, but no alert to operator (email, Slack, PagerDuty).
- Blocks: Silent failures; daily run could miss data for days unnoticed.
- Mitigation needed: Add notification step in workflow; post to Slack on ingest_log errors.

**No schema versioning:**
- Problem: CVM schema changes (new fields, renamed columns) are handled by adding more field name candidates. No versioning or migration tracking.
- Blocks: Hard to audit which schema version is being parsed for historical data.
- Mitigation needed: Add `schema_version` to ingest_log. Document expected fields per entity/doc_type/date range.

## Test Coverage Gaps

**CVM field mapping not tested against real data:**
- What's not tested: `_find_field()`, `_find_cnpj_field()`, `_find_inadimpl()` are only tested with hardcoded fixture field names.
- Files: `src/pipeline/cvm_pipeline.py:71-94`, test fixtures in `tests/test_cvm_fetch_parse.py:71-180`
- Risk: Real CVM datasets may have slightly different field names (spaces, case variations, abbreviations) not covered by fixtures.
- Priority: High — field mapping is critical path; real-world failures likely.

**BACEN dataframe normalization untested:**
- What's not tested: `_df_to_records()` in `src/fetchers/bacen_fetcher.py:30-58` handles NaN → None, datetime serialization, numpy type conversion. No tests for edge cases (all-NaN columns, mixed types, timezone-aware datetimes).
- Files: `src/fetchers/bacen_fetcher.py:30-58`
- Risk: BACEN ingest could produce malformed JSON or type errors on edge cases.
- Priority: High — BACEN is core pipeline.

**Async exception handling in gather loops:**
- What's not tested: `asyncio.gather(..., return_exceptions=True)` results handling. No test of partial failures (5 tasks succeed, 2 raise exceptions).
- Files: `src/pipeline/cvm_pipeline.py:567-570, 580-583, 604-607, 618-621, 632-635, 683-688`
- Risk: Failed ingest tasks silently ignored; totals undercount.
- Priority: Medium — backfill/daily_update may silently miss data.

**Upsert conflict handling:**
- What's not tested: `upsert_rows()` with duplicate rows and ON CONFLICT logic. No test of Supabase constraint violations.
- Files: `src/store/supabase_client.py:36-73`, used throughout pipeline
- Risk: If conflict_columns is wrong or incomplete, silent silent duplicates or update failures.
- Priority: Medium — data integrity issue.

**Month boundary logic:**
- What's not tested: `daily_update()` month transition (e.g., Dec 31 → Jan 1, or month with <31 days).
- Files: `src/pipeline/cvm_pipeline.py:640-691`
- Risk: Month boundaries may have missing data (Dec carryover, short months).
- Priority: Low-Medium — edge case but recurring monthly.

---

*Concerns audit: 2026-05-05*
