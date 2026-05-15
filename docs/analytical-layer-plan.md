# Analytical layer for cross-entity / cross-time queries + doc consolidation

## Context

P11 smoke-tests landed clean and P3 range fills are queued. Before pulling the
trigger on multi-year backfill, we need to make sure the **data model can
answer the questions we actually want to ask** — both today's use cases and
plausible future ones — without forcing every analyst to write 60-line CTEs
with NULL-safe joins, manual date-grain alignment, and reinvented benchmark
math each time.

The user's stated use cases:

1. **Transversal** — compare a metric across all funds for one period (e.g. FII variance for 2024-03)
2. **Horizontal** — same metric across many years (e.g. FIDC delinquency 2019-2024)
3. **Cross-entity** (future) — FII vs FIAGRO time series
4. **Benchmarking** — fund returns vs BACEN SGS series (SELIC, CDI, IPCA)

Today the raw landing tables ([src/store/schema.sql](src/store/schema.sql))
support (1) and (2) with hand-written SQL but have **no analytical layer at all**
(no views, no matviews, no registry, no benchmark joins). The raw schema is
fine — what's missing is a **semantic layer on top** that aligns column names,
normalizes time grains, and surfaces ready-made answers.

This plan also folds in the user's parallel ask: **consolidate the
documentation**, keeping only files we actively update.

**Timing**: design now, **implement after P3** so we have multi-year data to
validate the views against. No SQL ships from this plan beyond the design itself.

---

## Part 1 — Domain split: funds vs securities

The data has **two distinct domains** that share only macro context:

| Domain | Members | Identifier | Key columns | Time grain |
|---|---|---|---|---|
| **Funds** | FI, FIDC, FIP, FIAGRO, FII | `cnpj` (14 chars) | NAV (`vl_patrim_liq`), quota price (`vl_quota`), quotaholder count (`nr_cotst`), return, delinquency | Daily (FI) / Monthly (others) |
| **Securities** | CRA, CRI, OTS | `cnpj_securit` + `codigo_identificacao` / `codigo_isin` / `codigo_cetip` | Face value, coupon (`taxa_juros`), maturity, situação (Adimplente / Inadimplente / Liquidado), cash flows | Per-event / Daily / Yearly |

These are different financial concepts (open-end investment vehicles vs
issued debt certificates) and need separate dimension and fact tables. The
analytical layer joins them only at the cross-instrument view layer (L5)
where it makes sense (e.g., CRA yield curve vs FIDC tranche yields).

## Part 2 — Query catalog (what we'll be able to ask)

Ten categories the analytical layer should support out of the box. Categories
are tagged by domain: **(F)** fund-only, **(S)** security-only, **(X)** cross-domain.

| # | Category | Domain | Example question | Inputs |
|---|---|---|---|---|
| A | Industry-level totals | F | Total fund-industry AUM today? Net flows YoY? | All `cvm_*_mensal` + `cvm_fi_diario` aggregates |
| B | Per-entity aggregates | F | FIDC sector delinquency rate over 5 years? Median FII dividend yield by month? | `cvm_fidc_mensal`, `cvm_fii_mensal`, `cvm_fidc_aging` |
| C | Per-fund time series | F | NAV trajectory for fund X over 36 months | Single fund table |
| D | Cross-fund peer ranking | F | Top 10 FIIs by yield this quarter; which deciles fund X belongs to | `cvm_fii_mensal`, window functions |
| E | Cross-entity (fund) | F | FII vs FIAGRO median yield over time | UNION ALL across fund monthly tables |
| F | Tranche-level (FIDC) | F | Sênior vs Subordinada return spread; subordination ratio trend | `cvm_fidc_tranche` + `cvm_fidc_mensal` |
| G | Aging / delinquency dynamics | F | Aging bucket migration; 90+ day rate cohort curves | `cvm_fidc_aging` + `cvm_fidc_mensal` |
| H | Benchmark / macro overlay | F, S | Fund return vs CDI spread; real return (return − IPCA); CRA yield vs SELIC; FX exposure | All facts + `bacen_sgs` + `bacen_ptax` |
| I | New issuance & maturity profile (securities) | S | CRA emissions volume by year; CRI maturity ladder; delinquency rate of subordinada series | `cvm_securit_mensal`, `cvm_securit_serie`, `cvm_securit_fluxo` |
| J | **Cross-domain** | X | CRA secondary-market yield vs FIDC subordinada tranche return; FII dividend yield vs IPCA + spread | `fact_security_monthly` + `fact_fund_monthly` + `fact_bacen_monthly` |
| K | Data quality / coverage | F, S | Reporting coverage per period; zombie detection (no recent reports); audit gaps | All tables + `cvm_ingest_log` |

All eleven categories answerable with at most a single JOIN to a fact view.

---

## Part 3 — Schema design (5 layers, all additive)

Zero changes to raw landing tables. Every new object is a **view or
materialized view** prefixed `dim_` / `fact_` / `vw_`. The fund and security
domains stay separate through L1 and L2; they only mix at L5.

### L1 — Dimension tables

**`dim_fund`** — registry of fund CNPJs (FI / FIDC / FIP / FIAGRO / FII only):

```sql
CREATE VIEW dim_fund AS
SELECT cnpj, 'fi'     AS entity_type, MIN(dt_comptc) AS first_period, MAX(dt_comptc) AS last_period, COUNT(*) AS n_reports FROM cvm_fi_diario  GROUP BY cnpj
UNION ALL
SELECT cnpj, 'fidc'   AS entity_type, MIN(period)    AS first_period, MAX(period)    AS last_period, COUNT(*) AS n_reports FROM cvm_fidc_mensal GROUP BY cnpj
UNION ALL
SELECT cnpj, 'fiagro' AS entity_type, MIN(period),    MAX(period),    COUNT(*) FROM cvm_fiagro_mensal GROUP BY cnpj
UNION ALL
SELECT cnpj, 'fii'    AS entity_type, MIN(period),    MAX(period),    COUNT(*) FROM cvm_fii_mensal    GROUP BY cnpj
UNION ALL
SELECT cnpj, 'fip'    AS entity_type, make_date(MIN(period_year),1,1), make_date(MAX(period_year),12,31), COUNT(*) FROM cvm_fip_periodic GROUP BY cnpj
;
```

Columns: `cnpj`, `entity_type`, `first_period`, `last_period`, `n_reports`.

**`dim_security`** — registry of securitized debt instruments (CRA / CRI / OTS):

```sql
CREATE VIEW dim_security AS
SELECT
  cnpj_securit, codigo_identificacao, codigo_isin, codigo_cetip,
  instrument_type,                           -- 'cra' | 'cri' | 'ots'
  numero_serie,
  MIN(data_referencia) AS first_seen,
  MAX(data_referencia) AS last_seen,
  -- latest known static fields
  MAX(data_vencimento)  AS data_vencimento,
  MAX(taxa_juros)       AS taxa_juros_latest,
  MAX(situacao)         AS situacao_latest
FROM cvm_securit_serie
GROUP BY 1,2,3,4,5,6;
```

**Why views, not matviews**: small (<1M rows even at full backfill); cheap to
recompute; always fresh.

### L2 — Unified monthly facts

**`fact_fund_monthly`** — one row per `(cnpj, period, entity_type)` with
renamed-to-be-consistent columns. Aggregates `cvm_fi_diario` daily → monthly
(last `dt_comptc` per cnpj × month). Unified columns (NULLs where source
doesn't ship the metric): `vl_patrim_liq`, `vl_inadimpl`, `vl_quota`,
`pct_yield_mes`, `vl_rentab_mes`, `nr_cotst`, `captc_mes`, `resg_mes`,
`vl_ativo`.

```sql
CREATE MATERIALIZED VIEW fact_fund_monthly AS
SELECT cnpj, date_trunc('month', dt_comptc)::date AS period, 'fi' AS entity_type,
       LAST_VALUE(vl_patrim_liq) OVER w AS vl_patrim_liq, ...
FROM cvm_fi_diario WINDOW w AS ...
UNION ALL
SELECT cnpj, period, 'fidc', vl_patrim_liq, vl_inadimpl, NULL, ... FROM cvm_fidc_mensal
UNION ALL
-- one branch per fund monthly table
;
CREATE UNIQUE INDEX ix_fact_fund_monthly_pk ON fact_fund_monthly (cnpj, period, entity_type);
CREATE INDEX ix_fact_fund_monthly_period ON fact_fund_monthly (period);
```

**`fact_security_monthly`** — one row per `(cnpj_securit, codigo_identificacao,
period)`. Sources: `cvm_securit_serie` (last status per month) + `cvm_securit_fluxo`
(cash flow aggregates per month).

```sql
CREATE MATERIALIZED VIEW fact_security_monthly AS
SELECT
  s.cnpj_securit, s.codigo_identificacao, s.instrument_type,
  date_trunc('month', s.data_referencia)::date AS period,
  s.situacao, s.classificacao_risco_atual,
  s.valor_certificados, s.rendimentos, s.amortizacoes, s.rentabilidade,
  s.indice_subordinacao_minimo,
  f.recebimentos_direitos_creditorios,
  f.pagamentos_classe_senior,
  f.pagamentos_mezanino,
  f.pagamentos_subordinada
FROM cvm_securit_serie s
LEFT JOIN cvm_securit_fluxo f
  ON f.cnpj_securit = s.cnpj_securit
 AND f.codigo_identificacao = s.codigo_identificacao
 AND date_trunc('month', f.data_referencia) = date_trunc('month', s.data_referencia)
;
CREATE UNIQUE INDEX ix_fact_security_monthly_pk
  ON fact_security_monthly (cnpj_securit, codigo_identificacao, period);
```

**Why matviews**: FI daily→monthly aggregation is the expensive operation
(28M rows → ~1M monthly rows); the security join across `serie` and `fluxo`
benefits from a single pre-built shape. Both refresh in <2 min.

### L3 — BACEN monthly grain: `fact_bacen_monthly`

Daily `bacen_sgs` rolled up per series. Series-specific aggregation:

| Series | Code | Aggregation |
|---|---|---|
| SELIC daily | 11 | `prod(1 + value/100)` − 1 over month (cumulative) |
| CDI daily | 12 | Same as SELIC |
| IPCA monthly | 433 | Last value of month (already monthly upstream) |
| IGP-M monthly | 189 | Last value of month |
| USD/BRL EOM | `bacen_ptax` | Last business-day rate of month |

```sql
CREATE MATERIALIZED VIEW fact_bacen_monthly AS
SELECT date_trunc('month', reference_date)::date AS period, series_code,
       CASE
         WHEN series_code IN (11, 12) THEN ... -- cumulative product
         ELSE last_value(value) OVER (PARTITION BY ...)
       END AS value
FROM bacen_sgs ...;
```

### L4 — Benchmark joins (pure views)

**`vw_fund_vs_benchmark`** — `fact_fund_monthly` ⋈ `fact_bacen_monthly`:
```sql
CREATE VIEW vw_fund_vs_benchmark AS
SELECT f.*,
       b_cdi.value   AS cdi_mes,
       b_selic.value AS selic_mes,
       b_ipca.value  AS ipca_mes,
       (f.vl_rentab_mes - b_cdi.value)  AS spread_vs_cdi,
       (f.vl_rentab_mes - b_ipca.value) AS real_return_ipca
FROM fact_fund_monthly f
LEFT JOIN fact_bacen_monthly b_cdi   ON b_cdi.period   = f.period AND b_cdi.series_code   = 12
LEFT JOIN fact_bacen_monthly b_selic ON b_selic.period = f.period AND b_selic.series_code = 11
LEFT JOIN fact_bacen_monthly b_ipca  ON b_ipca.period  = f.period AND b_ipca.series_code  = 433;
```

**`vw_security_vs_benchmark`** — same shape for securities. Joins
`fact_security_monthly` to CDI / SELIC / IPCA to compute `spread_vs_cdi`,
`real_return_ipca` per CRA/CRI/OTS series.

### L5 — Cross-domain and cross-entity views

Thin views, one per question. The cross-domain views are the only place fund
and security data mix.

| View | Type | Purpose |
|---|---|---|
| `vw_fii_vs_fiagro` | Fund×Fund | UNION ALL of FII + FIAGRO from `fact_fund_monthly` for time-series comparison |
| `vw_fidc_tranche_detail` | Fund-only | `cvm_fidc_tranche` + `cvm_fidc_mensal` join with subordination ratio |
| `vw_securit_emission_trend` | Security-only | Issuance volume + new-series count per month per `instrument_type` |
| `vw_securit_yield_curve` | Security-only | `dim_security.data_vencimento − period` → maturity bucket × yield |
| `vw_fund_security_yield` | **Cross-domain** | FII monthly dividend yield vs CRA monthly rentabilidade in one frame, both vs CDI |
| `vw_fidc_vs_cra_yield` | **Cross-domain** | FIDC tranche return (subordinada) vs CRA subordinada-class rentabilidade |

Added one at a time as use cases surface; first six above are the seed list.

### What's intentionally NOT in the design

- **No new partitioning.** Only `cvm_fi_diario` is partitioned today (by year);
  every other table is small enough (<10M rows even after the full backfill)
  for B-tree indexes to handle. Re-evaluate after P3 lands and we see real
  query latencies.
- **No tp_fundo taxonomy normalization.** Raw `tp_fundo` values are kept; a
  canonical taxonomy view (`dim_fund_class`) can be added later if cross-entity
  classification becomes important.
- **No real-time refresh.** Matviews refresh on a schedule, accepting up to a
  day of staleness. CVM data publishes monthly anyway.
- **No HTTP analytical endpoints.** Per the user, surface is SQL-only for now
  (Supabase REST or psql); future Flask `/api/analytics/*` is a TODO.

---

## Part 4 — Refresh strategy (fault-safe, atomic)

**Default: regular VIEWs** wherever possible. They have no state, can't get
half-refreshed if a runner crashes, and are always consistent with the
underlying tables.

**Materialized views only for `fact_fund_monthly` and `fact_bacen_monthly`** —
where the FI daily-to-monthly aggregation is the expensive step.

For those two, **REFRESH MATERIALIZED VIEW CONCURRENTLY** is atomic in
Postgres: either the new snapshot replaces the old or the matview keeps its
previous content. There is no "half-refreshed" state, even if the client dies
mid-query.

**Trigger via `pg_cron` inside Postgres**, not from Flask:

```sql
SELECT cron.schedule(
  'refresh-fact-fund-monthly',
  '15 6 * * *',  -- daily at 06:15 UTC, after the GitHub Actions cron at 06:00
  $$ REFRESH MATERIALIZED VIEW CONCURRENTLY fact_fund_monthly; $$
);
```

Why pg_cron beats hooking into Flask `/api/daily`:

| Failure mode | Flask-hook | pg_cron |
|---|---|---|
| Local Flask runner crashes | refresh never runs | runs on schedule ✓ |
| Network partition between Flask and Supabase | refresh fails | runs server-side ✓ |
| Pipeline `daily_update` takes longer than expected | refresh blocked or skipped | independent schedule ✓ |
| Mid-refresh database failover | atomic — old state survives | atomic ✓ |
| Operator forgets to call `/api/refresh` | stale | runs anyway ✓ |

Initial refresh (when matviews are first created on a populated database) takes
1–2 min on `cvm_fi_diario` × 6 years × 12 months × ~5k funds. Run manually with
`REFRESH MATERIALIZED VIEW` (no CONCURRENTLY on first build) and then enable
the cron schedule.

**Backup plan if pg_cron isn't enabled on this Supabase tier**: add a
`/api/refresh-matviews` endpoint to Flask that operator can hit manually, plus
document that consumers should treat staleness as expected.

---

## Part 5 — Documentation consolidation

Current state — too many overlapping docs, several stale:

| File | Lines | Last touched | Decision |
|---|---|---|---|
| `README.md` | (kept) | recent | **KEEP** — entry point |
| `docs/PLAN.md` | 130+ | 2026-05-15 | **KEEP** — heartbeat tracker |
| `docs/AGENT_GUIDE.md` | 165 | 2026-05-14 | **KEEP** — agent workflows |
| `docs/pipeline-plan.md` | 700+ | 2026-05-14 | **KEEP** — deep CVM data dictionary |
| `TODO` | 85 | 2026-05-14 | **DELETE** — phase 0/1/2 already in PLAN.md priority queue; everything still pending gets folded into PLAN.md |
| `docs/pipeline-fixes-and-verification.md` | 131 | 2026-05-06 | **DELETE** — point-in-time post-fix report; superseded by PLAN.md "Schema fixes" section |
| `.planning/codebase/ARCHITECTURE.md` | 201 | 2026-05-06 | **DELETE** — snapshot, info now in README + pipeline-plan |
| `.planning/codebase/CONCERNS.md` | 267 | 2026-05-06 | **DELETE** — stale tech debt list, most items fixed |
| `.planning/codebase/CONVENTIONS.md` | 138 | 2026-05-05 | **DELETE** — never referenced |
| `.planning/codebase/INTEGRATIONS.md` | 146 | 2026-05-06 | **DELETE** — duplicates pipeline-plan §1 |
| `.planning/codebase/STACK.md` | 100 | 2026-05-05 | **DELETE** — duplicates requirements.txt |
| `.planning/codebase/STRUCTURE.md` | 248 | 2026-05-06 | **DELETE** — duplicates README "Repository layout" |
| `.planning/codebase/TESTING.md` | 326 | 2026-05-05 | **DELETE** — testing guidance ought to be in AGENT_GUIDE.md (and is, briefly) |

Final state: `README.md` (entry point) + 3 files in `docs/` (PLAN, AGENT_GUIDE,
pipeline-plan). Everything else gets pruned.

**Before deleting**: read each file once and migrate anything still useful that
isn't already in the kept files. Specifically:

- `CONCERNS.md` — check for unresolved tech debt items, add to PLAN.md priority
  queue if still relevant.
- `pipeline-fixes-and-verification.md` — already covered by PLAN.md "Schema fixes"
  log; nothing to migrate.
- `TODO` — phases 0/1/2 are done; Phase 3 details may have nuance worth
  folding into PLAN.md.

After consolidation, **`.planning/` directory is removed entirely** (was a
one-time codebase snapshot from May 2026, never updated).

---

## Part 6 — Files this plan eventually touches (no edits yet — plan only)

| Path | Change | When |
|---|---|---|
| `src/store/analytical_layer.sql` (new) | Contains `CREATE VIEW dim_fund`, `CREATE MATERIALIZED VIEW fact_fund_monthly`, `fact_bacen_monthly`, `CREATE VIEW vw_fund_vs_benchmark`, + 3 cross-instrument views, + pg_cron `cron.schedule` calls. Apply via `psql $SUPABASE_DB_URL -f src/store/analytical_layer.sql` after P3. | After P3 |
| [docs/PLAN.md](docs/PLAN.md) | New "P12: Analytical layer" priority. New "Query catalog" section listing the 10 categories. Mark TODO/pipeline-fixes-and-verification/.planning as deleted. | This plan's commit |
| [docs/pipeline-plan.md](docs/pipeline-plan.md) | New "Part 4 — Analytical layer" section that's the long-form companion to `analytical_layer.sql`. | When implementing |
| [docs/AGENT_GUIDE.md](docs/AGENT_GUIDE.md) | New "Querying via analytical views" section: when to query raw tables vs `fact_fund_monthly`, common pitfalls. | When implementing |
| [README.md](README.md) | Add "Analytical layer" subsection between Pipeline Stages and Quick Start. | When implementing |
| `TODO` (delete) | Remove file. Anything still relevant lives in PLAN.md priority queue. | This plan's commit |
| `docs/pipeline-fixes-and-verification.md` (delete) | Remove file. | This plan's commit |
| `.planning/` (delete) | Remove entire directory after migrating any unresolved items from `CONCERNS.md` into PLAN.md. | This plan's commit |

---

## Part 7 — Parallelization, commit cadence, safety hooks

The implementation has **three independent streams** that can be built in
parallel (different files, different tables, no shared state). They converge
at the cross-domain views.

```
            stream A — fund domain                    stream B — security domain
            ──────────────────────                    ─────────────────────────
                dim_fund                                    dim_security
                    │                                              │
                    ▼                                              ▼
            fact_fund_monthly                          fact_security_monthly
                    │                                              │
                    └──────────────┬───────────────────────────────┘
                                   │
                                   ▼
              stream C — benchmark                    L5 — cross-domain views
              ────────────────────                    ───────────────────────
                fact_bacen_monthly  ─→  vw_fund_vs_benchmark, vw_security_vs_benchmark
                                        vw_fund_security_yield, vw_fidc_vs_cra_yield
```

**Wave 1 (parallel)**: streams A1, B1, C1 — three small commits, no inter-dependency.

**Wave 2 (parallel)**: streams A2, B2 — depend only on their own L1. Each is a
matview build (5-10 min after P3 lands).

**Wave 3 (sequential)**: L4 benchmark joins → L5 cross-domain views. These read
from all three previous outputs.

### Implementation steps with commit boundaries

Each step is its own file in `src/store/analytical/` and its own commit, so
failed waves don't block green ones. Each commit is independently runnable —
operator can apply, smoke-test, and roll back any single layer without touching
the others.

| Wave | Step | File | Commit |
|---|---|---|---|
| 1 | A1 — `dim_fund` view | `src/store/analytical/01_dim_fund.sql` | `feat(analytics): dim_fund registry` |
| 1 | B1 — `dim_security` view | `src/store/analytical/02_dim_security.sql` | `feat(analytics): dim_security registry` |
| 1 | C1 — `fact_bacen_monthly` matview | `src/store/analytical/03_fact_bacen_monthly.sql` | `feat(analytics): BACEN monthly grain` |
| 2 | A2 — `fact_fund_monthly` matview | `src/store/analytical/04_fact_fund_monthly.sql` | `feat(analytics): unified monthly fund fact` |
| 2 | B2 — `fact_security_monthly` matview | `src/store/analytical/05_fact_security_monthly.sql` | `feat(analytics): unified monthly security fact` |
| 3 | L4 — benchmark views | `src/store/analytical/06_vw_benchmark.sql` | `feat(analytics): fund/security vs BACEN benchmarks` |
| 3 | L5 — cross-domain + helpers | `src/store/analytical/07_vw_cross_domain.sql` | `feat(analytics): cross-domain + tranche/yield-curve views` |
| 4 | Refresh schedule (`pg_cron`) | `src/store/analytical/08_cron_schedules.sql` | `feat(analytics): pg_cron daily refresh` |
| 4 | Smoke tests + docs | `scripts/analytical_smoke.sql`, README/PLAN/AGENT_GUIDE | `docs: analytical layer query catalog + smoke tests` |
| 5 | Doc consolidation | delete TODO + .planning + pipeline-fixes-and-verification | `docs: prune stale docs (TODO + .planning + verification snapshot)` |

### Safety hooks (per step)

Every analytical file starts with the same idempotent preamble:

```sql
BEGIN;                                  -- atomic application
SET statement_timeout = '15min';         -- so a stuck matview build can be cancelled

-- The step's CREATE OR REPLACE VIEW / CREATE MATERIALIZED VIEW IF NOT EXISTS
-- statements go here. Re-runs are no-ops on the second time through.

-- Inline smoke check — fail the transaction if it returns 0
DO $$
BEGIN
  IF (SELECT COUNT(*) FROM <new_object>) = 0 THEN
    RAISE EXCEPTION 'analytical step failed smoke check: <new_object> is empty';
  END IF;
END $$;

COMMIT;
```

This means:

- **Half-applied state is impossible** — `BEGIN…COMMIT` is atomic in Postgres.
- **Empty matviews don't get committed** — the `DO $$` smoke check raises and
  the transaction rolls back.
- **Long-running matview builds are bounded** — `statement_timeout = '15min'`
  kills anything stuck.
- **Re-running a step is safe** — `CREATE OR REPLACE` / `IF NOT EXISTS` make
  every step idempotent.

For the matviews specifically, the **initial build** uses
`CREATE MATERIALIZED VIEW IF NOT EXISTS …`. **Subsequent refreshes** use
`REFRESH MATERIALIZED VIEW CONCURRENTLY …` which holds a less-blocking lock
and never leaves a half-state.

### Commit safety on the pipeline / Flask side

This work touches `src/store/analytical/*.sql` only — none of `src/api/`,
`src/pipeline/`, `src/fetchers/`. The Flask control plane keeps running while
analytical layer changes are applied. Existing tests (109/109) stay relevant;
no changes there.

For the doc-deletion commit, **read each file before `git rm`** to migrate any
still-relevant tech debt into `docs/PLAN.md` priority queue. The audit happens
in the same commit as the deletion so nothing slips through.

---

## Part 8 — Migration to a remote session

The user is about to switch to a different (remote) session to do the
implementation. Everything below ensures the next session can resume cold,
without re-discovering state.

### State the next session needs

| Thing | Where it lives | Why |
|---|---|---|
| What's done in P11 | `docs/PLAN.md` Priority Queue + Table Status | Knows current row counts per table |
| Schema fixes already applied | `src/store/schema.sql` + `docs/PLAN.md` "Schema fixes" log | Knows what's been widened and why |
| All committed migrations | `git log --grep="migration"` + Supabase `supabase_migrations.schema_migrations` table | Live state of remote DB |
| Flask app status | `app.py` + `src/api/` (unchanged by this plan) | Can run partial fills if needed |
| This plan | `/Users/pedrotodescan/.claude/plans/refactored-plotting-duckling.md` | The implementation guide |
| Supabase credentials | `.env` (local, gitignored) | Needs SUPABASE_URL + SUPABASE_SERVICE_KEY |
| Test baseline | `pytest tests/ -v` should be 109/109 | Regression baseline |

### Pre-handoff checklist (do before switching to remote session)

1. **Push to origin** — `git push origin main` so the remote session can clone
   fresh. Currently 3 commits ahead of `origin/main` (P10 Flask, schema fixes,
   FIDC dedup) — confirm pushed.
2. **Verify `.env.example`** documents every var the analytical layer needs
   (it's all already there: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`,
   `SUPABASE_DB_URL`). No new env vars are introduced by this plan.
3. **Confirm Supabase MCP is wired** in `.mcp.json` and the next session can
   call `mcp__supabase__apply_migration`. If the remote session is in a fresh
   environment, the MCP server config must be re-attached.
4. **Confirm pg_cron availability** on the Supabase plan tier. If not
   available, swap step W4-`08_cron_schedules.sql` for a Flask
   `/api/refresh-matviews` endpoint and document in PLAN.md.
5. **Add a "Resuming this work" line to `docs/PLAN.md`** pointing at this
   plan file and at the priority queue position. The doc consolidation step
   will incorporate that.

### Important: copy this plan into the repo before migrating

This file lives at `~/.claude/plans/refactored-plotting-duckling.md` which is
**only on the local machine**. The remote session can't read it. The first
post-approval action is:

```bash
cp ~/.claude/plans/refactored-plotting-duckling.md docs/analytical-layer-plan.md
git add docs/analytical-layer-plan.md
git commit -m "docs: add analytical layer implementation plan (P12)"
git push origin main
```

This puts the plan in the repo so the remote session can `git pull` and read it.

### Resumption prompt (paste verbatim into the remote session)

```
Continue iliquid_nightly P12 — the analytical layer for cross-entity queries.

Plan: read docs/analytical-layer-plan.md in full before doing anything.

Where we left off (verify with `git log` and `docs/PLAN.md` Priority Queue):
- P10 (Flask control plane) done
- P11 (smoke-tests all 14 entity/doc_type pairs) done
- P3 range fills: check docs/PLAN.md Table Status — if any FIDC/FII/SECURIT/
  FIP/FIAGRO/FI table still shows ≤ smoke-test rowcount for the 2025-03 test
  slice, P3 isn't done yet. Resume P3 via Flask /api/ingest/range before
  starting P12.

Guardrails:
1. Apply src/store/analytical/*.sql files in numbered order (01 → 08).
2. Each file is wrapped in BEGIN…COMMIT with an inline smoke check — do
   NOT remove the smoke checks.
3. Check supabase_migrations.schema_migrations before applying each
   migration (use mcp__supabase__list_migrations).
4. After each wave, commit independently with the message format from
   the plan's "Implementation steps with commit boundaries" table, then
   stop and report.
5. Do NOT modify src/api/, src/pipeline/, or src/fetchers/ — analytical
   layer is additive, no pipeline changes.
6. Do NOT proceed past Wave 1 if any Wave 1 smoke check fails.

Environment: .env must contain SUPABASE_URL + SUPABASE_SERVICE_KEY +
SUPABASE_DB_URL.

Start by:
1. git pull
2. cat docs/analytical-layer-plan.md
3. cat docs/PLAN.md
4. Report current state of P3 backfill and propose first wave.
```

### Bootstrapping the remote environment

| Thing | Action |
|---|---|
| `.env` (gitignored — contains secrets) | `cp .env.example .env` then paste `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SUPABASE_DB_URL` from your password manager / Supabase dashboard |
| `.mcp.json` (Supabase MCP config) | Already committed — verify with `cat .mcp.json` |
| Python venv | `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt` |
| Verify Supabase reachable | `.venv/bin/python -c "from dotenv import load_dotenv; load_dotenv(); from src.store.supabase_client import get_supabase_client; print(get_supabase_client().table('cvm_ingest_log').select('run_id').limit(1).execute().data)"` should print a list (possibly empty) without error |
| Verify tests pass | `.venv/bin/python -m pytest tests/` should be 109/109 |

### What the remote session must NOT do (guardrails)

- Do NOT re-apply schema migrations that are already in `supabase_migrations.schema_migrations`.
  Use `mcp__supabase__list_migrations` to check first.
- Do NOT skip the inline smoke checks in each analytical SQL file — they're the only
  thing that catches an empty matview before it ships.
- Do NOT delete `docs/PLAN.md` content during the doc-consolidation step; it's the
  only living state document. Append-only edits to that file are fine; deletions are not.
- Do NOT enable pg_cron from this client side — it must be enabled in the
  Supabase dashboard first. The SQL just registers the schedule.

---

## Verification

Per-wave verification, each gating the next wave:

### Wave 1 verification

```sql
SELECT entity_type, COUNT(*) FROM dim_fund GROUP BY entity_type;
-- Expect rough magnitudes (after full P3): ~10k FI, ~3k FIDC, ~500 FIP, ~600 FII, ~20 FIAGRO

SELECT instrument_type, COUNT(*) FROM dim_security GROUP BY instrument_type;
-- Expect ~hundreds of CRAs, ~hundreds of CRIs, ~dozens of OTSs

SELECT series_code, MIN(period), MAX(period), COUNT(*) FROM fact_bacen_monthly GROUP BY series_code;
-- Expect monthly continuity for SELIC (11), CDI (12), IPCA (433), IGP-M (189)
```

### Wave 2 verification

```sql
SELECT entity_type, MIN(period), MAX(period), COUNT(*) FROM fact_fund_monthly GROUP BY entity_type;
-- Expect FI period range matches cvm_fi_diario's; row count ≈ funds × months

SELECT instrument_type, MIN(period), MAX(period), COUNT(*) FROM fact_security_monthly GROUP BY instrument_type;
```

### Wave 3 verification

```sql
SELECT period, AVG(spread_vs_cdi) FROM vw_fund_vs_benchmark
WHERE entity_type = 'fidc' AND period >= '2024-01-01' GROUP BY period ORDER BY period;
-- Expect non-NULL spreads

SELECT period, AVG(rentabilidade - cdi_mes) AS cra_excess
FROM vw_security_vs_benchmark
WHERE instrument_type = 'cra' AND period >= '2024-01-01' GROUP BY period;

SELECT * FROM vw_fund_security_yield LIMIT 20;  -- cross-domain shape check
```

### End-to-end query-catalog smoke

`scripts/analytical_smoke.sql` contains **one canned query per category A-K**
from Part 2. Operator runs it after Wave 4 lands:

```bash
psql "$SUPABASE_DB_URL" -f scripts/analytical_smoke.sql > smoke_$(date +%Y%m%d).log
```

Every query must return non-empty rows with non-NULL key metrics. The log
file is the runnable proof that the layer answers every category we said it
would.

### Refresh and concurrency tests

```sql
REFRESH MATERIALIZED VIEW CONCURRENTLY fact_fund_monthly;     -- should complete <2 min, no error
REFRESH MATERIALIZED VIEW CONCURRENTLY fact_security_monthly; -- should complete <30 sec
REFRESH MATERIALIZED VIEW CONCURRENTLY fact_bacen_monthly;    -- should complete <10 sec
SELECT * FROM cron.job;                                       -- expect 3 scheduled refreshes
```

### Documentation pass

- `README.md` "Analytical layer" subsection gives a 60-second intro pointing
  at `src/store/analytical/` and `scripts/analytical_smoke.sql`.
- `docs/AGENT_GUIDE.md` "Querying via analytical views" workflow.
- `docs/pipeline-plan.md` "Part 4 — Analytical layer" full reference.
- `docs/PLAN.md` P12 marked done with row counts and refresh schedule.
- Each `src/store/analytical/*.sql` has a comment header explaining the layer
  and inline comments on non-obvious aggregations (CDI cumulative product, FI
  `LAST_VALUE` to month-end, BACEN series-specific aggregation).

---

## Out of scope (deliberately deferred)

- **Flask `/api/analytics/*` endpoints** — SQL only for now per user. Document
  as a future P-task in PLAN.md.
- **dbt / sqlmesh modeling** — `analytical_layer.sql` is plain Postgres DDL.
  If the layer grows past ~10 views, revisit moving to dbt.
- **Time-series-DB extensions (TimescaleDB)** — premature; B-tree + the one
  existing partition on `cvm_fi_diario` handle current scale.
- **Front-end / dashboard layer** — out of scope; analytical layer is just the
  schema that a future dashboard would query.
- **Real-time / streaming** — CVM publishes monthly; daily refresh is more
  than enough.
- **Cross-instrument taxonomy normalization** (canonical sector codes,
  unified `tp_fundo` enum) — wait until a real use case shows up.
