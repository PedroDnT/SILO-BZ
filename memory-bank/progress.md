# Progress (Updated: 2026-02-26)

## Done

- Initialize project
- CVM Credit API (port 8000)
- BACEN API (port 8002)
- B3 CALC API (port 8001)
- Backfill tool for historical CVM data
- Test suite (58 tests, 100% passing)
- Docker Compose orchestration
- **Unified API Gateway** (port 8000) - Single entry point with YAML OpenAPI spec

## Doing

- Implement rate limiting across all APIs
- Connect B3 CALC live API
- Fix CORS configuration

## Next

- ANBIMA OAuth2 client
- Auth layer (JWT/API keys)
- Redis caching
