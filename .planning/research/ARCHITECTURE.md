# ARCHITECTURE.md — PostgreSQL Integration for iliquid_nightly

**Research type**: Architecture — DB layer integration into existing FastAPI multi-service Docker Compose
**Date**: 2026-03-12
**Scope**: Shared PostgreSQL across cvm_api (8000), b3_calc_api (8001), bacen_api (8002)

---

## 1. Component Boundaries

### 1.1 Current State (no DB)

```
Client
  │
  ├─► cvm_api:8000    ──► dados.cvm.gov.br (CSV/ZIP download, latin-1, ;-delimited)
  ├─► b3_calc_api:8001 ──► calculadorarendafixa.com.br  (or: sample data fallback)
  └─► bacen_api:8002  ──► python-bcb (sync wrapper → BACEN OData/SGS/PTAX APIs)
```

All three services are stateless. Every request hits an upstream source. No data is retained between requests.

### 1.2 Target State (with DB)

```
Client
  │
  ├─► cvm_api:8000    ──(1)──► postgres:5432 / schema: cvm
  │                   ──(2)──► dados.cvm.gov.br  [fallback / backfill only]
  │
  ├─► b3_calc_api:8001 ──(1)──► postgres:5432 / schema: b3_calc
  │                    ──(2)──► calculadorarendafixa.com.br  [fallback]
  │                    ──(3)──► sample data  [last-resort fallback, preserved]
  │
  └─► bacen_api:8002  ──(1)──► postgres:5432 / schema: bacen
                      ──(2)──► python-bcb  [fallback / backfill only]

  backfill_runner (one-shot / scheduled container or CLI)
    ──► postgres:5432  [writes all schemas]
    ──► upstream sources  [reads]

  alembic (migration container, runs at compose up, exits 0)
    ──► postgres:5432  [DDL only]
```

### 1.3 Access Rules

| Service | Schema(s) it reads/writes | Can it write other schemas? |
|---|---|---|
| cvm_api | `cvm` | No |
| b3_calc_api | `b3_calc` | No |
| bacen_api | `bacen` | No |
| backfill_runner | all (`cvm`, `bacen`, `b3_calc`) | Yes — this is its purpose |
| alembic | all (DDL) | Yes — migrations only |

A single PostgreSQL instance with three schemas. Each service uses a dedicated DSN with schema-level `search_path` set via the connection URL parameter (`?options=-csearch_path%3Dcvm`). This enforces isolation without the operational overhead of three separate databases.

---

## 2. Schema Design

### 2.1 BACEN — Time-Series (SGS and PTAX)

BACEN data is fundamentally time-series: each row is (series_id or currency, date, value). Columns are narrow, typed, and highly repetitive. A normalized time-series table with a composite primary key is correct here.

```sql
-- schema: bacen

CREATE TABLE sgs_observations (
    series_code   INTEGER      NOT NULL,   -- e.g. 433 (IPCA), 11 (SELIC_DIARIA)
    series_label  TEXT,                    -- e.g. "IPCA"
    obs_date      DATE         NOT NULL,
    value         NUMERIC(20,8),
    ingested_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (series_code, obs_date)
);

CREATE INDEX ON sgs_observations (series_code, obs_date DESC);

CREATE TABLE ptax_rates (
    currency_code    CHAR(3)      NOT NULL,   -- e.g. "USD", "EUR"
    rate_datetime    TIMESTAMPTZ  NOT NULL,   -- cotacaoCompra/Venda timestamps
    compra           NUMERIC(12,6),
    venda            NUMERIC(12,6),
    ingested_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (currency_code, rate_datetime)
);

CREATE INDEX ON ptax_rates (currency_code, rate_datetime DESC);

CREATE TABLE expectativas (
    endpoint         TEXT         NOT NULL,   -- ExpectativasMercadoAnuais etc.
    indicador        TEXT,
    data_referencia  TEXT,                    -- BACEN returns this as string
    obs_date         DATE,
    payload          JSONB        NOT NULL,   -- full row stored for flexibility
    ingested_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (endpoint, indicador, data_referencia, obs_date)
);

-- taxa_juros: schema is irregular across OData sub-endpoints; store as JSONB rows
CREATE TABLE taxa_juros_snapshots (
    endpoint         TEXT         NOT NULL,
    snapshot_date    DATE         NOT NULL DEFAULT CURRENT_DATE,
    payload          JSONB        NOT NULL,
    ingested_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (endpoint, snapshot_date)
);
```

**Rationale**: SGS and PTAX have stable, typed schemas — normalized columns win over JSONB for query performance and index efficiency. `expectativas` and `taxa_juros` have irregular structures across sub-endpoints, so JSONB payload is the right fit with typed extraction columns where possible.

### 2.2 CVM — Tabular CSV Rows

CVM CSVs have many columns (20–80+ per doc_type), all returned as strings from latin-1 source files. The column set differs per (entity, doc_type) combination. JSONB is the correct storage strategy for the row payload, with a small set of indexed extraction columns for common query patterns (CNPJ, date, entity).

```sql
-- schema: cvm

CREATE TABLE cvm_records (
    id              BIGSERIAL    PRIMARY KEY,
    entity          TEXT         NOT NULL,    -- fidc, fip, fiagro, securit
    doc_type        TEXT         NOT NULL,    -- mensal, cadastral, trimestral, etc.
    period_year     SMALLINT,                 -- NULL for non-periodic doc types
    period_month    SMALLINT,                 -- NULL for yearly/cadastral
    cnpj_key        TEXT,                     -- extracted: CNPJ_FUNDO or CNPJ_SECURIT
    competence_date DATE,                     -- extracted: DT_COMPTC where present
    payload         JSONB        NOT NULL,    -- full CSV row as key/value
    source_url      TEXT,                     -- URL of originating CSV/ZIP
    ingested_at     TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX ON cvm_records (entity, doc_type, period_year, period_month);
CREATE INDEX ON cvm_records (cnpj_key);
CREATE INDEX ON cvm_records (competence_date DESC);
CREATE INDEX ON cvm_records USING GIN (payload);  -- for JSONB key searches

-- Prevent duplicate ingestion of the same row
CREATE UNIQUE INDEX ON cvm_records (entity, doc_type, period_year, period_month, cnpj_key, competence_date)
    WHERE cnpj_key IS NOT NULL AND competence_date IS NOT NULL;

-- Ingestion tracking (replaces in-memory backfill resume logic)
CREATE TABLE cvm_ingest_log (
    entity          TEXT         NOT NULL,
    doc_type        TEXT         NOT NULL,
    period_year     SMALLINT     NOT NULL,
    period_month    SMALLINT     NOT NULL DEFAULT 0,
    status          TEXT         NOT NULL,   -- 'ok', 'error', 'skipped'
    row_count       INTEGER,
    error_msg       TEXT,
    ingested_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (entity, doc_type, period_year, period_month)
);
```

**Rationale**: The existing `DataResponse` shape returns `List[Dict[str, Any]]` — JSONB rows map directly to this without an ORM-level column explosion. The GIN index enables `payload @> '{"CNPJ_FUNDO": "12.345.678/0001-90"}'` queries. The `cvm_ingest_log` table replaces the file-based resume logic in `src/tools/backfill.py`, making it re-entrant and DB-driven.

### 2.3 B3 CALC — Pricing Snapshots

B3 CALC returns security listings and daily prices. These are snapshots, not a continuous time-series. JSONB payload per row.

```sql
-- schema: b3_calc

CREATE TABLE b3_securities (
    security_code   TEXT         NOT NULL,
    security_type   TEXT         NOT NULL,   -- debentures, cra, cri
    name            TEXT,
    issuer          TEXT,
    index_ref       TEXT,                    -- CDI, IPCA, etc.
    status          TEXT,
    payload         JSONB        NOT NULL,   -- full upstream response row
    last_seen_date  DATE         NOT NULL,
    ingested_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (security_code, security_type)
);

CREATE INDEX ON b3_securities (security_type, status);
CREATE INDEX ON b3_securities (last_seen_date DESC);

CREATE TABLE b3_prices (
    security_code    TEXT         NOT NULL,
    security_type    TEXT         NOT NULL,
    price_date       DATE         NOT NULL,
    payload          JSONB        NOT NULL,  -- full price response
    ingested_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (security_code, security_type, price_date)
);

CREATE INDEX ON b3_prices (security_code, security_type, price_date DESC);
```

**Rationale**: Pricing data changes daily; the primary key on `(security_code, security_type, price_date)` prevents duplicate inserts during incremental sync. The `b3_securities` table serves as the listing cache that today falls back to `SAMPLE_DEBENTURES` — once populated it replaces that fallback for production traffic.

---

## 3. DB-First-With-Live-Fallback Pattern

This is the critical data flow change. Each service route handler wraps all DB reads in a try/except so that DB unavailability degrades gracefully to the existing upstream fetch, preserving cold-start resilience.

### 3.1 Flow Diagram

```
API request arrives
        │
        ▼
[1] Query DB (SELECT with entity/doc_type/period filters)
        │
   ┌────┴────────────────────┐
   │ rows found?             │ no (empty result or DB unreachable)
   │ yes                     │
   ▼                         ▼
[2] Paginate DB rows    [3] Fetch from upstream (existing logic unchanged)
        │                    │
        ▼                    ├─► If upstream OK: return result + async write to DB
        │                    │     (fire-and-forget INSERT, does not block response)
        │                    └─► If upstream fails: return error (or sample data for B3)
        ▼
[4] Build DataResponse (same Pydantic shape as today)
        │
        ▼
[5] Return to client
```

### 3.2 Implementation Shape (per service)

Each service gains a `db.py` module alongside `config.py`, `models.py`, `services.py`, `main.py`:

```python
# src/cvm_api/db.py  (illustrative — not implemented yet)

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
import os

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://cvm_user:secret@postgres:5432/iliquid?options=-csearch_path%3Dcvm"
)

engine = create_async_engine(DATABASE_URL, pool_size=5, max_overflow=10)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)
```

The route handler pattern becomes:

```python
# src/cvm_api/main.py  (illustrative)

async def get_cvm_data(entity, doc_type, year, month, page, page_size, db: AsyncSession):
    try:
        rows = await db_service.query_cvm_records(db, entity, doc_type, year, month, page, page_size)
        if rows:
            return build_response_from_db(rows)
    except Exception:
        pass  # DB unavailable — fall through

    # Existing upstream fetch (unchanged logic)
    return await existing_service.fetch_and_parse(entity, doc_type, year, month, page, page_size)
```

### 3.3 Async Write-Through (background task)

When the DB miss path fetches from upstream successfully, the result is written to the DB asynchronously using FastAPI's `BackgroundTasks` — this does not block the response:

```python
background_tasks.add_task(db_service.insert_cvm_records, db, entity, doc_type, year, month, rows)
```

This means the DB populates organically from live traffic even before a full backfill is run.

### 3.4 B3 CALC Fallback Chain (preserved)

The B3 fallback chain becomes three-level, not two:

```
DB → live upstream → SAMPLE_DEBENTURES/SAMPLE_CRAS/SAMPLE_CRIS
```

The existing sample data fallback in `src/b3_calc_api/services.py` is not removed — it becomes the last resort. This is explicitly required by the CLAUDE.md convention.

---

## 4. Async Connection Pooling

### 4.1 Library Choice

Use `asyncpg` as the async PostgreSQL driver with `SQLAlchemy 2.x` async engine (`sqlalchemy[asyncio]`). This integrates with FastAPI's async request handling without blocking the event loop.

- **Do not use** `psycopg2` (sync driver, would require `run_in_executor` wrapping)
- **Do not use** `databases` (thin wrapper, less ecosystem support than SQLAlchemy 2)
- **Avoid** raw `asyncpg` without SQLAlchemy — the SQL composition overhead is high and the query logging/tracing is weaker

Dependencies to add per service:
```
sqlalchemy[asyncio]>=2.0
asyncpg>=0.29
```

### 4.2 Pool Sizing

In Docker Compose each service container runs with a single uvicorn process (1 worker by default). PostgreSQL default `max_connections=100`. With 3 services + backfill runner + alembic:

| Component | pool_size | max_overflow | Max connections |
|---|---|---|---|
| cvm_api | 5 | 10 | 15 |
| bacen_api | 5 | 10 | 15 |
| b3_calc_api | 3 | 5 | 8 |
| backfill_runner | 2 | 2 | 4 |
| **Total** | | | **42** (well within 100) |

```python
engine = create_async_engine(
    DATABASE_URL,
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
    pool_recycle=1800,   # avoid stale connections after 30 min idle
    echo=False,           # set True only during development
)
```

### 4.3 Session Injection via FastAPI Dependency

```python
# shared pattern across all three services

from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

# In route:
@router.get("/api/v1/{entity}/{doc_type}")
async def get_data(..., db: AsyncSession = Depends(get_db)):
    ...
```

---

## 5. Migration Strategy (Alembic)

### 5.1 Location

Migrations live in a shared `src/db/` directory, not inside any individual service directory. This reflects that the schema spans all three services and needs a single source of truth.

```
src/
  db/
    alembic.ini
    env.py
    migrations/
      versions/
        0001_initial_cvm_schema.py
        0002_initial_bacen_schema.py
        0003_initial_b3_calc_schema.py
    models/
      cvm.py         # SQLAlchemy ORM table definitions
      bacen.py
      b3_calc.py
      base.py        # declarative_base(), shared metadata
```

### 5.2 When Alembic Runs

A dedicated `alembic` service in `docker-compose.yml` runs migrations as a one-shot container before the API services start:

```yaml
# docker-compose.yml addition (illustrative)

  db:
    image: postgres:16-alpine
    container_name: postgres
    environment:
      POSTGRES_DB: iliquid
      POSTGRES_USER: iliquid_admin
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./src/db/init.sql:/docker-entrypoint-initdb.d/00_schemas.sql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U iliquid_admin"]
      interval: 5s
      timeout: 5s
      retries: 10
    networks:
      - br_finance

  db_migrate:
    build:
      context: .
      dockerfile: src/db/Dockerfile
    environment:
      - DATABASE_URL=postgresql+asyncpg://iliquid_admin:${POSTGRES_PASSWORD}@postgres:5432/iliquid
    depends_on:
      db:
        condition: service_healthy
    command: ["alembic", "upgrade", "head"]
    networks:
      - br_finance
```

API services gain `depends_on: db_migrate: condition: service_completed_successfully`. This ensures migrations are applied before any service opens its connection pool.

### 5.3 Schema Initialization (init.sql)

The `init.sql` run by the Postgres container creates the schemas and per-service users with restricted search_path:

```sql
-- src/db/init.sql
CREATE SCHEMA IF NOT EXISTS cvm;
CREATE SCHEMA IF NOT EXISTS bacen;
CREATE SCHEMA IF NOT EXISTS b3_calc;

CREATE USER cvm_user WITH PASSWORD '${CVM_DB_PASSWORD}';
GRANT USAGE ON SCHEMA cvm TO cvm_user;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA cvm TO cvm_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA cvm GRANT ALL ON TABLES TO cvm_user;

-- repeat for bacen_user, b3_calc_user
```

Each service's `DATABASE_URL` uses its restricted user. The backfill runner uses the `iliquid_admin` user (all schemas) or a dedicated `backfill_user` with GRANT on all three schemas.

### 5.4 Alembic Multi-Schema Configuration

`env.py` must set `include_schemas=True` and configure `version_table_schema` so migration version tracking works correctly across schemas:

```python
# src/db/env.py (key parts)

from src.db.models.base import metadata

def run_migrations_online():
    connectable = engine_from_config(...)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=metadata,
            include_schemas=True,
            version_table="alembic_version",
            version_table_schema="public",  # version table lives in public schema
        )
```

---

## 6. Backfill Pipeline Architecture

### 6.1 Current State

`src/tools/backfill.py` is a CLI script that downloads CVM CSV/ZIP files sequentially, with file-based progress tracking via `src/tools/progress_tracker.py`. It does not write to a DB.

### 6.2 Target Architecture

The backfill pipeline becomes DB-aware, resumable via `cvm_ingest_log`, and extended to cover BACEN and B3 CALC as well as CVM.

```
backfill_runner
  ├─ cvm_backfill.py     (extends existing backfill.py)
  │    reads: cvm_ingest_log (skip already-ingested periods)
  │    writes: cvm_records, cvm_ingest_log
  │    source: dados.cvm.gov.br (unchanged URL patterns)
  │
  ├─ bacen_backfill.py   (new)
  │    reads: sgs_observations (find last obs_date per series_code)
  │    writes: sgs_observations, ptax_rates, expectativas
  │    source: python-bcb (existing BacenClient)
  │
  └─ b3_backfill.py      (new)
       reads: b3_securities (find last last_seen_date)
       writes: b3_securities, b3_prices
       source: calculadorarendafixa.com.br (existing service layer)
```

### 6.3 Backfill Run Modes

```bash
# Full historical backfill (slow, run once)
python -m src.tools.backfill_db --all --from-year 2010

# Incremental sync (run daily via cron or compose restart)
python -m src.tools.backfill_db --incremental

# Single entity
python -m src.tools.backfill_db --entity cvm --doc-type fidc_mensal --year 2024

# Resume interrupted run (DB-driven, no manual state files needed)
python -m src.tools.backfill_db --resume
```

### 6.4 Idempotency

All INSERT statements use `ON CONFLICT DO NOTHING` (or `ON CONFLICT ... DO UPDATE` for PTAX where values may be revised). This makes every backfill run safely re-entrant:

```sql
-- CVM records
INSERT INTO cvm.cvm_records (entity, doc_type, period_year, period_month, cnpj_key, competence_date, payload, source_url)
VALUES (...)
ON CONFLICT ON CONSTRAINT cvm_records_unique_idx DO NOTHING;

-- PTAX (rates can be revised intraday)
INSERT INTO bacen.ptax_rates (currency_code, rate_datetime, compra, venda)
VALUES (...)
ON CONFLICT (currency_code, rate_datetime) DO UPDATE SET
    compra = EXCLUDED.compra,
    venda  = EXCLUDED.venda,
    ingested_at = now();
```

---

## 7. Suggested Build Order

The following sequence respects hard dependencies (each item requires all prior items to exist).

### Phase 1 — Foundation (nothing else can proceed without this)
1. Add `db` service to `docker-compose.yml` (Postgres 16 container, volume, healthcheck)
2. Create `src/db/init.sql` (schema creation, per-service users)
3. Create `src/db/models/` (SQLAlchemy table definitions for all three schemas)
4. Create `src/db/migrations/` with Alembic config and initial migration scripts
5. Add `db_migrate` one-shot service to compose; wire `depends_on` for API services
6. Verify: `docker-compose up db db_migrate` creates all tables cleanly

### Phase 2 — BACEN DB Layer (simplest data shape, best test case)
7. Add `asyncpg` + `sqlalchemy[asyncio]` to `src/bacen_api/requirements.txt`
8. Create `src/bacen_api/db.py` (engine, session factory, `get_db` dependency)
9. Create `src/bacen_api/db_service.py` (query functions: `get_sgs_observations`, `get_ptax_rates`, `insert_*`)
10. Modify `src/bacen_api/main.py` route handlers: DB-first with python-bcb fallback
11. Write `src/tools/bacen_backfill.py` (SGS + PTAX historical load)
12. Verify: PTAX endpoint returns DB data; fall through works when DB empty

### Phase 3 — CVM DB Layer (most data volume)
13. Add asyncpg + sqlalchemy to `src/cvm_api/requirements.txt`
14. Create `src/cvm_api/db.py` and `src/cvm_api/db_service.py`
15. Modify `src/cvm_api/main.py`: DB-first with CSV download fallback
16. Extend `src/tools/backfill.py` → `src/tools/backfill_db.py` (DB-aware, resume via `cvm_ingest_log`)
17. Run full historical CVM backfill for FIDC mensal (2018–present as first cut)
18. Verify: CVM endpoint returns DB data; existing response shape unchanged

### Phase 4 — B3 CALC DB Layer
19. Add asyncpg + sqlalchemy to `src/b3_calc_api/requirements.txt`
20. Create `src/b3_calc_api/db.py` and `src/b3_calc_api/db_service.py`
21. Modify `src/b3_calc_api/main.py`: DB-first → live upstream → sample data (three levels)
22. Write `src/tools/b3_backfill.py` (daily snapshot sync)
23. Verify: B3 CALC listing returns DB data; sample data fallback still reachable when DB + upstream both fail

### Phase 5 — Incremental Sync and Hardening
24. Add scheduled incremental sync (compose service with cron, or a separate `sync_runner` container)
25. Add DB-level health check to each service's `/health` endpoint (report DB connectivity status)
26. Ensure test suite passes (`PYTHONPATH=. pytest tests/ -v`) — mock DB session in unit tests
27. Update `cvm_ingest_log` to replace file-based progress tracker entirely
28. Remove temporary local CSV/ZIP files after successful DB ingest (optional — saves disk)

---

## 8. What Must Exist Before What (Dependency Graph)

```
postgres container
  └─► init.sql (schemas + users)
        └─► db_migrate (alembic upgrade head)
              ├─► cvm_api (Phase 3)
              ├─► bacen_api (Phase 2)
              └─► b3_calc_api (Phase 4)

src/db/models/ (SQLAlchemy ORM definitions)
  └─► alembic migrations (autogenerate from ORM)
        └─► all db_service.py files

src/bacen_api/db_service.py
  └─► bacen_backfill.py (uses same query functions)

src/cvm_api/db_service.py
  └─► backfill_db.py (uses same insert functions)

Existing services (cvm_api, bacen_api, b3_calc_api) must remain deployable
without a DB (DB-first pattern degrades gracefully) — this means Phase 1
completion is not a hard gate for running the services; it is a hard gate
for DB-backed responses.
```

---

## 9. Key Design Decisions and Rationale

| Decision | Rationale |
|---|---|
| Single PostgreSQL instance, three schemas | Reduces ops overhead; schema-level isolation is sufficient at this scale; easier backfill (one connection pool) |
| JSONB for CVM payload, typed columns for BACEN time-series | CVM has 20–80 columns per doc_type that vary; BACEN is narrow and typed — each gets the right structure |
| asyncpg + SQLAlchemy 2 async | Matches FastAPI's async model; avoids run_in_executor overhead; SQLAlchemy provides query composition and tracing |
| DB-first with fallback (not DB-only) | Services remain deployable without a DB; cold start still works; resilience is preserved |
| Alembic as one-shot compose service | Ensures migrations run before pool opens; no migration logic in application startup path |
| `ON CONFLICT DO NOTHING` for most inserts | Makes backfill idempotent; re-running any period is safe |
| `cvm_ingest_log` table replaces file-based progress tracker | DB-driven resume is atomic and visible; file state can be lost on container restart |
| B3 three-level fallback preserved | Explicit requirement from CLAUDE.md; sample data is last resort, not removed |
| Per-service DB users with schema search_path | Enforces service isolation at DB level; prevents accidental cross-schema writes from application code |

---

*Generated by project-researcher agent — 2026-03-12*
