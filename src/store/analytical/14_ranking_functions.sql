-- =============================================================================
-- 14_ranking_functions.sql
-- RPC functions for the administrator/gestor and asset-class analytics goals.
--   • administrator_rankings(period, metric, limit)
--   • gestor_rankings(period, metric, limit)
--   • asset_class_performance(start_date, end_date, benchmark_rate)
--   • quotaholder_trend_by_class(start_date, end_date)
--
-- All are SECURITY INVOKER STABLE, matching 09/10. They aggregate
-- fact_fund_monthly joined to the registry (admin/gestor) or dim_fund_category
-- (asset_class) at a resolved period (NULL → latest period present).
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- administrator_rankings(p_period, p_metric, p_limit)
-- Rank administrators at one period by aum | n_funds | net_flow | avg_yield |
-- total_inadimpl. p_period NULL → latest period in fact_fund_monthly.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION administrator_rankings(
    p_period DATE    DEFAULT NULL,
    p_metric TEXT    DEFAULT 'aum',
    p_limit  INT     DEFAULT 20
)
RETURNS TABLE (
    admin_name     TEXT,
    period         DATE,
    n_funds        BIGINT,
    total_aum      NUMERIC,
    net_flow       NUMERIC,
    avg_yield      NUMERIC,
    total_inadimpl NUMERIC,
    metric_value   NUMERIC,
    rank_pos       BIGINT
)
LANGUAGE sql STABLE SECURITY INVOKER
AS $$
    WITH resolved_period AS (
        SELECT COALESCE(p_period, (SELECT MAX(period) FROM fact_fund_monthly)) AS eff_period
    ),
    agg AS (
        SELECT
            r.admin_name,
            rp.eff_period                                AS period,
            COUNT(DISTINCT f.cnpj)                       AS n_funds,
            SUM(f.vl_patrim_liq)                         AS total_aum,
            SUM(COALESCE(f.captc_mes, 0) - COALESCE(f.resg_mes, 0)) AS net_flow,
            AVG(f.pct_yield_mes)                         AS avg_yield,
            SUM(f.vl_inadimpl)                           AS total_inadimpl
        FROM fact_fund_monthly f
        JOIN resolved_period rp ON f.period = rp.eff_period
        JOIN cvm_fund_registry r
          ON r.cnpj = f.cnpj AND r.entity_type = f.entity_type
        WHERE r.admin_name IS NOT NULL
        GROUP BY r.admin_name, rp.eff_period
    ),
    ranked AS (
        SELECT a.*,
            CASE p_metric
                WHEN 'aum'            THEN a.total_aum
                WHEN 'n_funds'        THEN a.n_funds::NUMERIC
                WHEN 'net_flow'       THEN a.net_flow
                WHEN 'avg_yield'      THEN a.avg_yield
                WHEN 'total_inadimpl' THEN a.total_inadimpl
                ELSE a.total_aum
            END AS metric_value
        FROM agg a
    )
    SELECT
        admin_name, period, n_funds, total_aum, net_flow, avg_yield, total_inadimpl,
        metric_value,
        RANK() OVER (ORDER BY metric_value DESC NULLS LAST) AS rank_pos
    FROM ranked
    ORDER BY rank_pos
    LIMIT p_limit
$$;

-- ---------------------------------------------------------------------------
-- gestor_rankings(p_period, p_metric, p_limit) — same shape, grouped by gestor
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION gestor_rankings(
    p_period DATE    DEFAULT NULL,
    p_metric TEXT    DEFAULT 'aum',
    p_limit  INT     DEFAULT 20
)
RETURNS TABLE (
    gestor_name    TEXT,
    period         DATE,
    n_funds        BIGINT,
    total_aum      NUMERIC,
    net_flow       NUMERIC,
    avg_yield      NUMERIC,
    total_inadimpl NUMERIC,
    metric_value   NUMERIC,
    rank_pos       BIGINT
)
LANGUAGE sql STABLE SECURITY INVOKER
AS $$
    WITH resolved_period AS (
        SELECT COALESCE(p_period, (SELECT MAX(period) FROM fact_fund_monthly)) AS eff_period
    ),
    agg AS (
        SELECT
            r.gestor_name,
            rp.eff_period                                AS period,
            COUNT(DISTINCT f.cnpj)                       AS n_funds,
            SUM(f.vl_patrim_liq)                         AS total_aum,
            SUM(COALESCE(f.captc_mes, 0) - COALESCE(f.resg_mes, 0)) AS net_flow,
            AVG(f.pct_yield_mes)                         AS avg_yield,
            SUM(f.vl_inadimpl)                           AS total_inadimpl
        FROM fact_fund_monthly f
        JOIN resolved_period rp ON f.period = rp.eff_period
        JOIN cvm_fund_registry r
          ON r.cnpj = f.cnpj AND r.entity_type = f.entity_type
        WHERE r.gestor_name IS NOT NULL
        GROUP BY r.gestor_name, rp.eff_period
    ),
    ranked AS (
        SELECT a.*,
            CASE p_metric
                WHEN 'aum'            THEN a.total_aum
                WHEN 'n_funds'        THEN a.n_funds::NUMERIC
                WHEN 'net_flow'       THEN a.net_flow
                WHEN 'avg_yield'      THEN a.avg_yield
                WHEN 'total_inadimpl' THEN a.total_inadimpl
                ELSE a.total_aum
            END AS metric_value
        FROM agg a
    )
    SELECT
        gestor_name, period, n_funds, total_aum, net_flow, avg_yield, total_inadimpl,
        metric_value,
        RANK() OVER (ORDER BY metric_value DESC NULLS LAST) AS rank_pos
    FROM ranked
    ORDER BY rank_pos
    LIMIT p_limit
$$;

-- ---------------------------------------------------------------------------
-- asset_class_performance(start_date, end_date, benchmark_rate)
-- Time series per conformed asset_class: AUM, fund count, median yield,
-- net flow, total cotistas, and optional yield spread vs a benchmark (% pts).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION asset_class_performance(
    start_date     DATE    DEFAULT '2019-01-01',
    end_date       DATE    DEFAULT CURRENT_DATE,
    benchmark_rate NUMERIC DEFAULT NULL
)
RETURNS TABLE (
    period          DATE,
    asset_class     TEXT,
    n_funds         BIGINT,
    total_aum       NUMERIC,
    median_yield    NUMERIC,
    net_flow        NUMERIC,
    total_cotistas  BIGINT,
    yield_spread_pp NUMERIC
)
LANGUAGE sql STABLE SECURITY INVOKER
AS $$
    SELECT
        f.period,
        c.asset_class,
        COUNT(DISTINCT f.cnpj)                                              AS n_funds,
        SUM(f.vl_patrim_liq)                                               AS total_aum,
        percentile_cont(0.5) WITHIN GROUP (ORDER BY f.pct_yield_mes)        AS median_yield,
        SUM(COALESCE(f.captc_mes, 0) - COALESCE(f.resg_mes, 0))            AS net_flow,
        SUM(f.nr_cotst)::BIGINT                                             AS total_cotistas,
        CASE WHEN benchmark_rate IS NULL THEN NULL
             ELSE percentile_cont(0.5) WITHIN GROUP (ORDER BY f.pct_yield_mes) - benchmark_rate
        END                                                                AS yield_spread_pp
    FROM fact_fund_monthly f
    JOIN dim_fund_category c
      ON c.cnpj = f.cnpj AND c.entity_type = f.entity_type
    WHERE f.period BETWEEN start_date AND end_date
    GROUP BY f.period, c.asset_class
    ORDER BY f.period, c.asset_class
$$;

-- ---------------------------------------------------------------------------
-- quotaholder_trend_by_class(start_date, end_date)
-- Investor-growth (nr_cotst) rolled up by conformed asset_class over time.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION quotaholder_trend_by_class(
    start_date DATE DEFAULT '2019-01-01',
    end_date   DATE DEFAULT CURRENT_DATE
)
RETURNS TABLE (
    period                DATE,
    asset_class           TEXT,
    total_cotistas        BIGINT,
    avg_cotistas_per_fund NUMERIC,
    n_funds_with_data     BIGINT
)
LANGUAGE sql STABLE SECURITY INVOKER
AS $$
    SELECT
        f.period,
        c.asset_class,
        SUM(f.nr_cotst)::BIGINT   AS total_cotistas,
        AVG(f.nr_cotst::NUMERIC)  AS avg_cotistas_per_fund,
        COUNT(DISTINCT f.cnpj)    AS n_funds_with_data
    FROM fact_fund_monthly f
    JOIN dim_fund_category c
      ON c.cnpj = f.cnpj AND c.entity_type = f.entity_type
    WHERE f.nr_cotst IS NOT NULL
      AND f.period BETWEEN start_date AND end_date
    GROUP BY f.period, c.asset_class
    ORDER BY f.period, c.asset_class
$$;

GRANT EXECUTE ON FUNCTION administrator_rankings(DATE, TEXT, INT)        TO anon, authenticated;
GRANT EXECUTE ON FUNCTION gestor_rankings(DATE, TEXT, INT)              TO anon, authenticated;
GRANT EXECUTE ON FUNCTION asset_class_performance(DATE, DATE, NUMERIC)  TO anon, authenticated;
GRANT EXECUTE ON FUNCTION quotaholder_trend_by_class(DATE, DATE)        TO anon, authenticated;

COMMIT;
