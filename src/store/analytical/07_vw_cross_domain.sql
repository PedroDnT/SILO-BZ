-- =============================================================================
-- 07_vw_cross_domain.sql
-- Cross-domain and cross-entity helper views.
--
-- vw_fii_vs_fiagro          — unified FII + FIAGRO slice (no params needed for
--                             quick comparisons; parameterised via cross_entity_comparison())
-- vw_fidc_tranche_detail    — tranche grain enriched with fund PL + delinquency
-- vw_fidc_aging_summary     — aging bucket aggregates (grouped into 5 duration bands)
--                             for the full FIDC universe; use fidc_aging_buckets() for
--                             single-fund time series or fidc_aging_universe() for ranking
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

-- Aging bucket summary: grouped into 5 duration bands across the FIDC universe
CREATE OR REPLACE VIEW vw_fidc_aging_summary AS
SELECT
    a.cnpj,
    a.period,
    a.vl_total_inad,
    COALESCE(a.vl_inad_30, 0)                                    AS vl_inad_0_30d,
    COALESCE(a.vl_inad_60, 0)  + COALESCE(a.vl_inad_90, 0)      AS vl_inad_31_90d,
    COALESCE(a.vl_inad_120, 0) + COALESCE(a.vl_inad_150, 0) +
    COALESCE(a.vl_inad_180, 0)                                   AS vl_inad_91_180d,
    COALESCE(a.vl_inad_360, 0)                                   AS vl_inad_181_360d,
    COALESCE(a.vl_inad_720, 0) + COALESCE(a.vl_inad_1080, 0) +
    COALESCE(a.vl_inad_maior_1080, 0)                            AS vl_long_tail,
    m.vl_patrim_liq                                               AS fund_pl,
    CASE WHEN m.vl_patrim_liq > 0 THEN
        ROUND(a.vl_total_inad / m.vl_patrim_liq * 100, 4)
    END                                                           AS inadimpl_rate
FROM cvm_fidc_aging a
LEFT JOIN cvm_fidc_mensal m ON m.cnpj = a.cnpj AND m.period = a.period;

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
