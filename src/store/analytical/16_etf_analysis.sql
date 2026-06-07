-- =============================================================================
-- 16_etf_analysis.sql
-- ETF-only analytics. ETFs are evaluated SEPARATELY from ordinary funds: they are
-- carved out of dim_fund / fact_fund_monthly (see 01 / 04) and analysed here on
-- their own axis, over:
--   • etf_daily  — cvm_etf_registry ⋈ cvm_fi_diario (NAV/quota, AUM, flows, daily
--                  return); one row per (ticker, dt_comptc).
--   • anbima_etf_class_monthly — ANBIMA boletim class metrics (RF=225 / RV=226 /
--                  category), R$ milhões; rentabilidade in percentage points.
--
-- Functions (all SECURITY INVOKER STABLE, matching 09/10/14):
--   • etf_performance_series(ticker, start, end)         — HORIZONTAL (one ETF over time)
--   • etf_performance_ranking(start, end, segment, metric, limit) — VERTICAL (rank ETFs)
--   • etf_class_performance(start, end)                  — ANBIMA RF/RV/category time series
-- =============================================================================

BEGIN;
SET statement_timeout = '60s';

-- ---------------------------------------------------------------------------
-- etf_performance_series(p_ticker, start_date, end_date) — HORIZONTAL
-- One ETF's daily trajectory: NAV/quota, AUM, flows, daily return, and a
-- cumulative return rebased to the first day in range. Cumulative is taken from
-- the quota level itself (vl_quota already compounds), so it needs no log math.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION etf_performance_series(
    p_ticker   TEXT,
    start_date DATE DEFAULT '2019-01-01',
    end_date   DATE DEFAULT CURRENT_DATE
)
RETURNS TABLE (
    ticker            TEXT,
    dt_comptc         DATE,
    vl_quota          NUMERIC,
    aum               NUMERIC,
    quotaholders      INT,
    net_flow          NUMERIC,
    daily_return      NUMERIC,
    cumulative_return NUMERIC
)
LANGUAGE sql STABLE SECURITY INVOKER
AS $$
    SELECT
        ticker,
        dt_comptc,
        vl_quota,
        aum,
        quotaholders,
        net_flow,
        daily_return,
        vl_quota / NULLIF(first_value(vl_quota) OVER (ORDER BY dt_comptc), 0) - 1
            AS cumulative_return
    FROM etf_daily
    WHERE ticker = p_ticker
      AND dt_comptc BETWEEN start_date AND end_date
      AND vl_quota IS NOT NULL
    ORDER BY dt_comptc
$$;

-- ---------------------------------------------------------------------------
-- etf_performance_ranking(start_date, end_date, p_segment, p_metric, p_limit)
-- VERTICAL: rank ETFs over a window by total quota return (default), latest AUM,
-- avg daily net flow, or daily-return volatility. NULL dates → trailing 12 months
-- ending at the latest etf_daily date, so "which ETF beat its peers over the last
-- year" is the default; pass explicit dates for a calendar year. p_segment filters
-- to one B3 segment. Total return = last quota / first quota − 1 in the window.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION etf_performance_ranking(
    start_date DATE DEFAULT NULL,
    end_date   DATE DEFAULT NULL,
    p_segment  TEXT DEFAULT NULL,
    p_metric   TEXT DEFAULT 'return',
    p_limit    INT  DEFAULT 20
)
RETURNS TABLE (
    rank_pos         BIGINT,
    ticker           TEXT,
    fund_name        TEXT,
    provider         TEXT,
    underlying_index TEXT,
    segment          TEXT,
    as_of            DATE,
    n_obs            BIGINT,
    total_return     NUMERIC,
    aum_end          NUMERIC,
    avg_net_flow     NUMERIC,
    daily_vol        NUMERIC,
    metric_value     NUMERIC
)
LANGUAGE sql STABLE SECURITY INVOKER
AS $$
    WITH win AS (
        SELECT
            COALESCE(end_date, (SELECT MAX(dt_comptc) FROM etf_daily))                       AS d_end,
            COALESCE(start_date,
                     (COALESCE(end_date, (SELECT MAX(dt_comptc) FROM etf_daily))
                      - INTERVAL '12 months')::date)                                          AS d_start
    ),
    scoped AS (
        SELECT e.*
        FROM etf_daily e CROSS JOIN win
        WHERE e.dt_comptc BETWEEN win.d_start AND win.d_end
          AND e.vl_quota IS NOT NULL
          AND (p_segment IS NULL OR e.segment = p_segment)
    ),
    first_q AS (
        SELECT DISTINCT ON (ticker) ticker, vl_quota AS q_first
        FROM scoped ORDER BY ticker, dt_comptc
    ),
    last_q AS (
        SELECT DISTINCT ON (ticker)
               ticker, vl_quota AS q_last, aum AS aum_end, dt_comptc AS as_of,
               fund_name, provider, underlying_index, segment
        FROM scoped ORDER BY ticker, dt_comptc DESC
    ),
    agg AS (
        SELECT ticker, COUNT(*) AS n_obs, AVG(net_flow) AS avg_net_flow,
               stddev_samp(daily_return) AS daily_vol
        FROM scoped GROUP BY ticker
    ),
    perf AS (
        SELECT
            l.ticker, l.fund_name, l.provider, l.underlying_index, l.segment, l.as_of,
            a.n_obs,
            l.q_last / NULLIF(f.q_first, 0) - 1 AS total_return,
            l.aum_end, a.avg_net_flow, a.daily_vol,
            CASE p_metric
                WHEN 'return'   THEN l.q_last / NULLIF(f.q_first, 0) - 1
                WHEN 'aum'      THEN l.aum_end
                WHEN 'net_flow' THEN a.avg_net_flow
                WHEN 'vol'      THEN a.daily_vol
                ELSE l.q_last / NULLIF(f.q_first, 0) - 1
            END AS metric_value
        FROM last_q l
        JOIN first_q f USING (ticker)
        JOIN agg     a USING (ticker)
        WHERE a.n_obs >= 2
    )
    SELECT
        RANK() OVER (ORDER BY metric_value DESC NULLS LAST) AS rank_pos,
        ticker, fund_name, provider, underlying_index, segment, as_of, n_obs,
        total_return, aum_end, avg_net_flow, daily_vol, metric_value
    FROM perf
    WHERE metric_value IS NOT NULL
    ORDER BY rank_pos
    LIMIT p_limit
$$;

-- ---------------------------------------------------------------------------
-- etf_class_performance(start_date, end_date)
-- ANBIMA ETF class time series — RF (225) / RV (226) / category aggregate — with
-- AUM, net flow, and return pivoted from the long anbima_etf_class_monthly table.
-- Monetary values are R$ milhões as published; rentabilidade is percentage points.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION etf_class_performance(
    start_date DATE DEFAULT '2019-01-01',
    end_date   DATE DEFAULT CURRENT_DATE
)
RETURNS TABLE (
    reference_date        DATE,
    anbima_type_id        INT,
    anbima_type_name      TEXT,
    pl_brl_mm             NUMERIC,
    net_flow_brl_mm       NUMERIC,
    net_flow_12m_brl_mm   NUMERIC,
    rentabilidade_pct     NUMERIC,
    rentabilidade_12m_pct NUMERIC,
    fund_count            NUMERIC
)
LANGUAGE sql STABLE SECURITY INVOKER
AS $$
    SELECT
        reference_date,
        anbima_type_id,
        anbima_type_name,
        MAX(value) FILTER (WHERE metric = 'pl_brl_mm')                   AS pl_brl_mm,
        MAX(value) FILTER (WHERE metric = 'captacao_liquida_brl_mm')     AS net_flow_brl_mm,
        MAX(value) FILTER (WHERE metric = 'captacao_liquida_12m_brl_mm') AS net_flow_12m_brl_mm,
        MAX(value) FILTER (WHERE metric = 'rentabilidade_pct')           AS rentabilidade_pct,
        MAX(value) FILTER (WHERE metric = 'rentabilidade_12m_pct')       AS rentabilidade_12m_pct,
        MAX(value) FILTER (WHERE metric = 'fund_count')                  AS fund_count
    FROM anbima_etf_class_monthly
    WHERE reference_date BETWEEN start_date AND end_date
    GROUP BY reference_date, anbima_type_id, anbima_type_name
    ORDER BY reference_date, anbima_type_name
$$;

GRANT EXECUTE ON FUNCTION etf_performance_series(TEXT, DATE, DATE)           TO anon, authenticated;
GRANT EXECUTE ON FUNCTION etf_performance_ranking(DATE, DATE, TEXT, TEXT, INT) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION etf_class_performance(DATE, DATE)                  TO anon, authenticated;

COMMIT;
