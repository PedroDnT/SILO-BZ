# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-12)

**Core value:** Any endpoint returns historical financial data instantly from a local database, without hitting upstream sources on every request.
**Current focus:** Phase 1 — DB Foundation

## Current Position

Phase: 1 of 4 (DB Foundation)
Plan: 2 of 4 in current phase
Status: In progress
Last activity: 2026-03-12 — Plan 01-02 complete: ORM model stubs for cvm/bacen/b3_calc schemas

Progress: [██░░░░░░░░] 20%

## Performance Metrics

**Velocity:**
- Total plans completed: 2
- Average duration: ~5min
- Total execution time: ~10min

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-db-foundation | 2 | ~10min | ~5min |

**Recent Trend:**
- Last 5 plans: 01-01 (Alembic scaffold), 01-02 (ORM stubs)
- Trend: On track

*Updated after each plan completion*
| Phase 01-db-foundation P01 | 2 | 3 tasks | 9 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Pre-Phase 1]: PostgreSQL over SQLite — multi-service access, JSONB for flexible CVM schemas, production-ready
- [Pre-Phase 1]: Single shared Postgres instance with three isolated schemas (cvm, bacen, b3_calc) — reduces ops overhead
- [Pre-Phase 1]: DB-first with live fallback — preserves cold-start resilience; DB unavailability silently degrades to existing upstream fetch
- [01-02]: Single DeclarativeBase shared across all schema models — ensures all three schemas captured in one target_metadata for Alembic autogenerate
- [01-02]: Text payload stubs in Phase 1 — produces non-empty migration baseline; later phases ALTER to JSONB without losing migration history
- [01-02]: No cross-schema ForeignKey references — avoids schema-qualification complexity; relationships handled at query time
- [Phase 01-01]: postgres -N 200 sets max_connections=200 per QUERY-04 for connection pool headroom across all three API services
- [Phase 01-01]: version_table_schema=public keeps alembic_version in public schema to avoid per-schema table sprawl
- [Phase 01-01]: include_schemas=True in Alembic env.py enables autogenerate to detect non-public schemas (cvm, bacen, b3_calc)

### Pending Todos

None yet.

### Blockers/Concerns

- [Phase 3]: CVM bulk insert performance for 200k+ row files — `asyncpg.copy_records_to_table` vs SQLAlchemy Core bulk values path; spike recommended before Phase 3 implementation
- [Phase 4]: B3 live upstream (`calculadorarendafixa.com.br`) reliability is unverified; Phase 4 still delivers value via sample-data fallback but live data ingestion may be limited

## Session Continuity

Last session: 2026-03-12
Stopped at: Completed 01-01-PLAN.md — PostgreSQL 16 container, init.sql schema/user creation, Alembic async migration setup, docker-compose three-tier dependency chain
Resume file: None
