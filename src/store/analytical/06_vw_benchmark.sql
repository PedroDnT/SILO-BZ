-- =============================================================================
-- 06_vw_benchmark.sql
-- Pure views (CREATE OR REPLACE VIEW — no materialization, always fresh).
--
-- vw_fund_vs_benchmark
--   fact_fund_monthly enriched with SELIC, CDI, IPCA, IGP-M monthly returns
--   and derived spread columns.
--   pct_yield_mes is populated for FII (complemento) only; NULL otherwise.
--
-- vw_security_vs_benchmark
--   fact_security_monthly enriched with the same benchmark columns.
--   rentabilidade_mes drives the spread.
-- =============================================================================

BEGIN;
SET statement_timeout = '15min';

-- ---------------------------------------------------------------------------
-- Helper: pivot fact_bacen_monthly into one wide row per period so we can
-- join it once rather than four times.
-- We reference this pattern inline with four lateral-style LEFT JOINs.
-- ---------------------------------------------------------------------------

-- vw_fund_vs_benchmark -------------------------------------------------------
CREATE OR REPLACE VIEW vw_fund_vs_benchmark AS
SELECT
  f.cnpj,
  f.period,
  f.entity_type,
  f.vl_patrim_liq,
  f.vl_quota,
  f.nr_cotst,
  f.vl_inadimpl,
  f.pct_yield_mes,
  f.captc_mes,
  f.resg_mes,
  f.vl_ativo,

  -- Benchmark rates for the same calendar month
  cdi.value                                       AS cdi_mes,
  selic.value                                     AS selic_mes,
  ipca.value                                      AS ipca_mes,
  igpm.value                                      AS igpm_mes,

  -- Spread columns — only meaningful when pct_yield_mes is populated
  CASE
    WHEN f.pct_yield_mes IS NOT NULL AND cdi.value IS NOT NULL
    THEN f.pct_yield_mes - cdi.value
  END                                             AS spread_vs_cdi,

  CASE
    WHEN f.pct_yield_mes IS NOT NULL AND ipca.value IS NOT NULL
    THEN f.pct_yield_mes - ipca.value
  END                                             AS real_return

FROM fact_fund_monthly f

-- CDI (series 12)
LEFT JOIN fact_bacen_monthly cdi
  ON  cdi.period      = f.period
  AND cdi.series_code = 12

-- SELIC (series 11)
LEFT JOIN fact_bacen_monthly selic
  ON  selic.period      = f.period
  AND selic.series_code = 11

-- IPCA (series 433)
LEFT JOIN fact_bacen_monthly ipca
  ON  ipca.period      = f.period
  AND ipca.series_code = 433

-- IGP-M (series 189)
LEFT JOIN fact_bacen_monthly igpm
  ON  igpm.period      = f.period
  AND igpm.series_code = 189
;

-- vw_security_vs_benchmark ---------------------------------------------------
CREATE OR REPLACE VIEW vw_security_vs_benchmark AS
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
  s.recebimentos_mes,
  s.pgt_senior_mes,
  s.pgt_mezanino_mes,
  s.pgt_junior_mes,
  s.variacao_caixa_mes,

  -- Benchmark rates
  cdi.value                                       AS cdi_mes,
  selic.value                                     AS selic_mes,
  ipca.value                                      AS ipca_mes,
  igpm.value                                      AS igpm_mes,

  -- Spread vs CDI
  CASE
    WHEN s.rentabilidade_mes IS NOT NULL AND cdi.value IS NOT NULL
    THEN s.rentabilidade_mes - cdi.value
  END                                             AS spread_vs_cdi

FROM fact_security_monthly s

LEFT JOIN fact_bacen_monthly cdi
  ON  cdi.period      = s.period
  AND cdi.series_code = 12

LEFT JOIN fact_bacen_monthly selic
  ON  selic.period      = s.period
  AND selic.series_code = 11

LEFT JOIN fact_bacen_monthly ipca
  ON  ipca.period      = s.period
  AND ipca.series_code = 433

LEFT JOIN fact_bacen_monthly igpm
  ON  igpm.period      = s.period
  AND igpm.series_code = 189
;

-- No smoke checks needed for pure views.

COMMIT;
