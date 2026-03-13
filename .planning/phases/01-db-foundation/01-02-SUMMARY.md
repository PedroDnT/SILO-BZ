---
phase: 01-db-foundation
plan: "02"
subsystem: database
tags: [sqlalchemy, postgresql, alembic, orm, schema]

# Dependency graph
requires:
  - phase: 01-db-foundation/01-01
    provides: src/db/requirements.txt with sqlalchemy[asyncio]==2.0.48, alembic, asyncpg; src/db/alembic/ scaffold; init.sql creating cvm/bacen/b3_calc schemas
provides:
  - Single DeclarativeBase class in src/db/models/base.py importable by Alembic env.py
  - CVMRecord ORM stub in cvm schema (cvm.records table)
  - SGSObservation and PTAXRate ORM stubs in bacen schema
  - B3Security and B3PricingSnapshot ORM stubs in b3_calc schema
  - src/db/models package that registers all five tables in Base.metadata on import
affects:
  - 01-db-foundation/01-03 (Alembic autogenerate reads Base.metadata via these models)
  - 01-db-foundation/01-04 (migration execution requires tables to be registered)
  - Phase 2 (bacen ingestion extends SGSObservation, PTAXRate models)
  - Phase 3 (CVM ingestion extends CVMRecord model with JSONB)
  - Phase 4 (B3 CALC extends B3Security, B3PricingSnapshot models with JSONB)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Single DeclarativeBase shared across all schema models"
    - "Per-schema ORM stubs with __table_args__ schema= for PostgreSQL schema assignment"
    - "Text payload stubs as migration baseline — later phases migrate to JSONB"
    - "No cross-schema ForeignKey references; relationships handled at query time"
    - "Composite Index definitions colocated in __table_args__ tuple"

key-files:
  created:
    - src/db/__init__.py
    - src/db/models/__init__.py
    - src/db/models/base.py
    - src/db/models/cvm.py
    - src/db/models/bacen.py
    - src/db/models/b3_calc.py
  modified: []

key-decisions:
  - "Single DeclarativeBase in base.py — ensures all three schemas are captured in one target_metadata for Alembic autogenerate"
  - "Text payload columns as Phase 1 stubs — produces non-empty Alembic migration; later phases ALTER to JSONB without losing migration history"
  - "No cross-schema ForeignKey references — avoids schema-qualification complexity in Phase 1; cross-schema joins done at query time"
  - "Composite indexes colocated in __table_args__ — keeps index definitions visible alongside the columns they index"

patterns-established:
  - "ORM stub pattern: define table structure now, extend columns/constraints in later phases"
  - "Schema qualification pattern: all models set {'schema': '<schema_name>'} in __table_args__"
  - "Models package as Alembic registration trigger: importing src.db.models registers all tables"

requirements-completed: [INFRA-02, INFRA-06]

# Metrics
duration: 1min
completed: 2026-03-12
---

# Phase 1 Plan 02: ORM Model Stubs Summary

**SQLAlchemy ORM stubs for five tables across three PostgreSQL schemas (cvm.records, bacen.sgs_observations, bacen.ptax_rates, b3_calc.securities, b3_calc.pricing_snapshots) with a shared DeclarativeBase for Alembic autogenerate**

## Performance

- **Duration:** 1 min
- **Started:** 2026-03-12T19:58:28Z
- **Completed:** 2026-03-12T20:00:00Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments
- Single `DeclarativeBase` in `src/db/models/base.py` shared by all three schema model files
- Five ORM model stubs (CVMRecord, SGSObservation, PTAXRate, B3Security, B3PricingSnapshot) registered in `Base.metadata` on package import
- All models use `__table_args__` with `schema=` for correct PostgreSQL schema assignment; no cross-schema ForeignKey references

## Task Commits

Each task was committed atomically:

1. **Task 1: Shared DeclarativeBase and package init files** - `8d45f94` (feat)
2. **Task 2: Three schema ORM model stubs** - `f595909` (feat)

## Files Created/Modified
- `src/db/__init__.py` - Empty package init making src/db a Python package
- `src/db/models/__init__.py` - Exports all model classes; triggers Base.metadata registration on import
- `src/db/models/base.py` - Single DeclarativeBase class used by all ORM models
- `src/db/models/cvm.py` - CVMRecord stub: cvm.records table with entity, doc_type, cnpj_key, competence_date, payload columns
- `src/db/models/bacen.py` - SGSObservation (bacen.sgs_observations) and PTAXRate (bacen.ptax_rates) stubs with Numeric(20,8) value columns
- `src/db/models/b3_calc.py` - B3Security (b3_calc.securities) and B3PricingSnapshot (b3_calc.pricing_snapshots) stubs

## Decisions Made
- Text payload columns used as Phase 1 stubs rather than JSONB — produces non-empty Alembic migration baseline; later phases ALTER column type to JSONB without losing migration history
- No cross-schema ForeignKey references in any model — avoids schema-qualification complexity at this stage; cross-schema relationships will be handled at query time in service layers

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Installed missing SQLAlchemy in local environment**
- **Found during:** Task 1 (base.py import verification)
- **Issue:** `sqlalchemy` not installed in the active Python environment; `from sqlalchemy.orm import DeclarativeBase` raised `ModuleNotFoundError`
- **Fix:** Ran `pip install sqlalchemy` — package was already declared in `src/db/requirements.txt` (created by Plan 01-01), just not installed in the dev environment
- **Files modified:** None (environment-only fix)
- **Verification:** `from src.db.models.base import Base` imports successfully
- **Committed in:** N/A (environment fix, not a code change)

---

**Total deviations:** 1 auto-fixed (1 blocking — missing dependency in dev environment)
**Impact on plan:** No scope creep. SQLAlchemy was already declared in requirements; the fix was installing it locally.

## Issues Encountered
- SQLAlchemy not installed in local Python environment despite being declared in `src/db/requirements.txt`. Fixed by running `pip install sqlalchemy`. No code changes required.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All five ORM model stubs are importable and registered in `Base.metadata`
- Plan 01-03 (Alembic env.py configuration) can now reference `from src.db.models.base import Base; target_metadata = Base.metadata`
- Plan 01-04 (migration execution) depends on 01-03 completing first
- Blockers: none — model stubs are self-contained Python; PostgreSQL connection not required for import verification

---
*Phase: 01-db-foundation*
*Completed: 2026-03-12*

## Self-Check: PASSED

- FOUND: src/db/__init__.py
- FOUND: src/db/models/__init__.py
- FOUND: src/db/models/base.py
- FOUND: src/db/models/cvm.py
- FOUND: src/db/models/bacen.py
- FOUND: src/db/models/b3_calc.py
- FOUND: .planning/phases/01-db-foundation/01-02-SUMMARY.md
- FOUND commit 8d45f94 (Task 1)
- FOUND commit f595909 (Task 2)
- FOUND commit 32b2d03 (metadata)
