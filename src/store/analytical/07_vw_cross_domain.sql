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

-- vw_fidc_aging_summary was dropped on 2026-09-30. Nothing read it (no api
-- object, dashboard source, query script, test or dependent view), and it
-- turned a blank aging bucket into 0, which the integrity rules forbid.
-- api.fidc_aging serves the ladder as filed. The DROP stays so a database that
-- still has the view loses it on the next apply.
DROP VIEW IF EXISTS vw_fidc_aging_summary;

-- Tranche detail enriched with fund-level PL and delinquency
CREATE OR REPLACE VIEW vw_fidc_tranche_detail AS
SELECT
  t.cnpj, t.period, t.classe_serie,
  t.qt_cota, t.vl_cota,
  -- Raw CVM pct values contain outliers — expose as-is; filter ABS(vl_rentab_mes) at client
  t.vl_rentab_mes, t.pr_desemp_esperado, t.pr_desemp_real,
  m.vl_patrim_liq  AS fund_pl,
  COALESCE(m.vl_inadimpl, a.vl_total_inad) AS fund_inadimpl
FROM cvm_fidc_tranche t
LEFT JOIN cvm_fidc_mensal m ON m.cnpj = t.cnpj AND m.period = t.period
LEFT JOIN cvm_fidc_aging a ON a.cnpj = t.cnpj AND a.period = t.period;

-- Monthly securitised instrument issuance trend (no params — use security_issuance_trend() for filtering)
-- One row per series per filing, the grain every per-series reader uses: a
-- series is (instrument_type, codigo_identificacao, numero_serie). Since
-- migration 52 cvm_securit_serie keeps every row CVM files, including several
-- rows for one series number (classes, occurrences) that repeat its value, so
-- counting and summing raw rows would inflate both measures (CRI, 2019/2022/
-- 2026 files: +8.1% of value). classe, id only make the pick deterministic.
CREATE OR REPLACE VIEW vw_securit_emission_trend AS
WITH per_series AS (
  SELECT DISTINCT ON (instrument_type, codigo_identificacao, numero_serie, data_referencia)
    instrument_type,
    data_referencia,
    valor_certificados
  FROM cvm_securit_serie
  WHERE data_referencia IS NOT NULL
  ORDER BY instrument_type, codigo_identificacao, numero_serie, data_referencia, classe, id
)
SELECT
  date_trunc('month', data_referencia)::date AS period,
  instrument_type,
  COUNT(*)                                   AS n_series,
  SUM(valor_certificados)                    AS total_value
FROM per_series
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
  s.cnpj_securit || ':' || s.codigo_identificacao || ':' || s.numero_serie,
  s.period,
  s.rentabilidade_mes,
  s.valor_certificados
FROM fact_security_monthly s
WHERE s.rentabilidade_mes IS NOT NULL;

COMMIT;
