-- =============================================================================
-- 07_vw_cross_domain.sql
-- Cross-domain and cross-entity helper views.
--
-- vw_fii_vs_fiagro          — unified FII + FIAGRO slice (no params needed for
--                             quick comparisons; parameterised via cross_entity_comparison())
-- vw_fidc_tranche_detail    — tranche grain enriched with fund PL + delinquency
-- vw_securit_emission_trend — monthly issuance volume by instrument type
-- vw_fund_security_yield    — UNION of fund yields + security returns (no BACEN;
--                             benchmark rate passed at query time via yield_universe())
--
-- NOTE: vw_fund_vs_benchmark and vw_security_vs_benchmark were removed in
-- migration "drop_bacen_analytical_objects". Use yield_distribution() and
-- yield_universe() functions with a benchmark_rate parameter instead.
-- =============================================================================

BEGIN;
SET statement_timeout = '15min';

-- Thin slice for quick FII vs FIAGRO dashboards
CREATE OR REPLACE VIEW vw_fii_vs_fiagro AS
SELECT cnpj, period, entity_type, vl_patrim_liq, pct_yield_mes, nr_cotst
FROM fact_fund_monthly
WHERE entity_type IN ('fii', 'fiagro');

-- Tranche detail enriched with fund-level PL and delinquency
CREATE OR REPLACE VIEW vw_fidc_tranche_detail AS
SELECT
  t.cnpj, t.period, t.classe_serie,
  t.qt_cota, t.vl_cota,
  -- Raw CVM pct values contain outliers — expose as-is; filter ABS(vl_rentab_mes) at client
  t.vl_rentab_mes, t.pr_desemp_esperado, t.pr_desemp_real,
  m.vl_patrim_liq  AS fund_pl,
  m.vl_inadimpl    AS fund_inadimpl
FROM cvm_fidc_tranche t
LEFT JOIN cvm_fidc_mensal m ON m.cnpj = t.cnpj AND m.period = t.period;

-- Monthly securitised instrument issuance trend (no params — use security_issuance_trend() for filtering)
CREATE OR REPLACE VIEW vw_securit_emission_trend AS
SELECT
  date_trunc('month', data_referencia)::date AS period,
  instrument_type,
  COUNT(*)                                   AS n_series,
  SUM(valor_certificados)                    AS total_value
FROM cvm_securit_serie
WHERE data_referencia IS NOT NULL
GROUP BY date_trunc('month', data_referencia)::date, instrument_type;

-- Cross-domain yield universe without benchmark (use yield_universe() function for parameterised version)
CREATE OR REPLACE VIEW vw_fund_security_yield AS
SELECT
  'fund'::TEXT      AS domain,
  f.entity_type     AS instrument,
  f.cnpj            AS identifier,
  f.period,
  f.pct_yield_mes   AS yield_mes,
  f.vl_patrim_liq
FROM fact_fund_monthly f
WHERE f.entity_type IN ('fii', 'fiagro')
  AND f.pct_yield_mes IS NOT NULL
UNION ALL
SELECT
  'security'::TEXT,
  s.instrument_type,
  s.cnpj_securit || ':' || s.codigo_identificacao,
  s.period,
  s.rentabilidade_mes,
  s.valor_certificados
FROM fact_security_monthly s
WHERE s.rentabilidade_mes IS NOT NULL;

COMMIT;
