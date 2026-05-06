# Agent Steering Guide — iliquid_nightly

How to resume work on this codebase with an AI coding agent (Claude Code or equivalent).

---

## Before you start a session

Point the agent at the two authoritative files:

```
Read TODO and docs/pipeline-plan.md and tell me where we are.
```

The agent will read the TODO (5-phase plan with checkboxes) and the full plan doc, then
give you a status summary. From there you pick a phase and say "proceed with Phase N".

---

## Phase-specific kickoff prompts

### Phase 0 — Bug fixes (1h)

```
Work on Phase 0 from TODO. Fix the SECURIT csv_name_pattern bug in src/fetchers/cvm_config.py,
then add the missing FII complemento fields to src/pipeline/cvm_pipeline.py and src/store/schema.sql.
Run tests after each change. Check off each TODO item when done.
```

Key files the agent needs:
- [src/fetchers/cvm_config.py](../src/fetchers/cvm_config.py) — change CRA/CRI/OTS patterns
- [src/pipeline/cvm_pipeline.py](../src/pipeline/cvm_pipeline.py) — add FII complemento field mappings
- [src/store/schema.sql](../src/store/schema.sql) — ADD COLUMN for new FII fields

Expected outcome: SECURIT pattern is explicit (not fallback), FII complemento table has 8 new columns.

### Phase 1 — FIDC tranche tables (half day)

```
Work on Phase 1 from TODO. Read docs/pipeline-plan.md section on FIDC ZIP structure (17 CSVs)
and the tranche accountability rules. Create the three new tables in schema.sql, add an
ingest_fidc_tranches() method to CVMIngestor, and wire it into daily_update and backfill.
```

Key context to give the agent:
- FIDC ZIP contains 17 CSVs. The tab_X_2 CSV has `TAB_X_CLASSE_SERIE` (tranche identifier),
  `TAB_X_A_VL_COTA`, `TAB_X_A_CAPTC_MES`, `TAB_X_A_RESG_MES`.
- tab_X_6 has `TAB_X_PR_DESEMP_ESPERADO` and `TAB_X_PR_DESEMP_REAL` (expected vs actual performance).
- tab_VI has delinquency aging bands.
- The new csv_name_pattern will be `inf_mensal_fidc_tab_X_2_{year}{month:02d}.csv` etc.

### Phase 2 — SECURIT series + cash flow (half day)

```
Work on Phase 2 from TODO. Read docs/pipeline-plan.md section on SECURIT ZIP structure (8 CSVs).
Create cvm_securit_serie and cvm_securit_fluxo tables in schema.sql, add ingest methods to
CVMIngestor. The source CSVs are inf_mensal_cra_classe_{year}.csv and
inf_mensal_cra_fluxo_caixa_{year}.csv.
```

Key context:
- `classe` CSV columns: `Codigo_CETIP`, `Situacao` (Adimplente/Inadimplente), `Classificacao_Risco`,
  `Valor_Total_Integralizado`, `Taxa_Juros` (free text, e.g. "CDI+2.0%").
- `fluxo_caixa` columns: `Pagamentos_Classe_Senior`, `Pagamentos_Classe_Subordinada_Mezanino`,
  `Pagamentos_Classe_Subordinada_Junior`, `Creditos_Cedidos_Carteira`.
- Same pattern applies for CRI and OTS ZIPs.

### Phase 3 — Supabase backfill

```
Work on Phase 3 from TODO. Apply the schema.sql changes against Supabase, then run backfills
for FIDC (2019 onward) and FII complemento (2019 onward). After re-ingesting SECURIT,
audit for duplicate rows using analysis_queries.sql query 9. Then run scripts/verify_pipeline.py
and confirm < 5% null on all key fields.
```

Commands to run:
```bash
psql "$SUPABASE_DB_URL" -f src/store/schema.sql
python -m src.pipeline.cvm_pipeline backfill --entity fidc --start 2019
python -m src.pipeline.cvm_pipeline backfill --entity fii --start 2019
python scripts/verify_pipeline.py
```

### Phase 4 — BACEN macro context

```
Work on Phase 4 from TODO. Verify that bacen_sgs is fetching SELIC (code 11), CDI (12),
IPCA (433), IGP-M (189). Then implement accountability rule R10 from docs/pipeline-plan.md
which flags FIDC delinquency anomalies relative to CDI spread.
```

---

## Verification after any phase

```
Run the local verification suite and tell me which queries PASS vs WARN vs EMPTY.
```

```bash
python scripts/seed_local_db.py --skip-fi   # ~2 min seed
python scripts/run_analysis_local.py         # 11 queries with verdicts
```

For Supabase state:
```bash
python scripts/verify_pipeline.py
```

---

## If the agent loses context mid-session

Give it these three anchors in order:

1. **Plan**: `Read TODO` — gives the 5-phase checklist with current state
2. **Detail**: `Read docs/pipeline-plan.md` — full data inventory, accountability rules, SQL
3. **Bugs**: `Read .planning/codebase/CONCERNS.md` — known bugs and fragile areas

---

## What the agent should NOT need to re-derive

These are already documented — just tell the agent to read the file instead of re-exploring:

| Question | File |
|---|---|
| Which CSVs are inside a FIDC ZIP? | `docs/pipeline-plan.md` §1 FIDC |
| Which CSVs are inside a SECURIT ZIP? | `docs/pipeline-plan.md` §1 SECURIT |
| What columns does tab_X have? | `docs/pipeline-plan.md` §1 FIDC |
| What accountability rules do we want? | `docs/pipeline-plan.md` §2 |
| What tables are planned? | `.planning/codebase/INTEGRATIONS.md` |
| What bugs are known? | `.planning/codebase/CONCERNS.md` Known Bugs |
| Which Supabase data is stale/needs backfill? | `docs/pipeline-fixes-and-verification.md` §4 |

---

## Signals that a session went well

- TODO checkboxes got ticked off
- Tests pass (`PYTHONPATH=. pytest tests/ -v`)
- `run_analysis_local.py` shows PASS on the newly added entity
- `verify_pipeline.py` shows the target null rate < 5% on the fixed field
