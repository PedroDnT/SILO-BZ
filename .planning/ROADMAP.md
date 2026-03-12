# Roadmap: iliquid_nightly — Database-Backed Historical Data Layer

## Overview

This milestone adds a shared PostgreSQL 16 persistence layer to three already-working FastAPI services (cvm_api, bacen_api, b3_calc_api). The build follows a hard dependency chain: infrastructure first, then each service DB layer in order of schema complexity (BACEN → CVM → B3 CALC). Every request path adopts DB-first-with-live-fallback so the existing cold-start resilience is preserved throughout. All existing API contracts remain unchanged.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: DB Foundation** - PostgreSQL container, schemas, migrations, and async session wiring in place; all API services can open a DB connection
- [ ] **Phase 2: BACEN DB Layer** - SGS and PTAX data stored and served from DB; BACEN routes query DB first and fall through to python-bcb on miss
- [ ] **Phase 3: CVM DB Layer** - CVM records stored with JSONB payload; DB-aware backfill replaces file-based progress tracker; bulk insert handles 200k+ row files
- [ ] **Phase 4: B3 CALC DB Layer** - B3 securities and pricing snapshots stored in DB; three-level fallback chain (DB → live upstream → sample data) operational

## Phase Details

### Phase 1: DB Foundation
**Goal**: Any API service can open an authenticated async connection to a running PostgreSQL 16 instance with the correct schema, table definitions, and user permissions established before the service starts
**Depends on**: Nothing (first phase)
**Requirements**: INFRA-01, INFRA-02, INFRA-03, INFRA-04, INFRA-05, INFRA-06, QUERY-01, QUERY-03, QUERY-04
**Success Criteria** (what must be TRUE):
  1. `docker-compose up` starts a Postgres 16 container, runs `db_migrate` to completion, then starts all API services — all services reach healthy state with no manual steps
  2. All existing API routes return identical responses with no schema changes — `QUERY-01` is enforced from day one
  3. A `GET /health` request to any service succeeds and the service can execute a query against its schema without error
  4. All DB credentials and `DATABASE_URL` are read from environment variables; no connection strings are hardcoded in any source file
  5. ORM table stubs exist in `src/db/models/` for all three schemas (`cvm`, `bacen`, `b3_calc`) and Alembic applies them via `alembic upgrade head`
**Plans**: 3 plans

Plans:
- [ ] 01-01-PLAN.md — Docker Compose topology + PostgreSQL init.sql + db_migrate Dockerfile + Alembic env.py
- [ ] 01-02-PLAN.md — src/db/models/ DeclarativeBase + three schema ORM stubs
- [ ] 01-03-PLAN.md — Per-service db.py (async engine + get_db) + lifespan engine disposal + requirements.txt updates

### Phase 2: BACEN DB Layer
**Goal**: BACEN SGS and PTAX data is stored in the database and served from it on subsequent requests; BACEN route handlers fall through to python-bcb only when the DB has no matching rows
**Depends on**: Phase 1
**Requirements**: BACEN-01, BACEN-02, BACEN-03, BACEN-04, BACEN-05, QUERY-02
**Success Criteria** (what must be TRUE):
  1. After running `bacen_backfill.py` for a series, a `GET /api/v1/bacen/sgs/{series_code}` request returns data with `X-Data-Source: db` header
  2. A `GET /api/v1/bacen/ptax/USD` request with no backfilled data returns live data from python-bcb and the response carries `X-Data-Source: live`
  3. Re-inserting the same SGS or PTAX rows (via backfill re-run) produces no duplicates — idempotent upsert is verified by record count staying constant
  4. `bacen_backfill.py` runs as a standalone CLI process with no FastAPI server running, populates the DB, and exits cleanly
**Plans**: TBD

Plans:
- [ ] 02-01: bacen schema tables, db_service.py query/upsert functions, and BACEN route handler DB-first wiring
- [ ] 02-02: bacen_backfill.py CLI and X-Data-Source header on all BACEN responses

### Phase 3: CVM DB Layer
**Goal**: CVM records are stored with JSONB payload and typed extraction columns; all CVM routes query the DB first; a DB-aware backfill CLI handles large monthly files efficiently and replaces the file-based progress tracker
**Depends on**: Phase 2
**Requirements**: CVM-01, CVM-02, CVM-03, CVM-04, CVM-05
**Success Criteria** (what must be TRUE):
  1. After backfilling a FIDC monthly file, a `GET /api/v1/cvm/fidc/mensal` request returns data with `X-Data-Source: db` header — no upstream download triggered
  2. Numeric fields in CVM JSONB payloads (Brazilian decimal-comma values) are stored as float/int, not strings — a direct DB query on a numeric column returns sortable values
  3. Re-running `backfill_db.py` for the same period produces no duplicate rows — `cvm_ingest_log` shows the period as already ingested and skips it
  4. A 200k+ row FIDC monthly file completes DB insertion in under 60 seconds (bulk insert path, not row-by-row)
**Plans**: TBD

Plans:
- [ ] 03-01: CVM schema tables (JSONB + typed extraction columns), normalize_cvm_row(), and db_service.py upsert functions
- [ ] 03-02: backfill_db.py CLI with cvm_ingest_log resume table and bulk insert path
- [ ] 03-03: CVM route handler DB-first wiring across all entity/doc_type combinations

### Phase 4: B3 CALC DB Layer
**Goal**: B3 CALC securities and pricing snapshots are stored in the database; route handlers follow a three-level chain (DB → live upstream → sample data); the existing sample-data fallback is preserved as last resort and sample data is never written to the DB
**Depends on**: Phase 3
**Requirements**: B3-01, B3-02, B3-03
**Success Criteria** (what must be TRUE):
  1. After running `b3_backfill.py`, a request for a previously fetched security returns `X-Data-Source: db` and matches the originally fetched data
  2. When the live upstream (`calculadorarendafixa.com.br`) is unavailable and the DB has no matching row, the response returns sample data — the existing fallback behavior is intact
  3. A direct DB query on the `b3_calc` schema returns zero rows that originated from sample data — only live upstream data is persisted
**Plans**: TBD

Plans:
- [ ] 04-01: b3_calc schema tables, db_service.py query/upsert functions, and three-level fallback chain in route handlers
- [ ] 04-02: b3_backfill.py CLI for daily pricing snapshot sync

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. DB Foundation | 0/3 | Not started | - |
| 2. BACEN DB Layer | 0/2 | Not started | - |
| 3. CVM DB Layer | 0/3 | Not started | - |
| 4. B3 CALC DB Layer | 0/2 | Not started | - |
