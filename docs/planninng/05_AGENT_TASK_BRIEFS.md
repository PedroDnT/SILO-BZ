# 05 — AGENT TASK BRIEFS (copy-paste)

Each brief is self-contained. Paste one into a Claude Code session. Every brief assumes
the agent has first read `00_CONTEXT.md` and `02_ARCHITECTURE_AND_CONVENTIONS.md`.

**Preamble to prepend to every brief:**
> You are working on `iliquid_nightly`. Read `planning/00_CONTEXT.md` and
> `planning/02_ARCHITECTURE_AND_CONVENTIONS.md` first. Follow the shared conventions
> exactly (typed-columns-are-the-interface, declarative field maps, numeric precision
> table, idempotent migrations, no destructive SQL, no secrets in code). Work on the
> branch named in the brief. Honor the Definition of Done in `02 §8`. The canonical DB
> is reached via `POSTGRES_URL`; confirm its host before any backfill.

---

## W0 — Reconcile main
Branch `chore/reconcile-main`. Make the repo match reality:
1. `git mv src/store/supabase_client.py src/store/pg_client.py`; update imports; remove "Supabase" wording from `README.md` and `docs/pipeline-plan.md`.
2. Rewrite `docs/PLAN.md` "Table Status" to current state (query the DB; cite live counts).
3. Delete `docker-compose.yml`. Delete `netlify.toml` unless it's the chosen serving layer. Keep exactly ONE of `dashboard.py` / `dashboard/`; remove the other. Fix the README's deploy section to match.
4. Resolve `fi-doc-balancete`: either add a table + field map + ingest, or remove its `cvm_config.py` entry.
Open a PR summarizing each decision. Do not change ingestion behavior.

---

## W1 — Field-map refactor (LAND BEFORE OTHERS)
Branch `refactor/declarative-field-maps`.
1. Create `src/parsers/field_maps/` with one module per dataset (`fi_diario.py`, `fi_cda.py`, `fi_perfil.py`, `fidc_mensal.py`, `fidc_tranche.py`, `fidc_tranche_flows.py`, `fidc_aging.py`, `fii_geral.py`, `fii_ativo_passivo.py`, `fii_complemento.py`, `fii_periodic.py`, `fip_periodic.py`, `fiagro_mensal.py`, `securit_mensal.py`, `securit_serie.py`, `securit_fluxo.py`, `securit_dfin.py`). Each exports `TABLE`, `CONFLICT`, `FIELD_MAP` per the `02 §2` shape. Derive candidates from the existing `_find_field(...)` calls in `cvm_pipeline.py` and from real CSV headers (download a recent zip per dataset to confirm names; CSVs are latin-1, `;`-delimited).
2. Add `apply_map(row, FIELD_MAP) -> (typed: dict, residual_raw: dict)` and `coerce(value, type)` in `src/parsers/`. `residual_raw` = original row minus mapped source keys.
3. Refactor `cvm_pipeline.py` to drive ingestion from the maps; remove the duplicated inline maps (the FI `inf_diario` map currently appears in both the daily and backfill paths). Extract per-entity ingest into thin modules.
4. Split the migration tail of `src/store/schema.sql` into `src/store/migrations/NN_<domain>.sql`; have `apply_schema.py` apply them in order (idempotent).
5. Validate: against the canonical DB, run a small backfill slice per dataset; confirm typed columns populate, `raw` holds only residual, re-running is idempotent, and null rates are explained.
**Start with FII** (messiest: 3 subtypes, most raw-only fields) as the reference implementation, then replicate the pattern to the others.

---

## W2 — fi-cad → registry
Branch `feat/fi-cad-registry`.
1. Add `fi`/`cad` to `cvm_config.py`: `{base}/FI/CAD/DADOS/cad_fi.csv` (single CSV, not yearly; confirm exact filename/columns by fetching it — latin-1, `;`).
2. `src/parsers/field_maps/fi_cad.py` mapping into existing `cvm_fund_registry` (cnpj, denom_social, tp_fundo/classe, situacao, administrator, registration/cancel dates). `CONFLICT=("cnpj","entity_type")`.
3. Wire into daily + backfill. Verify the registry populates and joins by `cnpj` to `cvm_fi_diario`.

---

## W3 — Numeric precision audit
Branch `chore/numeric-precision`.
1. For each numeric column, query `max(abs(...))` against loaded data; flag any exceeding its declared precision headroom.
2. Migrate under-spec columns to the `02 §3` convention (idempotent `ALTER COLUMN ... TYPE` migrations). Include the already-applied `vl_quota` widenings (`cvm_fi_diario`, `cvm_fidc_mensal`, `cvm_fiagro_mensal`) so they are permanent in code.
3. Document the convention in `docs/`.

---

## W5 — cia scaffold
Branch `feat/cia-scaffold`.
1. Add `cia` entity to `cvm_config.py` with ITR/DFP/IPE/FRE/CAD URL patterns (see `03_DATA_CATALOG.md`).
2. Fetcher support for `CIA_ABERTA` zips with multiple member CSVs (reuse the FIDC multi-CSV pattern).
3. Migration `src/store/migrations/NN_cia.sql` creating `cia_company`, `cia_filing`, `cia_account` (partition by `dt_refer` year, BRIN on `dt_refer` + btree `(cd_cvm, dt_refer DESC)`), `cia_event` (DDL in `04_WORKSTREAMS.md`).
No ingestion yet; just make download+unzip+enumerate work and tables exist.

---

## W6 — cia cadastre + IPE
Branch `feat/cia-cadastre-ipe` (needs W5).
1. `src/parsers/field_maps/cia_cad.py` → `cia_company`; `cia_ipe.py` → `cia_event` (cols in `03`). IPE `CONFLICT=("protocolo","versao")`.
2. Ingest + wire into backfill/daily. DoD per `02 §8`.

---

## W7 — cia ITR + DFP financials
Branch `feat/cia-financials` (needs W5).
1. Parser iterating the ~19 members per zip; for each statement member tag rows with `grupo` (from member name) and `escopo` (`con`/`ind`). Normalize `VL_CONTA` by `ESCALA_MOEDA` (`MIL`→×1000) at ingest. Upsert latest `VERSAO`.
2. `src/parsers/field_maps/cia_account.py` for the shared statement columns → `cia_account`; index members → `cia_filing`. `CONFLICT` = the `uq_cia_account` key.
3. Load ITR + DFP 2019→present. Verify revenue (`cd_conta='3.01'`), net income, equity retrievable per company per period.

---

## W9 — cia analytics
Branch `feat/cia-analytics` (needs W7).
- Add `src/store/analytical/` files (follow existing numbering): `dim_company`, `fact_company_quarterly` (pivot DRE/BPA account lines into wide fundamentals), peer-ranking views, and a **cross-domain bridge** view joining `cia_account.cnpj_cia` to fund portfolio CNPJs.

---

## W10 — API surfaces
Branch `feat/api-surfaces` (needs data).
- Expose `/funds/*`, `/securities/*`, `/companies/*`, `/macro/*` via the Neon Data API and/or the app. Keep funds and companies as separate surfaces (PRD). Add the cross-domain linker.

---

## Orchestrator notes
- Launch order: **W0 → W1** (serial), then dispatch {W2, W3, W5} in parallel; W6/W7 after W5; W9 after W7; W10 last.
- Each agent commits its own `src/store/migrations/NN_*.sql` and `src/parsers/field_maps/*.py` — disjoint files, no merge conflicts.
- Integration check after each merge: run `apply_schema.py` then a targeted backfill slice; confirm `cvm_ingest_log` ok and idempotency.
