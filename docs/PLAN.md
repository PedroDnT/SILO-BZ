# iliquid_nightly — Pipeline Status

_Living tracker. Update after each session. Deep technical reference: [`pipeline-plan.md`](pipeline-plan.md)._

---

## Priority Queue

| # | Task | Status |
|---|---|---|
| P0 | Commit `verify_pipeline.py` + `cvm_pipeline.py` | ✅ done |
| P1 | Create this file (`docs/PLAN.md`) | ✅ done |
| P2 | Apply `schema.sql` to live Supabase | ✅ done — RLS + public read enabled |
| P3 | Historical backfill (fidc → fii → securit → fip → fi) | 🔄 running |
| P4 | Run `verify_pipeline.py` against live DB; confirm null rates below thresholds | ❌ blocked on P3 |
| P5 | MCP + skill integration (verify / backfill / schema-status skills) | ⏳ Supabase MCP now connected |
| P6 | Pytest fixtures for fidc_tranche / fidc_aging / securit_serie / securit_fluxo | ❌ pending |
| P7 | BACEN macro ingestion wired into backfill CLI | ❌ low urgency |
| P8 | FII sparse-table decision: keep merged or split into geral/ativo_passivo/complemento | ❌ defer until analytics |
| P9 | Add `cvm_fi_diario_2027` partition to schema.sql (due 2027-01-01) | ❌ calendar |

---

## Table Status

| Table | Entity | Populated | Notes |
|---|---|---|---|
| `cvm_fi_diario` | FI | ✅ | — |
| `cvm_fi_cda` | FI | ✅ | — |
| `cvm_fi_perfil` | FI | ✅ | — |
| `cvm_fidc_mensal` | FIDC | ✅ | tab_IV NAV only |
| `cvm_fidc_tranche` | FIDC | ❌ | needs backfill |
| `cvm_fidc_tranche_flows` | FIDC | ❌ | needs backfill |
| `cvm_fidc_aging` | FIDC | ❌ | needs backfill |
| `cvm_fiagro_mensal` | FIAGRO | ⏳ | data from 2025-05 |
| `cvm_fip_periodic` | FIP | ✅ | — |
| `cvm_fii_mensal` | FII | ✅ geral/ativo_passivo | complemento yield columns need backfill |
| `cvm_fii_periodic` | FII | ✅ | — |
| `cvm_securit_mensal` | SECURIT | ✅ | pre-fix rows may have field bugs; truncate+re-ingest if null rates high |
| `cvm_securit_serie` | SECURIT | ❌ | needs backfill |
| `cvm_securit_fluxo` | SECURIT | ❌ | needs backfill |
| `cvm_securit_dfin` | SECURIT | ❌ | empty |
| `bacen_sgs` | BACEN | ✅ | — |
| `bacen_ptax` | BACEN | ✅ | — |
| `bacen_expectativas` | BACEN | ✅ | — |
| `cvm_ingest_log` | Audit | ✅ | active |

---

## Backfill Commands (run after P2)

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

## Not In Scope

- GitHub Actions cron — manual skill execution preferred for now
- Public REST/GraphQL API — consumers query Supabase directly
- B3 market data — no validated endpoint yet
- ANBIMA cross-validation — open data links are 404
- Docker / Alembic — Supabase is the single target
