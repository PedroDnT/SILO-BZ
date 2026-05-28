# iliquid_nightly — Netlify Agent Context

## What this project is

A Brazilian financial data platform that ingests, stores, and analyses public CVM (Comissão de Valores Mobiliários) and BACEN (Banco Central do Brasil) datasets. It is a **Python data pipeline + Flask API**, not a JS/frontend app.

The Netlify deployment exposes the Flask control plane as a lightweight API. The heavy lifting (historical backfill, daily ingestion) runs on GitHub Actions, not Netlify Functions.

---

## Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12 |
| API | Flask (`app.py` → `src/api/`) |
| Database | Neon Serverless Postgres (project: ILLIQUID, 3.2 GB) |
| DB client | psycopg2 via `POSTGRES_URL` |
| Ingestion | `src/pipeline/cvm_pipeline.py` + `src/pipeline/run_backfill.py` |
| CI/CD | GitHub Actions (`.github/workflows/`) |
| Hosting | Netlify (Flask API only) |

---

## Data domain

Brazilian illiquid investment funds and fixed-income securitisation:

- **FI** — daily NAV, quota, AUM, flows for ~40k investment funds (partitioned by year, 19M+ rows)
- **FIDC** — monthly receivables funds: tranche data, aging buckets, delinquency rates
- **FII** — real estate funds: monthly NAV, dividend yield, investor count
- **FIAGRO** — agribusiness funds (data from 2025-05)
- **FIP** — private equity funds (quarterly/quadrimestral reports)
- **SECURIT** — CRA/CRI/OTS securitisation: series, cash flows, financial statements
- **BACEN** — macro rates: SELIC, CDI, IPCA, PTAX, inflation expectations

Key analytical objects: `dim_fund`, `dim_security`, `fact_fund_monthly`, `fact_security_monthly`, `vw_fidc_aging_summary`, `vw_fidc_tranche_detail`, `vw_fii_vs_fiagro`, `vw_fund_security_yield`, `vw_securit_emission_trend`

---

## Flask API endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/healthz` | DB connectivity check |
| GET | `/api/status` | Row counts per table + recent ingest log |
| GET | `/api/dispatch` | All valid (entity, doc_type) pairs |
| POST | `/api/ingest` | Ingest one (entity, doc_type, year, month) slice |
| POST | `/api/ingest/range` | Ingest a year range for one entity/doc_type |
| POST | `/api/daily` | Run daily incremental update |
| GET | `/api/jobs` | List recent jobs |
| GET | `/api/jobs/<id>` | Poll a specific job |
| POST | `/api/verify` | Quality gate report (null rates) |

---

## Key commands

```bash
pip install -r requirements.txt   # install deps
flask --app app run               # local API on :5000
pytest                            # run tests
python -m src.pipeline.run_daily  # daily update
python -m src.pipeline.run_backfill --entity fi --start-year 2019 --cvm-only
```

---

## Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `POSTGRES_URL` | ✅ | Neon pooled connection string |
| `DATABASE_URL` | ✅ | Same as POSTGRES_URL |
| `PYTHON_VERSION` | ✅ | Must be `3.12` in Netlify build |
| `CVM_DAILY_SCOPE` | optional | `core` — which entities daily update runs |
| `CVM_REQUEST_TIMEOUT` | optional | `300` seconds |
| `CVM_UPSERT_CHUNK_SIZE` | optional | `1000` rows per DB batch |
| `LOG_LEVEL` | optional | `INFO` |
| `TZ` | optional | `America/Sao_Paulo` |

Never use `NETLIFY_DATABASE_URL` — this project uses Neon directly via `POSTGRES_URL`.

---

## What to build / suggest

Good tasks for the Netlify AI agent:

- **Dashboard pages**: AUM trends by fund type, FIDC delinquency heatmaps, FII dividend yield timeseries, CRA/CRI emission volume by year
- **API endpoints**: query endpoints on top of analytical views (`fact_fund_monthly`, `vw_fidc_aging_summary`, etc.)
- **Monitoring page**: live `/api/status` poll showing table row counts and last ingest run
- **Fund screener**: filter funds by entity type, AUM range, delinquency rate, dividend yield

Analytical angles that are interesting:
- FIDC credit quality deterioration: `vl_inad_30/60/90` aging buckets over time
- FII vs FIAGRO dividend yield spread
- CRA/CRI emission trends by index (IPCA vs CDI) and sector
- FI fund flows (`captc_dia - resg_dia`) as macro risk-sentiment indicator
- Cross-fund CNPJ overlap: which funds hold the same underlying receivables

---

## What NOT to do

- Do not use `npm`, `vite`, `next`, or any JS build tooling — this is a Python project
- Do not deploy ingestion as Netlify Functions — they time out at 10–26s, ingestion takes minutes
- Do not use `@netlify/database`, Drizzle ORM, or `NETLIFY_DATABASE_URL` — already removed
- Do not add `netlify/database/migrations/` — schema lives in `src/store/schema.sql`
- Do not commit `.env` or any file containing `POSTGRES_URL`, `npg_*`, or `napi_*` values
- Do not add `.local_db/` to git — contains large DuckDB binary files (already gitignored)
- Do not rewrite git history — the repo has been cleaned with `git filter-repo` already

---

## Style preferences

- Python-first: all backend logic in Python, no JS backend
- Small focused changes — preserve existing module structure in `src/`
- Env vars for all runtime tuning, never hardcode URLs or credentials
- SQL for analytics, Python for orchestration
- Comments only when the WHY is non-obvious
- Keep Flask API endpoints backward-compatible
