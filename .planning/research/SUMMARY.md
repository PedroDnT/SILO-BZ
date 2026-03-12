# Project Research Summary

**Project:** iliquid_nightly — PostgreSQL Persistence Layer
**Domain:** Database-backed financial time-series API (Brazilian market data — CVM, BACEN, B3 CALC)
**Researched:** 2026-03-12
**Confidence:** HIGH

## Executive Summary

This milestone adds a shared PostgreSQL 16 persistence layer to three already-working FastAPI services (cvm_api, bacen_api, b3_calc_api). The recommended approach is a single Postgres instance with three isolated schemas (cvm, bacen, b3_calc), accessed via SQLAlchemy 2.x async + asyncpg at runtime and Alembic + psycopg2 for schema migrations. All three services adopt a DB-first-with-live-fallback data flow: requests query the database first, fall through to upstream sources on cache miss, and write fetched results back to the DB asynchronously. This preserves the existing cold-start resilience and the B3 CALC sample-data fallback without any breaking changes to existing API contracts.

The build order is dictated by hard infrastructure dependencies: Postgres container and Alembic migrations must be fully operational before any service can use the DB layer. BACEN should be wired first because its data is narrow, typed, and easiest to validate. CVM follows because it carries the most data volume and requires a normalization step before storage. B3 CALC is last because its upstream is currently returning sample data, making a live DB test less meaningful. An incremental sync worker and operational health endpoints complete the milestone.

The primary risks are all well-understood and preventable: leaked async sessions, Alembic misconfiguration with asyncpg, connection pool exhaustion across three services, migration race conditions on Docker Compose startup, and CVM CSV numeric values stored as strings in JSONB. Each has a deterministic fix documented in PITFALLS.md. API contract preservation is the only ongoing concern — it must be enforced by contract snapshot tests from day one, not retrofitted after routes are changed.

---

## Key Findings

### Recommended Stack

The DB layer adds four new dependencies to the existing stack. SQLAlchemy 2.0.48 async provides the ORM, query builder, and Alembic integration; asyncpg 0.31.0 is the high-performance async Postgres driver used at runtime; Alembic 1.18.4 handles schema migrations with multi-schema support; and psycopg2-binary 2.9.11 is used exclusively in the Alembic migration container (Alembic's sync connection path is incompatible with asyncpg). All versions were verified against PyPI on 2026-03-12. The existing `pydantic-settings` in b3_calc_api should be added to cvm_api and bacen_api for environment-driven DB config.

SQLModel was rejected due to incomplete Pydantic v2 compatibility. Raw asyncpg without SQLAlchemy was rejected due to SQL composition overhead and lack of Alembic integration. Tortoise ORM was rejected due to event loop lifecycle conflicts with FastAPI. The `databases` library (encode/databases) was rejected as stale — SQLAlchemy 2.x async subsumes its entire value proposition.

**Core technologies:**
- PostgreSQL 16 (`postgres:16-alpine`): primary database — LTS release, JSONB support, multi-schema, proven at scale
- SQLAlchemy 2.0.48 async: ORM and query layer — first-class async API, integrates natively with FastAPI `Depends`, required by Alembic
- asyncpg 0.31.0: async Postgres driver at runtime — 3-5x faster than psycopg2 under async workloads, native asyncio, no thread-pool wrapping
- Alembic 1.18.4: schema migrations — autogenerates from ORM models, multi-schema support via `include_schemas=True`, one-shot Docker Compose container pattern
- psycopg2-binary 2.9.11: sync driver for Alembic migration container only — standard workaround for asyncpg/Alembic incompatibility

### Expected Features

The DB layer is not functional without the table stakes items: the schema must exist before any ingest can happen, and idempotent upserts must be correct before backfill and sync can be trusted. The live-fallback routing and operational health endpoints are v1.x additions after the DB is warm. Advanced queries (B3 point-in-time snapshots, CNPJ aggregation views, retention policy) are v2+ deferred until schema is stable and the B3 live API is connected.

**Must have (table stakes — P1):**
- Postgres schema + Alembic migrations for CVM FIDC, BACEN SGS, BACEN PTAX — critical path; blocks everything else
- Idempotent upsert (`INSERT ... ON CONFLICT`) — foundation of ingest correctness for both backfill and incremental sync
- Incremental sync worker with watermark-based delta detection — prevents full re-download on every sync run
- DB-primary query endpoints with date range, entity, and CNPJ filters, plus keyset pagination
- Staleness metadata (`data_source: "db"|"live"`, `last_updated_at`) on all responses — via response header, not Pydantic field
- Async DB driver wired via `get_db` FastAPI dependency — session-per-request, not global session
- `DATABASE_URL` and sync config in `.env.example` — no hardcoded connection strings

**Should have (P2 — operational reliability):**
- Per-dataset sync health endpoint (`GET /api/v1/sync/status`) — surfaces broken syncs before consumers notice stale data
- Coverage map endpoint (`GET /api/v1/coverage`) — per-dataset `{start_date, end_date, record_count, last_synced_at}`
- Live-fallback with DB-primary routing — bridges cold-start window; requires DB warm before enabling

**Defer (v2+):**
- Point-in-time B3 pricing snapshots — defer until B3 live API is connected (currently sample data only)
- CNPJ aggregation materialized view — defer until CVM schema is stable across entity types
- Configurable retention policy with range partitioning — defer until storage cost is measurable
- Redis caching — defer until load testing reveals actual hot queries

**Explicit anti-features for this milestone:**
- Real-time WebSocket streaming: upstream data is published daily/monthly — nothing to stream
- Full-text search: `ILIKE` on fund name + exact CNPJ match covers 95% of lookup cases; GIN tsvector adds migration complexity before schema stability
- Multi-tenant RLS: auth layer does not exist yet; RLS without a subject is meaningless
- GraphQL: dataset schemas are not deeply relational; REST with filter params covers the query space at far lower cost

### Architecture Approach

The architecture centers on a single shared Postgres instance with three schemas (cvm, bacen, b3_calc), each accessed only by its corresponding service via a restricted per-service database user with `search_path` set in the connection URL. A new `src/db/` directory holds all shared ORM models, Alembic configuration, and migration scripts, making the schema a single source of truth across services. Each service gains a `db.py` (engine + session factory) and `db_service.py` (query functions) alongside existing `config.py`, `models.py`, `services.py`, `main.py`. A dedicated one-shot `db_migrate` compose service runs Alembic before API services start. The backfill pipeline runs as a separate process, never inside a running FastAPI worker.

Schema strategy differs by data type: BACEN SGS and PTAX use typed normalized columns (narrow, repetitive, queryable); CVM uses a JSONB payload column (20-80 columns per doc_type that vary by entity) with typed extraction columns for common query fields (CNPJ, date, entity); B3 CALC uses per-security and per-price tables with JSONB payload. The DB-first-with-live-fallback pattern is a try/except wrapper in each route handler — DB unavailability silently degrades to the existing upstream fetch path, preserving cold-start resilience.

**Major components:**
1. `postgres:16-alpine` container — single shared instance, three schemas, per-service users, `pg_isready` healthcheck
2. `db_migrate` one-shot compose service — runs `alembic upgrade head` before any API service starts; uses psycopg2 sync DSN
3. `src/db/` — shared Alembic config, ORM models, migration scripts (cvm, bacen, b3_calc schemas)
4. Per-service `db.py` + `db_service.py` — async engine, session factory, query/insert functions; `get_db` dependency injected into route handlers
5. `backfill_db.py` CLI — DB-aware extension of existing `backfill.py`; writes to DB via same upsert functions as sync worker; runs as separate process
6. Incremental sync worker — watermark-based delta sync per dataset; runs on configurable interval as separate compose service or cron

### Critical Pitfalls

1. **Async session leaked as a module-level global** — use `async_sessionmaker` as the singleton, never `AsyncSession`; inject per-request via `Depends(get_db)`; set `expire_on_commit=False`
2. **Alembic env.py using asyncpg DSN with sync `engine.connect()`** — use `postgresql://` (psycopg2) DSN in Alembic `env.py` only; keep `postgresql+asyncpg://` for runtime; prevents `MissingGreenlet` crash
3. **Connection pool exhaustion across three services** — set `pool_size=5, max_overflow=10` per API service; `pool_size=2` for backfill runner; set `POSTGRES_MAX_CONNECTIONS=200` in compose; total 42 connections, well within limit
4. **Migration race on Docker Compose startup** — extract Alembic to a dedicated `db_migrate` one-shot container; API services `depends_on: db_migrate: condition: service_completed_successfully`; never run migrations in each service's entrypoint
5. **CVM CSV numeric strings inserted as JSONB strings** — add `normalize_cvm_row()` before DB insert to convert known numeric fields from Brazilian decimal-comma strings to Python float/int; otherwise `ORDER BY` and range queries on numeric fields fail silently
6. **API contract breakage via new Pydantic response fields** — never add fields to existing response models; use `X-Data-Source` response header for provenance; add contract snapshot tests from day one

---

## Implications for Roadmap

Based on research, the 5-phase structure from ARCHITECTURE.md is the correct build order. Each phase has a hard dependency on the prior one. Skipping or reordering phases results in integration failures that are expensive to untangle.

### Phase 1: DB Foundation
**Rationale:** Nothing else can proceed without Postgres container, schemas, users, and migrations. This is the critical path item that blocks all downstream phases. All infrastructure decisions (pool sizing, Alembic config, compose topology) must be correct here.
**Delivers:** Running Postgres 16 container in compose, three schemas (`cvm`, `bacen`, `b3_calc`), per-service DB users, SQLAlchemy ORM table definitions in `src/db/models/`, Alembic migration scripts applied via one-shot `db_migrate` compose service, connection pool patterns validated.
**Addresses features:** Schema design, schema migrations with version control, environment-driven DB config, async DB driver setup
**Avoids pitfalls:** Async Alembic env.py misconfiguration (Pitfall 2), migration race on startup (Pitfall 4), missing Postgres healthcheck (Pitfall 8), hardcoded DATABASE_URL

### Phase 2: BACEN DB Layer
**Rationale:** BACEN data has the simplest, most typed schema (narrow SGS/PTAX rows), making it the easiest integration to validate end-to-end. Completing this phase proves the DB-first-with-fallback pattern before tackling CVM's higher complexity and data volume. BACEN python-bcb library behavior is already well-understood.
**Delivers:** `src/bacen_api/db.py`, `src/bacen_api/db_service.py`, DB-first SGS/PTAX route handlers, `bacen_backfill.py` CLI, staleness metadata on BACEN responses.
**Uses stack:** asyncpg 0.31.0 + SQLAlchemy 2.0.48 async first live in a service; `get_db` dependency pattern
**Implements architecture:** BACEN schema (`sgs_observations`, `ptax_rates`, `expectativas`, `taxa_juros_snapshots`), DB-first-with-fallback flow, idempotent upsert for PTAX (rates can be revised)
**Avoids pitfalls:** Leaked async session (Pitfall 1), sync python-bcb blocking event loop during backfill (Pitfall 7), pool exhaustion (Pitfall 3)

### Phase 3: CVM DB Layer
**Rationale:** CVM carries the most data volume (200k+ rows per FIDC monthly file) and requires a normalization step before insert that BACEN does not. Building on the validated DB-first pattern from Phase 2, Phase 3 extends it with JSONB storage strategy, the `cvm_ingest_log` resume table, and bulk insert optimization. This phase replaces the file-based backfill progress tracker.
**Delivers:** `src/cvm_api/db.py`, `src/cvm_api/db_service.py`, DB-first CVM route handlers, `backfill_db.py` (DB-aware replacement for `backfill.py`), `normalize_cvm_row()` normalization function, `cvm_ingest_log` table replacing file-based progress tracker.
**Addresses features:** Historical backfill pipeline, DB-primary query endpoints for CVM, incremental sync with watermark, idempotent upsert
**Avoids pitfalls:** CVM CSV numerics as JSONB strings (Pitfall 5), API contract breakage (Pitfall 6), `SELECT *` without DB-side pagination

### Phase 4: B3 CALC DB Layer
**Rationale:** B3 CALC is deferred until Phase 4 because its upstream currently returns sample data, limiting the ability to validate live data ingestion. The schema differs from CVM/BACEN (pricing snapshots, not time-series), and the three-level fallback chain (DB → live upstream → sample data) is the most complex data flow. By Phase 4, the DB-first pattern is proven in two services.
**Delivers:** `src/b3_calc_api/db.py`, `src/b3_calc_api/db_service.py`, three-level fallback chain (DB → live → sample data), `b3_backfill.py` daily snapshot sync. Sample data fallback preserved as last resort per CLAUDE.md.
**Addresses features:** B3 CALC listings served from DB, live-fallback routing for B3
**Avoids pitfalls:** API contract breakage (Pitfall 6), B3 sample data being written to DB (it must not be; only live data belongs in storage)

### Phase 5: Incremental Sync and Hardening
**Rationale:** Once all three services have a DB layer, incremental sync can run across all datasets in a unified way. This phase adds the operational visibility endpoints, full test coverage with mocked DB sessions, and removes the remaining file-based state in `backfill.py`.
**Delivers:** Scheduled incremental sync runner (compose service or cron), `/api/v1/sync/status` health endpoint, `/api/v1/coverage` coverage map, DB health check in each service's `/health` endpoint, full pytest suite passing with Postgres container running, `cvm_ingest_log` fully replacing file-based progress tracker.
**Addresses features:** Per-dataset sync health endpoint (P2), coverage map endpoint (P2), live-fallback with DB-primary routing (P2)
**Avoids pitfalls:** All pitfalls verified via "Looks Done But Isn't" checklist from PITFALLS.md

### Phase Ordering Rationale

- Phase 1 (Foundation) must come first: Postgres container, schemas, and Alembic migrations are hard prerequisites for all subsequent phases. No service can open a connection pool to a schema that does not exist.
- Phase 2 (BACEN) before Phase 3 (CVM) because BACEN data is narrowly typed and the schema is smaller — it is the lowest-risk integration to validate the DB-first pattern before scaling to CVM's data volume.
- Phase 3 (CVM) before Phase 4 (B3) because CVM has the most volume and the normalization complexity should be resolved while the pattern is fresh; B3's upstream instability makes it the last to wire.
- Phase 5 (Hardening) last because it depends on all three service DB layers being operational before incremental sync and coverage endpoints are meaningful.
- Existing API contracts are preserved throughout: DB layer is additive; no existing routes, query params, or response shapes change. Contract snapshot tests added in Phase 1 enforce this for all subsequent phases.

### Research Flags

Phases with well-documented patterns (deep research-phase not needed):
- **Phase 1:** Alembic multi-schema setup and Docker Compose healthcheck/depends_on patterns are thoroughly documented; STACK.md provides exact configuration templates.
- **Phase 2:** BACEN schema is simple typed time-series; asyncpg + SQLAlchemy session injection into FastAPI is a canonical pattern.
- **Phase 3:** CVM JSONB strategy and bulk upsert patterns are documented; normalization approach is clear.
- **Phase 4:** B3 three-level fallback is a direct extension of existing two-level pattern; no novel architecture needed.

Phases that may need targeted research during planning:
- **Phase 3 (CVM backfill):** The `asyncpg.copy_records_to_table` bulk insert path for 200k+ row CVM files may benefit from a performance spike before implementation; row-by-row insert will be too slow at that volume.
- **Phase 5 (Incremental sync):** Scheduling mechanism (compose cron vs. dedicated `sync_runner` service vs. external scheduler) has trade-offs that depend on deployment environment; a quick spike is recommended.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All versions verified against PyPI on 2026-03-12; compatibility table explicitly provided in STACK.md; no version ambiguity |
| Features | HIGH | Feature set derived directly from existing codebase analysis and clear business requirements; dependency graph is explicit |
| Architecture | HIGH | Architecture is a straightforward extension of existing patterns; schema designs are complete SQL DDL, not hand-wavy; pool sizing arithmetic is shown |
| Pitfalls | HIGH | Pitfalls are grounded in specific existing code patterns (BacenClient global, ThreadPoolExecutor in backfill.py, asyncpg/Alembic known issue); not speculative |

**Overall confidence:** HIGH

### Gaps to Address

- **CVM bulk insert performance:** Row-by-row asyncpg inserts for FIDC monthly files (200k+ rows) will be unacceptably slow. The recommended path is `asyncpg.copy_records_to_table` or SQLAlchemy Core `insert()` with bulk values list. Exact performance threshold not yet measured — spike needed before Phase 3 implementation.
- **Incremental sync scheduling:** Docker Compose does not have a native cron mechanism. Options (dedicated `sync_runner` container with `sleep` loop, external cron, APScheduler inside a service) each have operational trade-offs. This gap does not block Phase 1–4 but must be resolved before Phase 5.
- **B3 live API availability:** The B3 CALC upstream (`calculadorarendafixa.com.br`) is currently unreliable enough that the codebase defaults to sample data. Phase 4 DB integration is partially speculative until the live API is confirmed accessible. The sample-data fallback path means Phase 4 still delivers value even if live data is unavailable.
- **Latin-1 to UTF-8 round-trip for accented fund names:** PITFALLS.md flags this as a verification requirement. The CVM service already decodes from latin-1 before returning data; the question is whether the decode happens before the asyncpg insert or after. Must be confirmed during Phase 3 implementation.

---

## Sources

### Primary (HIGH confidence)
- PyPI `pip index versions` (2026-03-12) — all version numbers verified
- SQLAlchemy 2.x async docs (`docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html`) — session patterns, engine config
- Alembic async migration cookbook (`alembic.sqlalchemy.org`) — psycopg2 DSN workaround for env.py
- FastAPI SQL databases tutorial (`fastapi.tiangolo.com/tutorial/sql-databases/`) — `Depends(get_db)` pattern
- Docker Compose v3.9 docs — `depends_on` with `condition: service_healthy`
- Project codebase (2026-03-12): `src/*/requirements.txt`, `src/cvm_api/services.py`, `src/bacen_api/main.py`, `src/tools/backfill.py`, `docker-compose.yml`
- `.planning/PROJECT.md` — PostgreSQL chosen, shared instance, DB-first with live fallback required

### Secondary (MEDIUM confidence)
- TimescaleDB documentation patterns — time-series schema design reference for financial data
- FRED API (Federal Reserve Economic Data) — public economic data API design reference
- asyncpg `TooManyConnectionsError` community reports — informs pool sizing recommendations

### Tertiary (LOW confidence)
- B3 CALC upstream availability (`calculadorarendafixa.com.br`) — current reliability unknown; Phase 4 has fallback but live data ingestion is unverified

---

*Research completed: 2026-03-12*
*Ready for roadmap: yes*
