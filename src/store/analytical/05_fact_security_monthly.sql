-- =============================================================================
-- 05_fact_security_monthly.sql
-- Materialized view: fact_security_monthly
-- One row per (cnpj_securit, codigo_identificacao, period, instrument_type).
-- period = date_trunc('month', data_referencia)::date
--
-- Joins cvm_securit_serie and cvm_securit_fluxo:
--   - From serie : latest situacao and rentabilidade within the month
--   - From fluxo : sum of cash-flow columns over the month
--
-- instrument_type distinguishes cra_mensal / cri_mensal / ots_mensal -- the
-- values ingest_securit._DOC_TO_INSTRUMENT writes, not the CVM doc_type names.
--
-- CASCADE on the drop: vw_fund_security_yield (07_vw_cross_domain.sql) is the
-- only known dependent (scripts/audit_matview_dependents.py), and it's
-- recreated later in the same apply_analytical.sh pass. Same silent-failure
-- history as fact_fund_monthly's drop — see the comment there.
-- =============================================================================

BEGIN;
SET statement_timeout = '15min';

DROP MATERIALIZED VIEW IF EXISTS fact_security_monthly CASCADE;

CREATE MATERIALIZED VIEW fact_security_monthly AS

WITH

-- ---------------------------------------------------------------------------
-- serie_monthly: latest snapshot per series per month
-- DISTINCT ON gives the last data_referencia within each (cnpj, id, month).
-- ---------------------------------------------------------------------------
serie_monthly AS (
  SELECT DISTINCT ON (
    cnpj_securit,
    codigo_identificacao,
    date_trunc('month', data_referencia),
    instrument_type
  )
    cnpj_securit,
    codigo_identificacao,
    instrument_type,
    date_trunc('month', data_referencia)::date  AS period,
    -- latest known situacao and rentabilidade for the month
    situacao                                    AS situacao_mes,
    rentabilidade                               AS rentabilidade_mes,
    -- carry through quasi-static fields for context
    numero_serie,
    data_vencimento,
    valor_certificados,
    quantidade_certificados
  FROM cvm_securit_serie
  WHERE data_referencia IS NOT NULL
  ORDER BY
    cnpj_securit,
    codigo_identificacao,
    date_trunc('month', data_referencia),
    instrument_type,
    data_referencia DESC
),

-- ---------------------------------------------------------------------------
-- fluxo_monthly: sum of all cash-flow columns per series per month.
-- fluxo rows may arrive at any frequency; bucket to calendar month.
-- ---------------------------------------------------------------------------
fluxo_monthly AS (
  SELECT
    cnpj_securit,
    codigo_identificacao,
    instrument_type,
    date_trunc('month', data_referencia)::date  AS period,
    SUM(recebimentos_direitos_creditorios)       AS recebimentos_mes,
    SUM(pagamentos_classe_senior)                AS pgt_senior_mes,
    SUM(pagamentos_senior_principal)             AS pgt_senior_principal_mes,
    SUM(pagamentos_senior_juros)                 AS pgt_senior_juros_mes,
    SUM(pagamentos_mezanino)                     AS pgt_mezanino_mes,
    SUM(pagamentos_mezanino_principal)           AS pgt_mezanino_principal_mes,
    SUM(pagamentos_mezanino_juros)               AS pgt_mezanino_juros_mes,
    SUM(pagamentos_junior)                       AS pgt_junior_mes,
    SUM(pagamentos_despesas)                     AS pgt_despesas_mes,
    SUM(variacao_liquida_caixa)                  AS variacao_caixa_mes
  FROM cvm_securit_fluxo
  WHERE data_referencia IS NOT NULL
  GROUP BY
    cnpj_securit,
    codigo_identificacao,
    instrument_type,
    date_trunc('month', data_referencia)::date
)

-- ---------------------------------------------------------------------------
-- Final join: serie drives the grain; fluxo is left-joined (may be absent
-- for some series or months where no cash events were recorded).
-- ---------------------------------------------------------------------------
SELECT
  s.cnpj_securit,
  s.codigo_identificacao,
  s.instrument_type,
  s.period,
  s.situacao_mes,
  s.rentabilidade_mes,
  s.numero_serie,
  s.data_vencimento,
  s.valor_certificados,
  s.quantidade_certificados,
  -- cash-flow columns from fluxo (NULL when no fluxo row for that month)
  f.recebimentos_mes,
  f.pgt_senior_mes,
  f.pgt_senior_principal_mes,
  f.pgt_senior_juros_mes,
  f.pgt_mezanino_mes,
  f.pgt_mezanino_principal_mes,
  f.pgt_mezanino_juros_mes,
  f.pgt_junior_mes,
  f.pgt_despesas_mes,
  f.variacao_caixa_mes
FROM serie_monthly s
LEFT JOIN fluxo_monthly f
  ON  f.cnpj_securit         = s.cnpj_securit
  AND f.codigo_identificacao  = s.codigo_identificacao
  AND f.instrument_type       = s.instrument_type
  AND f.period                = s.period
;

-- Unique index: one row per natural key
CREATE UNIQUE INDEX ix_fact_security_monthly_pk
  ON fact_security_monthly (cnpj_securit, codigo_identificacao, period, instrument_type);

CREATE INDEX ix_fact_security_monthly_period
  ON fact_security_monthly (period);

CREATE INDEX ix_fact_security_monthly_instrument
  ON fact_security_monthly (instrument_type, period);

-- -------------------------------------------------------------------------
-- Smoke check
-- NOTICE (not EXCEPTION): securit data may not be fully populated yet.
-- -------------------------------------------------------------------------
DO $$
DECLARE
  v_count BIGINT;
BEGIN
  SELECT COUNT(*) INTO v_count FROM fact_security_monthly;
  IF v_count = 0 THEN
    RAISE NOTICE 'fact_security_monthly empty — securit data not yet ingested; safe to continue';
  ELSE
    RAISE NOTICE 'fact_security_monthly smoke check OK: % rows', v_count;
  END IF;
END $$;

COMMIT;
