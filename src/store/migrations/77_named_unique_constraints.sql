-- 77_named_unique_constraints.sql
-- Named UNIQUE constraints on the natural key of three tables that had only a
-- primary key (#880, part of #865). AGENTS.md rule 5: every table has a named
-- UNIQUE constraint on its natural key, and upserts use ON CONFLICT ... DO UPDATE.
--
--   cvm_etf_registry      uq_cvm_etf_registry      (ticker)
--   cia_company           uq_cia_company           (cd_cvm)
--   anbima_class_monthly  uq_anbima_class_monthly  (reference_date, anbima_category,
--                                                   anbima_type_name, metric, level)
--
-- Each constraint covers the same columns as the table's primary key, so no
-- existing row can violate it and the upsert conflict targets (ingest_etf.CONFLICT,
-- cia_company.CONFLICT, anbima_pipeline.CONFLICT_COLUMNS) still infer an arbiter.
-- The primary keys stay. The cost is one more unique index per table; all three
-- tables are small registries or a monthly long table.
--
-- b3_credit_capture gets no UNIQUE constraint, by design. Its natural key IS
-- capture_id: a capture is one retrieval, keyed by that run's cvm_ingest_log
-- UUID (migration 74). Replaying the same capture is idempotent on capture_id;
-- a later retrieval is a new knowledge-time vintage even when its payload is
-- identical, so a key on (source, requested window) or payload_sha256 would
-- merge vintages and lose A -> B -> A revisions. fact_credit_market keys on
-- (capture_id, ...) through uq_fact_credit_market.
--
-- schema.sql carries uq_anbima_class_monthly inline. cvm_etf_registry and
-- cia_company are owned by migrations 06 and 04 and are not in schema.sql.
-- Idempotent: each ADD CONSTRAINT is guarded on the constraint name, so a
-- replay is a no-op. psql -v ON_ERROR_STOP=1 clean.

BEGIN;

DO $mig77$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'public.cvm_etf_registry'::regclass
           AND conname  = 'uq_cvm_etf_registry'
    ) THEN
        ALTER TABLE public.cvm_etf_registry
            ADD CONSTRAINT uq_cvm_etf_registry UNIQUE (ticker);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'public.cia_company'::regclass
           AND conname  = 'uq_cia_company'
    ) THEN
        ALTER TABLE public.cia_company
            ADD CONSTRAINT uq_cia_company UNIQUE (cd_cvm);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'public.anbima_class_monthly'::regclass
           AND conname  = 'uq_anbima_class_monthly'
    ) THEN
        ALTER TABLE public.anbima_class_monthly
            ADD CONSTRAINT uq_anbima_class_monthly
            UNIQUE (reference_date, anbima_category, anbima_type_name, metric, level);
    END IF;
END
$mig77$;

COMMIT;
