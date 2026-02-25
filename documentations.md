// The provided code snippet is a markdown document that serves as a guide for developers working on a
// Brazilian Financial Data Infrastructure project. It includes information about the project overview,
// repository structure, architecture details of different APIs (CVM Credit API, BACEN API, B3 CALC
// API), shared utilities, code style and patterns, commands for running services and tests, key
// technical details, environment variables, documentation setup, GitHub actions, memory bank
// structure, important conventions to follow, and known TODO items categorized as P1 (quick wins), P2
// (implement eventually), and P3 (low priority/skip).
// The above code provides detailed documentation for a repository that contains multiple services for
// accessing Brazilian financial market data from public sources. Here is a summary of the key points
// covered in the documentation:
# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Brazilian Financial Data Infrastructure — a multi-service platform for accessing Brazilian financial market data from public sources (CVM, ANBIMA, BACEN, B3 CALC).

## Repository Structure

```
.
├── src/
│   ├── cvm_api/          # FastAPI service for CVM credit market data (FIDC, FIP, FIAGRO, SECURIT)
│   │   ├── config.py     # DatasetConfig, EntityType enums, BaseConfig
│   │   ├── models.py     # Pydantic v2 response models (DataResponse, PaginationInfo, etc.)
│   │   ├── services.py   # CVMCreditDataService — downloads, parses, paginates CVM CSV/ZIP
│   │   ├── main.py       # FastAPI app, routes for /api/v1/{entity}/{doc_type}
│   │   ├── Dockerfile
│   │   └── README.md
│   ├── bacen_api/        # FastAPI service for BACEN public data (SGS, PTAX, Focus)
│   │   ├── config.py     # Module-level constants; no BaseConfig class (unlike cvm/b3 APIs)
│   │   ├── models.py
│   │   ├── main.py
│   │   ├── Dockerfile
│   │   └── README.md
│   ├── b3_calc_api/      # FastAPI service for B3 CALC fixed income pricing
│   │   ├── config.py     # BaseConfig class + sample data constants (SAMPLE_DEBENTURES, etc.)
│   │   ├── models.py
│   │   ├── services.py
│   │   ├── main.py
│   │   ├── Dockerfile
│   │   └── README.md
│   ├── clients/
│   │   └── bacen_client.py   # Async wrapper around python-bcb
│   ├── tools/
│   │   ├── backfill.py        # CLI: bulk historical CVM data download with resume
│   │   ├── backfill_config.py # Entity/period/URL configs for backfill
│   │   ├── progress_tracker.py
│   │   └── cvm_dir_mapper.py  # Maps CVM directory structure
│   └── validation_utils.py   # Shared: CNPJ, CPF, date, currency validators
├── tests/                # Pytest test suite (run from repo root) — 58 tests, 100% passing
│   ├── conftest.py       # Shared fixtures: CSV samples, mock HTTP sessions, temp dirs
│   ├── test_csv_parsing.py
│   ├── test_cvm_url_patterns.py
│   ├── test_data_validation.py
│   └── test_live_endpoints.py
├── scripts/
│   └── check_all_endpoints.py  # Dev tool: hit all live CVM endpoints and report
├── docs/                 # Static API documentation service (FastAPI)
│   ├── docs_server.py
│   ├── static/index.html
│   ├── Dockerfile
│   └── requirements.txt
├── memory-bank/          # AI assistant context files (do not delete)
│   ├── activeContext.md  # Current goals and blockers
│   ├── architect.md
│   ├── decisionLog.md    # Dated log of architectural decisions
│   ├── productContext.md
│   ├── progress.md       # Done / Doing / Next status
│   ├── projectBrief.md
│   └── systemPatterns.md
├── planning/             # Specification and planning documents (read-only reference)
├── docs.json             # Mintlify documentation site configuration
├── start.mdx             # Mintlify landing page stub
├── docker-compose.yml    # Orchestrates: cvm_api (8000), b3_calc_api (8001), bacen_api (8002), docs (8080)
├── compose.yaml          # Minimal compose for root Dockerfile (bziliquidscrapper image)
├── compose.debug.yaml    # Debug variant of compose.yaml
├── Dockerfile            # Root-level image (bziliquidscrapper)
├── requirements.txt      # Aggregate dev dependencies for local development
├── TODO                  # Tracked backlog (P1/P2/P3)
└── .env.example
```

## Architecture

### CVM Credit API (`src/cvm_api/`) — port 8000
- **Pattern**: `CVMCreditDataService` fetches CSV/ZIP from `dados.cvm.gov.br`, parses with `csv` module, paginates, returns via REST
- **Entities and doc types**:
  - `FIDC`: `mensal` (ZIP), `cadastral`, `trimestral`, `anual`
  - `FIP`: `inf_quadrimestral`, `inf_trimestral`, `cadastral`, `dfin`
  - `FIAGRO`: `mensal` (ZIP), `cadastral`, `trimestral`, `anual`
  - `SECURIT`: `cra_mensal`, `cri_mensal`, `ots_mensal`, `lca_mensal`, `lci_mensal` (all ZIP, yearly)
- **Data flow**: HTTP request → download CSV/ZIP → extract if ZIP → parse CSV (latin-1, `;`-delimited) → paginate → JSON
- **Config**: `DatasetConfig` in `config.py` maps entity+doc_type to URL patterns via `get_dataset_config(entity, doc_type)`
- **Resilience**: Network settings (`REQUEST_TIMEOUT=300`, `MAX_RETRIES=3`, `RETRY_DELAY=2`, DNS nameservers) are config-driven in `config.py`; do not hardcode request settings

### BACEN API (`src/bacen_api/`) — port 8002
- Wraps `python-bcb` (sync library) via `BacenClient` async wrapper in `src/clients/bacen_client.py`
- **Endpoints**:
  - `SGS`: well-known series list, single series, multi-series (`/api/v1/bacen/sgs/...`)
  - `PTAX`: USD/BRL and any currency, single date or range (`/api/v1/bacen/ptax/...`)
  - `Expectativas`: Focus/RDMercado market expectations (`/api/v1/bacen/expectativas/...`)
  - `TaxaJuros`: BACEN interest-rate OData (`/api/v1/bacen/taxas_juros/...`)
- **Config style**: Module-level constants (not a class), including `WELL_KNOWN_SGS`, `EXPECTATIVAS_ENDPOINTS`, `COMMON_CURRENCIES`

### B3 CALC API (`src/b3_calc_api/`) — port 8001
- Fixed income pricing for debentures, CRA, CRI
- **Fallback behavior**: Falls back to sample data (`SAMPLE_DEBENTURES`, `SAMPLE_CRAS`, `SAMPLE_CRIS` in `config.py`) if upstream (`calculadorarendafixa.com.br`) is unavailable; **preserve this behavior** unless explicitly requested to change
- Auto type detection and in-memory TTL cache (30-min TTL, max 64 entries) in `services.py`
- `B3_CALC_BASE_URL` is env-configurable (default: `https://calculadorarendafixa.com.br/webservice`)

### Shared utilities
- `src/validation_utils.py`: CNPJ/CPF checksum, date, currency, security code validators
- `src/clients/bacen_client.py`: Async wrapper around `python-bcb`

## Code Style and Patterns

- **Naming**: `PascalCase` for classes/enums, `snake_case` for functions/variables
- **Type hints**: All public methods should be typed
- **Service file structure**: Each service follows `config.py` (constants/env) → `models.py` (Pydantic contracts) → `services.py` (I/O + transformations) → `main.py` (FastAPI routing)
- **Import compatibility**: Services use `if __package__: ... else ...` guards to support both package and direct script execution (critical for git worktree and uvicorn compatibility)
- **Dual-run support**: Never use bare `uvicorn` in worktrees — always use `python -m uvicorn` which properly resolves src imports
- **Pydantic version**: Pydantic v2 (`pydantic==2.5.3`) is in use. Use `model_dump()` not `.dict()`, `model_json_schema()` not `.schema()`, `ConfigDict` not inner `Config` classes, and `json_schema_extra` not `schema_extra`. Migration from v1 patterns is in progress.
- **Datetime**: Use `datetime.now(timezone.utc)` — `datetime.utcnow()` is deprecated in Python 3.12

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run individual services locally (use python -m — bare uvicorn crashes in git worktrees)
python -m uvicorn src.cvm_api.main:app --reload --host 0.0.0.0 --port 8000
python -m uvicorn src.bacen_api.main:app --reload --host 0.0.0.0 --port 8002
python -m uvicorn src.b3_calc_api.main:app --reload --host 0.0.0.0 --port 8001

# Run all services with Docker Compose (primary multi-service setup)
docker-compose up -d

# Run backfill tool (from repo root)
python -m src.tools.backfill --entity FIDC --doc-type INF_MENSAL
python -m src.tools.backfill --all

# Check all live CVM endpoints
python scripts/check_all_endpoints.py
python scripts/check_all_endpoints.py --entity fidc --rows 5

# Tests — MUST run from repo root with PYTHONPATH set (src imports fail otherwise in worktrees)
PYTHONPATH=. pytest tests/ -v
PYTHONPATH=. pytest tests/test_csv_parsing.py -v
PYTHONPATH=. pytest tests/test_cvm_url_patterns.py::test_fidc_url -v

# Linting / formatting (mypy and flake8 may need to be installed separately)
black .
flake8 .
mypy .
isort .
```

## Key Technical Details

- **CVM CSV parsing**: `latin-1` encoding, `;` delimiter, empty-string normalization; preserve this behavior in `src/cvm_api/services.py`
- **ZIP handling**: Predictable CSV filenames (e.g., `inf_mensal_fidc_202502.csv`); extraction logic is in service layer
- **Pagination**: Done in-memory after full CSV download; limits and defaults centralized in `BaseConfig` (`DEFAULT_PAGE_SIZE=100`, `MAX_PAGE_SIZE=10000`)
- **Each service**: Has its own `Dockerfile` and `requirements.txt`; root `requirements.txt` is for local dev only
- **Import guards**: `src/cvm_api/main.py`, `src/bacen_api/main.py`, and `src/b3_calc_api/main.py` use `if __package__:` guards for dual-run compatibility
- **Authentication**: CVM and BACEN APIs are unauthenticated with permissive CORS (`allow_origins=["*"]`); ANBIMA requires OAuth2
- **Runtime directories**: `cache/`, `temp/`, `data/` are gitignored (runtime-generated); metadata and timestamps drive cache policy
- **DNS resilience**: CVM uses configurable nameservers (`CVM_DNS_NAMESERVERS` env var, default `1.1.1.1,8.8.8.8,9.9.9.9`) for network resilience
- **Test suite**: 58 tests, 100% passing as of 2026-02-24; pytest markers: `unit`, `integration`, `slow`, `cvm`, `validation`, `parsing`

## Environment Variables (from `.env.example`)

Key variables (copy `.env.example` to `.env` to configure):

| Variable | Default | Purpose |
|---|---|---|
| `CVM_DNS_NAMESERVERS` | `1.1.1.1,8.8.8.8,9.9.9.9` | DNS fallback for CVM downloads |
| `B3_CALC_BASE_URL` | `https://calculadorarendafixa.com.br/webservice` | B3 CALC upstream URL |
| `BACEN_API_HOST` / `BACEN_API_PORT` | `0.0.0.0` / `8002` | BACEN service bind address |
| `RATE_LIMIT_ENABLED` / `RATE_LIMIT_REQUESTS` / `RATE_LIMIT_WINDOW` | `true` / `100` / `60` | Rate limiting (not yet wired) |
| `CACHE_TTL` | `3600` | Cache TTL in seconds |
| `TZ` | `America/Sao_Paulo` | Timezone |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

## Documentation (`docs.json` / Mintlify)

The repository includes a Mintlify documentation site:

- `docs.json` — navigation and theme config (`$schema: https://mintlify.com/docs.json`, theme `mint`)
- `start.mdx` — landing page stub (MDX with YAML frontmatter required on all pages)
- `.claude/CLAUDE.md` — Mintlify-specific instructions for AI assistants working on docs

When editing docs, follow the `.claude/CLAUDE.md` conventions: second-person voice, frontmatter on every MDX page, relative internal links, tested code examples, language tags on all code blocks.

## GitHub Actions

- `.github/workflows/claude.yml` — triggers Claude Code action on `@claude` mentions in issues/PRs
- `.github/workflows/claude-code-review.yml` — automated code review via Claude
- `.github/workflows/update-docs.yml` — documentation update automation
- `.github/workflows/jekyll-gh-pages.yml` — GitHub Pages deployment
- `.github/copilot-instructions.md` — GitHub Copilot instructions
- `.github/*.chatmode.md` — VS Code Copilot chat modes (architect, ask, code, debug)

## Memory Bank

The `memory-bank/` directory holds structured context files for AI assistants:

- `activeContext.md` — current goals and blockers (update when focus shifts)
- `decisionLog.md` — dated table of architectural decisions and rationale
- `progress.md` — Done / Doing / Next status summary
- `systemPatterns.md` — recurring architectural and design patterns

These files should be kept current. When completing a significant task, update `progress.md` and `decisionLog.md`.

## Important Conventions

1. **Do not remove B3 fallback behavior**: The fallback-to-sample-data behavior in `src/b3_calc_api/services.py` is intentional; only modify if task explicitly requires it
2. **Preserve CVM cache behavior**: Cache and temp directory handling is integral to resilience; do not change without explicit request
3. **Query validation**: FastAPI route validation constraints and enums must be preserved; extend validation via `src/validation_utils.py`
4. **Pagination defaults**: Keep centralized in config; do not hardcode per-route defaults
5. **Network settings**: CVM retry/backoff and DNS settings are config-driven; avoid hardcoding request parameters
6. **Import guards**: Always preserve the `if __package__: ... else ...` pattern in service `main.py` files
7. **Pydantic v2**: New code must use v2 patterns (`model_dump()`, `ConfigDict`, `json_schema_extra`); do not introduce v1 patterns

## Known TODOs (from `TODO` file)

### P1 — Quick wins
- `datetime.utcnow()` deprecation warnings — partially fixed in main files; check `models.py` across all services
- Hardcoded absolute macOS paths in `.claude/launch.json` — make portable

### P2 — Implement eventually
- B3 CALC live API connection (currently falls back to sample data)
- Rate limiting via `slowapi` (env vars already defined, not yet wired)
- Pydantic v2 config migration (`schema_extra` → `json_schema_extra`, `BaseConfig` → `ConfigDict`)

### P3 — Low priority / skip
- ANBIMA OAuth2 client (requires paid credentials)
- Auth layer (JWT / API keys)
- Redis caching, PostgreSQL persistence, Prometheus metrics
