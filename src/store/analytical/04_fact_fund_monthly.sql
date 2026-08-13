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
--
-- CASCADE on the drop: every known dependent (dim_administrator, dim_gestor,
-- vw_fii_vs_fiagro, vw_fund_security_yield, mv_savings_flow_monthly +
-- api.mv_savings_flow_monthly) is recreated later in the same apply_analytical.sh
-- pass (13_dim_classification.sql, 07_vw_cross_domain.sql, 18_savings_flow.sql)
-- — captured via scripts/audit_matview_dependents.py before adding CASCADE, not
-- assumed. A plain DROP (no CASCADE) fails as soon as ANY of these exist, which
-- is always true after the first successful apply; that was silently failing
-- on every subsequent run (continue-on-error on the workflow step masked it),
-- so this matview's definition was not actually being refreshed in production.
-- If a NEW ad-hoc dependent shows up outside this repo, CASCADE will drop it
-- too — re-run the audit script before assuming this list is still complete.
-- =============================================================================

BEGIN;
SET statement_timeout = '15min';

DROP MATERIALIZED VIEW IF EXISTS fact_fund_monthly CASCADE;

CREATE MATERIALIZED VIEW fact_fund_monthly AS

  -- -------------------------------------------------------------------------
  -- FI: daily → monthly aggregation
  -- Last-day-of-month values via DISTINCT ON per subclasse, summed to a
  -- per-fund total; flows via GROUP BY. The two sub-queries are joined on
  -- (cnpj, period).
  -- -------------------------------------------------------------------------
  SELECT
    last_day.cnpj,
    last_day.period,
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
    -- Last reported row per (fund, subclasse, month), summed to a per-fund
    -- total. CVM-175 lets several subclasses (distinct pools of money) share
    -- one CNPJ_FUNDO_CLASSE (migrations/17_fi_diario_subclasse_key.sql) — PL
    -- and cotista count are additive across them, so they are summed rather
    -- than picking one arbitrarily. vl_quota is a per-unit price, not
    -- additive; the largest subclass's is used as the fund's representative
    -- quota, a real filed value rather than a fabricated blend.
    -- ETFs are excluded (their CNPJ is an ordinary cvm_fi_diario row) so they are
    -- not double-counted here and in etf_daily; they are evaluated separately via
    -- the etf_* objects. dim_fund applies the same carve-out.
    SELECT
      cnpj,
      date_trunc('month', dt_comptc)::date                                      AS period,
      SUM(vl_patrim_liq)                                                        AS vl_patrim_liq,
      (ARRAY_AGG(vl_quota ORDER BY vl_patrim_liq DESC NULLS LAST))[1]            AS vl_quota,
      SUM(nr_cotst)                                                             AS nr_cotst
    FROM (
      SELECT DISTINCT ON (cnpj, id_subclasse, date_trunc('month', dt_comptc))
        cnpj,
        id_subclasse,
        dt_comptc,
        vl_patrim_liq,
        vl_quota,
        nr_cotst
      FROM cvm_fi_diario d
      WHERE vl_patrim_liq IS NOT NULL
        AND NOT EXISTS (SELECT 1 FROM cvm_etf_registry e WHERE e.cnpj = d.cnpj)
      ORDER BY
        cnpj,
        id_subclasse,
        date_trunc('month', dt_comptc),
        dt_comptc DESC
    ) per_subclasse
    GROUP BY cnpj, date_trunc('month', dt_comptc)
  ) last_day
  JOIN (
    -- Monthly flow totals (ETFs excluded, same as above).
    SELECT
      cnpj,
      date_trunc('month', dt_comptc)::date AS period,
      SUM(captc_dia)                       AS captc_mes,
      SUM(resg_dia)                        AS resg_mes
    FROM cvm_fi_diario d
    WHERE NOT EXISTS (SELECT 1 FROM cvm_etf_registry e WHERE e.cnpj = d.cnpj)
    GROUP BY cnpj, date_trunc('month', dt_comptc)::date
  ) flows
    ON  flows.cnpj   = last_day.cnpj
    AND flows.period = last_day.period

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
