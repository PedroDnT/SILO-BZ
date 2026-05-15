-- =============================================================================
-- 07_vw_cross_domain.sql
-- Four pure cross-domain views (CREATE OR REPLACE VIEW).
--
-- vw_fii_vs_fiagro          — unified FII + FIAGRO comparison slice
-- vw_fidc_tranche_detail    — tranche-level detail joined to fund PL/delinquency
-- vw_securit_emission_trend — monthly issuance trend by instrument type
-- vw_fund_security_yield    — cross-domain yield universe (funds + securit)
--                             with CDI benchmark overlay
-- =============================================================================

BEGIN;
SET statement_timeout = '15min';

-- ---------------------------------------------------------------------------
-- vw_fii_vs_fiagro
-- Unified slice of FII and FIAGRO for side-by-side comparison.
-- Columns: cnpj, period, entity_type, vl_patrim_liq, pct_yield_mes, nr_cotst.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW vw_fii_vs_fiagro AS
SELECT
  cnpj,
  period,
  entity_type,
  vl_patrim_liq,
  pct_yield_mes,
  nr_cotst
FROM fact_fund_monthly
WHERE entity_type IN ('fii', 'fiagro')
;

-- ---------------------------------------------------------------------------
-- vw_fidc_tranche_detail
-- Tranche-level quota and performance data enriched with fund-level
-- PL and delinquency from the monthly snapshot.
-- Source tables:
--   cvm_fidc_tranche : tranche grain (cnpj, period, classe_serie)
--   cvm_fidc_mensal  : fund grain    (cnpj, period)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW vw_fidc_tranche_detail AS
SELECT
  t.cnpj,
  t.period,
  t.classe_serie,
  t.qt_cota,
  t.vl_cota,
  -- raw CVM values contain outliers — expose as-is; callers should FILTER
  -- on ABS(vl_rentab_mes) < threshold for analysis.
  t.vl_rentab_mes,
  t.pr_desemp_esperado,
  t.pr_desemp_real,
  -- fund-level aggregates from cvm_fidc_mensal
  m.vl_patrim_liq  AS fund_pl,
  m.vl_inadimpl    AS fund_inadimpl
FROM cvm_fidc_tranche t
LEFT JOIN cvm_fidc_mensal m
  ON  m.cnpj   = t.cnpj
  AND m.period = t.period
;

-- ---------------------------------------------------------------------------
-- vw_securit_emission_trend
-- Monthly aggregation of securitised instrument emissions by type.
-- Uses cvm_securit_serie (per-series status file) as the universe.
-- valor_certificados is the outstanding face value per series at that date.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW vw_securit_emission_trend AS
SELECT
  date_trunc('month', data_referencia)::date  AS period,
  instrument_type,
  COUNT(*)                                    AS n_series,
  SUM(valor_certificados)                     AS total_value
FROM cvm_securit_serie
WHERE data_referencia IS NOT NULL
GROUP BY
  date_trunc('month', data_referencia)::date,
  instrument_type
;

-- ---------------------------------------------------------------------------
-- vw_fund_security_yield
-- Cross-domain yield universe combining:
--   FII / FIAGRO (pct_yield_mes from fact_fund_monthly)
--   CRA / CRI / OTS (rentabilidade_mes from fact_security_monthly)
-- Enriched with CDI benchmark for spread computation.
--
-- Columns:
--   domain         TEXT  — 'fund' | 'security'
--   instrument     TEXT  — entity_type (fund) or instrument_type (security)
--   identifier     TEXT  — cnpj (fund) or cnpj_securit||':'||codigo_identificacao
--   period         DATE
--   yield_mes      NUMERIC — pct_yield_mes or rentabilidade_mes
--   vl_patrim_liq  NUMERIC — fund PL or security valor_certificados
--   cdi_mes        NUMERIC — CDI return for the period
--   spread_vs_cdi  NUMERIC — yield_mes - cdi_mes (NULL when either is NULL)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW vw_fund_security_yield AS

-- Fund side: FII and FIAGRO (the yield-bearing fund types)
SELECT
  'fund'                                AS domain,
  f.entity_type                         AS instrument,
  f.cnpj                                AS identifier,
  f.period,
  f.pct_yield_mes                       AS yield_mes,
  f.vl_patrim_liq,
  b.value                               AS cdi_mes,
  CASE
    WHEN f.pct_yield_mes IS NOT NULL AND b.value IS NOT NULL
    THEN f.pct_yield_mes - b.value
  END                                   AS spread_vs_cdi
FROM fact_fund_monthly f
LEFT JOIN fact_bacen_monthly b
  ON  b.period      = f.period
  AND b.series_code = 12
WHERE f.entity_type IN ('fii', 'fiagro')
  AND f.pct_yield_mes IS NOT NULL

UNION ALL

-- Security side: CRA, CRI, OTS (rent-bearing securitised instruments)
SELECT
  'security'                            AS domain,
  s.instrument_type                     AS instrument,
  s.cnpj_securit || ':' || s.codigo_identificacao AS identifier,
  s.period,
  s.rentabilidade_mes                   AS yield_mes,
  s.valor_certificados                  AS vl_patrim_liq,
  b.value                               AS cdi_mes,
  CASE
    WHEN s.rentabilidade_mes IS NOT NULL AND b.value IS NOT NULL
    THEN s.rentabilidade_mes - b.value
  END                                   AS spread_vs_cdi
FROM fact_security_monthly s
LEFT JOIN fact_bacen_monthly b
  ON  b.period      = s.period
  AND b.series_code = 12
WHERE s.rentabilidade_mes IS NOT NULL
;

-- No smoke checks needed for pure views.

COMMIT;
