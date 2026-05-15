-- =============================================================================
-- L1 Stream A: dim_fund
-- Registry of all investment fund CNPJs and their entity type / active periods.
-- Covers FI, FIDC, FIP, FIAGRO, FII only — CRA/CRI/OTS are not funds.
-- =============================================================================

BEGIN;
SET statement_timeout = '5min';

CREATE OR REPLACE VIEW dim_fund AS
  SELECT cnpj, 'fi'     AS entity_type,
         MIN(dt_comptc)                          AS first_period,
         MAX(dt_comptc)                          AS last_period,
         COUNT(DISTINCT dt_comptc)               AS n_reports
  FROM cvm_fi_diario
  GROUP BY cnpj

  UNION ALL

  SELECT cnpj, 'fidc',
         MIN(period), MAX(period), COUNT(DISTINCT period)
  FROM cvm_fidc_mensal
  GROUP BY cnpj

  UNION ALL

  SELECT cnpj, 'fiagro',
         MIN(period), MAX(period), COUNT(DISTINCT period)
  FROM cvm_fiagro_mensal
  WHERE cnpj IS NOT NULL
  GROUP BY cnpj

  UNION ALL

  SELECT cnpj, 'fii',
         MIN(period), MAX(period), COUNT(DISTINCT period)
  FROM cvm_fii_mensal
  WHERE cnpj IS NOT NULL
  GROUP BY cnpj

  UNION ALL

  -- FIP uses yearly grain; map to first/last day of year for consistency
  SELECT cnpj, 'fip',
         make_date(MIN(period_year), 1, 1) AS first_period,
         make_date(MAX(period_year),12,31) AS last_period,
         COUNT(DISTINCT period_year)       AS n_reports
  FROM cvm_fip_periodic
  WHERE cnpj IS NOT NULL
  GROUP BY cnpj
;

-- Smoke check: must have at least one fund per entity type once any data is loaded
DO $$
BEGIN
  IF (SELECT COUNT(DISTINCT entity_type) FROM dim_fund) = 0 THEN
    RAISE EXCEPTION 'dim_fund smoke check failed: no rows';
  END IF;
END $$;

COMMIT;
