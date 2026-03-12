---
phase: 01-db-foundation
plan: "01"
subsystem: database
tags: [postgres, alembic, sqlalchemy, asyncpg, docker-compose]

# Dependency graph
requires: []
provides:
  - PostgreSQL 16 container with pg_isready healthcheck
  - init.sql schema/user creation (cvm, bacen, b3_calc schemas + per-service users)
  - db_migrate one-shot Alembic async migration runner
  - Three-tier dependency chain (db -> db_migrate -> API services)
  - All *_DATABASE_URL env vars documented in .env.example
affects: [01-02, 01-03, 01-04, 02-data-ingestion, 03-query-layer, 04-b3-live]

# Tech tracking
tech-stack:
  added: [postgres:16, sqlalchemy[asyncio]==2.0.48, asyncpg==0.31.0, alembic==1.18.4, python-dotenv==1.0.1]
  patterns: [alembic-async-migrations, docker-service-health-ordering, per-schema-pg-users, environment-variable-substitution]

key-files:
  created:
    - src/db/init.sql
    - src/db/requirements.txt
    - src/db/Dockerfile
    - src/db/alembic.ini
    - src/db/alembic/env.py
    - src/db/alembic/script.py.mako
    - src/db/alembic/versions/.gitkeep
    - .env.example
  modified:
    - docker-compose.yml

key-decisions:
  - "postgres -N 200 sets max_connections=200 per QUERY-04 requirement for connection pool headroom"
  - "version_table_schema=public keeps alembic_version in public schema to avoid per-schema version table sprawl"
  - "include_schemas=True in Alembic context.configure enables autogenerate to detect cvm/bacen/b3_calc schemas"
  - "NullPool in async_engine_from_config ensures clean one-shot execution without dangling connections"
  - "Docker default values (${VAR:-default}) allow compose to work without .env file in dev while requiring proper env in production"

patterns-established:
  - "Per-schema isolation: each API service owns exactly one schema and one Postgres user"
  - "Three-tier startup ordering: db (healthy) -> db_migrate (completed) -> API services (started)"
  - "Environment variable substitution pattern: ${VAR:-safe_default} for all database connection strings"
  - "Alembic offline mode disabled: raises NotImplementedError to prevent silent no-op migrations"

requirements-completed: [INFRA-01, INFRA-03, INFRA-04, INFRA-05]

# Metrics
duration: 2min
completed: 2026-03-12
---

# Phase 1 Plan 01: DB Infrastructure Summary

**PostgreSQL 16 with async Alembic migrations, three-schema isolation (cvm/bacen/b3_calc), and Docker Compose three-tier startup ordering (db healthy -> db_migrate exits 0 -> API services start)**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-12T19:58:25Z
- **Completed:** 2026-03-12T20:00:37Z
- **Tasks:** 3
- **Files modified:** 9

## Accomplishments
- PostgreSQL 16 container with pg_isready healthcheck, postgres_data named volume, and init.sql mounted via docker-entrypoint-initdb.d
- init.sql creates three isolated schemas (cvm, bacen, b3_calc) with three per-service users and ALTER DEFAULT PRIVILEGES for future table grants
- Async Alembic migration runner with include_schemas=True, version_table_schema=public, NullPool, and DATABASE_URL injected from environment
- docker-compose.yml updated with db + db_migrate + full dependency chain; all API services declare service_completed_successfully on db_migrate

## Task Commits

Each task was committed atomically:

1. **Task 1: PostgreSQL 16 container + init.sql schema/user creation** - `8bcb644` (feat)
2. **Task 2: Alembic async migration setup + db_migrate Dockerfile** - `1170c78` (feat)
3. **Task 3: Update docker-compose.yml with full DB topology** - `f9034fb` (feat)

## Files Created/Modified
- `src/db/init.sql` - Three schemas, three per-service users, GRANT statements with ALTER DEFAULT PRIVILEGES
- `src/db/requirements.txt` - sqlalchemy[asyncio], asyncpg, alembic, python-dotenv for migration container
- `src/db/Dockerfile` - One-shot migration runner image (CMD: alembic -c src/db/alembic.ini upgrade head)
- `src/db/alembic.ini` - Minimal alembic config (script_location, logging); no hardcoded DATABASE_URL
- `src/db/alembic/env.py` - Async migration runner with include_schemas=True, version_table_schema=public, NullPool
- `src/db/alembic/script.py.mako` - Standard Alembic migration file template
- `src/db/alembic/versions/.gitkeep` - Keeps versions directory tracked in git before any migrations
- `.env.example` - Documents POSTGRES_PASSWORD + four *_DATABASE_URL variables (five total)
- `docker-compose.yml` - Added db, db_migrate services; updated all three API services with dependency chain and per-service DATABASE_URL env vars

## Decisions Made
- `postgres -N 200` sets max_connections=200 per QUERY-04 requirement for connection pool headroom across all three API services
- `version_table_schema=public` keeps the alembic_version tracking table in the public schema to avoid one table per schema
- `include_schemas=True` in Alembic enables autogenerate to detect changes in cvm, bacen, b3_calc schemas
- Docker `${VAR:-default}` syntax allows compose to work without a .env file in dev while production injects proper credentials

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None. All verification checks passed on first attempt.

Note: During verification check 7 (confirming src/db/__init__.py was NOT created by this plan), a prior Plan 01-02 execution was discovered in git history (commit 8d45f94). This is expected — the file was created by the correct owner plan. This plan correctly did not create it.

## User Setup Required

None — no external service configuration required for this infrastructure plan. Copy `.env.example` to `.env` and set `POSTGRES_PASSWORD` before running `docker-compose up`.

## Next Phase Readiness
- Plan 01-02 (models package) and Plan 01-03 (first migrations) can now execute
- src/db/__init__.py and src/db/models/ package already exist from a prior Plan 01-02 execution (commit 8d45f94)
- docker-compose.yml is ready for `docker-compose up` once POSTGRES_PASSWORD is set in .env

---
*Phase: 01-db-foundation*
*Completed: 2026-03-12*

## Self-Check: PASSED

All files confirmed present and all task commits verified in git history.

- `src/db/init.sql` - FOUND
- `src/db/requirements.txt` - FOUND
- `src/db/Dockerfile` - FOUND
- `src/db/alembic.ini` - FOUND
- `src/db/alembic/env.py` - FOUND
- `src/db/alembic/script.py.mako` - FOUND
- `src/db/alembic/versions/.gitkeep` - FOUND
- `.env.example` - FOUND
- `docker-compose.yml` - FOUND (modified)
- Commit `8bcb644` - FOUND
- Commit `1170c78` - FOUND
- Commit `f9034fb` - FOUND
