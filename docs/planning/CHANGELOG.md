# Changelog

| Date       | Branch                    | Change                                                                                              |
| ---------- | ------------------------- | --------------------------------------------------------------------------------------------------- |
| 2026-08-15 | cursor/serve-api-3f68     | Quote/NAV window (`from`/`range`) returns a `kind: series` envelope (rows or columnar) |
| 2026-08-14 | cursor/serve-api-3f68     | Public read contract: schema `api` + `serve/` HTTP (`docs/API.md`) — ticker/CNPJ, not landing tables |
| 2026-08-14 | cursor/b3-cotahist-3f68   | Fit `b3_cotahist` ingest/store/serve to Postgres practices: vista covering index, `vw_b3_quote_vista`, ANALYZE, partition rollover |
| 2026-08-14 | cursor/b3-cotahist-3f68   | Ingest B3 COTAHIST public quotation zips into `b3_cotahist` (daily run + opt-in yearly backfill)   |
| 2026-05-29 | chore/reconcile-main (W0) | Renamed pg_client, deleted dead files, wired cvm_fi_balancete (schema + field map + ingest path)   |
| 2026-05-29 | refactor/declarative-field-maps (W1) | Added src/parsers/mapping.py (apply_map + coerce), 17 field-map modules, 4 per-entity ingest modules, src/store/migrations/, updated apply_schema.py to run migrations in order, refactored cvm_pipeline.py to map-driven pattern |
| 2026-05-29 | feat/fi-cad-registry (W2) | Added fund_registry FIELD_MAP (verified against live cad_fi.csv headers), mapping engine, ingest_fund_registry_fi module; wired declarative path into cvm_pipeline.ingest_fund_registry for entity="fi" |
