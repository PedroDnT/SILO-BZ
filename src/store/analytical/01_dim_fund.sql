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

-- dim_fund is MATERIALIZED: the FI branch aggregates the full cvm_fi_diario
-- history and fund_performance_ranking (17) joins it twice, so a plain view cost
-- minutes per call. It is refreshed after ingest (08_cron_schedules) and rebuilt
-- by the daily apply_analytical re-create. CASCADE drops the dependent
-- classification views (dim_fund_category / dim_administrator / dim_gestor);
-- 13_dim_classification rebuilds them in the same apply pass.
DO $$
DECLARE k "char" := (SELECT relkind FROM pg_class WHERE oid = to_regclass('public.dim_fund'));
BEGIN
  IF k = 'm' THEN
    EXECUTE 'DROP MATERIALIZED VIEW dim_fund CASCADE';
  ELSIF k IS NOT NULL THEN
    EXECUTE 'DROP VIEW dim_fund CASCADE';
  END IF;
END $$;

CREATE MATERIALIZED VIEW dim_fund AS
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

-- Unique index → fast joins from dim_fund_category / fund_performance_ranking and
-- enables REFRESH MATERIALIZED VIEW CONCURRENTLY (08_cron_schedules).
CREATE UNIQUE INDEX ix_dim_fund_pk ON dim_fund (cnpj, entity_type);

-- Smoke check: must have at least one fund per entity type once any data is loaded.
-- CI compile runs (sql-compile job) apply this layer against an EMPTY throwaway
-- Postgres purely to prove the DDL builds; they set silo.ci_smoke_bypass=on via
-- PGOPTIONS, which downgrades the empty-data failure to a warning. Production
-- applies never set the GUC, so the guard still hard-fails there.
DO $$
BEGIN
  IF (SELECT COUNT(DISTINCT entity_type) FROM dim_fund) = 0 THEN
    IF current_setting('silo.ci_smoke_bypass', true) = 'on' THEN
      RAISE WARNING 'dim_fund smoke check skipped: no rows (silo.ci_smoke_bypass=on)';
    ELSE
      RAISE EXCEPTION 'dim_fund smoke check failed: no rows';
    END IF;
  END IF;
END $$;

COMMIT;
