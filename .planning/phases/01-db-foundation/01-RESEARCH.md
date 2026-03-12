# Phase 1: DB Foundation - Research

**Researched:** 2026-03-12
**Domain:** PostgreSQL 16 + SQLAlchemy 2.0 async + Alembic migrations + Docker Compose orchestration
**Confidence:** HIGH

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| INFRA-01 | PostgreSQL 16 container runs in Docker Compose with `pg_isready` healthcheck | Docker Compose postgres:16 image, pg_isready healthcheck pattern documented |
| INFRA-02 | Three isolated schemas (`cvm`, `bacen`, `b3_calc`) with per-service DB users | PostgreSQL `CREATE SCHEMA` + `GRANT` patterns; per-user schema isolation via `GRANT USAGE` + `GRANT ALL ON ALL TABLES` |
| INFRA-03 | Alembic migrations apply via dedicated one-shot `db_migrate` compose service before any API service starts | Alembic async env.py with `asyncio.run(run_async_migrations())`; docker-compose `command: alembic upgrade head` one-shot pattern |
| INFRA-04 | All API services declare `depends_on: db_migrate: condition: service_completed_successfully` | Docker Compose `service_completed_successfully` condition documented; requires `db_migrate` to exit 0 |
| INFRA-05 | `DATABASE_URL` and per-service DB credentials configurable via environment variables (no hardcoded strings) | `os.getenv` pattern already used in project; `async_engine_from_config` reads from alembic.ini which reads from env |
| INFRA-06 | ORM table definitions live in `src/db/models/` as shared source of truth | SQLAlchemy 2.0 DeclarativeBase with `__table_args__ = {"schema": "cvm"}` per model; single `Base` imported by all three service engines |
| QUERY-01 | All existing API routes, query parameters, and Pydantic response shapes remain unchanged | Phase 1 adds only `db.py` + `get_db` dependency; no route changes in this phase — routes remain untouched until Phases 2–4 |
| QUERY-03 | Async DB sessions injected via `Depends(get_db)` per-request; no module-level `AsyncSession` globals | `async def get_db()` yielding `AsyncSession` via `async_sessionmaker`; FastAPI `Depends(get_db)` pattern |
| QUERY-04 | Connection pool configured per-service (`pool_size=5, max_overflow=10`); `POSTGRES_MAX_CONNECTIONS=200` set in compose | `create_async_engine(pool_size=5, max_overflow=10)` per service; Postgres `max_connections=200` set via `POSTGRES_MAX_CONNECTIONS` env or `command: postgres -N 200` |
</phase_requirements>

---

## Summary

Phase 1 establishes the shared database infrastructure that every subsequent phase builds on. The technical work spans four layers: (1) a PostgreSQL 16 container with three isolated schemas and per-service users, (2) a one-shot `db_migrate` Alembic service in Docker Compose that runs before any API starts, (3) a shared `src/db/` package containing ORM stubs and the async engine/session factory pattern per service, and (4) a `get_db` FastAPI dependency that services will use in later phases. No existing routes change in this phase — QUERY-01 is satisfied by doing nothing to the routes.

The standard stack is mature and well-documented: SQLAlchemy 2.0.x with `create_async_engine` + `asyncpg` driver, Alembic 1.18.x with the `-t async` template for env.py, and the `postgres:16` Docker image. The only non-trivial configuration challenge is Alembic's multi-schema support: `include_schemas=True` and per-model `__table_args__ = {"schema": "..."}` must be set correctly, and the `search_path` must be SET within the migration transaction to avoid foreign key resolution failures across schemas.

Docker Compose orchestration requires `pg_isready` healthcheck on the postgres service, `db_migrate` depending on `db: condition: service_healthy`, and all three API services depending on `db_migrate: condition: service_completed_successfully`. This guarantees the startup ordering the requirements mandate without any manual intervention.

**Primary recommendation:** Use SQLAlchemy 2.0 `create_async_engine` + `asyncpg` + `async_sessionmaker` per service. Use Alembic `alembic init -t async` for env.py. Structure `src/db/` with a shared `models/` package and per-service `db.py` files containing the engine + `get_db` dependency.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| SQLAlchemy | 2.0.48 | Async ORM + engine + session management | Industry standard for Python async DB; 2.0 API is stable; full asyncio support via `create_async_engine` |
| asyncpg | 0.31.0 | PostgreSQL async driver (used by SQLAlchemy) | Fastest Python PostgreSQL driver; C-optimized; required by SQLAlchemy's `postgresql+asyncpg` dialect |
| Alembic | 1.18.4 | Schema migration management | SQLAlchemy's official migration tool; async template (-t async) supports asyncpg; autogenerate against ORM models |
| postgres | 16 (Docker image) | Database server | Required by INFRA-01; pg_isready included in image |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| python-dotenv | 1.0.x | Load `.env` into environment for Alembic CLI | Only needed for Alembic CLI invocation (env.py reads DATABASE_URL) |
| psycopg2-binary | 2.9.x | Sync driver (optional for Alembic offline mode) | Only if offline migration rendering is needed; asyncpg covers all online paths |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| asyncpg | psycopg3 (asyncio) | psycopg3 is newer but asyncpg has broader SQLAlchemy 2.0 test coverage; asyncpg is the documented first-choice driver |
| SQLAlchemy ORM stubs | Raw SQL (asyncpg native) | Raw asyncpg is faster but loses autogenerate migrations and type-checked models; ORM stubs without business logic is low overhead |
| Alembic | migrate or custom init SQL | Alembic is the only tool with SQLAlchemy metadata autogenerate; custom SQL is brittle across schema versions |

**Installation (shared root requirements.txt additions):**
```bash
pip install "sqlalchemy[asyncio]==2.0.48" "asyncpg==0.31.0" "alembic==1.18.4"
```

**Per-service requirements.txt additions (cvm_api, bacen_api, b3_calc_api):**
```bash
# Add to each service's requirements.txt
sqlalchemy[asyncio]==2.0.48
asyncpg==0.31.0
```

**db_migrate service requirements.txt (new file: src/db/requirements.txt):**
```bash
sqlalchemy[asyncio]==2.0.48
asyncpg==0.31.0
alembic==1.18.4
python-dotenv==1.0.1
```

---

## Architecture Patterns

### Recommended Project Structure

```
src/
├── db/
│   ├── __init__.py
│   ├── requirements.txt       # sqlalchemy, asyncpg, alembic
│   ├── Dockerfile             # one-shot: runs alembic upgrade head
│   ├── models/
│   │   ├── __init__.py        # exports all model classes
│   │   ├── base.py            # DeclarativeBase definition
│   │   ├── cvm.py             # CVM schema ORM stubs
│   │   ├── bacen.py           # BACEN schema ORM stubs
│   │   └── b3_calc.py         # B3 CALC schema ORM stubs
│   └── alembic/
│       ├── alembic.ini        # points to postgresql+asyncpg://
│       ├── env.py             # async runner with include_schemas=True
│       └── versions/          # generated migration files
├── cvm_api/
│   ├── db.py                  # engine + async_sessionmaker + get_db
│   └── ...                    # existing files unchanged
├── bacen_api/
│   ├── db.py                  # engine + async_sessionmaker + get_db
│   └── ...
└── b3_calc_api/
    ├── db.py                  # engine + async_sessionmaker + get_db
    └── ...
```

### Pattern 1: Shared DeclarativeBase with Per-Schema Models

**What:** A single `Base = DeclarativeBase()` defined in `src/db/models/base.py`, imported by all model files. Each model declares its schema via `__table_args__`.

**When to use:** Always — one Base ensures Alembic's `target_metadata` captures all three schemas in a single `alembic upgrade head`.

**Example:**
```python
# Source: https://docs.sqlalchemy.org/en/20/orm/declarative_tables.html
# src/db/models/base.py
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass

# src/db/models/cvm.py
from sqlalchemy import Column, Integer, String, Date, Text
from .base import Base

class CVMRecord(Base):
    __tablename__ = "records"
    __table_args__ = {"schema": "cvm"}

    id = Column(Integer, primary_key=True)
    entity = Column(String(20), nullable=False)
    doc_type = Column(String(50), nullable=False)
    cnpj_key = Column(String(18), nullable=False, index=True)
    competence_date = Column(Date, nullable=True)
    payload = Column(Text, nullable=False)  # JSONB in Phase 3; Text stub here

# src/db/models/bacen.py
from .base import Base
from sqlalchemy import Column, Integer, String, Date, Numeric

class SGSObservation(Base):
    __tablename__ = "sgs_observations"
    __table_args__ = {"schema": "bacen"}

    id = Column(Integer, primary_key=True)
    series_code = Column(Integer, nullable=False, index=True)
    obs_date = Column(Date, nullable=False)
    value = Column(Numeric(precision=20, scale=8), nullable=True)

class PTAXRate(Base):
    __tablename__ = "ptax_rates"
    __table_args__ = {"schema": "bacen"}

    id = Column(Integer, primary_key=True)
    currency_code = Column(String(3), nullable=False, index=True)
    rate_datetime = Column(Date, nullable=False)
    bid = Column(Numeric(precision=20, scale=8), nullable=True)
    ask = Column(Numeric(precision=20, scale=8), nullable=True)
```

### Pattern 2: Per-Service db.py with get_db Dependency

**What:** Each service has its own `db.py` that creates an `AsyncEngine` and `async_sessionmaker`. The `get_db` async generator is the FastAPI dependency.

**When to use:** Always — per-service engines support independent pool sizing and DATABASE_URL per service. No module-level `AsyncSession` globals (QUERY-03).

**Example:**
```python
# Source: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html
# src/cvm_api/db.py
import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

DATABASE_URL = os.environ["CVM_DATABASE_URL"]  # raises if missing — no default

engine = create_async_engine(
    DATABASE_URL,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
```

**FastAPI route usage (Phase 2+ pattern — Phase 1 wires it but doesn't use it in routes yet):**
```python
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

if __package__:
    from .db import get_db
else:
    from db import get_db

@app.get("/api/v1/fidc/{doc_type}")
async def get_fidc_data(
    ...,
    db: AsyncSession = Depends(get_db),  # injected, not global
):
    ...
```

### Pattern 3: Alembic Async env.py for Multi-Schema Migration

**What:** Alembic env.py uses `async_engine_from_config` + `asyncio.run()` to apply migrations to all three schemas in one `alembic upgrade head` call.

**When to use:** Always — this is how the `db_migrate` one-shot service applies migrations.

**Example:**
```python
# Source: https://alembic.sqlalchemy.org/en/latest/cookbook.html
# src/db/alembic/env.py (key sections)
import asyncio
import os
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy import pool, text
from alembic import context

# Import ALL models so autogenerate sees all tables
from src.db.models.base import Base
from src.db.models import cvm, bacen, b3_calc  # noqa: F401

target_metadata = Base.metadata

config.set_main_option(
    "sqlalchemy.url",
    os.environ["DATABASE_URL"].replace("postgresql://", "postgresql+asyncpg://", 1)
)


def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        version_table_schema="public",   # alembic_version stays in public schema
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations():
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online():
    asyncio.run(run_async_migrations())
```

### Pattern 4: Docker Compose Startup Ordering

**What:** Three-tier dependency chain: `db` (postgres) → `db_migrate` (one-shot alembic) → API services.

**When to use:** Always — this satisfies INFRA-03 and INFRA-04.

**Example:**
```yaml
# Source: https://docs.docker.com/compose/how-tos/startup-order/
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_DB: iliquid
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_MAX_CONNECTIONS: 200
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres -d iliquid"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s
    networks:
      - br_finance

  db_migrate:
    build:
      context: .
      dockerfile: src/db/Dockerfile
    command: alembic upgrade head
    environment:
      DATABASE_URL: postgresql+asyncpg://postgres:${POSTGRES_PASSWORD}@db:5432/iliquid
    depends_on:
      db:
        condition: service_healthy
    networks:
      - br_finance
    # No restart — this is a one-shot job

  cvm_api:
    ...
    environment:
      CVM_DATABASE_URL: postgresql+asyncpg://cvm_user:${CVM_DB_PASSWORD}@db:5432/iliquid
    depends_on:
      db_migrate:
        condition: service_completed_successfully
      db:
        condition: service_healthy
    ...
```

### Pattern 5: PostgreSQL Schema + User Initialization SQL

**What:** An init SQL script (mounted as `/docker-entrypoint-initdb.d/init.sql`) creates schemas and per-service users on first container boot.

**When to use:** First-time DB creation. The script runs automatically when the postgres container starts with an empty data volume.

**Example:**
```sql
-- src/db/init.sql (mounted to /docker-entrypoint-initdb.d/)
-- Creates three schemas and their owning roles

CREATE SCHEMA IF NOT EXISTS cvm;
CREATE SCHEMA IF NOT EXISTS bacen;
CREATE SCHEMA IF NOT EXISTS b3_calc;

CREATE USER cvm_user WITH PASSWORD 'cvm_secret';
CREATE USER bacen_user WITH PASSWORD 'bacen_secret';
CREATE USER b3_calc_user WITH PASSWORD 'b3_secret';

-- Schema owners (Alembic runs as postgres superuser)
GRANT USAGE ON SCHEMA cvm TO cvm_user;
GRANT ALL ON ALL TABLES IN SCHEMA cvm TO cvm_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA cvm GRANT ALL ON TABLES TO cvm_user;

GRANT USAGE ON SCHEMA bacen TO bacen_user;
GRANT ALL ON ALL TABLES IN SCHEMA bacen TO bacen_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA bacen GRANT ALL ON TABLES TO bacen_user;

GRANT USAGE ON SCHEMA b3_calc TO b3_calc_user;
GRANT ALL ON ALL TABLES IN SCHEMA b3_calc TO b3_calc_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA b3_calc GRANT ALL ON TABLES TO b3_calc_user;
```

### Anti-Patterns to Avoid

- **Module-level `AsyncSession` global:** Never do `session = AsyncSessionLocal()` at module level. Sessions must be created per-request via `get_db`. (QUERY-03 explicitly prohibits this.)
- **`restart: always` on db_migrate:** The migration service must not restart. It must exit 0 on success and let `service_completed_successfully` unblock the API services.
- **`depends_on: db` without condition:** Bare `depends_on: db` only waits for the container to start, not for PostgreSQL to accept connections. Always use `condition: service_healthy` with `pg_isready`.
- **Single Base with schema in metadata:** `MetaData(schema="cvm")` on the Base would make ALL models default to `cvm`. Use per-model `__table_args__` instead.
- **Lazy loading in async context:** SQLAlchemy forbids implicit lazy loads in async sessions. Use `selectinload()` or avoid relationship traversal in Phase 1 stubs (stubs don't need relationships yet).
- **Not calling `engine.dispose()` on shutdown:** Leaves dangling connections. Add a FastAPI lifespan that disposes the engine on shutdown.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Schema migrations | Custom SQL scripts in Dockerfile | Alembic | Alembic tracks applied versions, supports rollback, autogenerates from models |
| Async PostgreSQL driver | Custom asyncio socket code | asyncpg | asyncpg handles binary protocol, connection pooling, type coercion correctly |
| Connection pool | Manual connection tracking | SQLAlchemy `pool_size`/`max_overflow` | Pool handles connection health, recycling, overflow management with `pool_pre_ping` |
| DB startup waiting | `sleep 5` in entrypoint | `pg_isready` healthcheck + `service_healthy` condition | `sleep` is fragile; `pg_isready` probes the actual TCP port PostgreSQL listens on |
| Per-schema user creation | Hardcoded in application code | `init.sql` mounted to `/docker-entrypoint-initdb.d/` | Postgres executes this automatically on first volume init; idempotent with `IF NOT EXISTS` |
| Session lifecycle | Manual `session.close()` calls | `async with AsyncSessionLocal() as session: yield session` | Context manager guarantees close on exception paths |

**Key insight:** The Alembic + SQLAlchemy + asyncpg stack handles every correctness concern around schema versioning, connection health, and async I/O. The only project-specific logic is model definitions and `DATABASE_URL` routing per service.

---

## Common Pitfalls

### Pitfall 1: Alembic Does Not Detect New Schemas Without `include_schemas=True`

**What goes wrong:** Running `alembic revision --autogenerate` produces an empty migration — Alembic sees no tables to create. This happens even when models have `__table_args__ = {"schema": "cvm"}`.

**Why it happens:** By default, Alembic's autogenerate only inspects the `public` schema. Non-public schemas are invisible unless `include_schemas=True` is set in `context.configure()`.

**How to avoid:** Set `include_schemas=True` in `do_run_migrations()` before calling `context.run_migrations()`.

**Warning signs:** Autogenerated migration file body is empty (`pass` or no operations).

### Pitfall 2: `search_path` Cross-Schema Foreign Key Failures

**What goes wrong:** Alembic migration fails with `ERROR: relation "cvm.records" does not exist` when creating a foreign key reference across schemas.

**Why it happens:** PostgreSQL's default `search_path` is `"$user",public`. When Alembic runs as `postgres` user, `$user` resolves to `postgres` schema (not `cvm`). Cross-schema references need explicit qualification.

**How to avoid:** Use fully qualified table names in ORM models (e.g., `ForeignKey("cvm.records.id")`). For Phase 1 stubs, avoid cross-schema FKs entirely — they are not needed yet.

**Warning signs:** Migration error mentions `relation` or `table` not found even though it exists.

### Pitfall 3: `service_completed_successfully` Requires Zero Exit Code

**What goes wrong:** API services start before migrations finish, causing `psycopg2.errors.UndefinedTable` errors on first request.

**Why it happens:** If `alembic upgrade head` fails (non-zero exit), Docker Compose marks `db_migrate` as failed. If services depend on `service_completed_successfully`, they will NOT start — which is correct behavior. But if the developer uses `restart: on-failure` on `db_migrate`, it retries indefinitely.

**How to avoid:** Do NOT set `restart` on `db_migrate`. Let it fail cleanly so the developer sees the error. Once migrations succeed, it exits 0 and dependent services start.

**Warning signs:** API services never reach healthy state; `docker-compose logs db_migrate` shows migration errors.

### Pitfall 4: `expire_on_commit=False` Is Required for Async

**What goes wrong:** After `await session.commit()`, accessing any attribute on a committed ORM object triggers an implicit lazy load, which raises `MissingGreenlet` in async context.

**Why it happens:** SQLAlchemy expires all attributes on commit by default. In async context, expired attributes cannot be re-loaded implicitly.

**How to avoid:** Set `expire_on_commit=False` in `async_sessionmaker`. This is shown in the official docs and all current FastAPI + SQLAlchemy guides.

**Warning signs:** `MissingGreenlet` or `greenlet_spawn has not been called` error after a DB write.

### Pitfall 5: `db_migrate` Dockerfile Needs `COPY src/` Not Just `src/db/`

**What goes wrong:** Alembic's `env.py` imports `from src.db.models.base import Base` — this import fails if the Docker build context only copies `src/db/`.

**Why it happens:** The `alembic/env.py` must import the ORM models to generate autogenerate-aware migrations. The models live in `src/db/models/`, which is inside `src/`, so the build context must copy the full `src/` tree.

**How to avoid:** In `src/db/Dockerfile`, use `COPY src/ ./src/` and set `WORKDIR /app`. Alembic must run from `/app` so `src.db.models` is importable.

**Warning signs:** `ModuleNotFoundError: No module named 'src'` in `db_migrate` container logs.

### Pitfall 6: Pool Size × Number of Services Must Not Exceed `max_connections`

**What goes wrong:** Under load, connections are refused with `FATAL: remaining connection slots are reserved for non-replication superuser connections`.

**Why it happens:** Each service has its own pool. With 3 API services × (`pool_size=5` + `max_overflow=10`) = up to 45 connections peak. Plus Alembic's NullPool (1 connection). PostgreSQL default `max_connections=100` is too low.

**How to avoid:** Set `POSTGRES_MAX_CONNECTIONS=200` (QUERY-04). With 3 services at `pool_size=5, max_overflow=10`, maximum concurrent connections = 3 × 15 = 45, well within 200.

**Warning signs:** `OperationalError: FATAL: remaining connection slots` in service logs.

---

## Code Examples

Verified patterns from official sources:

### Engine Creation with Correct Pool Settings (QUERY-04)
```python
# Source: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
import os

engine = create_async_engine(
    os.environ["CVM_DATABASE_URL"],  # postgresql+asyncpg://cvm_user:pass@db:5432/iliquid
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,   # test connection health before use
    echo=False,           # set True for debugging; never True in production
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # REQUIRED for async — prevents MissingGreenlet errors
)
```

### get_db FastAPI Dependency (QUERY-03)
```python
# Source: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html
from sqlalchemy.ext.asyncio import AsyncSession

async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
        # Session auto-closed by context manager on exit
```

### Alembic Async env.py run_migrations_online (INFRA-03)
```python
# Source: https://alembic.sqlalchemy.org/en/latest/cookbook.html
import asyncio
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy import pool
from alembic import context

def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        version_table_schema="public",
    )
    with context.begin_transaction():
        context.run_migrations()

async def run_async_migrations():
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # NullPool: no connection reuse during migration
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()

def run_migrations_online():
    asyncio.run(run_async_migrations())
```

### Health Check that Exercises DB Connection
```python
# Pattern: health check verifies DB is reachable (used in Phase 1 success criteria #3)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

@app.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    return {
        "status": "healthy" if db_ok else "degraded",
        "database": "up" if db_ok else "down",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": config.API_VERSION,
    }
```

### PostgreSQL Container with pg_isready Healthcheck (INFRA-01)
```yaml
# Source: https://docs.docker.com/compose/how-tos/startup-order/
db:
  image: postgres:16
  environment:
    POSTGRES_DB: iliquid
    POSTGRES_USER: postgres
    POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
  command: postgres -N 200   # sets max_connections=200 (QUERY-04)
  volumes:
    - postgres_data:/var/lib/postgresql/data
    - ./src/db/init.sql:/docker-entrypoint-initdb.d/01-init.sql:ro
  healthcheck:
    test: ["CMD-SHELL", "pg_isready -U postgres -d iliquid"]
    interval: 10s
    timeout: 5s
    retries: 5
    start_period: 30s
  networks:
    - br_finance
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `psycopg2` sync driver | `asyncpg` via SQLAlchemy async dialect | SQLAlchemy 1.4+ (2021), matured in 2.0 (2023) | Full coroutine-native I/O; no thread-pool overhead |
| `Session` (sync) | `AsyncSession` + `async_sessionmaker` | SQLAlchemy 2.0 (2023) | `async_sessionmaker` replaces deprecated `sessionmaker(class_=AsyncSession)` pattern |
| `Base.metadata.create_all()` | Alembic `upgrade head` | Always preferred for production | `create_all()` has no version tracking; Alembic enables incremental schema evolution |
| `depends_on: db` (bare) | `depends_on: db: condition: service_healthy` | Docker Compose 3.x | Bare depends_on only waits for container start, not DB readiness |
| `event_loop` fixture in pytest | `anyio` or `asyncio_mode=auto` in pytest-asyncio | pytest-asyncio 0.21+ | `event_loop` session fixture is deprecated; use `asyncio_mode = "auto"` in pytest.ini |

**Deprecated/outdated:**
- `sessionmaker(class_=AsyncSession)`: Replaced by `async_sessionmaker` in SQLAlchemy 2.0 — use `async_sessionmaker` directly.
- `from sqlalchemy.ext.asyncio import AsyncSession` as a direct constructor argument to `sessionmaker`: Still works but `async_sessionmaker` is the idiomatic 2.0 API.
- `alembic init` (without `-t async`): Creates a sync-only `env.py`. For asyncpg, always use `alembic init -t async alembic`.

---

## Open Questions

1. **Single DATABASE_URL vs. per-schema DATABASE_URL for Alembic**
   - What we know: Alembic's `db_migrate` service runs as the postgres superuser and applies all three schemas in one `alembic upgrade head`. The per-service `CVM_DATABASE_URL`, `BACEN_DATABASE_URL`, `B3_CALC_DATABASE_URL` are for runtime API connections only.
   - What's unclear: Whether the per-service users need `CREATE TABLE` privileges during migration (they don't — Alembic runs as superuser) or just `SELECT/INSERT/UPDATE/DELETE` during runtime.
   - Recommendation: Alembic uses `DATABASE_URL` (superuser). API services use per-service `*_DATABASE_URL` (restricted users). Grant only `USAGE ON SCHEMA` + `ALL ON ALL TABLES` to per-service users.

2. **Whether the existing `HealthResponse` Pydantic model can accommodate a `database` field**
   - What we know: QUERY-01 prohibits changing existing response shapes. The health check enhancement in success criterion #3 adds a DB connectivity verification.
   - What's unclear: Should Phase 1 modify `HealthResponse` to add a `database` field, or just verify DB inside health check without surfacing it in the response?
   - Recommendation: In Phase 1, do NOT modify `HealthResponse`. Verify DB connection inside the health handler but return the same shape. The DB field can be added in a later phase when OPS-03 is tackled.

3. **Alembic working directory during Docker migration run**
   - What we know: `alembic upgrade head` must be run from a directory where `alembic.ini` is resolvable and `src.db.models` is importable.
   - What's unclear: Whether to set `WORKDIR /app` and `alembic.ini` in `src/db/alembic/`, or move `alembic.ini` to `/app` root.
   - Recommendation: Set `WORKDIR /app` in `src/db/Dockerfile`. Place `alembic.ini` at `src/db/alembic.ini`. Run `CMD ["alembic", "-c", "src/db/alembic.ini", "upgrade", "head"]`. This keeps the alembic directory co-located with models.

---

## Sources

### Primary (HIGH confidence)
- `https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html` — AsyncIO ORM extension: create_async_engine, async_sessionmaker, get_db patterns, pitfalls
- `https://alembic.sqlalchemy.org/en/latest/cookbook.html` — Official Alembic cookbook: async run_migrations_online, multi-schema search_path configuration
- `https://docs.docker.com/compose/how-tos/startup-order/` — Docker Compose official: service_healthy, service_completed_successfully conditions, pg_isready healthcheck
- `https://docs.sqlalchemy.org/en/20/orm/declarative_tables.html` — DeclarativeBase __table_args__ schema assignment pattern

### Secondary (MEDIUM confidence)
- `https://berkkaraal.com/blog/2024/09/19/setup-fastapi-project-with-async-sqlalchemy-2-alembic-postgresql-and-docker/` — Practical FastAPI + SQLAlchemy 2 + Alembic + Docker walkthrough (2024); confirmed against official docs
- `https://leapcell.io/blog/building-high-performance-async-apis-with-fastapi-sqlalchemy-2-0-and-asyncpg` — Pool configuration and get_db patterns; confirmed against official SQLAlchemy docs
- `https://gist.github.com/h4/fc9b6d350544ff66491308b535762fee` — Multi-schema Alembic env.py with search_path fix; confirmed against Alembic cookbook

### Tertiary (LOW confidence)
- WebSearch results for asyncpg 0.31.0 and Alembic 1.18.4 version numbers — cross-referenced against PyPI search results; not directly fetched from pypi.org

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — SQLAlchemy 2.0 + asyncpg + Alembic is the documented, canonical stack for async FastAPI + PostgreSQL. Version numbers verified via WebSearch against PyPI.
- Architecture: HIGH — All patterns sourced from official SQLAlchemy and Alembic docs. Docker Compose patterns from official Docker docs.
- Pitfalls: HIGH — `expire_on_commit=False`, `include_schemas=True`, and `service_completed_successfully` are documented behaviors with official references.

**Research date:** 2026-03-12
**Valid until:** 2026-06-12 (SQLAlchemy 2.0 is stable; Alembic 1.x is stable; Docker Compose syntax is stable)
