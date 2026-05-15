-- =============================================================================
-- 04_fact_fund_monthly.sql
-- Materialized view: fact_fund_monthly
-- One row per (cnpj, period, entity_type) across all five fund types.
--
-- Unified column set:
--   period         DATE    — first day of month
--   entity_type    TEXT    — fi | fidc | fiagro | fii | fip
--   vl_patrim_liq  NUMERIC — net asset value (end of month for FI, monthly snap for others)
--   vl_quota       NUMERIC — unit quota value (FI only)
--   nr_cotst       INT     — number of unit-holders
--   vl_inadimpl    NUMERIC — delinquent portfolio value (FIDC / FIAGRO only)
--   pct_yield_mes  NUMERIC — monthly yield % (FII complemento only)
--   captc_mes      NUMERIC — gross inflows over the month (FI only)
--   resg_mes       NUMERIC — gross redemptions over the month (FI only)
--   vl_ativo       NUMERIC — total assets (FII complemento only)
--
-- FI source is daily (cvm_fi_diario) — must be aggregated to monthly.
-- FIP source is yearly (cvm_fip_periodic) — period mapped to Dec-31 of the year.
-- FII: only doc_subtype = 'complemento' carries yield / cotistas / vl_ativo.
-- =============================================================================

BEGIN;
SET statement_timeout = '15min';

DROP MATERIALIZED VIEW IF EXISTS fact_fund_monthly;

CREATE MATERIALIZED VIEW fact_fund_monthly AS

  -- -------------------------------------------------------------------------
  -- FI: daily → monthly aggregation
  -- Last-day-of-month values via DISTINCT ON; flows via GROUP BY.
  -- The two sub-queries are joined on (cnpj, period).
  -- -------------------------------------------------------------------------
  SELECT
    last_day.cnpj,
    date_trunc('month', last_day.dt_comptc)::date   AS period,
    'fi'                                             AS entity_type,
    last_day.vl_patrim_liq,
    last_day.vl_quota,
    last_day.nr_cotst,
    NULL::numeric                                    AS vl_inadimpl,
    NULL::numeric                                    AS pct_yield_mes,
    flows.captc_mes,
    flows.resg_mes,
    NULL::numeric                                    AS vl_ativo
  FROM (
    -- Last reported row per (fund, month): highest dt_comptc wins.
    SELECT DISTINCT ON (cnpj, date_trunc('month', dt_comptc))
      cnpj,
      dt_comptc,
      vl_patrim_liq,
      vl_quota,
      nr_cotst
    FROM cvm_fi_diario
    WHERE vl_patrim_liq IS NOT NULL
    ORDER BY
      cnpj,
      date_trunc('month', dt_comptc),
      dt_comptc DESC
  ) last_day
  JOIN (
    -- Monthly flow totals.
    SELECT
      cnpj,
      date_trunc('month', dt_comptc)::date AS period,
      SUM(captc_dia)                       AS captc_mes,
      SUM(resg_dia)                        AS resg_mes
    FROM cvm_fi_diario
    GROUP BY cnpj, date_trunc('month', dt_comptc)::date
  ) flows
    ON  flows.cnpj   = last_day.cnpj
    AND flows.period = date_trunc('month', last_day.dt_comptc)::date

  UNION ALL

  -- -------------------------------------------------------------------------
  -- FIDC: monthly snapshot — direct passthrough
  -- -------------------------------------------------------------------------
  SELECT
    cnpj,
    period,
    'fidc'          AS entity_type,
    vl_patrim_liq,
    NULL::numeric   AS vl_quota,
    NULL::int       AS nr_cotst,
    vl_inadimpl,
    NULL::numeric   AS pct_yield_mes,
    NULL::numeric   AS captc_mes,
    NULL::numeric   AS resg_mes,
    NULL::numeric   AS vl_ativo
  FROM cvm_fidc_mensal

  UNION ALL

  -- -------------------------------------------------------------------------
  -- FIAGRO: monthly snapshot — same structure as FIDC
  -- -------------------------------------------------------------------------
  SELECT
    cnpj,
    period,
    'fiagro'        AS entity_type,
    vl_patrim_liq,
    NULL::numeric   AS vl_quota,
    NULL::int       AS nr_cotst,
    vl_inadimpl,
    NULL::numeric   AS pct_yield_mes,
    NULL::numeric   AS captc_mes,
    NULL::numeric   AS resg_mes,
    NULL::numeric   AS vl_ativo
  FROM cvm_fiagro_mensal
  WHERE cnpj IS NOT NULL

  UNION ALL

  -- -------------------------------------------------------------------------
  -- FII: use doc_subtype = 'complemento' which carries yield, cotistas, vl_ativo.
  -- Fallback to doc_subtype = 'geral' for PL when complemento is absent is handled
  -- downstream — here we surface only complemento rows to avoid duplicates.
  -- -------------------------------------------------------------------------
  SELECT
    cnpj,
    period,
    'fii'                       AS entity_type,
    vl_patrim_liq,
    NULL::numeric               AS vl_quota,
    nr_cotst,
    NULL::numeric               AS vl_inadimpl,
    pct_dividend_yield_mes      AS pct_yield_mes,
    NULL::numeric               AS captc_mes,
    NULL::numeric               AS resg_mes,
    vl_ativo
  FROM cvm_fii_mensal
  WHERE doc_subtype = 'complemento'
    AND cnpj IS NOT NULL

  UNION ALL

  -- -------------------------------------------------------------------------
  -- FIP: yearly grain — period = Dec-31 of the reported year
  -- -------------------------------------------------------------------------
  SELECT
    cnpj,
    make_date(period_year, 12, 31)  AS period,
    'fip'                           AS entity_type,
    vl_patrim_liq,
    NULL::numeric                   AS vl_quota,
    NULL::int                       AS nr_cotst,
    NULL::numeric                   AS vl_inadimpl,
    NULL::numeric                   AS pct_yield_mes,
    NULL::numeric                   AS captc_mes,
    NULL::numeric                   AS resg_mes,
    NULL::numeric                   AS vl_ativo
  FROM cvm_fip_periodic
  WHERE cnpj IS NOT NULL
;

-- Primary-key index — enforces uniqueness across the union
CREATE UNIQUE INDEX ix_fact_fund_monthly_pk
  ON fact_fund_monthly (cnpj, period, entity_type);

-- Period-scan index for time-series queries
CREATE INDEX ix_fact_fund_monthly_period
  ON fact_fund_monthly (period);

-- Entity-type filter support
CREATE INDEX ix_fact_fund_monthly_entity
  ON fact_fund_monthly (entity_type, period);

-- -------------------------------------------------------------------------
-- Smoke check
-- EXCEPTION: fund data must exist after smoke tests have been run.
-- -------------------------------------------------------------------------
DO $$
DECLARE
  v_count      BIGINT;
  v_entities   BIGINT;
BEGIN
  SELECT COUNT(*), COUNT(DISTINCT entity_type)
    INTO v_count, v_entities
  FROM fact_fund_monthly;

  IF v_count = 0 THEN
    RAISE EXCEPTION
      'fact_fund_monthly smoke check FAILED: 0 rows — ingest at least one fund type first';
  END IF;

  RAISE NOTICE 'fact_fund_monthly smoke check OK: % rows across % entity type(s)',
    v_count, v_entities;
END $$;

COMMIT;
