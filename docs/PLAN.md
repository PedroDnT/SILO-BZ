# iliquid_nightly — Pipeline Status

_Living tracker. Update after each session. Deep technical reference: [`pipeline-plan.md`](pipeline-plan.md)._

---

## Priority Queue

| #   | Task                                                                                                 | Status                                                    |
| --- | ---------------------------------------------------------------------------------------------------- | --------------------------------------------------------- |
| P0  | Commit `verify_pipeline.py` + `cvm_pipeline.py`                                                      | ✅ done                                                   |
| P1  | Create this file (`docs/PLAN.md`)                                                                    | ✅ done                                                   |
| P2  | Apply `schema.sql` to live Neon DB                                                                   | ✅ done                                                   |
| P3  | Historical backfill (fidc → fii → securit → fip → fi)                                                | 🔄 running — now driven through `/api/ingest/range` (P10) |
| P4  | Run `verify_pipeline.py` against live DB; confirm null rates below thresholds                        | ❌ blocked on P3                                          |
| P5  | MCP + skill integration (verify / backfill / schema-status skills)                                   | ⏳ Neon DB workflow now connected                         |
| P6  | Pytest fixtures for fidc_tranche / fidc_aging / securit_serie / securit_fluxo                        | ❌ pending                                                |
| P7  | BACEN macro ingestion wired into backfill CLI                                                        | ❌ low urgency                                            |
| P8  | FII sparse-table decision: keep merged or split into geral/ativo_passivo/complemento                 | ❌ defer until analytics                                  |
| P9  | Add `cvm_fi_diario_2027` partition to schema.sql (due 2027-01-01)                                    | ❌ calendar                                               |
| P10 | Flask control plane (`app.py` + `src/api/`): partial-fill endpoints + error hooks                    | ✅ done (2026-05-14)                                      |
| P11 | Smoke-test the remaining 13 empty tables via `/api/ingest` — find & fix schema bugs before P3 ranges | ✅ done (2026-05-15) — all entities tested                |

---

## Table Status

_Verifiable from code only (cannot query live DB). "schema exists" = present in `src/store/schema.sql`. "ingest path" = ingest method exists in `cvm_pipeline.py` and is wired into `backfill`/`daily_update`. Row counts below are from the last live check on 2026-05-14; treat as historical snapshots._

| Table                    | Entity  | Schema | Ingest path | Last-known live rows | Notes                                                                        |
| ------------------------ | ------- | ------ | ----------- | -------------------- | ---------------------------------------------------------------------------- |
| `cvm_fi_diario`          | FI      | exists | wired       | 482,069              | Partitioned by year. Ingest via `ingest_fi_diario` + HIST variant.           |
| `cvm_fi_cda`             | FI      | exists | wired       | 16,976               | Portfolio composition. Ingest via `ingest_fi_cda` + HIST variant.            |
| `cvm_fi_perfil`          | FI      | exists | wired       | 25,074               | Investor profile. Ingest via `ingest_fi_perfil`.                             |
| `cvm_fi_balancete`       | FI      | exists | wired       | 0                    | **Schema + map added in W0 (chore/reconcile-main). Backfill pending.**       |
| `cvm_fidc_mensal`        | FIDC    | exists | wired       | 3,007                | Monthly snapshot. Historical via HIST/ + current via tab_IV.                 |
| `cvm_fidc_tranche`       | FIDC    | exists | wired       | 9,899                | Per-tranche quota/return. 2 schema widenings applied.                        |
| `cvm_fidc_tranche_flows` | FIDC    | exists | wired       | 37,565               | Per-tranche flows. `qt_cota` widened; upsert dedup added.                    |
| `cvm_fidc_aging`         | FIDC    | exists | wired       | 3,007                | Delinquency aging buckets (tab_VI).                                          |
| `cvm_fiagro_mensal`      | FIAGRO  | exists | wired       | 18                   | Data available from 2025-05+.                                                |
| `cvm_fip_periodic`       | FIP     | exists | wired       | 3,773                | inf_trimestral (2010-2023) + inf_quadrimestral (2024+).                      |
| `cvm_fii_mensal`         | FII     | exists | wired       | 35,928               | 3 subtypes: geral, ativo_passivo, complemento. 2 migrations applied.        |
| `cvm_fii_periodic`       | FII     | exists | wired       | 1,046                | trimestral, anual, dfin.                                                     |
| `cvm_securit_mensal`     | SECURIT | exists | wired       | 6,946                | CRA/CRI/OTS monthly emissions.                                               |
| `cvm_securit_serie`      | SECURIT | exists | wired       | 883                  | Per-series status, rating, yield (classe CSV).                               |
| `cvm_securit_fluxo`      | SECURIT | exists | wired       | 231                  | Monthly cash flows by tranche (fluxo_caixa CSV).                             |
| `cvm_securit_dfin`       | SECURIT | exists | wired       | 20                   | Financial statements (dfin_cra, dfin_cri).                                   |
| `bacen_sgs`              | BACEN   | exists | wired       | 0                    | Separate `BacenIngestor`. SGS had transient BCB API issue at last check.     |
| `bacen_ptax`             | BACEN   | exists | wired       | 0                    | Same ingestor; 20 PTAX rows were loaded but DB was reset.                    |
| `bacen_expectativas`     | BACEN   | exists | wired       | 0                    | Same ingestor.                                                               |
| `cvm_fund_registry`      | FI/FII  | exists | wired       | —                    | Fund names + status from CAD files; also seeded from FIDC hist ingest.       |
| `cvm_ingest_log`         | Audit   | exists | wired       | 3                    | Populated by all `_log_start`/`_log_finish` calls.                           |

---

## Backfill Commands (run after P2)

Two options — pick by appetite for granularity:

**A. One-shot CLI** (faster wall-clock, all-or-nothing per entity):

```bash
# Apply schema first (idempotent)
psql "$NEON_DB_URL" -f src/store/schema.sql

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

| Field                         | Table               | Max null% |
| ----------------------------- | ------------------- | --------- |
| `vl_patrim_liq`               | `cvm_fidc_mensal`   | 1%        |
| `vl_rentab_mes`               | `cvm_fidc_tranche`  | 5%        |
| `vl_total_inad`               | `cvm_fidc_aging`    | 5%        |
| `vl_patrim_liq` (complemento) | `cvm_fii_mensal`    | 1%        |
| `pct_dividend_yield_mes`      | `cvm_fii_mensal`    | 5%        |
| `situacao`                    | `cvm_securit_serie` | 1%        |

---

## Schema fixes from partial-fill smoke testing (2026-05-14)

Driving the first slice (`fidc/tranche 2025-03`) through `/api/ingest` surfaced three bugs the
all-or-nothing CLI had been masking. Patterns to watch for in other tables:

| #   | Where                                                            | Root cause                                                                                                                                                | Fix                                                                                    |
| --- | ---------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| 1   | `cvm_fidc_tranche.qt_cota` `NUMERIC(20,8)`                       | CVM `TAB_X_QT_COTA` reaches **6.9 × 10¹³** (fund of funds quoting in micro-units)                                                                         | Migration `widen_cvm_fidc_tranche_numeric_columns` → `NUMERIC(28,8)`                   |
| 2   | `cvm_fidc_tranche.vl_rentab_mes` / `pr_desemp_*` `NUMERIC(10,6)` | Raw CVM percentage fields contain garbage like `164606333.00`                                                                                             | Migration `widen_cvm_fidc_tranche_pct_columns` → `NUMERIC(20,6)` (validate downstream) |
| 3   | `cvm_pipeline._log_finish`                                       | Used PostgREST upsert; NOT NULL on `entity`/`doc_type` fails the INSERT path _before_ `ON CONFLICT` routes to UPDATE                                      | Switched to true `UPDATE ... WHERE run_id = ...`                                       |
| 4   | `hooks.fetch_audit_warning`                                      | Filtered by API alias `doc_type` (`tranche`), pipeline logs the CVM-native `mensal_tab_x2`                                                                | Filter on `(entity, period)` only; pick the most recent error row                      |
| 5   | `cvm_fidc_tranche_flows.qt_cota` `NUMERIC(20,8)`                 | Same overflow as `cvm_fidc_tranche.qt_cota` (paired tab_X CSV)                                                                                            | Migration `widen_cvm_fidc_tranche_flows_qt_cota` → `NUMERIC(28,8)`                     |
| 6   | `supabase_client.upsert_rows`                                    | CVM `mensal_tab_x4` ships duplicate `(cnpj, period, classe_serie, tp_oper)` rows; PostgREST `ON CONFLICT` 21000s when a batch contains the same key twice | Defensive dedup before chunking — last write wins; logs collapsed count                |
| 7   | `cvm_fii_mensal.pct_*` four cols `NUMERIC(10,6)`                 | FII complemento ships dirty pct values (same pattern as FIDC)                                                                                             | Migration `widen_cvm_fii_mensal_pct_columns` → `NUMERIC(20,6)`                         |
| 8   | `cvm_fii_mensal.cotas_emitidas` `NUMERIC(20,6)`                  | FII `Cotas_Emitidas` reaches 6.46×10¹⁴ — overflows 10¹⁴ ceiling                                                                                           | Migration `widen_cvm_fii_mensal_cotas_emitidas` → `NUMERIC(28,6)`                      |

**Sizing heuristic for the next 13 tables:** any `NUMERIC(20,8)` or `NUMERIC(10,6)` is a likely
overflow candidate when the column stores raw CVM values (quota counts, percentages, AUM).
Widen to `NUMERIC(28,8)` and `NUMERIC(20,6)` respectively when the smoke-test surfaces 22003.

---

## Smoke-test plan for remaining empty tables

Goal: fire one representative slice per (entity, doc_type), find any schema/code bugs, fix
them once, then trigger the full range. Each slice picks **the same well-published period
(2025-03)** so we can correlate across tables.

| #      | Slice                                                | API call body               | Watch for                                |
| ------ | ---------------------------------------------------- | --------------------------- | ---------------------------------------- |
| ~~1~~  | ~~fidc/tranche 2025-03~~                             | ~~done — 9,899 rows~~       | clean after 2 migrations                 |
| ~~2~~  | ~~fidc/mensal 2025-03~~                              | ~~done — 3,007 rows~~       | clean, no schema changes                 |
| ~~3~~  | ~~fidc/tranche_flows 2025-03~~                       | ~~done — 37,565 rows~~      | needed `qt_cota` widen + upsert dedup    |
| ~~4~~  | ~~fidc/aging 2025-03~~                               | ~~done — 3,007 rows~~       | clean, no schema changes                 |
| ~~5~~  | ~~fi/diario 2025-03~~                                | ~~done — 482,069 rows~~     | clean, no schema changes                 |
| ~~6~~  | ~~fi/cda 2025-03~~                                   | ~~done — 16,976 rows~~      | clean                                    |
| ~~7~~  | ~~fi/perfil 2025-03~~                                | ~~done — 25,074 rows~~      | clean                                    |
| ~~8~~  | ~~fip/inf_trimestral 2023 + inf_quadrimestral 2024~~ | ~~done — 1787 + 1986 rows~~ | clean (2024 needs quadrimestral variant) |
| ~~9~~  | ~~fii/mensal_complemento 2024~~                      | ~~done — 11,976 rows~~      | 2 migrations: pct cols + cotas_emitidas  |
| ~~10~~ | ~~fii/mensal_geral 2024~~                            | ~~done — 11,976 rows~~      | clean                                    |
| ~~11~~ | ~~fii/mensal_ativo_passivo 2024~~                    | ~~done — 11,976 rows~~      | clean                                    |
| ~~12~~ | ~~fii/dfin 2024~~                                    | ~~done — 1,046 rows~~       | clean                                    |
| ~~13~~ | ~~securit/cra_mensal 2024~~                          | ~~done — 6,946 rows~~       | clean                                    |
| ~~14~~ | ~~securit/cra_classe 2024~~                          | ~~done — 883 rows~~         | clean                                    |
| ~~15~~ | ~~securit/cra_fluxo 2024~~                           | ~~done — 231 rows~~         | clean                                    |
| ~~16~~ | ~~securit/dfin_cra 2024~~                            | ~~done — 20 rows~~          | clean                                    |
| ~~17~~ | ~~fiagro/mensal 2025-06~~                            | ~~done — 18 rows~~          | clean (data starts 2025-05)              |

✅ All 17 slices done (2026-05-15). Schema is now validated against real data.
**Next: trigger P3 range fills** per "Backfill Commands (run after P2)" → Surface B.

The remaining `securit/cri_*`, `securit/ots_*`, `securit/dfin_cri` instrument variants share
schema with their CRA counterparts — smoke-testing all three CRA flavours is sufficient.

---

## P12 — Analytical layer ✅ done (2026-05-15)

SQL in `src/store/analytical/01-08*.sql`. Applied against Neon DB.
Smoke-test results post-apply:

| Object                      | Type    | Rows                                                                          |
| --------------------------- | ------- | ----------------------------------------------------------------------------- |
| `dim_fund`                  | view    | 32,933 funds across 5 entity types                                            |
| `dim_security`              | view    | 176 CRA/CRI/OTS instruments                                                   |
| `fact_fund_monthly`         | matview | 69,904 (FI+FIDC+FII+FIP+FIAGRO)                                               |
| `fact_security_monthly`     | matview | 231 CRA series                                                                |
| `fact_bacen_monthly`        | matview | 1 (BACEN SGS API issue — PTAX only; re-run `BacenIngestor` when SGS resolves) |
| `vw_fidc_tranche_detail`    | view    | 22,899                                                                        |
| `vw_fii_vs_fiagro`          | view    | 11,994                                                                        |
| `vw_fund_security_yield`    | view    | 11,133 (cross-domain FII+FIAGRO+CRA)                                          |
| `vw_securit_emission_trend` | view    | 12                                                                            |

BACEN note: SGS fetch returns 0 rows due to a transient BCB API error (ODataPropertyFilter issue in `python-bcb`). PTAX (20 rows) and Expectativas (1 row) landed. Re-run `BacenIngestor().daily_update()` once BCB API is stable to populate SELIC/CDI/IPCA series, then `REFRESH MATERIALIZED VIEW CONCURRENTLY fact_bacen_monthly`.

Plan reference: `docs/analytical-layer-plan.md`

Streams created: `dim_fund`, `dim_security` → `fact_fund_monthly`, `fact_security_monthly`, `fact_bacen_monthly` → `vw_fund_vs_benchmark`, `vw_security_vs_benchmark` → 4 cross-domain views.

- **Stream A**: `dim_fund` → `fact_fund_monthly` (unified monthly fact across FI/FIDC/FII/FIP/FIAGRO)
- **Stream B**: `dim_security` → `fact_security_monthly` (CRA/CRI/OTS instruments — NOT funds)
- **Stream C**: `fact_bacen_monthly` (SELIC/CDI/IPCA/IGP-M monthly grain from `bacen_sgs`)

Then: `vw_fund_vs_benchmark`, `vw_security_vs_benchmark`, cross-domain views, pg_cron refresh.
SQL in `src/store/analytical/01-08*.sql`. Verify with `scripts/analytical_smoke.sql`.

---

## Tech debt (from .planning/codebase/CONCERNS.md, captured before deletion)

Lower priority — address as encountered, not blocking P3/P12:

| #   | File                                   | Issue                                                                                                              | Risk                                                          |
| --- | -------------------------------------- | ------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------- |
| TD1 | `src/pipeline/cvm_pipeline.py:110-111` | `_period_to_date` bare `except Exception: pass` swallows date parse errors silently                                | Date column populated with fallback without any log trace     |
| TD2 | `src/fetchers/cvm_fetcher.py:161-163`  | DNS resolver init failure falls back to system resolver with only a warning                                        | Intermittent DNS failures invisible in logs                   |
| TD3 | `src/fetchers/cvm_fetcher.py:183-184`  | `_is_cache_valid` catches all exceptions, returns `False` — corrupted cache metadata silently triggers re-download | Wastes bandwidth, hard to diagnose                            |
| TD4 | `src/fetchers/cvm_fetcher.py:283-284`  | CSV selection falls back to alphabetically-first file in ZIP when `csv_name_pattern` doesn't match                 | Schema drift invisible if CVM adds a new CSV that sorts first |
| TD5 | `src/pipeline/cvm_pipeline.py:130-155` | `_log_start/_log_finish` swallow all exceptions — if Supabase is down, audit trail is silently lost                | Failed ingests go unrecorded                                  |

---

## Future scope

- **BACEN TaxaJuros** — credit interest rates by sector (useful for FIDC yield spread context); endpoint exists but not yet wired
- **B3 market data** — no validated public endpoint yet
- **ANBIMA** — paid API credentials blocked; open data links 404
- **Docker / Alembic** — Supabase is single target, defer until multi-environment
- **Flask `/api/analytics/*` endpoints** — SQL-only surface for now; add API layer when consumers are identified
- **Cross-instrument taxonomy** — canonical `tp_fundo` enum shared across FI/FIDC/FII; defer until analytics reveal a need

---

## Not In Scope

- GitHub Actions cron — manual Flask `/api/daily` preferred for now
- Public REST/GraphQL API — consumers query Neon/Postgres directly
- Docker / Alembic — Neon/Postgres is the single source of truth
