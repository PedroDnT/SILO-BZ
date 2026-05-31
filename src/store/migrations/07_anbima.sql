-- =============================================================================
-- 07_anbima.sql — ANBIMA ETF monthly metrics
--
-- cvm_etf_registry is owned by 05_etf.sql. This file only adds the ANBIMA
-- Boletim de Fundos ETF metrics table, which had no repo DDL (it existed only
-- in the live database). Captured here so the schema is fully reproducible
-- via scripts/apply_schema.py. Idempotent, single-statement.
-- =============================================================================

-- ANBIMA Boletim de Fundos — ETF category/type monthly metrics.
-- Monetary values in R$ milhoes as published; rentabilidade in percentage points.
-- Idempotent upsert on (reference_date, anbima_type_name, metric).
CREATE TABLE IF NOT EXISTS anbima_etf_class_monthly (
    reference_date   DATE          NOT NULL,
    anbima_category  TEXT          NOT NULL DEFAULT 'ETF',
    anbima_type_id   INT,
    anbima_type_name TEXT          NOT NULL,
    metric           TEXT          NOT NULL,
    value            NUMERIC(20,6),
    source_sheet     TEXT,
    boletim_ref      TEXT,
    updated_at       TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    CONSTRAINT anbima_etf_class_monthly_pkey
        PRIMARY KEY (reference_date, anbima_type_name, metric)
);
