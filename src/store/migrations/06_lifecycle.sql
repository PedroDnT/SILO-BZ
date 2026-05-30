-- 06_lifecycle.sql — retain discontinued instruments + active/inactive flags
--
-- Goal: survivorship-bias-free analysis. Discontinued instruments are kept in
-- the DB (we never delete on re-ingest) and surfaced with an is_active flag.
--
--   cvm_fund_registry.is_active — derived from CVM status/SIT at ingest
--                                 (dt_cancel is already populated from cad_fi).
--   instrument_activity (view)  — lifecycle for EVERY entity, including those
--                                 with no cadastral file (FIDC/FIP/FIAGRO/
--                                 SECURIT): first/last reported period per
--                                 (entity_type, cnpj) derived from the data
--                                 tables, with is_active from recency.
--
-- All statements are idempotent and single-statement. No semicolons in comments.

ALTER TABLE cvm_fund_registry ADD COLUMN IF NOT EXISTS is_active BOOLEAN;

CREATE INDEX IF NOT EXISTS idx_fund_registry_active ON cvm_fund_registry (entity_type, is_active);

-- Per-instrument lifecycle derived from actual reporting. Heavy on first run
-- (scans the data tables) — materialise downstream if it becomes hot.
CREATE OR REPLACE VIEW instrument_activity AS
WITH activity AS (
    SELECT 'fi'::text AS entity_type, cnpj, 'daily'::text AS granularity,
           MIN(dt_comptc) AS first_period, MAX(dt_comptc) AS last_period, COUNT(*) AS n_obs
    FROM cvm_fi_diario
    GROUP BY cnpj
    UNION ALL
    SELECT 'fidc', cnpj, 'monthly', MIN(period), MAX(period), COUNT(*)
    FROM cvm_fidc_mensal
    GROUP BY cnpj
    UNION ALL
    SELECT 'fiagro', cnpj, 'monthly', MIN(period), MAX(period), COUNT(*)
    FROM cvm_fiagro_mensal
    GROUP BY cnpj
    UNION ALL
    SELECT 'fii', cnpj, 'monthly', MIN(period), MAX(period), COUNT(*)
    FROM cvm_fii_mensal
    GROUP BY cnpj
    UNION ALL
    SELECT 'fip', cnpj, 'yearly',
           make_date(MIN(period_year), 12, 1), make_date(MAX(period_year), 12, 1), COUNT(*)
    FROM cvm_fip_periodic
    WHERE cnpj IS NOT NULL
    GROUP BY cnpj
    UNION ALL
    SELECT 'securit', cnpj_securit, 'yearly',
           make_date(MIN(period_year), 12, 1), make_date(MAX(period_year), 12, 1), COUNT(*)
    FROM cvm_securit_mensal
    WHERE cnpj_securit IS NOT NULL
    GROUP BY cnpj_securit
)
SELECT
    entity_type,
    cnpj,
    granularity,
    first_period,
    last_period,
    n_obs,
    CASE
        WHEN granularity = 'yearly'
            THEN last_period >= make_date(EXTRACT(YEAR FROM CURRENT_DATE)::int - 1, 1, 1)
        ELSE last_period >= (date_trunc('month', CURRENT_DATE)::date - INTERVAL '3 months')
    END AS is_active
FROM activity;
