# Changelog

| Date       | Branch                    | Change                                                                                              |
| ---------- | ------------------------- | --------------------------------------------------------------------------------------------------- |
| 2026-05-29 | chore/reconcile-main (W0) | Renamed pg_client, deleted dead files, wired cvm_fi_balancete (schema + field map + ingest path)   |
| 2026-05-29 | refactor/declarative-field-maps (W1) | Added src/parsers/mapping.py (apply_map + coerce), 17 field-map modules, 4 per-entity ingest modules, src/store/migrations/, updated apply_schema.py to run migrations in order, refactored cvm_pipeline.py to map-driven pattern |
