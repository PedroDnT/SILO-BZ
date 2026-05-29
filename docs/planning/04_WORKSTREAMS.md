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

## W0 — Repo reconciliation  ·  branch `chore/reconcile-main`  ·  small  ·  **done**
Make the repo describe what actually exists.
- Rename `src/store/supabase_client.py` → `src/store/pg_client.py`; purge "Supabase" wording from README + `docs/pipeline-plan.md` (code already uses `POSTGRES_URL`/psycopg2).
- Rewrite `docs/PLAN.md` "Table Status" to current reality (it cites stale row counts).
- Decide & act on ghosts: delete `docker-compose.yml`; delete `netlify.toml` OR document it; pick **one** of `dashboard.py` (Streamlit) vs `dashboard/` (Evidence) and remove the other; resolve the GH-Actions-vs-Flask deploy contradiction in the README.
- Decide `fi-doc-balancete`: finish (table + map) or delete the config line.
- **DoD:** README matches the tree; one presentation layer; no dead config.


## W1 — Field-map refactor + modularization  ·  branch `refactor/declarative-field-maps`  ·  medium  ·  **blocks the rest**  ·  **done**
Implement `02 §1–2 §7`.
- Add `src/parsers/field_maps/<dataset>.py` (one per dataset) + a generic `apply_map(row, FIELD_MAP) -> (typed, residual_raw)` in `src/parsers/`.
- Extend `src/parsers/validation.py` with `coerce_type` handlers (latin-1 numbers, BR/ISO dates, CNPJ→14, pct).
- Refactor `cvm_pipeline.py`: replace inline `_find_field` dicts (incl. the duplicated daily/backfill FI map) with map-driven ingest; split per-entity logic into thin modules so the 1,550-line file shrinks and agents stop colliding in it.
- Split the `schema.sql` migration tail into `src/store/migrations/`; `apply_schema.py` runs them in order.
- **DoD:** funds backfill reloads from empty and reproduces identical typed data with zero manual SQL; `raw` holds only residual; idempotency + null-rate checks pass.
- **Template to follow:** `05_AGENT_TASK_BRIEFS.md` → "W1 starter (FII)".

## W2 — `fi-cad` → fund registry  ·  branch `feat/fi-cad-registry`  ·  small  ·  needs W1  ·  **done**
- `fi/cad` dataset already in `cvm_config.py` (`{base}/FI/CAD/DADOS/cad_fi.csv` — single CSV, not yearly).
- `src/parsers/field_maps/fund_registry.py` — FIELD_MAP with verified CSV column names from live `cad_fi.csv` header (CNPJ_FUNDO, DENOM_SOCIAL, SIT, TP_FUNDO, DT_REG, DT_CONST, DT_CANCEL).
- `src/parsers/mapping.py` — `apply_map` / `coerce` engine (introduced in W1).
- `src/pipeline/ingest_fi.py` — `ingest_fund_registry_fi(conn, rows)` applies map, injects `entity_type="fi"`, stores residual in `raw`.
- `cvm_pipeline.py` `ingest_fund_registry` delegates to `ingest_fund_registry_fi` for `entity="fi"`.
- Both `backfill` and `daily_update` already call `ingest_fund_registry("fi")` once per run (not per month/year).
- **DoD:** registry populated; fund labels joinable by CNPJ across all fund tables; idempotent.

## W3 — Numeric precision audit  ·  branch `chore/numeric-precision`  ·  small  ·  **done**
- Query observed max magnitudes per numeric column; migrate any under-spec column to the `02 §3` convention; add migrations. Fold in `vl_quota` widenings already applied so they're permanent in code.
- **DoD:** no `NUMERIC(20,12)` monetary/quota columns remain under-spec; convention documented.

## W4 — FI lamina/extrato (optional)  ·  branch `feat/fi-lamina-extrato`  ·  small  ·  defer
Add only when the UI needs fee/essential-info columns.

## W5 — `cia_aberta` scaffold  ·  branch `feat/cia-scaffold`  ·  medium  ·  needs W1
- New `cia` entity in `cvm_config.py` (ITR/DFP/IPE/FRE/CAD URL patterns from `03`).
- New fetcher path for `CIA_ABERTA` (multi-CSV zip handling, like FIDC tab_X).
- Migration creating `cia_company`, `cia_filing`, `cia_account` (partitioned by `dt_refer` year), `cia_event` (DDL sketch below).
- **DoD:** tables exist; fetcher can download + unzip + enumerate members; no ingest yet.

## W6 — cia B0: cadastre + IPE  ·  branch `feat/cia-cadastre-ipe`  ·  medium  ·  needs W5  ·  **done**
- Field maps + ingest for `cia_aberta-cad` → `cia_company` and `ipe` → `cia_event`.
- **Implementation summary:**
  - `src/parsers/field_maps/cia_company.py` — CAD field map verified against live
    `cad_cia_aberta.csv` header. Maps `CD_CVM` (PK), `CNPJ_CIA`, `DENOM_SOCIAL`,
    `SETOR_ATIV`, `CATEG_REG` (as `segmento` — closest analog; no native segment
    column in CAD), `SIT`. `SIT_EMISSOR`, `CONTROLE_ACIONARIO`, contact fields,
    and auditor info fall through to `raw` JSONB.
  - `src/parsers/field_maps/cia_event.py` — IPE field map verified against live
    `ipe_cia_aberta_2024.zip`. Maps `Codigo_CVM`, `CNPJ_Companhia`,
    `Data_Referencia`, `Data_Entrega`, `Categoria`, `Tipo`, `Especie`,
    `Assunto`, `Protocolo_Entrega`, `Versao`, `Link_Download`. Unique key
    `(protocolo, versao)`. `cia_event` has no `raw` column — residuals are
    discarded by `ingest_cia_event` (`Nome_Companhia`, `Tipo_Apresentacao`
    are denormalised against `cia_company` and the IPE row itself).
  - `src/pipeline/ingest_cia.py` — `ingest_cia_company` (drops rows missing
    `cd_cvm`) and `ingest_cia_event` (drops rows missing `cd_cvm`, `protocolo`,
    or `versao`).
  - `src/pipeline/cvm_pipeline.py` — `CVMIngestor.ingest_cia_cad()` (once per
    run) and `CVMIngestor.ingest_cia_ipe(year)` (per year). `cia_aberta` added
    to `_ALL_ENTITIES`, `_ALL_TABLES`, `--entity` CLI help. Backfill scope
    iterates `_CIA_IPE_FIRST_YEAR=2010` → end_year. Daily update refreshes
    CAD and current-year IPE.
  - Tests: `tests/test_cia_field_maps.py` covers field-map projection,
    residual semantics, drop-row rules, upsert call shape, and a
    parametrised PK smoke test (15 tests, all passing).
- **DoD:** company dim populated; material-facts feed queryable; idempotent; null-rate checked.

## W7 — cia B1: ITR + DFP financials  ·  branch `feat/cia-financials`  ·  large  ·  needs W5  ·  **done**
- Parser iterating the ~19 zip members, tagging each row with `grupo` (BPA/BPP/DRE/…) + `escopo` (con/ind); normalize `VL_CONTA` by `ESCALA_MOEDA`; upsert latest `VERSAO`.
- Field map for the shared statement-CSV columns → `cia_account`; index rows → `cia_filing`.
- **Implementation summary:**
  - `src/parsers/field_maps/cia_account.py` — statement-CSV field map verified
    live against `dfp_cia_aberta_2023.zip`. Maps `CNPJ_CIA`, `CD_CVM`, `DT_REFER`,
    `VERSAO`, `ORDEM_EXERC`, `DT_INI_EXERC` (absent in BPA/BPP — tolerated),
    `DT_FIM_EXERC`, `CD_CONTA`, `DS_CONTA`, `VL_CONTA` (pre-scale), `ESCALA_MOEDA`,
    `ST_CONTA_FIXA`. `grupo`/`escopo`/`doc_type` are injected by ingest (from the
    `CIAMember` name / call arg), NOT read from the CSV; `GRUPO_DFP`/`MOEDA`/
    `DENOM_CIA` fall to `raw`. Conflict key matches `uq_cia_account`.
  - `src/parsers/field_maps/cia_filing.py` — summary-header field map
    (`ID_DOC`, `DT_RECEB`, `LINK_DOC` + cd_cvm/dt_refer/versao). No `raw` column;
    residual discarded. Conflict key matches `uq_cia_filing`.
  - `src/parsers/mapping.py` — new `cd_cvm` coerce type strips non-digits and
    leading zeros so the 6-digit-padded ITR/DFP code (`001023`) joins the
    unpadded CAD/IPE code (`1023`). `cia_company`/`cia_event` retrofitted to it.
  - `src/pipeline/ingest_cia.py` — `ingest_cia_filing(conn, summary_rows, doc_type)`
    and `ingest_cia_account(conn, members, doc_type)`: iterate account-data members,
    inject grupo/escopo/doc_type, scale `vl_conta` by ESCALA_MOEDA (`_MONEY_SCALE`:
    MIL→×1000, MILHÃO→×1e6, else ×1), stash residual in `raw`, drop rows missing
    `cd_cvm`/`cd_conta`/`dt_refer`; one upsert per member.
  - `src/pipeline/cvm_pipeline.py` — `CVMIngestor.ingest_cia_itr_dfp(doc_type, year)`
    fetches the multi-CSV zip via `CIAFetcher.fetch_zip_members_async(..., include_summary=True)`,
    routes summary→filing + members→account. `cia_filing`/`cia_account` added to
    `_ALL_TABLES`; backfill loads ITR+DFP for `years >= _CIA_ITR_DFP_FIRST_YEAR=2019`
    at low concurrency; daily_update refreshes current-year ITR+DFP.
  - Tests: `tests/test_cia_financials.py` — field-map projection (incl. BPA missing
    `DT_INI_EXERC`), cd_cvm zero-strip, ESCALA_MOEDA scaling, grupo/escopo/doc_type
    injection, drop-row rules, upsert call shape, residual→raw (28 tests).
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
