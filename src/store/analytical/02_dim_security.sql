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
    -- Stored values are 'cra_mensal' | 'cri_mensal' | 'ots_mensal', NOT the
    -- CVM doc_type names: src/pipeline/ingest_securit.py::_DOC_TO_INSTRUMENT
    -- maps cra_classe/cri_classe/ots_classe (and the _fluxo doc_types) onto the
    -- instrument they describe before upsert, so one instrument_type covers a
    -- security's serie and fluxo rows alike.
    instrument_type,
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
