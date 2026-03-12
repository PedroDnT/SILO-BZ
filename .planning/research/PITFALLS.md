# Pitfalls Research

**Domain:** PostgreSQL persistence layer on FastAPI multi-service app (Brazilian financial data)
**Researched:** 2026-03-12
**Confidence:** HIGH

---

## Critical Pitfalls

### Pitfall 1: Async SQLAlchemy Session Leaked Across Requests

**What goes wrong:**
A single `AsyncSession` or `async_sessionmaker` instance is created at module scope (e.g., as a `_db = AsyncSession(engine)` global, analogous to how `_client = BacenClient()` is currently done in `src/bacen_api/main.py`). The session is reused across concurrent FastAPI requests, causing dirty reads, rollback contamination, and "this Session's transaction has been rolled back due to a previous exception" errors under load.

**Why it happens:**
Developers copy the pattern that works for stateless HTTP clients (`BacenClient` is safe as a global because it holds no transaction state) and apply it to SQLAlchemy sessions, which are explicitly not thread- or coroutine-safe to share.

**How to avoid:**
Use `async_sessionmaker` as the module-level singleton, and create a new session per request via a FastAPI dependency:

```python
# db/session.py
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

engine = create_async_engine(DATABASE_URL, pool_size=10, max_overflow=5)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
```

```python
# In route handlers:
@app.get("/api/v1/bacen/sgs/{series_code}")
async def get_sgs(series_code: int, db: AsyncSession = Depends(get_db)):
    ...
```

The `async with` on the session factory guarantees the session is closed (and connection returned to pool) even on exceptions.

**Warning signs:**
- "Can't reconnect until invalid transaction is rolled back" errors in logs
- Intermittent 500s under concurrent load that disappear under single-threaded testing
- Session state leaking between requests (data from previous request appearing in current)

**Phase to address:** DB foundation phase (before any service integration)

---

### Pitfall 2: Alembic `env.py` Not Configured for Async Engine

**What goes wrong:**
Alembic's default `env.py` uses a synchronous `engine.connect()` call. When SQLAlchemy async drivers (`asyncpg`) are used, running `alembic upgrade head` in Docker either silently skips migrations or raises `sqlalchemy.exc.MissingGreenlet: greenlet_spawn has not been called`.

**Why it happens:**
`alembic init` generates a sync `env.py`. The asyncpg driver cannot be used with synchronous connection calls. Most tutorials show the sync pattern.

**How to avoid:**
Use the async migration pattern in `env.py`:

```python
# alembic/env.py — async pattern
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from alembic import context
import asyncio

def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()

async def run_migrations_online():
    connectable = create_async_engine(DATABASE_URL)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()

asyncio.run(run_migrations_online())
```

Alternatively, use a **synchronous** `psycopg2` connection string only for Alembic (`postgresql://` not `postgresql+asyncpg://`) while keeping `asyncpg` for the runtime engine. This avoids patching `env.py` and is more portable.

**Warning signs:**
- `alembic upgrade head` exits 0 but tables never appear in Postgres
- `MissingGreenlet` or `greenlet_spawn` in migration output
- Migrations pass locally but fail inside Docker (different driver availability)

**Phase to address:** DB foundation phase, before any service touches the schema

---

### Pitfall 3: Connection Pool Exhaustion Across Three Services Sharing One Postgres

**What goes wrong:**
Each of the three FastAPI services (`cvm_api`, `bacen_api`, `b3_calc_api`) is configured with the default SQLAlchemy pool (`pool_size=5, max_overflow=10` = 15 connections per service). With three services, that is 45 connections attempted concurrently. The default `max_connections` in Postgres is 100; in Docker with a single shared instance, this headroom disappears quickly during backfill operations, causing `asyncpg.TooManyConnectionsError` and cascading 500s.

**Why it happens:**
Per-service pool sizing is set in isolation. No one accounts for the aggregate. The backfill pipeline running in parallel (via `ThreadPoolExecutor` in `src/tools/backfill.py`) adds additional connection demand outside the FastAPI process.

**How to avoid:**
- Set conservative per-service pools: `pool_size=3, max_overflow=2` for API services (writes are rare; reads are short)
- Add `PgBouncer` as a connection pooler service in `docker-compose.yml`, OR configure Postgres `max_connections=200` explicitly
- Set `pool_pre_ping=True` to detect stale connections after Postgres restarts
- For the backfill pipeline, use a **separate, limited connection pool** (or a dedicated sync `psycopg2` connection with explicit `max_workers` cap) rather than inheriting from the API pool

```yaml
# docker-compose.yml — Postgres service
postgres:
  image: postgres:16-alpine
  environment:
    POSTGRES_MAX_CONNECTIONS: "200"
    POSTGRES_SHARED_BUFFERS: "256MB"
```

**Warning signs:**
- `FATAL: remaining connection slots are reserved` in Postgres logs
- Health checks failing on all three services simultaneously (not one at a time)
- Backfill runs causing API latency spikes

**Phase to address:** DB infrastructure phase (Docker Compose setup) and backfill integration phase

---

### Pitfall 4: Alembic Migration Race on Docker Compose Startup

**What goes wrong:**
`docker-compose up` starts all services in parallel. Each service runs `alembic upgrade head` in its entrypoint. Three services racing to run migrations simultaneously against the same schema causes lock contention, duplicate migration attempts, or `DuplicateTable` errors. The service that loses the race crashes and is never restarted correctly.

**Why it happens:**
Docker Compose `depends_on` with `condition: service_healthy` ensures Postgres is up, but does not serialize the three application containers' migration steps. Each container independently runs Alembic.

**How to avoid:**
Extract migrations into a **dedicated one-shot init container** that runs before any service starts:

```yaml
# docker-compose.yml
  db_migrate:
    image: cvm-api:latest  # any image with alembic installed
    command: ["alembic", "upgrade", "head"]
    depends_on:
      postgres:
        condition: service_healthy
    networks:
      - br_finance

  cvm_api:
    depends_on:
      db_migrate:
        condition: service_completed_successfully
      postgres:
        condition: service_healthy
```

Alternatively, use a migration lock table (Alembic's `alembic_version` table is already serialized by Postgres row-level locking, but only if migrations are short — long migrations under concurrent startup can still deadlock).

**Warning signs:**
- `(psycopg2.errors.DuplicateTable) relation "alembic_version" already exists`
- One service starts healthy while another is stuck in crash-loop on startup
- Migrations succeed on first `docker-compose up` but fail on subsequent restarts

**Phase to address:** DB infrastructure phase (Docker Compose setup)

---

### Pitfall 5: Backfill Pipeline Writing Raw CVM CSV Strings to JSONB Without Schema Normalization

**What goes wrong:**
The CVM CSV parser (`_parse_csv_content` in `src/cvm_api/services.py`) returns `List[Dict[str, Any]]` where all values are `str | None` (latin-1 decoded, `;`-delimited). When these dicts are inserted directly into a Postgres `JSONB` column, numeric fields like `VL_TOTAL`, `VL_QUOTA`, `QT_TITULOS` are stored as strings (`"1234,56"` with Brazilian comma decimal). Range queries, aggregations, and sorting on these fields become impossible without cast-on-read, and indexes on JSONB numeric fields are useless.

**Why it happens:**
JSONB is chosen for flexibility (CVM schemas vary by entity/doc_type). Developers insert the already-parsed dict without a normalization step, reasoning "we can cast later."

**How to avoid:**
Apply a normalization pass before insert. Either:
1. Add a `normalize_cvm_row(row: dict, entity: str, doc_type: str) -> dict` function in `src/cvm_api/services.py` that converts known numeric fields (using `_get_validation_config` field type hints already present) to `float`/`int`/`date` before storage
2. Or use typed columns for the high-value queryable fields (CNPJ, DT_COMPTC, VL_TOTAL) and a `JSONB` overflow column for the rest

For BACEN (SGS, PTAX), data is already typed via `python-bcb` — store as `NUMERIC` and `DATE` columns, not JSONB.

**Warning signs:**
- `ORDER BY value DESC` returns lexicographic order (`"9" > "10"`)
- `WHERE valor > 1000000` returns zero rows even when data exists
- Brazilian decimal commas (`1.234,56`) cause `NUMERIC` cast failures

**Phase to address:** Schema design phase and backfill pipeline phase

---

### Pitfall 6: Breaking Existing API Contracts via Response Model Changes

**What goes wrong:**
Adding a `source: str = "db"` field or `db_id: int` to existing Pydantic response models (`DataResponse`, `SGSSeriesResponse`, etc.) silently changes the JSON shape returned to callers. Even optional fields can break strict clients and violate the project constraint that "all existing API routes, query params, and response shapes must remain unchanged."

**Why it happens:**
The natural impulse is to add provenance metadata ("did this come from DB or live?") to the response. Response models feel like the right place.

**How to avoid:**
- Never add new fields to existing response models — add a separate internal `DBRecord` model for ORM layer, and keep the existing Pydantic models as the serialization contract
- If provenance is needed, use a response header (`X-Data-Source: db`) not a body field
- Add a contract test to the pytest suite that asserts the exact keys in each response model do not change (snapshot test against the current `model_json_schema()`)

```python
# tests/test_api_contracts.py
def test_data_response_schema_unchanged():
    schema = DataResponse.model_json_schema()
    assert set(schema["properties"].keys()) == {"entity", "doc_type", "data", "pagination", "metadata"}
```

**Warning signs:**
- New optional fields appearing in OpenAPI schema (`/docs`) that were not there before
- Test suite still green but integration callers report unexpected keys
- `model_json_schema()` output differs from a stored snapshot

**Phase to address:** Every phase that touches models — enforce via contract tests from Day 1

---

### Pitfall 7: `python-bcb` Sync Calls Blocking the Async Event Loop During Backfill

**What goes wrong:**
`BacenClient` wraps `python-bcb` (a sync library) using `asyncio.get_event_loop().run_in_executor(None, ...)` or `asyncio.to_thread(...)`. During backfill, thousands of PTAX/SGS date-range calls are made. If the backfill runs inside the FastAPI process (same event loop), every sync `python-bcb` call blocks a thread-pool worker. Thread pool saturation causes API request handlers to queue behind backfill tasks.

**Why it happens:**
The backfill tool currently uses `requests` and `ThreadPoolExecutor` (`src/tools/backfill.py`). When extended to hit BACEN, developers may reuse `BacenClient` inside the same async context for convenience.

**How to avoid:**
- Run the backfill pipeline as a **separate process** (CLI invocation via `docker-compose run` or a dedicated `backfill` service), never inside a running FastAPI worker
- For BACEN backfill, call `python-bcb` directly (synchronously) from the CLI process — no need for `asyncio.to_thread` in a standalone script
- Set `PYTHONPATH=.` and invoke: `python -m src.tools.backfill --entity bacen --series 11,12,433`

**Warning signs:**
- API P99 latency spikes during backfill runs
- FastAPI worker logs showing requests queued longer than `REQUEST_TIMEOUT`
- `ThreadPoolExecutor` saturation warnings in Python logs

**Phase to address:** Backfill pipeline phase

---

### Pitfall 8: Missing `depend_on: postgres` with Health Condition in Docker Compose

**What goes wrong:**
Services start before Postgres has finished initializing (accepting connections). The first DB query from a service raises `asyncpg.exceptions.CannotConnectNowError` or `connection refused`. Because `restart: unless-stopped` is set, the container crash-loops, but logs are lost in the restart noise and the root cause (startup ordering) is missed.

**Why it happens:**
The current `docker-compose.yml` has no `postgres` service at all — it will be added. Developers add `depends_on: postgres` (service name only) without `condition: service_healthy`, which only waits for the container to start, not for Postgres to accept connections.

**How to avoid:**
```yaml
postgres:
  image: postgres:16-alpine
  healthcheck:
    test: ["CMD-SHELL", "pg_isready -U $$POSTGRES_USER -d $$POSTGRES_DB"]
    interval: 5s
    timeout: 5s
    retries: 10
    start_period: 10s

cvm_api:
  depends_on:
    postgres:
      condition: service_healthy
```

Add exponential-backoff retry logic in the application startup as a second line of defense:
```python
# On app startup, retry DB connection with backoff
for attempt in range(5):
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        break
    except Exception:
        await asyncio.sleep(2 ** attempt)
```

**Warning signs:**
- Services in crash-loop immediately after `docker-compose up` but healthy after manual restart
- `connection refused :5432` in service logs within the first 5 seconds
- `depends_on` present but no `condition` key

**Phase to address:** DB infrastructure phase (Docker Compose setup)

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Store all CVM CSV fields as JSONB strings | No schema migration per entity | No range queries, no index on numerics, cast-on-every-read tax | MVP only — must normalize before production |
| Single shared `AsyncSession` as global | Fewer lines of code | Transaction contamination under concurrent load | Never |
| Skip Alembic, use `Base.metadata.create_all()` | Faster initial setup | No rollback path, no auditability, breaks team workflow | Local dev only — never in Docker |
| Run backfill inside FastAPI process on `@app.on_event("startup")` | Simple wiring | Blocks event loop, starves API requests during cold start | Never |
| Hardcode `DATABASE_URL` in `config.py` | No env var setup needed | Breaks Docker, breaks CI, leaks credentials | Never |
| Use `pool_size=20` per service for safety margin | Fewer connection timeout errors | Pool exhaustion on multi-service startup, OOM in small Docker VMs | Never without PgBouncer |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| `asyncpg` + Alembic | Use `postgresql+asyncpg://` in Alembic `env.py` with sync connect | Use `postgresql://` (psycopg2) for Alembic only; keep asyncpg for runtime |
| `python-bcb` + SQLAlchemy backfill | Run inside FastAPI event loop via `asyncio.to_thread` | Run as separate CLI process with direct sync `python-bcb` calls |
| CVM CSV latin-1 + Postgres | Insert raw bytes; Postgres rejects non-UTF8 | Decode with `latin-1` (already done in `services.py`) before insert — never pass raw bytes to asyncpg |
| `docker-compose.yml` + Postgres init scripts | Mount `.sql` init scripts after volume already initialized | Postgres only runs `/docker-entrypoint-initdb.d/` on first container start with empty data volume — delete volume to re-run |
| Pydantic v2 + SQLAlchemy ORM models | Use `from_orm=True` (v1 pattern) | Use `model_validate(obj, from_attributes=True)` (v2 pattern with `model_config = ConfigDict(from_attributes=True)`) |
| FastAPI `Depends(get_db)` + background tasks | Pass `db` session into `BackgroundTask` — session closes when response is sent | Create a new session inside the background task function, independent of request lifecycle |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Full CVM CSV downloaded and parsed on every cache miss, then inserted row-by-row | Backfill takes hours; insert latency visible in API response time | Use `COPY` or bulk `INSERT ... VALUES` via `asyncpg.copy_records_to_table` | At ~50k rows per CVM monthly file (FIDC has 200k+ rows) |
| JSONB GIN index on entire document | Index creation takes minutes; queries still slow for numeric range | Index specific JSONB keys: `CREATE INDEX ON cvm_records ((data->>'VL_TOTAL')::numeric)` | At 1M+ stored records |
| `SELECT *` from `cvm_records` without pagination pushed to DB | Service loads full table into Python memory | Always apply `LIMIT`/`OFFSET` or keyset pagination in SQL, not in Python | At ~10k rows returned |
| `expire_on_commit=True` (SQLAlchemy default) | Accessing model attributes after commit triggers lazy loads — `MissingGreenlet` in async | Set `expire_on_commit=False` in `async_sessionmaker` | On first attribute access after `session.commit()` |
| Implicit table lock during Alembic `ADD COLUMN` on large table | Migration blocks all reads for duration of ALTER TABLE | Use `ADD COLUMN ... DEFAULT NULL` (no rewrite) or `pg_rewrite` extension | Tables > 1M rows |

---

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| `DATABASE_URL` in `docker-compose.yml` environment block (plaintext) | Credentials in git history | Use Docker secrets or `.env` file (gitignored); reference via `${POSTGRES_PASSWORD}` |
| `allow_origins=["*"]` preserved after DB layer exposes write endpoints | CSRF risk if mutation endpoints added | Keep `["*"]` only for read-only GET endpoints; restrict for any POST/PUT added during DB phase |
| Postgres `POSTGRES_HOST_AUTH_METHOD=trust` in dev Docker | Dev config accidentally deployed to prod | Always use `POSTGRES_PASSWORD`; never use `trust` even in dev |
| Raw f-string SQL in backfill scripts | SQL injection from entity/doc_type parameters | Always use SQLAlchemy bound parameters; never format SQL strings with user-supplied values |

---

## "Looks Done But Isn't" Checklist

- [ ] **Alembic migrations:** `alembic upgrade head` passes locally — verify it also runs cleanly inside Docker with `docker-compose run db_migrate alembic upgrade head`
- [ ] **Connection pool:** Pool sizes sum to less than `max_connections - 10` (reserve for admin connections) — verify with `SELECT count(*) FROM pg_stat_activity` under load
- [ ] **API contract preservation:** All 114 existing tests still pass with DB layer active — verify `PYTHONPATH=. pytest tests/ -v` passes with Postgres container running
- [ ] **Backfill idempotency:** Running backfill twice does not create duplicate rows — verify with `INSERT ... ON CONFLICT DO NOTHING` or upsert logic
- [ ] **Live fallback:** If Postgres is down, API falls back to live fetch (not 500) — verify by stopping the `postgres` container and hitting each endpoint
- [ ] **CVM latin-1 encoding:** Rows with accented characters (FIDC fund names with ã, ç, etc.) round-trip correctly through Postgres UTF-8 storage — verify with `SELECT denom_social FROM cvm_fidc WHERE denom_social LIKE '%ã%'`
- [ ] **Backfill runs as separate process:** Verify no SQLAlchemy session or `async_sessionmaker` is imported inside `src/tools/backfill.py` at module scope before DB layer is wired
- [ ] **`expire_on_commit=False`:** Set in `async_sessionmaker` — verify no `MissingGreenlet` errors after commit in integration tests
- [ ] **Pydantic v2 ORM models:** All ORM-backed response models use `ConfigDict(from_attributes=True)` not `orm_mode = True` — verify with `grep -r "orm_mode" src/`

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Leaked session causing dirty reads in production | HIGH | Roll back deployment; audit all `AsyncSession` usages; add integration test under concurrency before re-deploy |
| Async Alembic env.py misconfigured — migrations never ran | MEDIUM | Add `postgresql://` sync URL for Alembic only; run `alembic stamp head` after manual table creation to resync state |
| Connection pool exhaustion causing cascading 500s | MEDIUM | `docker-compose restart postgres`; reduce `pool_size` in all services; add PgBouncer before next deploy |
| Backfill inserted CVM numerics as strings | HIGH | Write and run a one-time migration: `UPDATE cvm_records SET data = jsonb_set(data, '{VL_TOTAL}', (data->>'VL_TOTAL')::numeric::text::jsonb)` — test on copy first |
| API contract broken by new Pydantic field | LOW | Revert the field addition; add contract snapshot test; use response header for provenance instead |
| Duplicate rows from non-idempotent backfill | MEDIUM | `DELETE FROM cvm_records WHERE ctid NOT IN (SELECT min(ctid) FROM cvm_records GROUP BY entity, doc_type, period, cnpj)` |

---

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Leaked async session | Phase 1: DB foundation — session factory and `get_db` dependency | Integration test: concurrent requests do not share transaction state |
| Async Alembic env.py | Phase 1: DB foundation — Alembic init | `docker-compose run db_migrate alembic upgrade head` exits 0 and tables exist |
| Connection pool exhaustion | Phase 2: Docker Compose integration — pool sizing | `pg_stat_activity` count < `max_connections - 10` under load |
| Migration race on startup | Phase 2: Docker Compose integration — init container | All three services start cleanly on fresh `docker-compose up` without manual restarts |
| CVM strings in JSONB | Phase 3: Schema design — normalization function | `SELECT` with numeric range filter returns correct rows |
| API contract breakage | Every phase — contract snapshot tests from Phase 1 | `pytest tests/test_api_contracts.py` passes after every model change |
| Sync python-bcb blocking event loop | Phase 4: Backfill pipeline — process separation | API latency unchanged while backfill runs concurrently |
| Missing Postgres healthcheck | Phase 2: Docker Compose integration | Services never enter crash-loop on fresh `docker-compose up` |

---

## Sources

- SQLAlchemy async docs: `https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html` — session-per-request pattern
- Alembic async migration cookbook: `https://alembic.sqlalchemy.org/en/latest/cookbook.html#using-asyncio-with-alembic`
- FastAPI SQL databases guide: `https://fastapi.tiangolo.com/tutorial/sql-databases/` — `Depends(get_db)` pattern
- asyncpg `TooManyConnectionsError` — commonly reported when multiple services share one Postgres without PgBouncer
- Pydantic v2 migration guide: `https://docs.pydantic.dev/latest/migration/` — `from_attributes=True` replaces `orm_mode`
- Docker Compose `depends_on` with `condition: service_healthy` — Docker docs v3.9
- Project codebase: `src/cvm_api/services.py` (CSV parsing, cache layer), `src/bacen_api/main.py` (BacenClient global pattern), `src/tools/backfill.py` (ThreadPoolExecutor), `docker-compose.yml` (current network topology)

---
*Pitfalls research for: PostgreSQL persistence layer — FastAPI multi-service Brazilian financial data platform*
*Researched: 2026-03-12*
