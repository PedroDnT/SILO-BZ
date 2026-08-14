# AGENTS.md

See `CLAUDE.md` and `README.md` for the full architecture, data-integrity rules, and
command reference. This file only adds context specific to running the project inside a
Cursor Cloud agent VM.

## Cursor Cloud specific instructions

### Environment layout
- Python **3.12** in a virtualenv at `.venv/` (gitignored, persisted in the VM snapshot).
  The startup update script (`python3 -m venv .venv` + `pip install -r requirements.txt` +
  `pip install duckdb`) keeps it fresh. Run Python via `.venv/bin/python` (or
  `source .venv/bin/activate`); there is no global install of the project deps.
- `duckdb` is required by the offline verification scripts but is used only for local dev;
  it is listed in `requirements.txt` under "Local dev / offline verification".
- Git hooks live in `.githooks/` (enabled with `bash scripts/install_hooks.sh`, which sets
  `core.hooksPath`). Only a `pre-commit` hook exists (secret scan + `py_compile`/`bash -n`);
  despite `CLAUDE.md` mentioning a pre-push hook, there is none in `.githooks/`.

### What runs without credentials (default dev/testing loop)
No `POSTGRES_URL` / Supabase credentials are needed for the core loop:
- Lint/syntax gate: `.venv/bin/python -m py_compile <changed .py files>` (what the
  pre-commit hook runs). There is no ruff/flake8/black configured.
- Tests: `.venv/bin/python -m pytest tests/ -q` — 360 tests, fully offline (DB + HTTP mocked).
- End-to-end pipeline (fetch→parse→store) against **real CVM data over the network** into a
  local DuckDB file: `.venv/bin/python scripts/seed_local_db.py --skip-fi` then
  `.venv/bin/python scripts/run_analysis_local.py`. This is the self-contained way to prove
  the pipeline works. Note: it downloads from the (slow) `dados.cvm.gov.br` server, so
  `--skip-fi` realistically takes ~10–15 min here (the README's "~2 min" is optimistic).
  It writes `.local_db/iliquid_local.duckdb` (~100 MB) — do not commit that file.
- Flask control plane: `.venv/bin/flask --app app run` (binds `127.0.0.1:5000`). It starts
  without a DB and `/healthz` returns `status: degraded` / `postgres: error` when
  `POSTGRES_URL` is unset — that is expected. DB-free endpoints like `GET /api/dispatch`
  work fully; ingest/status endpoints need a live Supabase.

### What needs secrets (not runnable in a fresh VM by default)
- The live pipeline (`python -m src.pipeline.run_daily` / `run_backfill`), `scripts/apply_schema.py`,
  `scripts/verify_pipeline.py`, and real Flask ingest/status all require `POSTGRES_URL`
  (Supabase Postgres, `sslmode=require`) via `.env` (copy from `.env.example`).
- The `dashboard/` and `webapp/` Evidence.dev apps (`npm install && npm run sources &&
  npm run dev`) are read-only consumers that need a populated Supabase to render data.
- `etf_market_snapshot` ingestion self-skips unless `APIFY_TOKEN` is set.
