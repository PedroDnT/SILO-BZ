-- =============================================================================
-- L1 Stream B: dim_security
-- Registry of CRA, CRI, and OTS debt instruments.
-- These are securitized debt certificates — NOT investment funds.
-- Primary key is (cnpj_securit, codigo_identificacao, instrument_type, numero_serie).
-- =============================================================================

BEGIN;
SET statement_timeout = '5min';

CREATE OR REPLACE VIEW dim_security AS
  SELECT
    cnpj_securit,
    codigo_identificacao,
    codigo_isin,
    codigo_cetip,
    instrument_type,       -- 'cra_classe' | 'cri_classe' | 'ots_classe' from source doc_type
    numero_serie,
    MIN(data_referencia)   AS first_seen,
    MAX(data_referencia)   AS last_seen,
    -- latest known quasi-static fields (last seen value wins)
    MAX(data_vencimento)   AS data_vencimento,
    MAX(taxa_juros)        AS taxa_juros_latest,
    MAX(situacao)          AS situacao_latest,
    MAX(classificacao_risco_atual) AS rating_latest,
    COUNT(DISTINCT data_referencia) AS n_reports
  FROM cvm_securit_serie
  GROUP BY
    cnpj_securit, codigo_identificacao, codigo_isin,
    codigo_cetip, instrument_type, numero_serie
;

-- Smoke check
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM dim_security LIMIT 1) THEN
    RAISE NOTICE 'dim_security is empty (no securit data yet — safe to proceed)';
  END IF;
END $$;

COMMIT;
