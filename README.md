---
mode: "wide"
---

# Brazilian Financial Data Infrastructure

A multi-service FastAPI platform for accessing Brazilian public financial datasets with a unified developer experience.

## Overview

This repository provides APIs and tools for:

- **CVM credit market datasets** (FIDC, FIP, FIAGRO, SECURIT)
- **BACEN (BCB) data** (SGS, PTAX, Focus expectations, interest rates)
- **B3 CALC fixed-income pricing** (debentures, CRA, CRI)
- **Operational tooling** for historical CVM backfill and endpoint checks

## Services

| Service       | Port   | Purpose                                                  |
| ------------- | -----: | -------------------------------------------------------- |
| `cvm_api`     | `8000` | CVM open data ingestion, parsing, and pagination         |
| `b3_calc_api` | `8001` | B3 CALC pricing proxy with normalization and cache       |
| `bacen_api`   | `8002` | BACEN public data wrappers (SGS/PTAX/Expectativas/Taxas) |
| `docs`        | `8080` | Documentation service                                    |

## Repository Structure

```text
.
├── src/
│   ├── cvm_api/          # CVM FastAPI service
│   ├── b3_calc_api/      # B3 CALC FastAPI service
│   ├── bacen_api/        # BACEN FastAPI service
│   ├── clients/          # Shared external clients
│   ├── tools/            # Backfill and support CLIs
│   └── validation_utils.py
├── tests/                # Pytest suite
├── scripts/              # Utility scripts
├── docs/                 # Docs service
├── docker-compose.yml
└── requirements.txt
```

## Prerequisites

- Python **3.12+**
- `pip`
- Docker + Docker Compose (optional, for containerized run)

## Local Development

create and activate .venv

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Run services (separate terminals):

```bash
python -m uvicorn src.cvm_api.main:app --host 0.0.0.0 --port 8000 --reload
python -m uvicorn src.b3_calc_api.main:app --host 0.0.0.0 --port 8001 --reload
python -m uvicorn src.bacen_api.main:app --host 0.0.0.0 --port 8002 --reload
```

OpenAPI docs:

- CVM: http://localhost:8000/docs
- B3 CALC: http://localhost:8001/docs
- BACEN: http://localhost:8002/docs

## Docker Compose

Build and start all services:

```bash
docker-compose up --build
```

> **Note:** The `version` attribute in `docker-compose.yml` is obsolete and will be ignored. It has been removed to avoid potential confusion.

Service URLs:

- CVM API: http://localhost:8000
- B3 CALC API: http://localhost:8001
- BACEN API: http://localhost:8002
- Docs: http://localhost:8080
##

## Key Endpoints

### CVM API

- `GET /health`
- `GET /api/v1/endpoints`
- `GET /api/v1/fidc/{doc_type}`
- `GET /api/v1/fip/{doc_type}`
- `GET /api/v1/fiagro/{doc_type}`
- `GET /api/v1/securit/{doc_type}`

### B3 CALC API

- `GET /health`
- `GET /api/v1/`
- `GET /api/v1/prices/{symbol}`
- `GET /api/v1/indexes`
- `GET /api/v1/market-data`
- `GET /api/v1/securities/{security_type}`

### BACEN API

- `GET /health`
- `GET /api/v1/bacen/sgs/well-known`
- `GET /api/v1/bacen/sgs/{series_code}`
- `GET /api/v1/bacen/sgs/multi`
- `GET /api/v1/bacen/ptax/dolar`
- `GET /api/v1/bacen/ptax/moedas`
- `GET /api/v1/bacen/expectativas/{endpoint_name}`
- `GET /api/v1/bacen/taxas_juros/{endpoint_name}`

## Testing and Quality

From the repository root:

```bash
PYTHONPATH=. pytest tests/ -v
black .
isort .
flake8 .
mypy .
```

## Utility Commands

CVM live endpoint smoke check:

```bash
python scripts/check_all_endpoints.py
```

Historical backfill:

```bash
python -m src.tools.backfill --entity FIDC --doc-type INF_MENSAL
python -m src.tools.backfill --all
```

## Notes

- Runtime-generated directories (`cache/`, `temp/`, `data/`) are gitignored.
- Public endpoints are currently unauthenticated and CORS-permissive.
- See service-specific guides in:
  - `src/cvm_api/README.md`
  - `src/b3_calc_api/README.md`
  - `src/bacen_api/README.md`