# CHANGELOG (planning / platform)

One line per merged workstream or material DB change. Newest first.

## Pre-orchestration (manual, already applied to the canonical DB)
- **2026-05-29** — Aligned canonical DB (`ep-cold-moon`) to current `schema.sql`: created `cvm_fund_registry` and the previously-missing columns (`cvm_fi_perfil.mod_var`, `tp_fundo` on fidc/fiagro/fii mensal, `cvm_fii_periodic.data_referencia`, `cvm_securit_fluxo.recebimentos_alienacao_caixa`, `cvm_securit_serie.indice_subordinacao_data_base`). Widened `vl_quota` to `NUMERIC(28,12)` on `cvm_fi_diario` (+ partitions) and `cvm_fidc_mensal`, and `NUMERIC(28,6)` on `cvm_fiagro_mensal`. **Action still required:** these column widenings must be encoded into `schema.sql` + `apply_schema.py` migrations (W3) so they survive a from-empty rebuild; and the funds backfill must be re-run to populate the formerly-erroring tables.
- **2026-05-29** — Confirmed canonical DB target = Neon `ep-cold-moon-ak9pl909` / `neondb` (us-west-2). Two stray projects (`ep-divine-truth`, an empty auth-only project) are not used.

## Workstreams
<!-- e.g. 2026-06-01 — W0 chore/reconcile-main (abc1234): renamed pg client, removed docker-compose/netlify, chose Evidence, README synced. -->
