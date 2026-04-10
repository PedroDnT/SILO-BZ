# Technology Stack

**Analysis Date:** 2026-04-10

## Languages

**Primary:**
- Python 3.12 - All services, tools, and tests

**Secondary:**
- None (pure Python monorepo)

## Runtime

**Environment:**
- Python 3.12 (pinned in Dockerfiles: `FROM python:3.12-slim`)

**Package Manager:**
- pip (no Poetry at runtime; Dockerfile installs Poetry env vars but uses plain pip)
- Lockfile: `requirements.txt` present at root and per-service; no `pip.lock` or `poetry.lock`

## Frameworks

**Core:**
- FastAPI 0.109.0 - REST API framework for all three services
- Uvicorn 0.27.0 (with `[standard]` extras: uvloop, httptools) - ASGI server; always launched via `python -m uvicorn` in dev, bare `uvicorn` in Docker CMD

**Data:**
- Pydantic 2.5.3 - Request/response models; use `model_dump()`, `ConfigDict`, `json_schema_extra` (v2 patterns)
- pandas 2.2.0 - DataFrame operations; used in BACEN client for time-series normalization
- numpy 1.26.3 - Companion to pandas; used for NaN/type normalization in `src/clients/bacen_client.py`

**Testing:**
- pytest (root `requirements.txt` does not pin; `src/b3_calc_api/requirements.txt` pins `pytest==8.0.1`)
- pytest-asyncio 0.23.5
- pytest-cov 4.1.0

**Build/Dev:**
- black - code formatting
- flake8 - linting
- mypy - static type checking
- isort - import sorting
- rich 13.7.0 - terminal output in backfill CLI
- tqdm 4.66.1 - progress bars in backfill CLI

## Key Dependencies

**Critical:**
- `python-bcb>=0.3.0` - Sole interface to BACEN SGS/PTAX/Expectativas/TaxaJuros APIs; sync library wrapped in `asyncio.to_thread` in `src/clients/bacen_client.py`
- `aiohttp==3.9.1` - Async HTTP client for CVM file downloads in `src/cvm_api/services.py`; used with custom `RotatingDNSResolver`
- `httpx==0.27.0` - Async HTTP client for B3 CALC upstream in `src/b3_calc_api/services.py`
- `dnspython==2.6.1` - Powers `RotatingDNSResolver` in `src/cvm_api/services.py` for CVM resilience
- `aiofiles==23.2.1` - Async file I/O for CVM disk cache reads/writes in `src/cvm_api/services.py`

**Infrastructure:**
- `cachetools==5.3.2` - Referenced in requirements; in-memory cache for B3 CALC is hand-rolled in `src/b3_calc_api/services.py` (`CacheManager` class with TTL + FIFO eviction)
- `tenacity==8.2.3` - Retry library present in root `requirements.txt`; CVM retry loop is currently hand-rolled, not using tenacity directly
- `requests==2.31.0` - Sync HTTP; used only in `src/tools/backfill.py` (CLI tool, not service)
- `click==8.1.7` - CLI argument parsing for `src/tools/backfill.py`
- `python-dateutil==2.8.2` - Date parsing helpers

## Configuration

**Environment:**
- Copy `.env.example` to `.env` to configure
- Key env vars: `CVM_DNS_NAMESERVERS`, `B3_CALC_BASE_URL`, `BACEN_API_HOST`, `BACEN_API_PORT`, `RATE_LIMIT_ENABLED`, `RATE_LIMIT_REQUESTS`, `RATE_LIMIT_WINDOW`, `CACHE_TTL`, `TZ`, `LOG_LEVEL`
- Config classes: `BaseConfig` in `src/cvm_api/config.py` and `src/b3_calc_api/config.py`; module-level constants (no class) in `src/bacen_api/config.py`

**Build:**
- `docker-compose.yml` — primary multi-service orchestration (cvm_api:8000, b3_calc_api:8001, bacen_api:8002, docs:8080)
- `compose.yaml` — minimal root-level Dockerfile image (`bziliquidscrapper`)
- `compose.debug.yaml` — debug variant
- Each service has its own `src/{service}/Dockerfile` using multi-stage build (builder + python:3.12-slim runtime)
- `tini` used as PID 1 in Docker containers for signal handling

## Platform Requirements

**Development:**
- Python 3.12
- `PYTHONPATH=.` required when running pytest from repo root (import resolution)
- `python -m uvicorn` required in git worktrees (bare `uvicorn` crashes)

**Production:**
- Docker Compose (bridge network `br_finance`)
- Services expose ports: 8000, 8001, 8002, 8080
- Volumes: `./cache` and `./temp` mounted into cvm_api container
- Health checks via `curl -f http://localhost:{port}/health`
- Non-root appuser (uid 1000) inside containers

---

*Stack analysis: 2026-04-10*
