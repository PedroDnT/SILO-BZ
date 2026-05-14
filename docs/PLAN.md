# iliquid_nightly — Pipeline Status

_Living tracker. Update after each session. Deep technical reference: [`pipeline-plan.md`](pipeline-plan.md)._

---

## Priority Queue

| # | Task | Status |
|---|---|---|
| P0 | Commit `verify_pipeline.py` + `cvm_pipeline.py` | ✅ done |
| P1 | Create this file (`docs/PLAN.md`) | ✅ done |
| P2 | Apply `schema.sql` to live Supabase | ✅ done — RLS + public read enabled |
| P3 | Historical backfill (fidc → fii → securit → fip → fi) | 🔄 running — now driven through `/api/ingest/range` (P10) |
| P4 | Run `verify_pipeline.py` against live DB; confirm null rates below thresholds | ❌ blocked on P3 |
| P5 | MCP + skill integration (verify / backfill / schema-status skills) | ⏳ Supabase MCP now connected |
| P6 | Pytest fixtures for fidc_tranche / fidc_aging / securit_serie / securit_fluxo | ❌ pending |
| P7 | BACEN macro ingestion wired into backfill CLI | ❌ low urgency |
| P8 | FII sparse-table decision: keep merged or split into geral/ativo_passivo/complemento | ❌ defer until analytics |
| P9 | Add `cvm_fi_diario_2027` partition to schema.sql (due 2027-01-01) | ❌ calendar |
| P10 | Flask control plane (`app.py` + `src/api/`): partial-fill endpoints + error hooks | ✅ done (2026-05-14) |
| P11 | Smoke-test the remaining 13 empty tables via `/api/ingest` — find & fix schema bugs before P3 ranges | 🔄 in progress (1/14 done — fidc/tranche) |

---

## Table Status

_Reset: `cuducxhrtnzxxlmpwoaa` is a fresh Supabase project; schema applied but data needs full re-ingest. Status below reflects live `cvm_ingest_log` + `count(*)` as of 2026-05-14, not historical notes._

| Table | Entity | Live rows | Notes |
|---|---|---|---|
| `cvm_fi_diario` | FI | 0 | Needs smoke-test before range fills (huge daily file ~400k rows/month) |
| `cvm_fi_cda` | FI | 0 | Needs smoke-test |
| `cvm_fi_perfil` | FI | 0 | Needs smoke-test |
| `cvm_fidc_mensal` | FIDC | 0 | tab_IV NAV only — needs smoke-test |
| `cvm_fidc_tranche` | FIDC | **9,899** | ✅ 2025-03 smoke-tested clean after 2 schema widenings |
| `cvm_fidc_tranche_flows` | FIDC | 0 | Same ZIP as tranche — schema risk likely similar |
| `cvm_fidc_aging` | FIDC | 0 | tab_V/tab_VI delinquency buckets |
| `cvm_fiagro_mensal` | FIAGRO | 0 | Data from 2025-05 onward only |
| `cvm_fip_periodic` | FIP | 0 | Yearly doc_type — pick `inf_trimestral` 2024 |
| `cvm_fii_mensal` | FII | 0 | 3 doc_types: `mensal_geral`, `mensal_ativo_passivo`, `mensal_complemento` |
| `cvm_fii_periodic` | FII | 0 | 3 doc_types: `trimestral`, `anual`, `dfin` |
| `cvm_securit_mensal` | SECURIT | 0 | 3 instrument_types: `cra_mensal`, `cri_mensal`, `ots_mensal` |
| `cvm_securit_serie` | SECURIT | 0 | `*_classe` doc_types |
| `cvm_securit_fluxo` | SECURIT | 0 | `*_fluxo` doc_types |
| `cvm_securit_dfin` | SECURIT | 0 | `dfin_cra`, `dfin_cri` |
| `bacen_sgs` | BACEN | 0 | Out of scope for Flask plane (separate ingestor) |
| `bacen_ptax` | BACEN | 0 | Same |
| `bacen_expectativas` | BACEN | 0 | Same |
| `cvm_ingest_log` | Audit | 3 | All 3 entries are smoke-test runs for fidc/tranche 2025-03 |

---

## Backfill Commands (run after P2)

Two options — pick by appetite for granularity:

**A. One-shot CLI** (faster wall-clock, all-or-nothing per entity):

```bash
# Apply schema first (idempotent)
psql "$SUPABASE_DB_URL" -f src/store/schema.sql

# Backfill order: smaller/faster first, FI last
python -m src.pipeline.cvm_pipeline backfill --entity fidc --start 2019
python -m src.pipeline.cvm_pipeline backfill --entity fii --start 2019
python -m src.pipeline.cvm_pipeline backfill --entity securit --start 2021
python -m src.pipeline.cvm_pipeline backfill --entity fip --start 2010
python -m src.pipeline.cvm_pipeline backfill --entity fi --start 2019

# Verify
python scripts/verify_pipeline.py
```

**B. Flask control plane** (slower, but retryable per-slice with classified errors):

```bash
flask --app app run                                # local server :5000

# Fill one (entity, doc_type, year, month) at a time, watch progress:
curl -XPOST localhost:5000/api/ingest -H 'content-type: application/json' \
     -d '{"entity":"fidc","doc_type":"tranche","year":2024,"month":5}'
curl localhost:5000/api/jobs/<job_id>              # poll until done

# Or chain a year range (still sequential — same CVM rate limits):
curl -XPOST localhost:5000/api/ingest/range -H 'content-type: application/json' \
     -d '{"entity":"fidc","doc_type":"tranche","year_start":2019,"year_end":2023}'

curl -XPOST localhost:5000/api/verify              # quality-gate report (P4 input)
```

Use surface A to fill clean years; switch to B when slices start failing — the
hook output (`error.type`, `warnings[]`) tells you whether to retry, fix schema,
or just wait for CVM to publish.

---

## Quality Gates (P4)

| Field | Table | Max null% |
|---|---|---|
| `vl_patrim_liq` | `cvm_fidc_mensal` | 1% |
| `vl_rentab_mes` | `cvm_fidc_tranche` | 5% |
| `vl_total_inad` | `cvm_fidc_aging` | 5% |
| `vl_patrim_liq` (complemento) | `cvm_fii_mensal` | 1% |
| `pct_dividend_yield_mes` | `cvm_fii_mensal` | 5% |
| `situacao` | `cvm_securit_serie` | 1% |

---

## Schema fixes from partial-fill smoke testing (2026-05-14)

Driving the first slice (`fidc/tranche 2025-03`) through `/api/ingest` surfaced three bugs the
all-or-nothing CLI had been masking. Patterns to watch for in other tables:

| # | Where | Root cause | Fix |
|---|---|---|---|
| 1 | `cvm_fidc_tranche.qt_cota` `NUMERIC(20,8)` | CVM `TAB_X_QT_COTA` reaches **6.9 × 10¹³** (fund of funds quoting in micro-units) | Migration `widen_cvm_fidc_tranche_numeric_columns` → `NUMERIC(28,8)` |
| 2 | `cvm_fidc_tranche.vl_rentab_mes` / `pr_desemp_*` `NUMERIC(10,6)` | Raw CVM percentage fields contain garbage like `164606333.00` | Migration `widen_cvm_fidc_tranche_pct_columns` → `NUMERIC(20,6)` (validate downstream) |
| 3 | `cvm_pipeline._log_finish` | Used PostgREST upsert; NOT NULL on `entity`/`doc_type` fails the INSERT path *before* `ON CONFLICT` routes to UPDATE | Switched to true `UPDATE ... WHERE run_id = ...` |
| 4 | `hooks.fetch_audit_warning` | Filtered by API alias `doc_type` (`tranche`), pipeline logs the CVM-native `mensal_tab_x2` | Filter on `(entity, period)` only; pick the most recent error row |

**Sizing heuristic for the next 13 tables:** any `NUMERIC(20,8)` or `NUMERIC(10,6)` is a likely
overflow candidate when the column stores raw CVM values (quota counts, percentages, AUM).
Widen to `NUMERIC(28,8)` and `NUMERIC(20,6)` respectively when the smoke-test surfaces 22003.

---

## Smoke-test plan for remaining empty tables

Goal: fire one representative slice per (entity, doc_type), find any schema/code bugs, fix
them once, then trigger the full range. Each slice picks **the same well-published period
(2025-03)** so we can correlate across tables.

| # | Slice | API call body | Watch for |
|---|---|---|---|
| 1 | ✅ fidc/tranche 2025-03 | `{"entity":"fidc","doc_type":"tranche","year":2025,"month":3}` | done |
| 2 | fidc/mensal 2025-03 | `{"entity":"fidc","doc_type":"mensal","year":2025,"month":3}` | NUMERIC overflow on `vl_patrim_liq`, `vl_inadimpl` |
| 3 | fidc/tranche_flows 2025-03 | `{"entity":"fidc","doc_type":"tranche_flows","year":2025,"month":3}` | Same overflow risk as tranche (paired CVM ZIP) |
| 4 | fidc/aging 2025-03 | `{"entity":"fidc","doc_type":"aging","year":2025,"month":3}` | Many `vl_*` columns from tab_V/tab_VI |
| 5 | fi/diario 2025-03 | `{"entity":"fi","doc_type":"diario","year":2025,"month":3}` | **~400k rows** — confirms supabase upsert throughput |
| 6 | fi/cda 2025-03 | `{"entity":"fi","doc_type":"cda","year":2025,"month":3}` | Portfolio composition — JSON `raw` size |
| 7 | fi/perfil 2025-03 | `{"entity":"fi","doc_type":"perfil","year":2025,"month":3}` | Smaller, investor profile counts |
| 8 | fip/inf_trimestral 2024 | `{"entity":"fip","doc_type":"inf_trimestral","year":2024}` | Yearly call — no `month` field |
| 9 | fii/mensal_complemento 2024 | `{"entity":"fii","doc_type":"mensal_complemento","year":2024}` | Dividend yield columns are the known gap |
| 10 | fii/mensal_geral 2024 | `{"entity":"fii","doc_type":"mensal_geral","year":2024}` | NAV column overflow likely |
| 11 | fii/mensal_ativo_passivo 2024 | `{"entity":"fii","doc_type":"mensal_ativo_passivo","year":2024}` | Asset/liability balance lines |
| 12 | fii/dfin 2024 | `{"entity":"fii","doc_type":"dfin","year":2024}` | Financial statements |
| 13 | securit/cra_mensal 2024 | `{"entity":"securit","doc_type":"cra_mensal","year":2024}` | CRA emissions |
| 14 | securit/cra_classe 2024 | `{"entity":"securit","doc_type":"cra_classe","year":2024}` | Series-level rentabilidade — overflow likely |
| 15 | securit/cra_fluxo 2024 | `{"entity":"securit","doc_type":"cra_fluxo","year":2024}` | Cash flow columns |
| 16 | securit/dfin_cra 2024 | `{"entity":"securit","doc_type":"dfin_cra","year":2024}` | Financial statements |
| 17 | fiagro/mensal 2025-06 | `{"entity":"fiagro","doc_type":"mensal","year":2025,"month":6}` | Data only from 2025-05+ — picking June to be safe |

After each row, if status=done with rows>0, move on. If failed or warnings, fix and retry.
After all 17 pass, trigger range fills (P3) per the section "Backfill Commands (run after P2)" → Surface B.

The remaining `securit/cri_*`, `securit/ots_*`, `securit/dfin_cri` instrument variants share
schema with their CRA counterparts — smoke-testing all three CRA flavours is sufficient.

---

## Not In Scope

- GitHub Actions cron — manual skill execution preferred for now
- Public REST/GraphQL API — consumers query Supabase directly
- B3 market data — no validated endpoint yet
- ANBIMA cross-validation — open data links are 404
- Docker / Alembic — Supabase is the single target
