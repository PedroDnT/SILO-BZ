# Workstreams

## W0 — Repo Reconciliation

**Status:** in-progress  
**Branch:** `chore/reconcile-main`

Goal: make the repo match reality — no ingest behaviour changes — except the one approved addition of `fi-doc-balancete`.

Tasks:
- [x] Rename `src/store/supabase_client.py` → `src/store/pg_client.py`; update all imports
- [x] Replace Supabase wording with Neon/psycopg2 in README and docs
- [x] Delete dead files: `docker-compose.yml`, `netlify.toml`, `dashboard.py`, `dashboard/`
- [x] Create `docs/planning/` directory (this file)
- [x] Add `cvm_fi_balancete` table DDL to `src/store/schema.sql`
- [x] Create `src/parsers/field_maps/__init__.py` + `fi_balancete.py`
- [x] Wire `ingest_fi_balancete` into `cvm_pipeline.py` (backfill + daily_update)
- [x] Update `docs/PLAN.md` table status section
- [ ] Open PR against main

## W1 — Field Map Migration

**Status:** pending  
**Branch:** TBD

Goal: migrate all ingest methods from ad-hoc `_find_field` calls to the
`src/parsers/field_maps/` pattern introduced in W0. One field map per dataset,
shared `apply_map()` helper in `src/parsers/validation.py`.

## W2 — Balancete Backfill

**Status:** pending (blocked on W0 merge)  
**Branch:** TBD

Goal: trigger historical backfill for `cvm_fi_balancete` from 2019 (or earliest
available) through current month. Verify row counts and null rates.
