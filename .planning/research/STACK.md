# Stack Research

**Domain:** PostgreSQL persistence layer — FastAPI multi-service Python 3.12 app (Brazilian financial data)
**Researched:** 2026-03-12
**Research type:** Subsequent milestone — adding DB persistence to existing working API
**Confidence:** HIGH (versions verified via `pip index versions` against PyPI on 2026-03-12)

---

## Context Snapshot (Existing Stack — Do Not Re-Research)

The three services already in production use:

| Component | Current version |
|-----------|----------------|
| FastAPI | 0.109.2 |
| Pydantic | v2 (2.5.3 / 2.6.1 across services) |
| Python | 3.12 |
| aiohttp | 3.9.1–3.9.3 |
| httpx | 0.27.0 |
| python-bcb | >=0.3.0 |
| Deployment | Docker Compose, single `br_finance` bridge network |

This STACK.md covers only what must be added for the DB layer. It does not re-recommend anything already present.

---

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended | Confidence |
|------------|---------|---------|-----------------|------------|
| PostgreSQL | 16 (Docker image: `postgres:16-alpine`) | Primary database | LTS release as of 2026; `postgres:16-alpine` is the production-standard lightweight image; JSONB support, multi-schema, proven at scale; already chosen in PROJECT.md | HIGH |
| SQLAlchemy (async) | `sqlalchemy[asyncio]==2.0.48` | ORM / query layer for all three services | 2.x is the current stable series (2.0.48 is latest as of 2026-03-12); first-class async API (`AsyncSession`, `async_sessionmaker`, `create_async_engine`); integrates natively with FastAPI `Depends`; query composition, type safety, migration target generation for Alembic | HIGH |
| asyncpg | `asyncpg==0.31.0` | Async PostgreSQL driver (runtime) | Latest stable (0.31.0); the canonical high-performance async Postgres driver for Python; used as the SQLAlchemy dialect via `postgresql+asyncpg://`; built on Python's `asyncio`, no thread-pool wrapping needed; benchmarks consistently 3–5x faster than psycopg2 under async workloads | HIGH |
| Alembic | `alembic==1.18.4` | Database migrations | Latest stable (1.18.4); the official SQLAlchemy migration framework; autogenerates migration scripts from ORM models; supports multi-schema configuration via `include_schemas=True`; one-shot Docker Compose init container pattern is the standard production deployment | HIGH |
| psycopg2-binary | `psycopg2-binary==2.9.11` | Sync driver for Alembic only | Latest stable (2.9.11); Alembic's `env.py` uses a synchronous connection path internally; using `postgresql://` (psycopg2) for Alembic while keeping `postgresql+asyncpg://` for runtime is the standard solution to the asyncpg-Alembic incompatibility (see PITFALLS.md Pitfall 2); `psycopg2-binary` is the pre-compiled wheel, no libpq build step needed in Docker | HIGH |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pydantic-settings` | `pydantic-settings==2.13.1` | `DATABASE_URL` and DB config via env vars | Already in `b3_calc_api/requirements.txt` at 2.2.1; add to `cvm_api` and `bacen_api` as well; use `BaseSettings` to load `DATABASE_URL`, per-service DB credentials, and pool size config from environment | HIGH |
| `greenlet` | `greenlet==3.3.2` | SQLAlchemy async support dependency | Automatically installed as a transitive dependency of `sqlalchemy[asyncio]`; do not pin explicitly — let SQLAlchemy resolve the compatible version; listed here for awareness since it appears in pip's dependency tree | MEDIUM |

### Development and Migration Tools

| Tool | Version | Purpose | Notes |
|------|---------|---------|-------|
| Alembic CLI | (included in `alembic==1.18.4`) | `alembic revision --autogenerate`, `alembic upgrade head`, `alembic downgrade` | Run from `src/db/` directory; configure `script_location` in `alembic.ini` to point to `src/db/migrations/` |
| `postgres:16-alpine` (Docker image) | `16` tag | Postgres container in Docker Compose | Alpine-based = smaller image; `pg_isready` available for healthcheck; set `POSTGRES_MAX_CONNECTIONS=200` via environment for headroom across 3 services + backfill |

---

## Installation

```bash
# Per-service requirements.txt additions (all three: cvm_api, bacen_api, b3_calc_api)
sqlalchemy[asyncio]==2.0.48
asyncpg==0.31.0

# Shared DB tooling — add to src/db/requirements.txt (migration container)
sqlalchemy[asyncio]==2.0.48
asyncpg==0.31.0
alembic==1.18.4
psycopg2-binary==2.9.11

# Config management — add to any service that doesn't already have it
pydantic-settings==2.13.1
```

---

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative | Why Not Here |
|-------------|-------------|-------------------------|--------------|
| SQLAlchemy 2.x async | **SQLModel 0.0.37** | Greenfield projects where one model serves as both ORM and Pydantic API model | SQLModel is built on SQLAlchemy 2 + Pydantic v1 patterns; its Pydantic v2 compatibility is incomplete (still at version 0.0.x); the existing codebase has fully separate Pydantic models and ORM will add new models — no benefit from merging them; SQLModel's `select()` API is less powerful for complex joins and JSONB queries |
| SQLAlchemy 2.x async | **asyncpg directly (no ORM)** | Single-service apps with simple, static SQL; teams comfortable with raw SQL composition | Three services with different schemas; raw asyncpg requires manual SQL string composition, no migration target generation, no query tracing integration; the overhead of SQLAlchemy's core abstraction is justified by the Alembic integration and `select()` query builder |
| SQLAlchemy 2.x async | **databases 0.9.0** (encode/databases) | Simple query patterns, if you want a thinner wrapper | Last release 0.9.0 (stale development cadence); does not integrate with Alembic natively; SQLAlchemy has absorbed all its async patterns natively in 2.x; the `databases` library's original value proposition (async DB access for Starlette) is now met directly by SQLAlchemy async |
| SQLAlchemy 2.x async | **Tortoise ORM 1.1.6** | Django-style active record pattern; teams from Django background | Tortoise uses `asyncio.run()` model lifecycle that conflicts with FastAPI's event loop management; migrations via Aerich (less mature than Alembic); no straightforward multi-schema support; not the ecosystem standard for FastAPI+PostgreSQL |
| asyncpg (runtime driver) | **psycopg3 (psycopg 3.3.3)** | Greenfield projects; if you want a single driver for both Alembic and runtime | `asyncpg` has deeper native Python async integration and a longer FastAPI+SQLAlchemy track record; `psycopg3` async support is newer and less battle-tested in this specific stack combination; asyncpg 0.31.0 has explicit SQLAlchemy 2.x dialect support; acceptable to switch to psycopg3 in a future milestone |
| PostgreSQL 16 | **PostgreSQL 17** | New projects started today with no legacy concerns | Postgres 17 is stable but Postgres 16 is the most widely deployed LTS version in Docker workflows as of 2026-Q1; `postgres:16-alpine` image is more battle-tested in CI; migrate to 17 when it becomes the default LTS recommendation |
| Alembic (one-shot container) | **`Base.metadata.create_all(engine)` on startup** | Local development only, throwaway databases | `create_all` has no rollback path, no version history, and no way to evolve an existing schema without dropping tables; never acceptable in production or Docker Compose; Alembic is the only acceptable choice here |

---

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `psycopg2` (sync) as the runtime FastAPI driver | Blocking I/O in an async event loop; requires `run_in_executor` wrapping on every DB call; defeats the purpose of FastAPI's async model; `psycopg2-binary` is acceptable **for Alembic only** (sync migration path) | `asyncpg==0.31.0` for runtime; `psycopg2-binary==2.9.11` for Alembic only |
| `databases` (encode/databases) | Stale development cadence; no Alembic integration; SQLAlchemy 2.x async replaces its entire value proposition natively | `sqlalchemy[asyncio]` + `asyncpg` |
| SQLModel 0.0.x | Incomplete Pydantic v2 compatibility; still at pre-1.0 version; conflates ORM and API models in a way that breaks this project's existing separation | SQLAlchemy 2.x + existing Pydantic v2 models (kept separate) |
| Tortoise ORM | Event loop lifecycle conflicts with FastAPI; Aerich migrations less mature than Alembic; no multi-schema support out of the box | SQLAlchemy 2.x async |
| Raw asyncpg without SQLAlchemy | No query builder, no migration target autogeneration, no tracing integration, high SQL composition burden across three schemas | SQLAlchemy 2.x async core with `select()` / `insert()` constructors |
| SQLAlchemy 1.4 (the "async preview" version) | Async support was experimental in 1.4; 2.x rewrote the async layer; 1.4 is EOL | SQLAlchemy 2.0.48 |
| `postgresql+asyncpg://` URL in Alembic `env.py` with sync `engine.connect()` | Raises `MissingGreenlet: greenlet_spawn has not been called` — asyncpg cannot be used with synchronous connection calls; migrations silently skip or crash | Use `postgresql://` (psycopg2) DSN for Alembic `env.py` only; keep `postgresql+asyncpg://` for runtime SQLAlchemy engine |
| `pool_size=10` or higher per service without PgBouncer | Three services × 10 connections + max_overflow = 60+ connections; default `max_connections=100`; backfill runner adds more; pool exhaustion causes cascading 500s | `pool_size=5, max_overflow=10` per API service; `pool_size=2, max_overflow=2` for backfill runner |
| Running `alembic upgrade head` inside each service's container entrypoint | Three containers racing to run migrations simultaneously causes `DuplicateTable` errors and lock contention | Dedicated one-shot `db_migrate` container with `depends_on: postgres: condition: service_healthy`; API services set `depends_on: db_migrate: condition: service_completed_successfully` |
| Hardcoding `DATABASE_URL` in `config.py` | Breaks Docker networking, leaks credentials into git history | `os.getenv("DATABASE_URL", ...)` with a safe localhost default; loaded via `pydantic-settings` |

---

## Stack Patterns by Variant

**If Postgres container is unavailable (cold start, DB down):**
- Use the existing DB-first-with-live-fallback pattern (see ARCHITECTURE.md §3)
- SQLAlchemy engine raises `asyncpg.exceptions.CannotConnectNowError` — catch at service layer, fall through to upstream fetch
- B3 CALC: three-level fallback (DB → live upstream → sample data) — sample data fallback is never removed per CLAUDE.md

**If running migrations (Docker Compose startup):**
- Use `postgresql://` (psycopg2 sync DSN) in Alembic `env.py`, not `postgresql+asyncpg://`
- Run as one-shot `db_migrate` container; API services `depends_on` its completion
- `alembic.ini` `script_location` points to `src/db/migrations/`

**If running backfill (CLI, separate process):**
- Do not run inside FastAPI worker (event loop contamination)
- Use direct synchronous `python-bcb` calls for BACEN data (no `asyncio.to_thread` needed in a CLI script)
- Use a separate, size-limited connection pool (`pool_size=2`) separate from API pools
- Invoke: `PYTHONPATH=. python -m src.tools.backfill_db --incremental`

**If adding a new service in the future:**
- Copy the `db.py` + `db_service.py` pattern from an existing service
- Add a new schema to `src/db/init.sql` and a new Alembic migration
- Create a restricted Postgres user for the new service
- Update pool sizing arithmetic (keep total < `max_connections - 10`)

---

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| `sqlalchemy[asyncio]==2.0.48` | `asyncpg==0.31.0` | asyncpg is the standard async dialect for SQLAlchemy 2.x; these versions have verified compatibility |
| `sqlalchemy[asyncio]==2.0.48` | `alembic==1.18.4` | Alembic 1.18.x tracks SQLAlchemy 2.x; Alembic autogenerate uses `sqlalchemy.orm.DeclarativeBase` (not `declarative_base()` from 1.x) |
| `sqlalchemy[asyncio]==2.0.48` | `pydantic==2.6.1` (existing) | No direct dependency; ORM models and Pydantic models are kept separate; `model_validate(obj, from_attributes=True)` is the v2 bridge |
| `asyncpg==0.31.0` | Python 3.12 | asyncpg 0.29+ has explicit Python 3.12 support; confirmed |
| `psycopg2-binary==2.9.11` | Python 3.12 | psycopg2-binary 2.9.x supports Python 3.12; used only in the migration container, not runtime |
| `alembic==1.18.4` | `psycopg2-binary==2.9.11` | Standard sync migration path; no compatibility issues |
| `pydantic-settings==2.13.1` | `pydantic==2.6.1` (existing) | pydantic-settings 2.x requires pydantic 2.x; 2.13.1 is compatible with pydantic 2.6.1 |
| `greenlet==3.3.2` | `sqlalchemy[asyncio]==2.0.48` | Installed automatically as SQLAlchemy async transitive dependency; do not pin separately |

---

## Engine and Session Configuration Reference

```python
# src/{service}/db.py — canonical pattern for all three services

import os
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker,
)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://localhost:5432/iliquid"
)

engine = create_async_engine(
    DATABASE_URL,
    pool_size=5,           # per API service; 3 for b3_calc_api
    max_overflow=10,
    pool_timeout=30,
    pool_recycle=1800,     # recycle stale connections after 30 min idle
    pool_pre_ping=True,    # detect stale connections after Postgres restart
    echo=False,            # set True only during development
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    expire_on_commit=False,  # REQUIRED: prevents MissingGreenlet on attribute access post-commit
    class_=AsyncSession,
)

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields a per-request session, always closes on exit."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
```

---

## Alembic Multi-Schema Configuration Reference

```python
# src/db/env.py — async migration pattern using psycopg2 DSN (not asyncpg)
# This avoids the MissingGreenlet error from using asyncpg in sync Alembic context.

import os
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
from src.db.models.base import metadata  # SQLAlchemy MetaData with all schemas

config = context.config
fileConfig(config.config_file_name)

# Use sync psycopg2 DSN for Alembic — swap asyncpg DSN to psycopg2
sync_url = os.getenv("DATABASE_URL", "postgresql://localhost/iliquid").replace(
    "postgresql+asyncpg://", "postgresql://"
)
config.set_main_option("sqlalchemy.url", sync_url)

def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=metadata,
            include_schemas=True,               # REQUIRED for multi-schema
            version_table="alembic_version",
            version_table_schema="public",      # version table in public schema
        )
        with context.begin_transaction():
            context.run_migrations()

run_migrations_online()
```

---

## Sources

- PyPI `pip index versions` (2026-03-12): SQLAlchemy latest = 2.0.48, Alembic = 1.18.4, asyncpg = 0.31.0, psycopg2-binary = 2.9.11, psycopg (psycopg3) = 3.3.3, SQLModel = 0.0.37, databases = 0.9.0, pydantic-settings = 2.13.1
- SQLAlchemy 2.x async docs: `https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html` — async session, engine, `async_sessionmaker` patterns
- Alembic async cookbook: `https://alembic.sqlalchemy.org/en/latest/cookbook.html#using-asyncio-with-alembic` — the psycopg2 DSN workaround for Alembic env.py
- FastAPI SQL databases tutorial: `https://fastapi.tiangolo.com/tutorial/sql-databases/` — `Depends(get_db)` dependency injection pattern
- Project codebase (2026-03-12): `src/*/requirements.txt`, `docker-compose.yml`, `src/b3_calc_api/config.py`, `src/bacen_api/models.py`, `src/cvm_api/models.py` — verified existing stack constraints
- `.planning/PROJECT.md`: PostgreSQL chosen over SQLite; shared instance; DB-first with live fallback required; Pydantic v2 throughout
- `.planning/research/ARCHITECTURE.md` (same milestone): detailed schema design, pool sizing table, compose topology — informs pool size and driver choices in this document
- `.planning/research/PITFALLS.md` (same milestone): asyncpg/Alembic incompatibility (Pitfall 2), pool exhaustion (Pitfall 3), migration race (Pitfall 4) — inform the "What NOT to Use" and configuration reference sections above

---

*Stack research for: PostgreSQL persistence layer — FastAPI multi-service Brazilian financial data platform*
*Researched: 2026-03-12*
