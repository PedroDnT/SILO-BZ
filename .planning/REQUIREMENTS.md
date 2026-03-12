# Requirements: iliquid_nightly — Database Persistence Layer

**Defined:** 2026-03-12
**Core Value:** Any endpoint returns historical financial data instantly from a local database, without hitting upstream sources on every request.

## v1 Requirements

### Infrastructure

- [ ] **INFRA-01**: PostgreSQL 16 container runs in Docker Compose with `pg_isready` healthcheck
- [x] **INFRA-02**: Three isolated schemas exist (`cvm`, `bacen`, `b3_calc`) with per-service DB users
- [ ] **INFRA-03**: Alembic migrations apply via a dedicated one-shot `db_migrate` compose service before any API service starts
- [ ] **INFRA-04**: All API services declare `depends_on: db_migrate: condition: service_completed_successfully`
- [ ] **INFRA-05**: `DATABASE_URL` and per-service DB credentials configurable via environment variables (no hardcoded strings)
- [x] **INFRA-06**: ORM table definitions live in `src/db/models/` as shared source of truth

### BACEN DB Layer

- [ ] **BACEN-01**: SGS observations stored and served from `bacen.sgs_observations` table with typed columns `(series_code, obs_date, value)`
- [ ] **BACEN-02**: PTAX rates stored and served from `bacen.ptax_rates` table with typed columns `(currency_code, rate_datetime, bid, ask)`
- [ ] **BACEN-03**: BACEN route handlers query DB first; fall through to `python-bcb` on DB miss
- [ ] **BACEN-04**: BACEN backfill CLI populates DB from historical `python-bcb` data as a separate process (not inside FastAPI worker)
- [ ] **BACEN-05**: Idempotent upsert (`INSERT ... ON CONFLICT DO UPDATE`) used for all BACEN inserts

### CVM DB Layer

- [ ] **CVM-01**: CVM records stored with JSONB payload column per row plus extracted typed columns (`cnpj_key`, `competence_date`, `entity`, `doc_type`)
- [ ] **CVM-02**: `normalize_cvm_row()` function converts Brazilian decimal-comma strings to float/int before DB insert
- [ ] **CVM-03**: CVM route handlers query DB first; fall through to CSV/ZIP download on DB miss
- [ ] **CVM-04**: DB-aware backfill CLI (`backfill_db.py`) writes to DB via idempotent upsert; replaces file-based progress tracker with `cvm_ingest_log` table
- [ ] **CVM-05**: Bulk insert path used for CVM files (not row-by-row) to handle 200k+ row monthly files

### B3 CALC DB Layer

- [ ] **B3-01**: B3 CALC securities and pricing snapshots stored in `b3_calc` schema tables with JSONB payload
- [ ] **B3-02**: B3 CALC route handlers follow three-level chain: DB → live upstream → sample data (existing fallback preserved)
- [ ] **B3-03**: Only live upstream data written to DB; sample data fallback values never persisted

### Query and Contract

- [ ] **QUERY-01**: All existing API routes, query parameters, and Pydantic response shapes remain unchanged
- [ ] **QUERY-02**: `X-Data-Source` response header set to `"db"` or `"live"` on all responses (provenance without breaking response schema)
- [ ] **QUERY-03**: Async DB sessions injected via `Depends(get_db)` per-request; no module-level `AsyncSession` globals
- [ ] **QUERY-04**: Connection pool configured per-service (`pool_size=5, max_overflow=10`); `POSTGRES_MAX_CONNECTIONS=200` set in compose

## v2 Requirements

### Operational Visibility

- **OPS-01**: `/api/v1/sync/status` endpoint showing per-dataset last sync time and record count
- **OPS-02**: `/api/v1/coverage` endpoint showing date range and record count per dataset
- **OPS-03**: DB reachability check added to each service's `/health` endpoint

### Sync Automation

- **SYNC-01**: Scheduled incremental sync runner (watermark-based delta detection) as a dedicated compose service
- **SYNC-02**: Incremental sync covers all three services in a unified way

### Advanced Queries

- **ADV-01**: CNPJ aggregation view across CVM entity types
- **ADV-02**: Point-in-time B3 pricing snapshots (defer until B3 live API is confirmed stable)
- **ADV-03**: Configurable retention policy with Postgres range partitioning

## Out of Scope

| Feature | Reason |
|---------|--------|
| Redis caching | DB is the durable cache; Redis adds two cache-invalidation problems before load testing reveals actual hot queries |
| Real-time WebSocket streaming | Upstream data is published daily/monthly — nothing to stream |
| Full-text search (GIN tsvector) | `ILIKE` + exact CNPJ match covers lookup cases; GIN adds migration complexity before schema stability |
| Multi-tenant row-level security | Auth layer does not exist; RLS has no subject to bind to |
| GraphQL | Dataset schemas are not deeply relational; REST with filter params covers the query space |
| ANBIMA OAuth2 | Requires paid credentials |
| Authentication / API keys | Out of scope for this milestone |
| Frontend / dashboard UI | API-only milestone |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| INFRA-01 | Phase 1 | Pending |
| INFRA-02 | Phase 1 | Complete |
| INFRA-03 | Phase 1 | Pending |
| INFRA-04 | Phase 1 | Pending |
| INFRA-05 | Phase 1 | Pending |
| INFRA-06 | Phase 1 | Complete |
| QUERY-01 | Phase 1 | Pending |
| QUERY-03 | Phase 1 | Pending |
| QUERY-04 | Phase 1 | Pending |
| BACEN-01 | Phase 2 | Pending |
| BACEN-02 | Phase 2 | Pending |
| BACEN-03 | Phase 2 | Pending |
| BACEN-04 | Phase 2 | Pending |
| BACEN-05 | Phase 2 | Pending |
| QUERY-02 | Phase 2 | Pending |
| CVM-01 | Phase 3 | Pending |
| CVM-02 | Phase 3 | Pending |
| CVM-03 | Phase 3 | Pending |
| CVM-04 | Phase 3 | Pending |
| CVM-05 | Phase 3 | Pending |
| B3-01 | Phase 4 | Pending |
| B3-02 | Phase 4 | Pending |
| B3-03 | Phase 4 | Pending |

**Coverage:**
- v1 requirements: 23 total
- Mapped to phases: 23
- Unmapped: 0

---
*Requirements defined: 2026-03-12*
*Last updated: 2026-03-12 after roadmap creation — QUERY-01 assigned to Phase 1 (constraint established and enforced from Phase 1 onwards)*
