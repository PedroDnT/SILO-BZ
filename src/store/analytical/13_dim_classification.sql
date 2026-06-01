-- =============================================================================
-- 13_dim_classification.sql
-- Conformed classification dimensions for cross-entity analytics:
--   • dim_fund_category   — (cnpj, entity_type) → asset_class / category
--   • dim_administrator   — one row per administrator, with funds + AUM served
--   • dim_gestor          — one row per gestor (portfolio manager), same shape
--
-- asset_class is a conformed bucket over heterogeneous CVM entity types so the
-- four fund families can be compared on one axis. It is derived from entity_type
-- plus the registry tp_fundo label (best-effort; FI splits into FI/RF/Equity/
-- Multimarket from tp_fundo keywords, everything else maps by entity_type).
--
-- admin/gestor come from typed columns lifted at ingest (migration 11):
-- cvm_fund_registry.admin_cnpj / admin_name / gestor_id / gestor_name.
-- Rankings group by NAME (the stable, presentable key); the CNPJ/CPF id is
-- carried for drill-through.
-- =============================================================================

BEGIN;
SET statement_timeout = '5min';

-- ---------------------------------------------------------------------------
-- dim_fund_category — conformed asset_class per fund
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW dim_fund_category AS
  SELECT
    d.cnpj,
    d.entity_type,
    d.tp_fundo,
    CASE
      WHEN d.entity_type = 'fidc'   THEN 'Structured Credit'
      WHEN d.entity_type = 'fii'    THEN 'Real Estate'
      WHEN d.entity_type = 'fiagro' THEN 'Agribusiness'
      WHEN d.entity_type = 'fip'    THEN 'Private Equity'
      WHEN d.entity_type = 'fi' THEN
        CASE
          WHEN d.tp_fundo ILIKE '%renda fixa%' OR d.tp_fundo ILIKE '%curto prazo%'
               OR d.tp_fundo ILIKE '%referenciad%' OR d.tp_fundo ILIKE '%cambial%'
            THEN 'Fixed Income'
          WHEN d.tp_fundo ILIKE '%ações%' OR d.tp_fundo ILIKE '%acoes%'
               OR d.tp_fundo ILIKE '%equity%'
            THEN 'Equity'
          WHEN d.tp_fundo ILIKE '%multimercado%' OR d.tp_fundo ILIKE '%multimarket%'
            THEN 'Multimarket'
          ELSE 'Other FI'
        END
      ELSE 'Other'
    END AS asset_class,
    COALESCE(d.tp_fundo, d.entity_type) AS category
  FROM dim_fund d;

-- ---------------------------------------------------------------------------
-- dim_administrator — administrator universe with funds + latest AUM served
-- AUM is summed from each fund's most recent fact_fund_monthly observation.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW dim_administrator AS
  WITH latest_fund AS (
    SELECT DISTINCT ON (cnpj, entity_type)
           cnpj, entity_type, period, vl_patrim_liq
    FROM fact_fund_monthly
    ORDER BY cnpj, entity_type, period DESC
  )
  SELECT
    r.admin_name,
    MIN(r.admin_cnpj)                                   AS admin_cnpj,
    COUNT(DISTINCT r.cnpj)                              AS n_funds,
    COUNT(DISTINCT r.cnpj) FILTER (WHERE r.is_active)   AS n_active_funds,
    COALESCE(SUM(lf.vl_patrim_liq), 0)                  AS total_aum
  FROM cvm_fund_registry r
  LEFT JOIN latest_fund lf
    ON lf.cnpj = r.cnpj AND lf.entity_type = r.entity_type
  WHERE r.admin_name IS NOT NULL
  GROUP BY r.admin_name;

-- ---------------------------------------------------------------------------
-- dim_gestor — gestor (portfolio manager) universe, same shape as administrator
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW dim_gestor AS
  WITH latest_fund AS (
    SELECT DISTINCT ON (cnpj, entity_type)
           cnpj, entity_type, period, vl_patrim_liq
    FROM fact_fund_monthly
    ORDER BY cnpj, entity_type, period DESC
  )
  SELECT
    r.gestor_name,
    MIN(r.gestor_id)                                    AS gestor_id,
    COUNT(DISTINCT r.cnpj)                              AS n_funds,
    COUNT(DISTINCT r.cnpj) FILTER (WHERE r.is_active)   AS n_active_funds,
    COALESCE(SUM(lf.vl_patrim_liq), 0)                  AS total_aum
  FROM cvm_fund_registry r
  LEFT JOIN latest_fund lf
    ON lf.cnpj = r.cnpj AND lf.entity_type = r.entity_type
  WHERE r.gestor_name IS NOT NULL
  GROUP BY r.gestor_name;

GRANT SELECT ON dim_fund_category TO anon, authenticated;
GRANT SELECT ON dim_administrator TO anon, authenticated;
GRANT SELECT ON dim_gestor        TO anon, authenticated;

COMMIT;
