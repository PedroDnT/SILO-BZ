# iliquid_nightly — Database-Backed Historical Data Layer

## What This Is

A Brazilian financial data infrastructure platform (FastAPI, multi-service) that currently fetches CVM, BACEN, and B3 CALC data live on every API request. The next milestone adds a persistent database layer: historical data is stored once and served from the database, eliminating repeated downloads and enabling time-series queries.

## Core Value

Any endpoint can return historical financial data instantly from a local database, without hitting upstream sources on every request.

## Requirements

### Validated

- ✓ CVM API endpoints (FIDC, FIP, FIAGRO, SECURIT) — existing, fetching CSV/ZIP on-demand
- ✓ BACEN API endpoints (SGS, PTAX, Focus/Expectativas, TaxaJuros) — existing, wrapping python-bcb
- ✓ B3 CALC API endpoints (debentures, CRA, CRI pricing) — existing, fallback to sample data
- ✓ Pagination, CORS, rate limiting config — existing
- ✓ Docker Compose multi-service orchestration — existing
- ✓ Vercel serverless deployment config — existing

### Active

- [ ] Database schema for all three services (CVM, BACEN, B3 CALC historical records)
- [ ] Backfill pipeline: populate DB with historical data from all existing sources
- [ ] API endpoints read from DB first; fall through to live fetch only on cache miss
- [ ] Incremental sync: scheduled or on-demand refresh of new data into DB
- [ ] DB integrated into Docker Compose stack
- [ ] Existing test suite remains green after DB layer is introduced

### Out of Scope

- Real-time streaming / WebSocket updates — not needed, data is batch-updated
- Authentication / API keys — out of scope for this milestone
- ANBIMA OAuth2 integration — requires paid credentials, deferred
- Redis/external caching layer — DB serves as the durable cache
- Frontend / dashboard UI — API only

## Context

- **Current data flow**: HTTP request → download CSV/ZIP from upstream → parse → paginate → respond. Slow, fragile, hits Vercel 30s timeout for CVM.
- **CVM**: CSV/ZIP from `dados.cvm.gov.br`, latin-1 encoded, `;`-delimited, monthly/quarterly/annual cadence. Existing backfill tool in `src/tools/backfill.py`.
- **BACEN**: Wraps `python-bcb` (sync). PTAX and SGS are time-series — natural fit for DB.
- **B3 CALC**: Currently falls back to sample data. Live source is `calculadorarendafixa.com.br`.
- **Pydantic v2** throughout (`model_dump()`, `ConfigDict`).
- **Import guards** (`if __package__`) must be preserved in all `main.py` files.

## Constraints

- **Tech stack**: Python 3.12, FastAPI, Pydantic v2 — no framework changes
- **Database**: Must run in Docker Compose alongside existing services; PostgreSQL preferred (production-grade, supports JSONB for flexible CSV schemas)
- **Backwards compatibility**: All existing API routes, query params, and response shapes must remain unchanged
- **Backfill tool**: `src/tools/backfill.py` already exists — extend rather than replace
- **Test suite**: 114 tests currently passing; must not regress

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| PostgreSQL over SQLite | Multi-service access, JSONB for flexible schemas, production-ready | — Pending |
| DB-first with live fallback | Preserves resilience; cold start still works with no DB | — Pending |
| Shared DB vs per-service DB | Single Postgres instance reduces ops overhead for this scale | — Pending |

---
*Last updated: 2026-03-12 after initialization*
