-- Migration 13: widen the ANBIMA boletim table from ETF-only to ALL classes
-- =============================================================================
-- The ANBIMA "Boletim de Fundos de Investimento" publishes every ANBIMA class
-- (Renda Fixa, Acoes, Multimercados, Cambial, Previdencia, ETF, FIDC, FIP,
-- FIAGRO, FII, Off Shore) and ~110 ANBIMA types. The pipeline used to keep only
-- the ETF slice; this migration reshapes the table to hold all of them.
--
-- WHY THE PRIMARY KEY CHANGES (this is the whole point of the migration)
-- ---------------------------------------------------------------------
-- The old key was (reference_date, anbima_type_name, metric). That is unique for
-- the ETF slice but NOT once every class is stored: in the type sheets
-- (Pag. 5 / Pag. 9) the labels "Cambial", "FIP" and "FIAGRO" each appear TWICE
-- -- once as a class aggregate row (no type id) and once as an ANBIMA type row
-- (ids 251 / 238 / 348). Same name, same metric, same date, different meaning
-- and different level of the hierarchy. Under the old key the type row would
-- silently overwrite the class aggregate. The new key therefore adds both the
-- owning category and the hierarchy level:
--
--     (reference_date, anbima_category, anbima_type_name, metric, level)
--
-- level values (NOT NULL, no synthesised data -- it records which row of the
-- published sheet the value came from):
--   'category' -> a class aggregate row  (e.g. "ETF", "Renda Fixa")
--   'type'     -> an ANBIMA type row     (e.g. "ETF Renda Fixa", id 225)
--   'total'    -> an industry total row  (e.g. "Total Geral"), stored with
--                 anbima_category = 'TOTAL' because a total belongs to no class
--
-- BACKWARD COMPATIBILITY
-- ----------------------
-- `anbima_etf_class_monthly` survives as a VIEW over the ETF slice, so anything
-- still selecting from it keeps working unchanged.
--
-- APPLY ORDER NOTE (why this file is defensive)
-- ---------------------------------------------
-- schema.sql runs first, then migrations 01..13 in lexical order, on EVERY CI
-- run. Migration 09 (which must never be edited) unconditionally re-creates
-- `anbima_etf_class_monthly` as a TABLE plus indexes, and CREATE INDEX on a view
-- is a hard error -- so schema.sql drops the compat view up front and this file,
-- running after 09, folds whatever 09 re-created back into the widened table.
-- Every branch below is a no-op on a database that is already migrated.

-- ---------------------------------------------------------------------------
-- Step 1 - fold the legacy ETF-only table into the widened table.
--   branch A: only the legacy table exists  -> rename it in place (no data copy)
--   branch B: both exist                    -> move the rows across, drop legacy
-- Either way not a single published row is lost, and `level` is derived from the
-- row's own type id (NULL id == class aggregate) rather than guessed.
-- ---------------------------------------------------------------------------
DO $mig13_fold$
DECLARE
    legacy_kind "char";
    widened_kind "char";
BEGIN
    SELECT c.relkind INTO legacy_kind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'public' AND c.relname = 'anbima_etf_class_monthly';

    SELECT c.relkind INTO widened_kind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'public' AND c.relname = 'anbima_class_monthly';

    IF legacy_kind = 'r' AND widened_kind IS NULL THEN
        ALTER TABLE public.anbima_etf_class_monthly RENAME TO anbima_class_monthly;

        ALTER TABLE public.anbima_class_monthly
            ADD COLUMN IF NOT EXISTS level TEXT NOT NULL DEFAULT 'category';

        -- One-time backfill of the newly added column for rows that predate it.
        -- A row that carries an ANBIMA type id IS a type row by construction
        -- (migration 09 documented exactly that); everything else is a class
        -- aggregate, which is what the column default already says.
        UPDATE public.anbima_class_monthly
           SET level = 'type'
         WHERE anbima_type_id IS NOT NULL
           AND level = 'category';

    ELSIF legacy_kind = 'r' AND widened_kind = 'r' THEN
        INSERT INTO public.anbima_class_monthly (
            reference_date, anbima_category, anbima_type_id, anbima_type_name,
            metric, value, source_sheet, boletim_ref, updated_at, level
        )
        SELECT
            o.reference_date, o.anbima_category, o.anbima_type_id, o.anbima_type_name,
            o.metric, o.value, o.source_sheet, o.boletim_ref, o.updated_at,
            CASE WHEN o.anbima_type_id IS NULL THEN 'category' ELSE 'type' END
        FROM public.anbima_etf_class_monthly o
        ON CONFLICT DO NOTHING;

        DROP TABLE public.anbima_etf_class_monthly;
    END IF;
END
$mig13_fold$;

-- ---------------------------------------------------------------------------
-- Step 2 - the widened table (safety net: neither table existed).
-- Kept byte-for-byte in sync with the copy in src/store/schema.sql.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS anbima_class_monthly (
    reference_date          DATE            NOT NULL,
    anbima_category         TEXT            NOT NULL,
    anbima_type_id          INT,
    anbima_type_name        TEXT            NOT NULL,
    metric                  TEXT            NOT NULL,
    value                   NUMERIC(20, 6),
    level                   TEXT            NOT NULL DEFAULT 'category',
    source_sheet            TEXT,
    boletim_ref             TEXT,
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT anbima_class_monthly_pkey
        PRIMARY KEY (reference_date, anbima_category, anbima_type_name, metric, level)
);

-- ---------------------------------------------------------------------------
-- Step 3 - reshape (no-ops once applied).
-- ---------------------------------------------------------------------------
ALTER TABLE anbima_class_monthly
    ADD COLUMN IF NOT EXISTS level TEXT NOT NULL DEFAULT 'category';

-- 'ETF' was the old column default, which only made sense while the table held
-- the ETF slice. Every ingested row now carries its own category from the sheet.
ALTER TABLE anbima_class_monthly
    ALTER COLUMN anbima_category DROP DEFAULT;

-- Swap the primary key. The new key is a strict superset of the old one, so no
-- existing row can collide while it is created.
ALTER TABLE anbima_class_monthly
    DROP CONSTRAINT IF EXISTS anbima_etf_class_monthly_pkey;

DO $mig13_pkey$
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM pg_constraint
         WHERE conrelid = 'public.anbima_class_monthly'::regclass
           AND contype  = 'p'
    ) THEN
        ALTER TABLE public.anbima_class_monthly
            ADD CONSTRAINT anbima_class_monthly_pkey
            PRIMARY KEY (reference_date, anbima_category, anbima_type_name, metric, level);
    END IF;
END
$mig13_pkey$;

-- ---------------------------------------------------------------------------
-- Step 4 - indexes. The old ETF-shaped index led on type name; with 11 classes
-- the useful lead column is the category.
-- ---------------------------------------------------------------------------
DROP INDEX IF EXISTS idx_anbima_etf_class_type_metric;
DROP INDEX IF EXISTS idx_anbima_etf_class_boletim_ref;

CREATE INDEX IF NOT EXISTS idx_anbima_class_cat_type_metric
    ON anbima_class_monthly (anbima_category, anbima_type_name, metric, reference_date DESC);

CREATE INDEX IF NOT EXISTS idx_anbima_class_metric_date
    ON anbima_class_monthly (metric, reference_date DESC);

CREATE INDEX IF NOT EXISTS idx_anbima_class_boletim_ref
    ON anbima_class_monthly (boletim_ref);

-- ---------------------------------------------------------------------------
-- Step 5 - compatibility view for consumers written against the ETF-only table.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW anbima_etf_class_monthly AS
    SELECT * FROM anbima_class_monthly WHERE anbima_category = 'ETF';

COMMENT ON TABLE anbima_class_monthly IS
    'ANBIMA Boletim de Fundos de Investimento - monthly metrics for every ANBIMA '
    'class and type. Monetary values are in R$ milhoes as published; '
    'rentabilidade values are percentage points (e.g. 4.37 = 4.37%). '
    'Idempotent upsert on (reference_date, anbima_category, anbima_type_name, metric, level).';

COMMENT ON COLUMN anbima_class_monthly.level IS
    'Which row of the published sheet the value came from: category (class '
    'aggregate) | type (ANBIMA type) | total (industry total, anbima_category = TOTAL). '
    'Part of the primary key: Cambial / FIP / FIAGRO each appear as BOTH a class '
    'aggregate and a type of the same name.';

COMMENT ON VIEW anbima_etf_class_monthly IS
    'Backward-compatible ETF slice of anbima_class_monthly (migration 13). '
    'Read anbima_class_monthly directly for the other ANBIMA classes.';
