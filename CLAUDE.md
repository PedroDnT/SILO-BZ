# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Headless ingestion pipeline for Brazilian public financial data, built for **financial
accountability** of the fund industry (NAV, delinquency, tranche performance, structural
health). It downloads, parses, validates, and upserts data from **CVM** (fund disclosures:
FI, FIDC, FII, FIP, FIAGRO, SECURIT, plus listed-company CIA filings) and **BACEN** (SGS
time series, PTAX, Focus expectativas) into a **Supabase Postgres** database via psycopg2.

There is **no public API**. Downstream consumers (the `dashboard/` and `webapp/`) query
Supabase directly. A localhost-only Flask control plane (`app.py` + `src/api/`) wraps the
pipeline so operators can trigger partial-fill ingests one slice at a time.

> Read `README.md` for the full operator guide and `docs/pipeline-plan.md` /
> `docs/planning/` for the roadmap and conventions. A previous version had multiple FastAPI
> services + a Solana "Delos Oracle" + a `b3_calc_api`; all were removed. Do not reintroduce
> a public API surface, Docker/Alembic, local Postgres-as-source-of-truth, or B3 — see
> "What's intentionally not here" in `README.md`.

## Data integrity rules (NON-NEGOTIABLE)

These are the only way to truly break this codebase — fake data silently corrupts every
downstream metric. Full text in `.agents/rules/data-integrity.md`. Summary:

1. **Never fabricate data.** A failed fetch must `raise` — never return a plausible-looking
   fallback dict (this is exactly why `b3_calc_api` was deleted). Mocks live in `tests/` only.
2. **No silent `except: pass`** around network/DB calls. Classify and surface (`src/api/hooks.py`).
3. **Preserve provenance.** Every row carries its natural keys (e.g. `cnpj` / `cnpj_securit`
   and `dt_comptc` / `period` / `data_referencia` / `reference_date`, depending on the table)
   directly from source — never synthesize them. Every ingest writes exactly one
   `cvm_ingest_log` row.
4. **Validate before upsert.** All records pass `DataValidator` (`src/parsers/validation.py`):
   CNPJ = 14 digits, dates must parse, NAV/PL non-negative or explicitly nullable. A row that
   fails validation is dropped and counted — never coerced into a guess.
5. **Idempotent by construction.** Every table has a named UNIQUE constraint on its natural
   key; upserts use `ON CONFLICT ... DO UPDATE`. Never plain `INSERT`.

If a change makes `scripts/verify_pipeline.py` / `/api/verify` fail, the change is wrong —
not the verifier.

## Architecture

Three stages, orchestrated per `(entity, doc_type)` pair:

```
FETCH (src/fetchers/) → PARSE (src/parsers/) → STORE (src/store/)
                         ↑ ORCHESTRATE (src/pipeline/)
```

- **`src/fetchers/`** — HTTP/SDK calls only. `cvm_fetcher.CVMFetcher.fetch(entity, doc_type,
  year, month)` is the single entry point; downloads ZIP/CSV from `dados.cvm.gov.br` with
  retry, DNS rotation, and on-disk cache (`CVM_CACHE_DIR`). `bacen_fetcher.BacenClient` wraps
  `python-bcb`. `cia_fetcher` handles listed-company filings. `cvm_config.py` holds the
  `DatasetConfig` matrix (URL template, csv_name_pattern, periodicity, encoding).
- **`src/parsers/`** — `validation.DataValidator` (shared CNPJ/date/numeric validators) and
  `field_maps/<entity>_<doctype>.py` (each exposes one `FIELD_MAP: dict[str,str]`, CSV header
  → DB column). CSV extraction is co-located with the fetcher because it needs URL/filename
  context.
- **`src/store/`** — `pg_client.get_pg_client()` (one psycopg2 connection per run) and
  `pg_client.upsert_rows(table, rows, conflict_cols)` (chunked at 1000, `ON CONFLICT DO
  UPDATE`). **Never open a raw DB connection elsewhere — always go through `pg_client`.**
  `schema.sql` is the canonical schema; `migrations/NNN_*.sql` are append-only.
- **`src/pipeline/`** — `cvm_pipeline.CVMIngestor` and `bacen_pipeline.BacenIngestor` wire
  the stages and write audit-log rows. `ingest_<entity>.py` modules hold the per-entity
  `ingest_*` methods. CLI entry points: `run_daily.py` (cron: current month + 7-day window)
  and `run_backfill.py` (one-shot, all years).
- **`src/api/`** — Flask control plane (local-only, no auth, bind `127.0.0.1`). `routes.py`
  exposes ingest/status/jobs/verify; `jobs.py` is an in-process job registry (UUID → state);
  `dispatch.py` maps `(entity, doc_type)` → ingestor method; `hooks.py` is a post-job error
  classifier (`network` / `csv_parse` / `db_write` / `schema_mismatch` / `unknown`) and
  inefficiency detector. Hooks classify only — they never auto-retry.

Storage layout: ~25 tables named `cvm_<entity>_<doctype>` or `bacen_<series>`, plus the
`cvm_ingest_log` audit table. The README's CSV-coverage table is kept in sync but may lag;
trust `src/store/schema.sql` + `migrations/` + `src/api/dispatch.py` as the source of truth.
Wired datasets now include `cvm_fidc_tranche`, `cvm_fidc_aging`, `cvm_securit_serie`,
`cvm_securit_fluxo`, `cvm_fi_balancete`, `cvm_cia_*`, and the ETF tables.

### Adding a dataset (the `(entity, doc_type)` matrix)

Touch these in order (per `docs/planning/ARCHITECTURE_CONVENTIONS.md`):

1. `src/fetchers/cvm_config.py` — add a `DatasetConfig`.
2. `src/parsers/field_maps/<entity>_<doctype>.py` — add the `FIELD_MAP`.
3. `src/store/schema.sql` **and** a new `src/store/migrations/NNN_*.sql` — add the table
   (never edit historical migrations; keep `schema.sql` in sync).
4. `src/pipeline/ingest_<entity>.py` — add the `ingest_*` method.
5. `src/api/dispatch.py` — register `(entity, doc_type) → method` (skip this and the Flask
   control plane can't see the dataset).
6. `tests/` — add an offline test with a CSV fixture (skip this and pre-push won't protect it).

Periodicity: **monthly** datasets (`fi`, `fidc *`, `fiagro mensal`) take `(year, month)` and
key on `competencia` = first day of the month; **yearly** datasets (`fii *`, `fip`,
`securit *`) take `(year)` only; **BACEN** time series key on `(series_code, date)`.

For a *new class* of data (e.g. market/price series for securities), read
`docs/DATA_MODELING.md` first: extend the existing `dim_`/`fact_` star schema and model
time series as a **long fact** keyed on `(instrument natural key, date[, metric])` rather
than a wide per-source table — same provenance + idempotent-upsert rules apply.

The daily run probes a **gap-aware trailing window** for monthly datasets
(`CVM_DAILY_LOOKBACK_MONTHS`, default 4): it always refreshes the current + previous month
and additionally re-fetches any month in the window with no successful `cvm_ingest_log`
row, so a slice CVM publishes late (its 1–2 month lag) is healed on the next run instead of
missed forever. A not-yet-published month 404s and is logged `skipped`, not `error`. Deep
history is still `run_backfill`'s job, not the daily window's.

## Commands

```bash
# Setup
python3 -m venv .venv && source .venv/bin/activate   # Python 3.12
pip install -r requirements.txt
bash scripts/install_hooks.sh        # installs .githooks (pre-commit secret/syntax, pre-push tests)
cp .env.example .env                 # set POSTGRES_URL (Supabase conn string, sslmode=require)

# Schema
python scripts/apply_schema.py       # apply base schema + all migrations (idempotent)
python scripts/apply_migrations.py   # apply migrations only
bash scripts/apply_analytical.sh     # build analytical views/functions — run AFTER data exists

# Run the pipeline
python -m src.pipeline.run_daily                      # incremental
python -m src.pipeline.run_backfill --start-year 2019 # full historical (optional --entity)

# Flask control plane (local only)
flask --app app run                  # 127.0.0.1:5000; needs POSTGRES_URL

# Verify
python scripts/seed_local_db.py --skip-fi && python scripts/run_analysis_local.py  # offline, ~2min
python scripts/verify_pipeline.py    # against live Supabase (quality gate; keep green)

# Tests (pytest.ini sets pythonpath = ., so no PYTHONPATH prefix needed)
pytest tests/ -v        # all offline (DB + HTTP mocked)
pytest tests/test_api.py -v          # one file
pytest tests/test_api.py::test_name  # one test
```

`pytest.ini` sets `pythonpath = .` and `asyncio_mode = auto`. The pre-push hook runs the full
offline suite and blocks the push on failure; the pre-commit hook blocks committing Postgres
URLs with credentials and Python that fails `py_compile`. The `.claude/settings.json`
PostToolUse hook auto-runs `py_compile` after every Edit/Write to a `.py` file.

## Consumers (read-only, query Supabase directly)

Both are **Evidence.dev** projects (Node-based: `npm install && npm run sources && npm run dev`
→ localhost:3000; `npm run build` → `build/`). They connect to the same Supabase Postgres via
`@evidence-dev/postgres` and only read — never write.

- **`dashboard/`** — fund-health analytics: Overview (`/`), FIDC Credit Monitor (`/fidc`),
  FII Market (`/fii`), Suspicious Screens (`/suspicious`). Deployed to a static host / Netlify.
- **`webapp/`** — Evidence.dev instance for CIA Aberta (listed-company) analytics; in progress
  on the `feat/cia-financials` branch alongside the `cia_*` tables.

## Deploy

Single target: **GitHub Actions cron → Supabase Postgres**. Required GitHub secret: `POSTGRES_URL`.
No container registry, Vercel, or Docker.

- `.github/workflows/daily_ingest.yml` — 06:00 UTC daily (`run_daily`) + `workflow_dispatch`
  (`mode=daily|backfill`, optional `entity`/`start_year`/`end_year`). It bootstraps the schema
  via `psql` on every run, then `ANALYZE`s the tables.
- `.github/workflows/backfill.yml` — on-demand full backfill; FI runs one parallel job per year,
  other entities/BACEN/ETF in parallel, gated on a one-time `apply-schema` job.

Schema rollout = commit `schema.sql` + a new `migrations/NNN_*.sql`, then either let CI apply it
or run `scripts/apply_schema.py` against Supabase. Idempotent via `CREATE TABLE IF NOT EXISTS` +
named UNIQUE constraints. Note CI applies schema with `psql -v ON_ERROR_STOP=1` (parses SQL
comments correctly), so author migrations to be psql-clean.
