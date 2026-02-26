# System Patterns

## Architectural Patterns

- **Service-Oriented Architecture**: Separate FastAPI services per data source (CVM, BACEN, B3 CALC)
- **Fallback Pattern**: B3 CALC returns sample data when upstream unavailable - always preserve unless explicitly requested
- **Config-Driven Resilience**: Network settings (timeouts, retries, DNS) centralized in config.py

## Design Patterns

- **Repository Pattern**: Service layer abstracts data fetching from CVM/BACEN/B3 sources
- **Pagination**: In-memory pagination after full CSV download (DEFAULT_PAGE_SIZE=100, MAX_PAGE_SIZE=10000)
- **Cache Pattern**: B3 CALC uses in-memory TTL cache (30-min TTL, max 64 entries)

## Common Idioms

- **Import Guards**: `if __package__: ... else ...` pattern in service main.py for dual-run compatibility
- **Pydantic v2**: Use `model_dump()`, `ConfigDict`, `json_schema_extra` (not v1 patterns)
- **Latin-1 Encoding**: Required for CVM CSV parsing (`encoding='latin-1'`, `delimiter=';'`)
- **Timezone-Aware Datetime**: Use `datetime.now(timezone.utc)` (not deprecated `utcnow()`)

---

_Last updated: 2026-02-26_
