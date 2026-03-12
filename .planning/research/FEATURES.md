# Feature Research

**Domain:** Database-backed financial time-series API — Brazilian market data (CVM funds, BACEN PTAX/SGS, B3 CALC pricing snapshots)
**Researched:** 2026-03-12
**Confidence:** HIGH

## Context

The existing system fetches CVM, BACEN, and B3 CALC data live on every request. This milestone adds a Postgres persistence layer so that historical data is stored, served from DB, and kept in sync via a background sync process. The analysis below focuses on what changes when you add a DB layer to a live-fetch API — not on the live-fetch features themselves (those are already built).

---

## Feature Landscape

### Table Stakes (The DB Layer Doesn't Work Without These)

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Schema design for time-series data | Every downstream query depends on correct partitioning and indexing | MEDIUM | CVM fund data is tabular/relational; BACEN SGS/PTAX and B3 pricing are pure time-series. Different access patterns require different schema strategies. Timescale or native Postgres partitioning by date range are both viable. |
| Idempotent upsert on ingest | Backfill and incremental sync run on overlapping date windows; duplicate rows corrupt aggregations | LOW | Use `INSERT ... ON CONFLICT (source_id, reference_date) DO UPDATE` pattern. Requires a stable composite natural key per dataset. |
| Incremental sync (delta / watermark-based) | Full re-download of CVM ZIP files on every sync is too slow and hammers the upstream | MEDIUM | Store a `last_synced_at` watermark per dataset+period. CVM publishes monthly ZIPs — sync only the current-month file after the first full load. BACEN SGS supports date-range queries natively. |
| Historical backfill pipeline | The existing `src/tools/backfill.py` already does bulk download; it needs a DB write path alongside or instead of file-based storage | MEDIUM | Reuse the existing resume/progress-tracker logic; add a DB sink. Backfill and live-fetch must share the same upsert function to avoid schema drift. |
| Query endpoint for stored data | Consumers need to query stored records by date range, entity, and CNPJ/fund code — the live-fetch route signature is not sufficient | MEDIUM | New route family: `GET /api/v1/db/{entity}?start_date=&end_date=&cnpj=&page=`. Must support keyset or cursor-based pagination for large date ranges. |
| Staleness metadata on every response | Consumers need to know whether data came from DB cache or live upstream, and how old the DB record is | LOW | Add `data_source: "db" | "live"`, `last_updated_at`, and `coverage_start` / `coverage_end` fields to every response. This is the contract for reliability. |
| DB connection pooling and async driver | FastAPI is async; blocking DB calls inside async handlers will serialize all requests | LOW | Use `asyncpg` or `SQLAlchemy 2.x async` with a connection pool sized to concurrency needs. Do not use synchronous `psycopg2` in async handlers. |
| Schema migrations with version control | Schema changes must be tracked and reproducible across environments | LOW | Alembic is the standard. Each dataset type (CVM fund, BACEN SGS, PTAX, B3 pricing) should have its own migration file. |
| Environment-driven DB config | DB URL, pool size, and sync interval must be env-configurable, consistent with the existing `.env.example` pattern | LOW | Add `DATABASE_URL`, `DB_POOL_SIZE`, `SYNC_INTERVAL_SECONDS` to `.env.example`. No hardcoded connection strings anywhere. |

---

### Differentiators (Competitive Advantage for This System)

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Unified coverage map endpoint | `GET /api/v1/coverage` returns per-dataset `{start_date, end_date, record_count, last_synced_at}` — consumers can discover gaps without probing data routes | LOW | A single metadata table (`dataset_coverage`) updated on every sync run. Very low cost, high trust signal. |
| Live-fallback with DB-primary routing | For any request: try DB first; if no records in range, fall back to live fetch and write-through to DB | MEDIUM | This bridges the cold-start window and keeps the API available even if sync is lagging. Requires a routing layer in the service, not just in the DB. The B3 CALC sample-data fallback pattern is a direct analogue — extend it. |
| Per-dataset sync health endpoint | `GET /api/v1/sync/status` returns last sync time, record count delta, and error count per dataset | LOW | Drives operational monitoring without external tooling. Surfaces broken syncs before consumers notice stale data. |
| Configurable retention policy | Keep N years of history per dataset; auto-purge older records | MEDIUM | CVM FIDC monthly data goes back to 2005; storing everything indefinitely is expensive. A per-entity TTL config in `config.py` is cleaner than a blanket policy. Depends on partitioning being in place. |
| Point-in-time snapshot queries for B3 pricing | B3 CALC pricing data is a snapshot as of a pricing date; enabling `?as_of=` queries lets consumers reconstruct portfolios at historical dates | HIGH | Requires immutable append-only writes for pricing rows (never update, only insert with a `priced_at` timestamp). Schema differs from the CVM/BACEN time-series pattern. |
| CNPJ-centric aggregation view | For CVM fund data, a materialized view grouping all doc types for a given CNPJ/fund enables single-query fund profiles | MEDIUM | Materialized views in Postgres refresh on schedule. Useful for downstream dashboards. Requires CVM entity schemas to share a `cnpj` column. |

---

### Anti-Features (Deliberate Non-Goals for This Milestone)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Real-time streaming / WebSocket push | Consumers want to be notified when new data arrives | Upstream CVM and BACEN data is published at daily/monthly cadence — there is nothing to stream. Adds protocol complexity for zero benefit at this data frequency. | Polling the staleness metadata endpoint (`last_updated_at`) is sufficient. Add WebSocket only if a high-frequency data source is added. |
| Full-text search across fund documents | Seems useful for fund name lookup | CVM CSV data has structured fields, not documents. A Postgres `GIN` index on a `tsvector` of fund names is easy to add but creates migration complexity before schema is stable. | Exact CNPJ match + `ILIKE` on fund name covers 95% of lookup cases with zero extra infrastructure. |
| Redis caching layer on top of DB | Faster reads, reduce DB load | The DB is already the cache. Adding Redis before load testing creates two cache-invalidation problems instead of one. The existing in-memory TTL cache in `b3_calc_api/services.py` is sufficient for hot paths. | Revisit after load testing reveals actual hot queries. Redis is in the `TODO` P2 list for good reason. |
| Multi-tenant data isolation | API key per consumer with row-level security | No auth layer exists yet. Implementing RLS before auth is backwards — RLS rules have no subject to bind to. | Implement the auth layer (JWT/API keys, already in TODO) first. RLS is a single ALTER TABLE away once auth is in place. |
| GraphQL API | Flexible querying | The dataset schemas are not deeply relational. GraphQL's value comes from graph traversal across many entity types. A REST API with well-designed filter params covers the query space at far lower implementation cost. | Keep REST. Add compound filter params (`?fields=`, `?sort=`) if projection is needed. |
| Automatic schema inference from CSV | Infer DB columns from CVM CSV headers dynamically | CVM CSV column sets change across years (breaking the inference). Schema must be explicit and versioned. Dynamic schema inference leads to `TEXT` columns everywhere and breaks type safety. | Explicit column definitions per dataset in `config.py`, migrated via Alembic. |

---

## Feature Dependencies

```
[Postgres schema + migrations]
    └──required by──> [Idempotent upsert]
    └──required by──> [Incremental sync]
    └──required by──> [Backfill DB sink]
    └──required by──> [Query endpoints for stored data]

[Idempotent upsert]
    └──required by──> [Incremental sync]
    └──required by──> [Backfill DB sink]

[Incremental sync]
    └──enables──> [Staleness metadata on responses]
    └──enables──> [Per-dataset sync health endpoint]
    └──enables──> [Coverage map endpoint]

[Live-fallback with DB-primary routing]
    └──requires──> [Query endpoints for stored data]
    └──requires──> [Incremental sync] (to know when DB is warm)

[Retention policy]
    └──requires──> [Postgres partitioning by date range]

[Point-in-time B3 pricing snapshots]
    └──requires──> [Append-only write semantics for pricing table]
    └──conflicts──> [Idempotent upsert on B3 rows] (upsert overwrites; snapshots must not)

[CNPJ aggregation materialized view]
    └──requires──> [CVM schema stable and migrated]
    └──requires──> [Backfill DB sink populated]
```

### Dependency Notes

- **Schema migrations block everything:** No ingest, no query, no sync until Alembic migrations are applied and tested. This is the critical path item.
- **Idempotent upsert is the foundation of ingest correctness:** Both backfill and incremental sync write through the same upsert function. If this is wrong, data is corrupted silently.
- **B3 pricing conflicts with upsert pattern:** CVM and BACEN data is mutable (corrections are published); B3 pricing snapshots are immutable. These two write patterns must not share infrastructure.
- **Live-fallback requires knowing when the DB is warm:** A cold DB (backfill not complete) should not serve empty results; it should fall through to live fetch. This requires the coverage map to be accurate before the fallback router is enabled.
- **Retention policy requires partitioning:** Range partitioning by month or quarter allows `DROP PARTITION` for expiry without a table-wide `DELETE` that locks rows.

---

## MVP Definition

### Launch With (v1 — DB Layer is Functional)

- [ ] Postgres schema + Alembic migrations for CVM FIDC monthly, BACEN SGS, BACEN PTAX — the three highest-value datasets
- [ ] Idempotent upsert function shared by backfill and sync
- [ ] Incremental sync worker (watermark-based, runs on configurable interval)
- [ ] DB-primary query endpoints with date range and CNPJ filters
- [ ] Staleness metadata (`data_source`, `last_updated_at`) on all responses
- [ ] `DATABASE_URL` and sync config in `.env.example`

### Add After Validation (v1.x — Operational Confidence)

- [ ] Per-dataset sync health endpoint (`/api/v1/sync/status`) — add once sync is running and gaps need visibility
- [ ] Coverage map endpoint (`/api/v1/coverage`) — add once multiple datasets are backfilled
- [ ] Live-fallback routing — add once DB is warm and the cold-start window is understood

### Future Consideration (v2+ — Advanced Queries)

- [ ] Point-in-time B3 pricing snapshots — defer until B3 live API is connected (currently sample data only)
- [ ] CNPJ aggregation materialized view — defer until schema is stable across CVM entity types
- [ ] Retention policy with partitioning — defer until storage cost is measurable
- [ ] Redis caching — defer until load testing reveals actual hot queries

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Postgres schema + Alembic migrations | HIGH | MEDIUM | P1 |
| Idempotent upsert | HIGH | LOW | P1 |
| Incremental sync worker | HIGH | MEDIUM | P1 |
| DB-primary query endpoints | HIGH | MEDIUM | P1 |
| Staleness metadata on responses | HIGH | LOW | P1 |
| Async DB driver (asyncpg) | HIGH | LOW | P1 |
| Per-dataset sync health endpoint | MEDIUM | LOW | P2 |
| Coverage map endpoint | MEDIUM | LOW | P2 |
| Live-fallback with DB-primary routing | MEDIUM | MEDIUM | P2 |
| Configurable retention policy | LOW | MEDIUM | P3 |
| Point-in-time B3 pricing snapshots | MEDIUM | HIGH | P3 |
| CNPJ aggregation materialized view | MEDIUM | MEDIUM | P3 |

**Priority key:**
- P1: Required for the DB layer to function
- P2: Required for operational reliability
- P3: Nice to have, future milestone

---

## Competitor / Reference Analysis

| Feature | TimescaleDB pattern | FRED API (Federal Reserve) | Our Approach |
|---------|---------------------|----------------------------|--------------|
| Time-series storage | Hypertable auto-partitioned by time | Relational, date-indexed | Native Postgres range partitioning first; evaluate Timescale extension if query performance degrades |
| Series metadata | Separate `series` catalog table | Inline in response | Separate `dataset_catalog` table with source URL, update frequency, first/last date |
| Incremental sync | Continuous aggregates | N/A (static dataset) | Watermark-based sync per dataset; no continuous aggregates needed at this data frequency |
| Data corrections | Append-only with correction flag | Overwrite | Upsert (overwrite) for CVM/BACEN (corrections replace prior values); append-only for B3 pricing |
| Pagination | Cursor-based (keyset) | Offset-based with limits | Keyset pagination on `(reference_date, id)` for large date ranges; offset for small result sets |

---

## Schema Design Notes (Brazilian Market Data Specifics)

**CVM fund data** (FIDC, FIP, FIAGRO, SECURIT):
- Natural key: `(cnpj_fundo, dt_competencia, doc_type)` — CNPJ is the fund identifier, competencia is the reference month
- Encoding hazard: latin-1 CSV source; store as UTF-8 in Postgres after decode
- Schema per doc type (mensal, trimestral, cadastral) — columns differ; do not force into a single table

**BACEN SGS time-series**:
- Natural key: `(series_code, reference_date)` — series_code is the SGS integer identifier
- Values are always numeric (float or integer); store as `NUMERIC(18,8)` not `TEXT`
- Series metadata (name, unit, frequency) belongs in a separate `sgs_series` catalog table

**BACEN PTAX**:
- Natural key: `(currency_code, rate_date, rate_type)` — rate_type distinguishes buy/sell
- Very low cardinality on currency_code; no separate dimension table needed
- Date gaps are expected (weekends, holidays) — do not interpret gaps as missing data

**B3 CALC pricing**:
- Natural key: `(isin_or_debenture_code, priced_at_date)` — immutable snapshot
- Must NOT be updated after insert; corrections are a new row with `correction: true` flag
- Fallback sample data (`SAMPLE_DEBENTURES`, etc.) should never be written to DB — only live data belongs in storage

---

## Sources

- Existing codebase: `src/cvm_api/`, `src/bacen_api/`, `src/b3_calc_api/`, `src/tools/backfill.py`
- CLAUDE.md architecture notes and known TODOs
- TimescaleDB documentation patterns for financial time-series
- FRED (Federal Reserve Economic Data) API design as reference for public economic data APIs
- Postgres documentation: range partitioning, upsert (`ON CONFLICT`), async drivers

---

*Feature research for: DB-backed financial time-series API (Brazilian market data)*
*Researched: 2026-03-12*
