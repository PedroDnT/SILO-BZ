-- =============================================================================
-- 15_fraud_screens.sql
-- Promote the dashboard's ad-hoc "suspicious deal" SQL (dashboard/pages/
-- suspicious.md) into reusable, parameterised RPC functions so the dashboard and
-- the analytical layer share ONE definition of each screen.
--
--   • fraud_screen_zombie_growth(period, min_delinq_pct, min_aum)
--   • fraud_screen_captive_vehicles(period_lookback_months, max_investors, min_aum)
--   • fraud_screen_evergreen_aging(lookback_months, min_longtail_pct, max_variation_pp)
--   • fraud_screen_overdue_securit(min_volume)
--
-- These are signals, not verdicts — always confirm against primary sources.
-- Delinquency-acceleration is already covered by fidc_delinquency_screen() in
-- 10_analytical_functions_advanced.sql.
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- Zombie growth — FIDCs with delinquency > X% still carrying meaningful AUM.
-- p_period NULL → latest aging period.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fraud_screen_zombie_growth(
    p_period        DATE    DEFAULT NULL,
    min_delinq_pct  NUMERIC DEFAULT 5,
    min_aum         NUMERIC DEFAULT 1e6
)
RETURNS TABLE (
    cnpj      TEXT,
    fund_name TEXT,
    period    DATE,
    pl_mm     NUMERIC,
    inad_pct  NUMERIC
)
LANGUAGE sql STABLE SECURITY INVOKER
AS $$
    WITH rp AS (
        SELECT COALESCE(p_period, (SELECT MAX(period) FROM cvm_fidc_aging)) AS eff_period
    )
    SELECT
        a.cnpj,
        COALESCE(r.fund_name, a.cnpj)                                    AS fund_name,
        a.period,
        m.vl_patrim_liq / 1e6                                           AS pl_mm,
        ROUND(100.0 * a.vl_total_inad / NULLIF(m.vl_patrim_liq, 0), 1)  AS inad_pct
    FROM cvm_fidc_aging a
    JOIN rp ON a.period = rp.eff_period
    JOIN cvm_fidc_mensal m USING (cnpj, period)
    LEFT JOIN cvm_fund_registry r ON r.cnpj = a.cnpj AND r.entity_type = 'fidc'
    WHERE m.vl_patrim_liq > min_aum
      AND 100.0 * a.vl_total_inad / NULLIF(m.vl_patrim_liq, 0) > min_delinq_pct
    ORDER BY pl_mm DESC NULLS LAST
$$;

-- ---------------------------------------------------------------------------
-- Captive vehicles — FIIs with high AUM but very few investors (single-LP).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fraud_screen_captive_vehicles(
    p_lookback_months INT     DEFAULT 3,
    max_investors     INT     DEFAULT 10,
    min_aum           NUMERIC DEFAULT 5e7
)
RETURNS TABLE (
    cnpj          TEXT,
    fund_name     TEXT,
    latest_period DATE,
    pl_mm         NUMERIC,
    min_investors INT
)
LANGUAGE sql STABLE SECURITY INVOKER
AS $$
    SELECT
        m.cnpj,
        COALESCE(MAX(r.fund_name), m.cnpj)  AS fund_name,
        MAX(m.period)                       AS latest_period,
        MAX(m.vl_patrim_liq) / 1e6          AS pl_mm,
        MIN(m.nr_cotst)                     AS min_investors
    FROM cvm_fii_mensal m
    LEFT JOIN cvm_fund_registry r ON r.cnpj = m.cnpj AND r.entity_type = 'fii'
    WHERE m.doc_subtype = 'complemento'
      AND m.period >= CURRENT_DATE - make_interval(months => p_lookback_months)
    GROUP BY m.cnpj
    HAVING MIN(m.nr_cotst) < max_investors AND MAX(m.vl_patrim_liq) > min_aum
    ORDER BY pl_mm DESC NULLS LAST
$$;

-- ---------------------------------------------------------------------------
-- Evergreen aging — FIDCs where long-tail (>1080d) delinquency stays high and
-- barely moves: credits rolled, not resolved.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fraud_screen_evergreen_aging(
    p_lookback_months INT     DEFAULT 12,
    min_longtail_pct  NUMERIC DEFAULT 70,
    max_variation_pp  NUMERIC DEFAULT 10
)
RETURNS TABLE (
    cnpj             TEXT,
    fund_name        TEXT,
    months_observed  BIGINT,
    min_longtail_pct NUMERIC,
    max_longtail_pct NUMERIC
)
LANGUAGE sql STABLE SECURITY INVOKER
AS $$
    SELECT
        a.cnpj,
        COALESCE(MAX(r.fund_name), a.cnpj) AS fund_name,
        COUNT(DISTINCT a.period)           AS months_observed,
        MIN(ROUND(100.0 * a.vl_inad_maior_1080 / NULLIF(a.vl_total_inad, 0), 1)) AS min_longtail_pct,
        MAX(ROUND(100.0 * a.vl_inad_maior_1080 / NULLIF(a.vl_total_inad, 0), 1)) AS max_longtail_pct
    FROM cvm_fidc_aging a
    LEFT JOIN cvm_fund_registry r ON r.cnpj = a.cnpj AND r.entity_type = 'fidc'
    WHERE a.period >= CURRENT_DATE - make_interval(months => p_lookback_months)
      AND a.vl_total_inad > 1e5
    GROUP BY a.cnpj
    HAVING MAX(ROUND(100.0 * a.vl_inad_maior_1080 / NULLIF(a.vl_total_inad, 0), 1)) > min_longtail_pct
       AND MAX(ROUND(100.0 * a.vl_inad_maior_1080 / NULLIF(a.vl_total_inad, 0), 1))
         - MIN(ROUND(100.0 * a.vl_inad_maior_1080 / NULLIF(a.vl_total_inad, 0), 1)) < max_variation_pp
    ORDER BY max_longtail_pct DESC NULLS LAST
$$;

-- ---------------------------------------------------------------------------
-- Overdue securit — CRA/CRI/OTS series past maturity but not marked terminal.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fraud_screen_overdue_securit(
    min_volume NUMERIC DEFAULT 1e5
)
RETURNS TABLE (
    instrument_type      TEXT,
    cnpj_securit         TEXT,
    codigo_identificacao TEXT,
    data_vencimento      DATE,
    situacao             TEXT,
    volume_mm            NUMERIC,
    rating               TEXT
)
LANGUAGE sql STABLE SECURITY INVOKER
AS $$
    SELECT
        s.instrument_type,
        s.cnpj_securit,
        s.codigo_identificacao,
        s.data_vencimento,
        s.situacao,
        s.valor_total_integralizado / 1e6  AS volume_mm,
        s.classificacao_risco_atual         AS rating
    FROM cvm_securit_serie s
    WHERE s.data_vencimento < CURRENT_DATE
      AND s.situacao NOT IN ('Cancelado', 'Vencido', 'Liquidado', 'Encerrado')
      AND s.valor_total_integralizado > min_volume
    ORDER BY s.data_vencimento ASC
$$;

GRANT EXECUTE ON FUNCTION fraud_screen_zombie_growth(DATE, NUMERIC, NUMERIC)      TO anon, authenticated;
GRANT EXECUTE ON FUNCTION fraud_screen_captive_vehicles(INT, INT, NUMERIC)        TO anon, authenticated;
GRANT EXECUTE ON FUNCTION fraud_screen_evergreen_aging(INT, NUMERIC, NUMERIC)     TO anon, authenticated;
GRANT EXECUTE ON FUNCTION fraud_screen_overdue_securit(NUMERIC)                   TO anon, authenticated;

COMMIT;
