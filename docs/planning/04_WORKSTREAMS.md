# 04 — WORKSTREAMS (Dependency Graph & Branches)

Each workstream = one branch off `main`. After **W0 + W1**, the remaining workstreams
touch disjoint files (per `02 §7`) and run in parallel.

## Dependency graph
```
W0 (repo reconcile) ─┐
                     ├─> [parallel] W2, W3, W4   (Domain A completion)
W1 (field-map +      ┘
    modularization) ─┬─> W5 (cia scaffold) ─> W6 (cadastre+IPE) ─> W10 (API)
                     │                      └─> W7 (ITR/DFP) ─> W9 (cia analytics) ─> W10
                     └─> (Domain A reload validates the refactor)
W8 (cia FRE/CGVN/VLMO) depends on W5; do last.
```
**Land first, serially:** W0, then W1. Then fan out.

---

## W0 — Repo reconciliation  ·  branch `chore/reconcile-main`  ·  small
Make the repo describe what actually exists.
- Rename `src/store/supabase_client.py` → `src/store/pg_client.py`; purge "Supabase" wording from README + `docs/pipeline-plan.md` (code already uses `POSTGRES_URL`/psycopg2).
- Rewrite `docs/PLAN.md` "Table Status" to current reality (it cites stale row counts).
- Decide & act on ghosts: delete `docker-compose.yml`; delete `netlify.toml` OR document it; pick **one** of `dashboard.py` (Streamlit) vs `dashboard/` (Evidence) and remove the other; resolve the GH-Actions-vs-Flask deploy contradiction in the README.
- Decide `fi-doc-balancete`: finish (table + map) or delete the config line.
- **DoD:** README matches the tree; one presentation layer; no dead config.


## W1 — Field-map refactor + modularization  ·  branch `refactor/declarative-field-maps`  ·  medium  ·  **blocks the rest**  ·  in-progress
Implement `02 §1–2 §7`.
- Add `src/parsers/field_maps/<dataset>.py` (one per dataset) + a generic `apply_map(row, FIELD_MAP) -> (typed, residual_raw)` in `src/parsers/`.
- Extend `src/parsers/validation.py` with `coerce_type` handlers (latin-1 numbers, BR/ISO dates, CNPJ→14, pct).
- Refactor `cvm_pipeline.py`: replace inline `_find_field` dicts (incl. the duplicated daily/backfill FI map) with map-driven ingest; split per-entity logic into thin modules so the 1,550-line file shrinks and agents stop colliding in it.
- Split the `schema.sql` migration tail into `src/store/migrations/`; `apply_schema.py` runs them in order.
- **DoD:** funds backfill reloads from empty and reproduces identical typed data with zero manual SQL; `raw` holds only residual; idempotency + null-rate checks pass.
- **Template to follow:** `05_AGENT_TASK_BRIEFS.md` → "W1 starter (FII)".

## W2 — `fi-cad` → fund registry  ·  branch `feat/fi-cad-registry`  ·  small  ·  needs W1 standard
- Add `fi` `cad` dataset to `cvm_config.py` (`{base}/FI/CAD/DADOS/cad_fi.csv` — single CSV, not yearly).
- Field map → populate existing `cvm_fund_registry` (cnpj, denom, type, situation, administrator, dates).
- Wire into daily + backfill. **DoD:** registry populated; fund labels joinable by CNPJ across all fund tables.

## W3 — Numeric precision audit  ·  branch `chore/numeric-precision`  ·  small  ·  **in-progress**
- Query observed max magnitudes per numeric column; migrate any under-spec column to the `02 §3` convention; add migrations. Fold in `vl_quota` widenings already applied so they're permanent in code.
- **DoD:** no `NUMERIC(20,12)` monetary/quota columns remain under-spec; convention documented.

## W4 — FI lamina/extrato (optional)  ·  branch `feat/fi-lamina-extrato`  ·  small  ·  defer
Add only when the UI needs fee/essential-info columns.

## W5 — `cia_aberta` scaffold  ·  branch `feat/cia-scaffold`  ·  medium  ·  needs W1
- New `cia` entity in `cvm_config.py` (ITR/DFP/IPE/FRE/CAD URL patterns from `03`).
- New fetcher path for `CIA_ABERTA` (multi-CSV zip handling, like FIDC tab_X).
- Migration creating `cia_company`, `cia_filing`, `cia_account` (partitioned by `dt_refer` year), `cia_event` (DDL sketch below).
- **DoD:** tables exist; fetcher can download + unzip + enumerate members; no ingest yet.

## W6 — cia B0: cadastre + IPE  ·  branch `feat/cia-cadastre-ipe`  ·  medium  ·  needs W5
- Field maps + ingest for `cia_aberta-cad` → `cia_company` and `ipe` → `cia_event`.
- **DoD:** company dim populated; material-facts feed queryable; idempotent; null-rate checked.

## W7 — cia B1: ITR + DFP financials  ·  branch `feat/cia-financials`  ·  large  ·  needs W5
- Parser iterating the ~19 zip members, tagging each row with `grupo` (BPA/BPP/DRE/…) + `escopo` (con/ind); normalize `VL_CONTA` by `ESCALA_MOEDA`; upsert latest `VERSAO`.
- Field map for the shared statement-CSV columns → `cia_account`; index rows → `cia_filing`.
- **DoD:** ITR+DFP 2019→present loaded; `cia_account` partitioned; revenue/net-income/equity retrievable per company per period.

## W8 — cia B2: FRE/CGVN/VLMO  ·  branch `feat/cia-enrichment`  ·  medium  ·  needs W5  ·  defer
Selective ingest of governance/capital/insider-trade datasets per UI need.

## W9 — cia analytical layer  ·  branch `feat/cia-analytics`  ·  medium  ·  needs W7
- `dim_company`, `fact_company_quarterly` (pivot key DRE/BPA lines to wide fundamentals), peer-ranking views, and the **cross-domain bridge view** (`cnpj_cia` ↔ fund portfolios).
- Mirror the existing `src/store/analytical/` numbering convention.

## W10 — API/webapp surfaces  ·  branch `feat/api-surfaces`  ·  medium  ·  needs data
- `/funds/*`, `/securities/*`, `/companies/*`, `/macro/*` on the Neon Data API and/or Flask/Next app; cross-domain linker widget.

---

## Domain B DDL sketch (for W5)
```sql
CREATE TABLE IF NOT EXISTS cia_company (
    cd_cvm     TEXT PRIMARY KEY, cnpj_cia TEXT, denom_cia TEXT,
    setor TEXT, segmento TEXT, situacao TEXT, raw JSONB, fetched_at TIMESTAMPTZ DEFAULT NOW());

CREATE TABLE IF NOT EXISTS cia_filing (
    id BIGSERIAL PRIMARY KEY, cd_cvm TEXT NOT NULL, doc_type TEXT NOT NULL,
    dt_refer DATE NOT NULL, versao INT, id_doc TEXT, dt_receb DATE, link_doc TEXT,
    CONSTRAINT uq_cia_filing UNIQUE (cd_cvm, doc_type, dt_refer, versao));

CREATE TABLE IF NOT EXISTS cia_account (
    id BIGSERIAL, cd_cvm TEXT NOT NULL, cnpj_cia TEXT, doc_type TEXT NOT NULL,
    grupo TEXT NOT NULL, escopo TEXT NOT NULL, dt_refer DATE NOT NULL, ordem_exerc TEXT,
    dt_ini_exerc DATE, dt_fim_exerc DATE, cd_conta TEXT NOT NULL, ds_conta TEXT,
    vl_conta NUMERIC(28,2), escala_moeda TEXT, st_conta_fixa CHAR(1), versao INT, raw JSONB,
    CONSTRAINT uq_cia_account UNIQUE (cd_cvm, doc_type, grupo, escopo, dt_refer, ordem_exerc, cd_conta, versao)
) PARTITION BY RANGE (dt_refer);

CREATE TABLE IF NOT EXISTS cia_event (
    id BIGSERIAL PRIMARY KEY, cd_cvm TEXT NOT NULL, cnpj_cia TEXT, data_refer DATE,
    data_entrega TIMESTAMPTZ, categoria TEXT, tipo TEXT, especie TEXT, assunto TEXT,
    protocolo TEXT, versao INT, link_download TEXT,
    CONSTRAINT uq_cia_event UNIQUE (protocolo, versao));
```
