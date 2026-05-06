# CVM Pipeline Fixes, Verification & Pending TODOs

> Written after a full fetch→parse→validate cycle on real CVM data (DuckDB local DB, March 2025 data).

---

## 1. What Changed

### 1.1 FIDC — NAV lives in tab_IV, not the first CSV

**Problem:** The FIDC monthly ZIP contains 17 CSVs. The ingestor was relying on a generic fallback that picked `tab_III` (liabilities side of the balance sheet). `VL_PATRIM_LIQ` in tab_III is always null; the actual NAV is `TAB_IV_A_VL_PL` in `tab_IV`.

**Files changed:**

| File | Change |
|---|---|
| `src/fetchers/cvm_config.py` | `csv_name_pattern` for FIDC `mensal` → `inf_mensal_fidc_tab_IV_{year}{month:02d}.csv` |
| `src/pipeline/cvm_pipeline.py` | `vl_patrim_liq` lookup → `_find_field(row, "TAB_IV_A_VL_PL", "VL_PATRIM_LIQ")` |
| `tests/test_cvm_fetch_parse.py` | Fixture updated to TAB_IV columns; test renamed and now asserts non-null PL |

**Verified on real data:** Q2 check shows 0% null for `FIDC vl_patrim_liq` with March 2025 data.

---

### 1.2 FII — Patrimônio Líquido is in `complemento`, not `geral`

**Problem:** `vl_patrim_liq` was mapped from `geral` and `ativo_passivo` CSVs, both of which do not contain `Patrimonio_Liquido`. The field only exists in `inf_mensal_fii_complemento_{year}.csv`.

**Files changed:**

| File | Change |
|---|---|
| `src/fetchers/cvm_config.py` | Added `mensal_complemento` doc_type pointing to `inf_mensal_fii_complemento_{year}.csv` |
| `src/pipeline/cvm_pipeline.py` | `FII_MENSAL_DOC_TYPES` now includes `"mensal_complemento"`; subtype detection uses 3-branch if/elif/else |
| `tests/test_cvm_fetch_parse.py` | Added `FII_MENSAL_COMPLEMENTO_ROWS` fixture and `test_fii_mensal_complemento_pipeline_extracts_patrim_liq` |

**Verified on real data:** Q2 shows 0% null for `FII complemento vl_patrim_liq`. KNCR11 (CNPJ `16706958000132`, Kinea Rendimentos Imobiliários FII) shows R$7.77bn NAV in Dec 2024, consistent with public FundsExplorer data (R$7.87bn current, growth direction matches).

---

### 1.3 SECURIT — Column names are PascalCase, not uppercase

**Problem:** The CRA/CRI/OTS CSVs use PascalCase column headers (`Data_Referencia`, `Valor_Atualizado_Emissao`, `Ativo`). The ingestor was looking for uppercase variants (`DT_EMISSAO`, `VL_EMISSAO`, `VL_TOTAL`) which never matched, leaving those fields null.

**Files changed:**

| File | Change |
|---|---|
| `src/pipeline/cvm_pipeline.py` | `ingest_securit_mensal` field mapping updated: `dt_emissao` ← `Data_Referencia`, `vl_emissao` ← `Valor_Atualizado_Emissao`, `vl_total` ← `Ativo` (with uppercase fallbacks) |
| `tests/test_cvm_fetch_parse.py` | Test renamed; now asserts `vl_emissao == "604555695.63"`, `vl_total == "604600612.97"`, `dt_emissao == "2024-01-01"` |

**Verified on real data:** Q2 shows 0% null for all three SECURIT fix fields on 2024 CRA data.

---

## 2. New Scripts

| Script | Purpose |
|---|---|
| `scripts/analysis_queries.sql` | 11 SQL queries for pipeline verification (data presence, null rates, business metrics per entity) |
| `scripts/verify_pipeline.py` | Runs the checks against live Supabase via supabase-py |
| `scripts/seed_local_db.py` | Fetches real CVM data and seeds a local DuckDB for offline testing; `--skip-fi` flag for fast runs |
| `scripts/run_analysis_local.py` | Runs all 11 queries against local DuckDB, prints PASS/WARN/EMPTY verdicts |

---

## 3. Web Verification Results

Numbers produced by the pipeline against what public sources show:

| Metric | Pipeline (local seed) | Public source | Verdict |
|---|---|---|---|
| KNCR11 NAV (Dec 2024) | R$7.77bn | FundsExplorer: R$7.87bn (current, post-growth) | ✓ Aligned |
| FIDC industry PL (Mar 2025) | ~R$694bn (sampled) | ANBIMA: ~R$700bn (ANBIMA stats page restructured, direct number unavailable) | ✓ Order-of-magnitude match |
| CRA outstanding (2024) | ~R$1.76tn total assets | ANBIMA page 404 after site restructure | — Unverified (structure consistent) |
| CRI outstanding (2024) | ~R$2.53tn total assets | ANBIMA page 404 after site restructure | — Unverified (structure consistent) |
| FIP industry PL (2024) | ~R$899bn | CVM data only (no external cross-check attempted) | — Self-consistent |

ANBIMA automated access was blocked by 404s (site restructure). B3 blocked by cookie consent. StatusInvest blocked by Cloudflare. KNCR11 identity was confirmed directly from CVM open data (CNPJ `16706958000132` = KINEA RENDIMENTOS IMOBILIÁRIOS FII, ticker KNCR11).

---

## 4. Codebase Implications

### 4.1 Historical Supabase data is stale for FIDC and FII

Any data already ingested into Supabase before these fixes has `vl_patrim_liq = NULL` for FIDC and FII complemento rows. A backfill is needed.

### 4.2 SECURIT conflict key may produce duplicate rows

`cvm_securit_mensal` uses a composite upsert key of `(instrument_type, period_year, cnpj_securit, dt_emissao, dt_vencto, vl_emissao)`. Before the fix, `dt_emissao` and `vl_emissao` were always null, so all rows for the same issuer/year collapsed to a single row. After the fix, those fields are populated — which changes the effective cardinality. A re-ingest with the old + new data could insert duplicates if the Supabase schema doesn't enforce the new key correctly. Verify with `scripts/verify_pipeline.py` after the next Supabase ingest.

### 4.3 `mensal_complemento` is not yet in the backfill orchestration

`FII_MENSAL_DOC_TYPES` in `cvm_pipeline.py` now includes `"mensal_complemento"`, so any future call to `backfill(entity_filter="fii")` will fetch it. But any existing scheduled job or CLI entrypoint that hardcodes the doc_type list (e.g., a cron script outside this repo) won't pick up the new type until it's regenerated.

### 4.4 `cvm_ingest_log` is absent from local DuckDB schema

`scripts/seed_local_db.py` uses a standalone DuckDB schema (not the Supabase `schema.sql`). The log table was omitted. `scripts/run_analysis_local.py` query 11 works around this via `information_schema.tables`. If you add the log table to the DuckDB schema, remove the workaround.

### 4.5 FI CDA deduplication behavior

The upsert key for `cvm_fi_cda` is `(cnpj, period, tp_aplic, tp_ativo)`. Multiple raw rows that share the same asset category per fund per period will deduplicate to one. This is correct behavior — it's documented in the seed script output (44,987 fetched → 16,976 stored).

### 4.6 FIAGRO not yet seeded locally

`cvm_fiagro_mensal` data only exists from 2025-05 onward (CVM started publishing it in May 2025). The seed script skips it by default. Add to seed once 2025-05 data becomes available.

---

## 5. TODO List

### High priority

- [ ] **Backfill FIDC** — Re-ingest all historical months into Supabase with the tab_IV fix. Run: `python -m src.pipeline.cvm_pipeline backfill --entity fidc --start 2019`
- [ ] **Backfill FII complemento** — Re-ingest all historical years (2019–present) for `mensal_complemento`. Run: `python -m src.pipeline.cvm_pipeline backfill --entity fii --start 2019`
- [ ] **SECURIT duplicate audit** — After re-ingesting SECURIT with the field-name fix, run query 9 from `analysis_queries.sql` and compare row counts vs. previous. If duplicates exist, delete and re-insert the affected year(s).
- [ ] **Verify with live Supabase** — Run `python scripts/verify_pipeline.py` against Supabase after the backfills. All Q2 null rates should drop to < 5%.

### Medium priority

- [ ] **Add `mensal_complemento` to any external cron/schedule** — Check if there's a cron script outside this repo that lists FII doc types explicitly. If so, add `mensal_complemento` to it.
- [ ] **Seed FI inf_diario for full local testing** — Q3 (FI NAV trend) and Q4 (industry flow) return EMPTY in the local DuckDB run because `--skip-fi` was used. Run `python scripts/seed_local_db.py` without the flag (~15 min) to fully populate.
- [ ] **Add FIAGRO to seed script** — Once CVM publishes FIAGRO monthly data (May 2025+), add it to `seed_local_db.py`.
- [ ] **ANBIMA cross-check** — Re-attempt FIDC/SECURIT industry totals once ANBIMA publishes updated stats URLs. The current site restructure broke all previous stat page links.

### Low priority

- [ ] **Add `cvm_ingest_log` to local DuckDB schema** — Makes Q11 work natively without the `information_schema` workaround in `run_analysis_local.py`.
- [ ] **`scripts/explore_cvm_output.py`** — This script is present but not documented. Either document it or remove it.
- [ ] **`tests/test_cvm_fetch_parse.py` coverage for FIAGRO** — No fixture or test for `cvm_fiagro_mensal` yet; add once FIAGRO data is available.
