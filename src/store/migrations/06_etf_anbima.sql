-- =============================================================================
-- 06_etf_anbima.sql — ETF registry + ANBIMA ETF monthly metrics
--
-- These two tables existed in the Supabase project but had no repo DDL.
-- Captured here (from live information_schema) so the schema is fully
-- reproducible from `scripts/apply_schema.py`. Idempotent.
-- =============================================================================

-- ETF registry — one row per listed ETF ticker (B3 / CVM cadastral + provider enrich)
CREATE TABLE IF NOT EXISTS cvm_etf_registry (
    ticker               TEXT          PRIMARY KEY,
    cnpj                 TEXT          NOT NULL,
    fund_name            TEXT,
    provider             TEXT,
    underlying_index     TEXT,
    segment              TEXT,
    situacao             TEXT,
    is_active            BOOLEAN,
    dt_cancel            DATE,
    classe_anbima        TEXT,
    taxa_adm             NUMERIC(14,6),
    taxa_perfm           NUMERIC(14,6),
    admin                TEXT,
    gestor               TEXT,
    dt_reg               DATE,
    vl_patrim_liq        NUMERIC(20,2),
    dt_patrim_liq        DATE,
    raw                  JSONB,
    updated_at           TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    blackrock_product_id TEXT,
    blackrock_csv_url    TEXT
);
CREATE INDEX IF NOT EXISTS idx_etf_registry_cnpj     ON cvm_etf_registry (cnpj);
CREATE INDEX IF NOT EXISTS idx_etf_registry_active   ON cvm_etf_registry (is_active) WHERE is_active;

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
COMMENT ON TABLE anbima_etf_class_monthly IS
    'ANBIMA Boletim de Fundos de Investimento - ETF category and type monthly metrics. '
    'Monetary values are in R$ milhoes as published. rentabilidade values are percentage '
    'points (e.g. 4.37 = 4.37%). Idempotent upsert on (reference_date, anbima_type_name, metric).';
