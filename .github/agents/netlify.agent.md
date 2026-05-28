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

---

## Investigation paths (pre-built SQL in `scripts/queries/`)

Each file is a ready-to-run analytical module. Build dashboards or API endpoints directly from these.

### `01_market_overview.sql` — Macro pulse
Industry-wide AUM by entity type (FI/FIDC/FII/FIP/FIAGRO), FIDC sector delinquency trend, data freshness per entity. Good for a homepage summary card.

### `02_fii_market.sql` — Real estate funds deep-dive
FII vs FIAGRO AUM comparison, yield distribution across all FIIs, CDI spread (fetch live CDI from BCB API at `api.bcb.gov.br/dados/serie/bcdata.sgs.12`), top funds by AUM and yield, investor concentration.

### `03_fidc_credit_monitor.sql` — Receivables fund credit quality
Sector delinquency trend (trailing 24 months), top FIDCs by AUM with names, funds with highest delinquency rates, tranche-level performance. Core screen for credit risk.

### `04_securit_issuance.sql` — CRA/CRI/OTS issuance market
Monthly issuance by instrument type, maturity ladder (outstanding principal bucketed by time-to-maturity), distressed securities screen (overdue but still "em curso"). Good for fixed-income origination trends.

### `05_yield_universe.sql` — Cross-asset yield comparison
FII + FIAGRO dividend yield vs CRA/CRI yield vs CDI benchmark in one table. Requires live CDI from BCB API. Best view for relative-value positioning.

### `06_fund_lookup.sql` — Fund profile / search
Search any fund by name fragment (`search_funds('kinea', NULL, 20)`), full profile for a CNPJ, NAV history, flow trend, peer ranking within entity type. Foundation for a fund detail page.

### `07_new_fund_activity.sql` — Market formation trends
New fund registrations per month by entity type, zombie funds (stopped reporting 90+ days ago), dissolution trends. Useful for spotting market cycles and regulatory pressure.

### `08_ingest_health.sql` — Pipeline ops
Last 7/30 days of ingest runs, error counts by entity, coverage gaps (entities with no new data in 35+ days). Use for a monitoring/ops dashboard.

### `10_fidc_advanced.sql` — FIDC forensics
1. **Universe aging screen**: rank FIDCs by long-tail (360+ day) delinquency concentration — funds with high `pct_long_tail` carry embedded losses the headline rate hides.
2. Delinquency acceleration: month-over-month deterioration rate.
3. Flow-delinquency correlation: are investors fleeing before disclosures?

### `11_suspicious_deals.sql` — Red flag screens
Eight forensic patterns:
1. **Cross-fund circular holdings** — FoF structures masking real AUM
2. **Zombie growth** — AUM rising while delinquency accelerates (classic Ponzi signal)
3. **Pre-disclosure redemption spikes** — unusual outflows before bad news
4. **Captive vehicles** — high AUM, almost no investors (single LP structures)
5. **Evergreen aging** — credits never migrating to longer delinquency buckets (rolled/hidden)
6. **Subordination erosion** — junior tranche being wiped while senior is still priced fine
7. **Senior yield decoupling** — fund stress not reflected in tranche returns
8. **Overdue securit series** — CRA/CRI in default but status still "em curso"

---

## Analytical angles worth surfacing

- **FIDC delinquency acceleration vs fund flow**: do investors redeem *before* disclosures hit? (`vl_inad_*` buckets vs `captc_dia/resg_dia` timing)
- **FII dividend yield vs CDI spread over time**: when does the spread compress below zero? A leading indicator of FII selloffs
- **CRA/CRI IPCA-linked vs CDI-linked issuance mix**: tracks inflation expectations from the originator side
- **New FIDC registrations vs delinquency levels**: are new vehicles being created to roll bad credits?
- **Fund manager concentration**: which 10 managers control >50% of FIDC AUM? Systemic risk view
- **Zombie fund tracker**: funds that stopped reporting — liquidation, merger, or stealth closure?

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
