-- =============================================================================
-- L1 Stream A: dim_fund
-- Registry of all investment fund CNPJs and their entity type / active periods.
-- Covers FI, FIDC, FIP, FIAGRO, FII only — CRA/CRI/OTS are not funds.
--
-- ETFs are EXCLUDED from the fund universe here. An ETF's CNPJ is an ordinary
-- cvm_fi_diario row, so without this filter ETFs would be double-counted inside
-- the FI ('Fixed Income'/'Equity') buckets. ETFs are evaluated on their own axis
-- via etf_daily / etf_latest and the etf_* functions (16_etf_analysis.sql). The
-- carve-out lives in the two FI enumerations (here and fact_fund_monthly); every
-- other fund object derives from these, so it propagates automatically.
-- =============================================================================

BEGIN;
SET statement_timeout = '5min';

CREATE OR REPLACE VIEW dim_fund AS
  SELECT
    t.cnpj,
    t.entity_type,
    t.first_period,
    t.last_period,
    t.n_reports,
    r.fund_name,       -- from cvm_fund_registry (NULL for FI/FII until pipeline runs)
    r.status,
    r.tp_fundo
  FROM (
    SELECT cnpj, 'fi' AS entity_type,
           MIN(dt_comptc) AS first_period, MAX(dt_comptc) AS last_period,
           COUNT(DISTINCT dt_comptc) AS n_reports
    FROM cvm_fi_diario d
    WHERE NOT EXISTS (SELECT 1 FROM cvm_etf_registry e WHERE e.cnpj = d.cnpj)
    GROUP BY cnpj

    UNION ALL

    SELECT cnpj, 'fidc',
           MIN(period), MAX(period), COUNT(DISTINCT period)
    FROM cvm_fidc_mensal GROUP BY cnpj

    UNION ALL

    SELECT cnpj, 'fiagro',
           MIN(period), MAX(period), COUNT(DISTINCT period)
    FROM cvm_fiagro_mensal WHERE cnpj IS NOT NULL GROUP BY cnpj

    UNION ALL

    SELECT cnpj, 'fii',
           MIN(period), MAX(period), COUNT(DISTINCT period)
    FROM cvm_fii_mensal WHERE cnpj IS NOT NULL GROUP BY cnpj

    UNION ALL

    -- FIP uses yearly grain; map to first/last day of year for consistency
    SELECT cnpj, 'fip',
           make_date(MIN(period_year), 1, 1) AS first_period,
           make_date(MAX(period_year),12,31)  AS last_period,
           COUNT(DISTINCT period_year)        AS n_reports
    FROM cvm_fip_periodic WHERE cnpj IS NOT NULL GROUP BY cnpj
  ) t
  LEFT JOIN cvm_fund_registry r
    ON r.cnpj = t.cnpj AND r.entity_type = t.entity_type;

-- Smoke check: must have at least one fund per entity type once any data is loaded
DO $$
BEGIN
  IF (SELECT COUNT(DISTINCT entity_type) FROM dim_fund) = 0 THEN
    RAISE EXCEPTION 'dim_fund smoke check failed: no rows';
  END IF;
END $$;

COMMIT;
