# Changelog

| Date       | Branch                    | Change                                                                                              |
| ---------- | ------------------------- | --------------------------------------------------------------------------------------------------- |
| 2026-08-27 | cursor/instruments-adjustment-1119 | Catalog v3: `close_return` meaning says unadjusted (splits look like crashes); instruments plan: cotacao.b3.com.br appendix + adjustment verification |
| 2026-08-27 | cursor/advisor-warnings-1119 | Performance Advisor lints after compute upgrade: do not add PKs / drop indexes; leftover `messages` |
| 2026-08-27 | cursor/mintlify-docs-3f68 | Document live Data API `https://zcjbtpxuhdekpwcxmepn.supabase.co/rest/v1/`; Mintlify navbar + GitHub |
| 2026-08-17 | cursor/agents-md-3f68     | AGENTS.md: SILO skill, CLI ingest, post-edit hook; move `serve/` to secrets                          |
| 2026-08-16 | cursor/kill-ingest-flask-3f68 | Remove ingest Flask (`app.py`, `src/api/`, `tests/test_api.py`); ingest is Actions + pipeline CLI |
| 2026-08-16 | cursor/silo-skill-3f68    | Replace auto-generated iliquid_nightly skill with SILO integrity/serving contract; gate PostToolUse pytest |
| 2026-08-16 | cursor/prune-daily-backfill-3f68 | Daily Ingest: drop duplicate `backfill` mode; CVM history stays on `backfill.yml` |
| 2026-08-16 | cursor/ci-tests-3f68      | CI Tests workflow: pytest on PR/push (pip + .pytest_cache); dispatch-only read-only `api.*` smoke |
| 2026-08-16 | cursor/b3-backfill-dispatch-3f68 | Archive unused Actions: coverage + matview-dependent audits (scripts remain; run locally) |
| 2026-08-15 | cursor/serve-catalog-3f68 | `GET /v1/catalog` + `/v1/tools`; no `/v1/query`. User-driven serving requirements in `docs/planning/SERVING.md` |
| 2026-08-15 | cursor/serve-api-3f68     | Researcher panel: `/v1/panel` mixes ticker close with fund NAV/delinquency; wide matrix for correlation; no ffill |
| 2026-08-15 | cursor/serve-api-3f68     | Quote/NAV window (`from`/`range`) returns a `kind: series` envelope (rows or columnar) |
| 2026-08-14 | cursor/serve-api-3f68     | Public read contract: schema `api` + `serve/` HTTP (`docs/API.md`) — ticker/CNPJ, not landing tables |
| 2026-08-14 | cursor/b3-cotahist-3f68   | Fit `b3_cotahist` ingest/store/serve to Postgres practices: vista covering index, `vw_b3_quote_vista`, ANALYZE, partition rollover |
| 2026-08-14 | cursor/b3-cotahist-3f68   | Ingest B3 COTAHIST public quotation zips into `b3_cotahist` (daily run + opt-in yearly backfill)   |
| 2026-05-29 | chore/reconcile-main (W0) | Renamed pg_client, deleted dead files, wired cvm_fi_balancete (schema + field map + ingest path)   |
| 2026-05-29 | refactor/declarative-field-maps (W1) | Added src/parsers/mapping.py (apply_map + coerce), 17 field-map modules, 4 per-entity ingest modules, src/store/migrations/, updated apply_schema.py to run migrations in order, refactored cvm_pipeline.py to map-driven pattern |
| 2026-05-29 | feat/fi-cad-registry (W2) | Added fund_registry FIELD_MAP (verified against live cad_fi.csv headers), mapping engine, ingest_fund_registry_fi module; wired declarative path into cvm_pipeline.ingest_fund_registry for entity="fi" |
