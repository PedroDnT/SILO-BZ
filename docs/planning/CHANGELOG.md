# Changelog

| Date       | Branch                    | Change                                                                                              |
| ---------- | ------------------------- | --------------------------------------------------------------------------------------------------- |
| 2026-05-29 | chore/reconcile-main (W0) | Renamed pg_client, deleted dead files, wired cvm_fi_balancete (schema + field map + ingest path)   |
| 2026-05-29 | refactor/declarative-field-maps (W1) | Added src/parsers/mapping.py (apply_map + coerce), 17 field-map modules, 4 per-entity ingest modules, src/store/migrations/, updated apply_schema.py to run migrations in order, refactored cvm_pipeline.py to map-driven pattern |
| 2026-05-29 | feat/fi-cad-registry (W2) | Added fund_registry FIELD_MAP (verified against live cad_fi.csv headers), mapping engine, ingest_fund_registry_fi module; wired declarative path into cvm_pipeline.ingest_fund_registry for entity="fi" |
| 2026-05-29 | chore/numeric-precision (W3) | Added src/store/migrations/03_precision.sql: corrected cvm_fiagro_mensal.vl_quota to NUMERIC(28,12), widened cvm_securit_mensal.qt_titulos to NUMERIC(28,6), and typed bare NUMERIC columns on bacen_sgs/ptax/expectativas to explicit precision. |
| 2026-05-29 | feat/cia-scaffold (W5) | CIA_ABERTA scaffold: cvm_config entries (cad/ipe/itr/dfp), CIAFetcher with multi-CSV zip support, src/store/migrations/04_cia.sql (cia_company, cia_filing, cia_account [17 year partitions], cia_event) |
