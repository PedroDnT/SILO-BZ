-- =============================================================================
-- 17_performance_analysis.sql
-- Per-asset-class performance on two axes, over fact_fund_monthly ⋈
-- dim_fund_category (both already EXCLUDE ETFs — see 01/04; ETFs are ranked
-- separately in 16_etf_analysis.sql):
--   • fund_performance_series(cnpj, start, end)            — HORIZONTAL (one fund over time)
--   • fund_performance_ranking(asset_class, start, end, …) — VERTICAL ("who beat their peers")
--
-- Return basis is per entity_type and is RETURNED as a column, never conflated:
--   • FI                : quota return   — last/first vl_quota − 1 (a true NAV return)
--   • FII               : dividend yield — compounded monthly pct_yield_mes
--   • FIDC/FIAGRO/FIP   : pl_growth      — last/first vl_patrim_liq − 1; labelled as
--                         GROWTH, not a clean return (it conflates flows), because these
--                         families publish no quota/return. Compare within a class, on
--                         its own basis; do not compare a quota_return to a pl_growth.
--
-- All SECURITY INVOKER STABLE, matching 09/10/14.
-- =============================================================================

BEGIN;
SET statement_timeout = '60s';

-- ---------------------------------------------------------------------------
-- fund_performance_series(p_cnpj, start_date, end_date) — HORIZONTAL
-- One fund's per-period return and cumulative return on its class basis. For FI
-- and PL-growth families the cumulative is the level rebased to the first period
-- (exact); for FII it is the compounded monthly dividend yield.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fund_performance_series(
    p_cnpj     TEXT,
    start_date DATE DEFAULT '2019-01-01',
    end_date   DATE DEFAULT CURRENT_DATE
)
RETURNS TABLE (
    cnpj              TEXT,
    period            DATE,
    entity_type       TEXT,
    asset_class       TEXT,
    return_basis      TEXT,
    level_value       NUMERIC,
    vl_patrim_liq     NUMERIC,
    period_return     NUMERIC,
    cumulative_return NUMERIC
)
LANGUAGE sql STABLE SECURITY INVOKER
AS $$
    WITH f AS (
        SELECT
            m.cnpj, m.period, m.entity_type, m.vl_patrim_liq, m.vl_quota, m.pct_yield_mes,
            c.asset_class
        FROM fact_fund_monthly m
        LEFT JOIN dim_fund_category c
          ON c.cnpj = m.cnpj AND c.entity_type = m.entity_type
        WHERE m.cnpj = p_cnpj
          AND m.period BETWEEN start_date AND end_date
    ),
    r AS (
        SELECT
            f.*,
            CASE entity_type
                WHEN 'fi'  THEN vl_quota      / NULLIF(lag(vl_quota)      OVER w, 0) - 1
                WHEN 'fii' THEN pct_yield_mes / 100.0
                ELSE            vl_patrim_liq / NULLIF(lag(vl_patrim_liq) OVER w, 0) - 1
            END AS period_return
        FROM f
        WINDOW w AS (ORDER BY period)
    )
    SELECT
        cnpj, period, entity_type, asset_class,
        CASE entity_type WHEN 'fi' THEN 'quota_return'
                         WHEN 'fii' THEN 'dividend_yield'
                         ELSE 'pl_growth' END                       AS return_basis,
        COALESCE(vl_quota, vl_patrim_liq)                           AS level_value,
        vl_patrim_liq,
        period_return,
        CASE WHEN entity_type = 'fii'
             THEN exp(sum(ln(1 + GREATEST(COALESCE(period_return, 0), -0.99))) OVER (ORDER BY period)) - 1
             ELSE COALESCE(vl_quota, vl_patrim_liq)
                  / NULLIF(first_value(COALESCE(vl_quota, vl_patrim_liq)) OVER (ORDER BY period), 0) - 1
        END                                                         AS cumulative_return
    FROM r
    ORDER BY period
$$;

-- ---------------------------------------------------------------------------
-- fund_performance_ranking(p_asset_class, start_date, end_date, p_entity_type,
--                          p_limit, p_min_obs)
-- VERTICAL: window total performance per fund, RANK()ed WITHIN each asset_class
-- (top p_limit per class) with its percentile. NULL dates → trailing 12 months
-- ending at the latest period; pass a calendar year for "who beat their peers in
-- <year>". p_asset_class / p_entity_type filter scope; p_min_obs drops funds with
-- too few observations to compute a return.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fund_performance_ranking(
    p_asset_class TEXT DEFAULT NULL,
    start_date    DATE DEFAULT NULL,
    end_date      DATE DEFAULT NULL,
    p_entity_type TEXT DEFAULT NULL,
    p_limit       INT  DEFAULT 50,
    p_min_obs     INT  DEFAULT 2
)
RETURNS TABLE (
    rank_in_class     BIGINT,
    pctile_in_class   NUMERIC,
    asset_class       TEXT,
    entity_type       TEXT,
    cnpj              TEXT,
    fund_name         TEXT,
    return_basis      TEXT,
    as_of             DATE,
    n_obs             BIGINT,
    total_performance NUMERIC,
    aum_end           NUMERIC
)
LANGUAGE sql STABLE SECURITY INVOKER
AS $$
    WITH win AS (
        SELECT
            COALESCE(end_date, (SELECT MAX(period) FROM fact_fund_monthly))                  AS d_end,
            COALESCE(start_date,
                     (COALESCE(end_date, (SELECT MAX(period) FROM fact_fund_monthly))
                      - INTERVAL '12 months')::date)                                          AS d_start
    ),
    scoped AS (
        SELECT m.cnpj, m.entity_type, m.period, m.vl_patrim_liq, m.vl_quota, m.pct_yield_mes,
               c.asset_class
        FROM fact_fund_monthly m
        JOIN dim_fund_category c
          ON c.cnpj = m.cnpj AND c.entity_type = m.entity_type
        CROSS JOIN win
        WHERE m.period BETWEEN win.d_start AND win.d_end
          AND (p_asset_class IS NULL OR c.asset_class = p_asset_class)
          AND (p_entity_type IS NULL OR m.entity_type  = p_entity_type)
    ),
    first_row AS (
        SELECT DISTINCT ON (cnpj, entity_type)
               cnpj, entity_type, vl_quota AS q_first, vl_patrim_liq AS pl_first
        FROM scoped ORDER BY cnpj, entity_type, period
    ),
    last_row AS (
        SELECT DISTINCT ON (cnpj, entity_type)
               cnpj, entity_type, asset_class, period AS as_of,
               vl_quota AS q_last, vl_patrim_liq AS pl_last
        FROM scoped ORDER BY cnpj, entity_type, period DESC
    ),
    agg AS (
        SELECT cnpj, entity_type, COUNT(*) AS n_obs,
               exp(sum(ln(1 + GREATEST(COALESCE(pct_yield_mes, 0) / 100.0, -0.99)))) - 1
                   AS yield_compounded
        FROM scoped GROUP BY cnpj, entity_type
    ),
    perf AS (
        SELECT
            l.cnpj, l.entity_type, l.asset_class, l.as_of, a.n_obs,
            CASE l.entity_type
                WHEN 'fi'  THEN l.q_last  / NULLIF(f.q_first, 0)  - 1
                WHEN 'fii' THEN a.yield_compounded
                ELSE            l.pl_last / NULLIF(f.pl_first, 0) - 1
            END AS total_performance,
            CASE l.entity_type WHEN 'fi' THEN 'quota_return'
                               WHEN 'fii' THEN 'dividend_yield'
                               ELSE 'pl_growth' END AS return_basis,
            l.pl_last AS aum_end
        FROM last_row l
        JOIN first_row f USING (cnpj, entity_type)
        JOIN agg       a USING (cnpj, entity_type)
        WHERE a.n_obs >= p_min_obs
    ),
    ranked AS (
        SELECT
            p.*,
            d.fund_name,
            RANK() OVER (PARTITION BY p.asset_class ORDER BY p.total_performance DESC NULLS LAST)
                AS rank_in_class,
            ROUND((PERCENT_RANK() OVER (
                     PARTITION BY p.asset_class ORDER BY p.total_performance ASC))::numeric, 4)
                AS pctile_in_class
        FROM perf p
        LEFT JOIN dim_fund d ON d.cnpj = p.cnpj AND d.entity_type = p.entity_type
    )
    SELECT
        rank_in_class, pctile_in_class, asset_class, entity_type, cnpj, fund_name,
        return_basis, as_of, n_obs, total_performance, aum_end
    FROM ranked
    WHERE rank_in_class <= p_limit
    ORDER BY asset_class, rank_in_class
$$;

GRANT EXECUTE ON FUNCTION fund_performance_series(TEXT, DATE, DATE)                    TO anon, authenticated;
GRANT EXECUTE ON FUNCTION fund_performance_ranking(TEXT, DATE, DATE, TEXT, INT, INT)   TO anon, authenticated;

COMMIT;
