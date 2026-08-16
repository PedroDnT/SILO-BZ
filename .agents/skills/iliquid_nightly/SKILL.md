---
name: silo
description: >
  SILO-BZ integrity and serving contract. Load when changing ingest, CVM/BACEN/B3
  fetchers, schema.sql, migrations, analytical SQL, schema api, serve/, catalog,
  panel metrics, GitHub ingest workflows, or reviewing PRs that touch those.
  Also load before adding a dataset or a new panel metric.
---

# SILO

Headless CVM/BACEN/B3 ingest into Supabase. The product is a researcher panel
`(id, date, metric, value)` via schema `api` + `serve/`. Full rules: `CLAUDE.md`,
`docs/planning/SERVING.md`, `docs/API.md`.

## Integrity (non-negotiable)

1. Never fabricate a price, fill, fallback dict, or ticker↔CNPJ join. A failed
   fetch `raise`s. Null stays null. No ffill.
2. No silent `except: pass` around network/DB. Failures go to `cvm_ingest_log`.
3. Provenance from source keys. One ingest log row per slice.
4. Validate before upsert (`DataValidator`). Drop invalid rows; never coerce.
5. Upsert only: `ON CONFLICT ... DO UPDATE`. Never plain `INSERT`.

HTTP is an adapter: one `SELECT` / `api.*()` per handler. Unknown ticker → 404.
Known ticker, empty window → 200 empty series. Never a guessed last close.

## Do not

- Add or grow ingest HTTP (`app.py`, `src/api/`, `POST /api/ingest`). Ingest is
  GitHub Actions + `python -m src.pipeline.run_daily` / `run_backfill`.
- Add `POST /v1/query` or Pearson/rank/spread over HTTP. Reducers stay in the
  notebook (`serve/catalog.py`).
- `GRANT anon` on `public` landing tables (`cvm_*`, `b3_cotahist`,
  `cvm_ingest_log`). The generic Supabase skill is wrong here. For DDL, use
  `supabase-postgres-best-practices`.
- Reintroduce Docker/Alembic, local Postgres-as-source-of-truth, or `b3_calc_api`.

## Add a dataset

1. `src/fetchers/cvm_config.py`
2. `src/parsers/field_maps/<entity>_<doctype>.py`
3. `schema.sql` + new `migrations/NNN_*.sql` (never edit historical migrations)
4. `ingest_*` on `CVMIngestor`; wire `daily_update` / `backfill`
5. Offline CSV fixture in `tests/test_*.py`

## Add a panel metric

1. `serve/catalog.py` `METRICS` (`id_type`, `grain`, `source`, `meaning`)
2. `api.panel` union arm in `19_api_contract.sql`
3. Bump `CATALOG_VERSION`
4. Offline test; keep `_PANEL_METRICS == tuple(METRICS)`

Serving open: limits before `fetchall` (step 3), honest returns (4), lookup (5),
`silo_api` role (6), HTTPS (7). Do not ship public HTTP until 3 and 6.

## Reviewing `serve/` or `19_*.sql`

Check “What we will not do” in `docs/planning/SERVING.md`. Caps belong in SQL
before Python `fetchall`. Catalog `meaning` must match the SQL.

## Commands

```bash
.venv/bin/python -m pytest tests/ -q
.venv/bin/python -m src.pipeline.run_backfill --cvm-only --entity fidc --start-year 2024 --end-year 2024
python -m serve.app   # read-only, 127.0.0.1:8080
```

Python: snake_case files and functions, `from src...` across packages, tests in
`tests/test_*.py` (pytest — not `*.test.py` or camelCase).
