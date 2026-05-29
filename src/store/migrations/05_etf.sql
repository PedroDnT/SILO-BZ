-- 05_etf.sql — ETF (Fundo de Índice) dataset
--
-- CVM open data has no ETF flag. TP_FUNDO is only FI/FACFIF/FAPI/FCCE, and the
-- CVM-175 Classificacao is Multimercado/Renda Fixa/Ações/Cambial/FMP-FGTS —
-- none isolate ETFs. ETFs are enumerated by B3 (the ticker assigner), so we
-- keep a curated ticker to CNPJ seed (src/store/seeds/etf_registry_seed.csv,
-- loaded by src/pipeline/ingest_etf.py) and join it to data we already ingest.
--
-- cvm_etf_registry  — ETF identity (ticker, CNPJ, provider, index, segment)
--                     enriched from cad_fi by CNPJ (fees, admin/gestor, status).
-- etf_daily (view)  — registry joined to cvm_fi_diario on CNPJ. NAV/quota, AUM
--                     (VL_PATRIM_LIQ), quotaholders (NR_COTST), flows, returns.
-- etf_latest (view) — most recent snapshot per ticker.
--
-- All statements are idempotent and single-statement (apply_schema.py splits on
-- the semicolon), so there are no PL/pgSQL bodies and no semicolons in comments.

CREATE TABLE IF NOT EXISTS cvm_etf_registry (
    ticker            TEXT PRIMARY KEY,
    cnpj              TEXT          NOT NULL,
    fund_name         TEXT,
    provider          TEXT,
    underlying_index  TEXT,
    segment           TEXT,
    situacao          TEXT,
    is_active         BOOLEAN,
    dt_cancel         DATE,
    classe_anbima     TEXT,
    taxa_adm          NUMERIC(14, 6),
    taxa_perfm        NUMERIC(14, 6),
    admin             TEXT,
    gestor            TEXT,
    dt_reg            DATE,
    vl_patrim_liq     NUMERIC(20, 2),
    dt_patrim_liq     DATE,
    raw               JSONB,
    updated_at        TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_etf_registry_cnpj    ON cvm_etf_registry (cnpj);
CREATE INDEX IF NOT EXISTS idx_etf_registry_segment ON cvm_etf_registry (segment);

-- Daily ETF time series: AUM, quotaholders, NAV/quota, flows, daily return.
CREATE OR REPLACE VIEW etf_daily AS
SELECT
    e.ticker,
    e.cnpj,
    e.fund_name,
    e.provider,
    e.underlying_index,
    e.segment,
    e.is_active,
    d.dt_comptc,
    d.vl_quota,
    d.vl_patrim_liq                                      AS aum,
    d.nr_cotst                                           AS quotaholders,
    d.captc_dia,
    d.resg_dia,
    (COALESCE(d.captc_dia, 0) - COALESCE(d.resg_dia, 0)) AS net_flow,
    e.taxa_adm,
    e.taxa_perfm,
    d.vl_quota / NULLIF(LAG(d.vl_quota) OVER (PARTITION BY e.ticker ORDER BY d.dt_comptc), 0) - 1
                                                         AS daily_return
FROM cvm_etf_registry e
JOIN cvm_fi_diario d ON d.cnpj = e.cnpj;

-- Latest snapshot per ETF.
CREATE OR REPLACE VIEW etf_latest AS
SELECT DISTINCT ON (ticker)
    ticker, cnpj, fund_name, provider, underlying_index, segment, is_active,
    dt_comptc, vl_quota, aum, quotaholders, net_flow, taxa_adm, taxa_perfm
FROM etf_daily
ORDER BY ticker, dt_comptc DESC;
