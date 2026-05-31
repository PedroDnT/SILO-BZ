-- Migration 09: ANBIMA ETF class monthly metrics
-- Stores AUM (PL), net flows (captação líquida), fund count, and returns
-- sourced from the ANBIMA Boletim de Fundos de Investimento monthly XLSX.
--
-- Monetary values (pl_brl_mm, captacao_liquida_*) are in R$ milhões as
-- published by ANBIMA. Do NOT convert to full BRL; document units in queries.
--
-- Grain: one row per (reference_date, anbima_type_name, metric).
--   - anbima_type_id NULL  → category-level aggregate   (e.g. "ETF" from sheet Pág.4)
--   - anbima_type_id 225   → "ETF Renda Fixa"
--   - anbima_type_id 226   → "ETF Renda Variável"
--
-- Metric values:
--   pl_brl_mm                  → AUM from Pág.4 (category) or Pág.5 (type), R$ mm
--   captacao_liquida_brl_mm    → monthly net flow from Pág.9 (type only), R$ mm
--   captacao_liquida_ytd_brl_mm → YTD accumulated net flow from Pág.8 (category annual) or Pág.9 (type YTD col)
--   captacao_liquida_12m_brl_mm → 12-month net flow from Pág.9 (type only), R$ mm
--   fund_count                 → number of funds from Pág.13, integer stored as NUMERIC
--   rentabilidade_pct          → monthly return % from Pág.11, already in pct points (e.g. 4.37)
--   rentabilidade_ytd_pct      → YTD return % from Pág.11
--   rentabilidade_12m_pct      → 12-month return % from Pág.11

CREATE TABLE IF NOT EXISTS anbima_etf_class_monthly (
    reference_date          DATE            NOT NULL,
    anbima_category         TEXT            NOT NULL DEFAULT 'ETF',
    anbima_type_id          INT,                          -- NULL = category aggregate
    anbima_type_name        TEXT            NOT NULL,     -- 'ETF', 'ETF Renda Fixa', 'ETF Renda Variável'
    metric                  TEXT            NOT NULL,
    value                   NUMERIC(20, 6),
    source_sheet            TEXT,                         -- e.g. 'Pág. 4 - PL por Classe'
    boletim_ref             TEXT,                         -- ANBIMA upload slug / filename
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT anbima_etf_class_monthly_pkey
        PRIMARY KEY (reference_date, anbima_type_name, metric)
);

-- Index for fast time-series scans by type + metric
CREATE INDEX IF NOT EXISTS idx_anbima_etf_class_type_metric
    ON anbima_etf_class_monthly (anbima_type_name, metric, reference_date DESC);

-- Index for boletim provenance lookups
CREATE INDEX IF NOT EXISTS idx_anbima_etf_class_boletim_ref
    ON anbima_etf_class_monthly (boletim_ref);

COMMENT ON TABLE anbima_etf_class_monthly IS
    'ANBIMA Boletim de Fundos de Investimento — ETF category and type monthly metrics. '
    'Monetary values (pl_brl_mm, captacao_liquida_*) are in R$ milhões as published. '
    'rentabilidade_* values are percentage points (e.g. 4.37 = 4.37%). '
    'Updated nightly; idempotent upsert on (reference_date, anbima_type_name, metric).';
