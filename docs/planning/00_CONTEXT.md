# 00 — CONTEXT (Ground Truth)

## What this project is
`iliquid_nightly` is a headless data pipeline that ingests Brazilian public market
data (CVM open data + BACEN) into a Neon Postgres database, with an analytical layer
on top. It is being expanded from a funds-focused tool into a **comprehensive
Brazilian markets data platform** spanning two domains (see `01_PRD.md`):
1. **Funds & Securities** (existing): FI, FIDC, FII, FIP, FIAGRO, securitizations (CRA/CRI/OTS), plus BACEN macro series.
2. **Listed Companies** (new): `cia_aberta` — ITR/DFP financial statements, IPE material facts, FRE reference forms.

## Pipeline shape
`fetch → parse → store → orchestrate`, all under `src/`:
- `src/fetchers/` — HTTP/SDK retrieval. `cvm_config.py` declares the dataset matrix (entity × doc_type → URL pattern).
- `src/parsers/` — `validation.py` (type coercion/validation). **Field maps to be added here (W1).**
- `src/pipeline/` — `cvm_pipeline.py` (orchestration + per-dataset parsing + store calls, ~1,550 lines — the refactor target), `run_backfill.py`, `run_daily.py`, `bacen_pipeline.py`.
- `src/store/` — `supabase_client.py` (a **Neon psycopg2 client**, misnamed — rename pending), `schema.sql` (28 tables), `analytical/*.sql` (dims, facts, views, functions), `apply_schema.py` (idempotent migrations).
- `src/api/` + `app.py` — local Flask control plane.
- `.github/workflows/backfill.yml` — historical backfill (FI = one parallel job per year via matrix; other entities single jobs). A daily ingest workflow also exists.

## Database — canonical target
- The canonical DB is the Neon project reached via the **`POSTGRES_URL`** env var / GH Actions secret.
  - It must point at the Neon endpoint host `ep-cold-moon-ak9pl909-pooler.c-3.us-west-2.aws.neon.tech`, database `neondb`.
  - **This project also has Neon Auth (`neon_auth`, `auth` schemas) and the Data API (`pgrst`) enabled** — it is intended to be both the data warehouse and the app backend.
- The client reads `os.environ["POSTGRES_URL"]` (`src/store/supabase_client.py`). Upserts go through `upsert_rows(...)` using `psycopg2.extras.execute_values` + explicit `ON CONFLICT (<conflict_columns>) DO UPDATE`.
- **Connection note for agents/tools:** native Postgres port 5432 may be blocked in some sandboxes. Neon also exposes an HTTPS SQL endpoint at `https://<host>/sql` (POST JSON `{"query":...,"params":[]}` with header `Neon-Connection-String`) which works for read/DDL when 5432 is unavailable. Claude Code on a normal machine should use 5432 directly via `POSTGRES_URL`.

## Verified current state (snapshot — re-query live before relying on it)
- **Funds domain loaded (partial):** `cvm_fi_diario` ≈ 24M rows across year partitions (2019–2026), `cvm_fi_cda` ≈ 650k, `cvm_fidc_tranche_flows` ≈ 651k, `cvm_fidc_tranche` ≈ 174k, `cvm_securit_mensal` ≈ 114k, FIP ≈ 13k, BACEN SGS/PTAX/expectativas ≈ 21k total.
- **Last backfill: 165 ok / 350 error slices.** The errors were almost all **schema-version mismatch** on the canonical DB (it had been built from an older `schema.sql`): missing columns (`cvm_fi_perfil.mod_var`, `tp_fundo` on several tables, `cvm_fii_periodic.data_referencia`, `cvm_securit_fluxo.recebimentos_alienacao_caixa`, `cvm_securit_serie.indice_subordinacao_data_base`), a missing table (`cvm_fund_registry`), and numeric overflow on `vl_quota`.
- **Already fixed (applied to the canonical DB):** all missing columns + `cvm_fund_registry` created from current `schema.sql`; `cvm_fiagro_mensal.vl_quota`, `cvm_fi_diario.vl_quota`, `cvm_fidc_mensal.vl_quota` widened to `NUMERIC(28,12/28,6)`. **A re-run of the backfill is required** to populate `cvm_fi_perfil`, `cvm_fii_mensal`, `cvm_fidc_mensal`, `cvm_securit_serie/fluxo`, `cvm_fiagro_mensal`, `cvm_fund_registry`. The ~21 remaining `Data not found` errors are benign (CVM hasn't published those periods).
- **Empty/never-populated:** `cvm_fund_registry` (no fetch path yet — see W2), and everything in the listed-companies domain (not started).

## Known traps (learned the hard way)
1. **Wrong-DB writes.** A run can complete "green" while writing to a *different* Neon project than you're inspecting. Always confirm `POSTGRES_URL`'s host before/after a backfill; `cvm_ingest_log` gets a row at the start of every slice, so an empty log on a finished run = wrong target.
2. **Missing GH secret.** If `POSTGRES_URL` isn't set as a repository **Secret** (not a Variable, not environment-scoped), the workflow falls back / writes nowhere useful.
3. **`schema.sql` drift.** `CREATE TABLE IF NOT EXISTS` silently skips column additions on an existing table. Always run `apply_schema.py` (the `ADD COLUMN IF NOT EXISTS` migrations) against any DB *before* the first backfill.
4. **Manual SQL patches don't survive a reload.** The previous session hand-patched typed columns with one-off `UPDATE`s; a DB reset wiped them. All fixes must live in code/migrations (W1 addresses this root cause).

## Outstanding decisions (owner: Pedro)
- Presentation layer: an Evidence project (`dashboard/`), a Streamlit app (`dashboard.py`), and `netlify.toml` all coexist while the README says "no dashboard." Pick one (the Neon Data API + a web app is the likely intent). See W0.
- `fi-doc-balancete` is configured in `cvm_config.py` but has no table — finish or delete.
- Keep `raw` JSONB as residual audit (recommended) vs drop entirely — see `02`.
