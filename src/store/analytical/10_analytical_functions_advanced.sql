-- =============================================================================
-- 10_analytical_functions_advanced.sql
-- Advanced FIDC analytics: aging buckets, delinquency screening,
-- flow-vs-delinquency, senior tranche benchmarking.
--
-- New functions (callable via RPC):
--   GROUP 9 — FIDC ADVANCED
--   fidc_aging_buckets         — aging bucket evolution for one fund over time
--   fidc_aging_universe        — universe screen by long-tail concentration
--   fidc_delinquency_screen    — per-fund acceleration screen across the universe
--   fidc_flow_vs_delinquency   — net capital flow alongside delinquency for one fund
--   fidc_senior_vs_benchmark   — senior tranche returns vs a benchmark rate
-- =============================================================================

BEGIN;
SET statement_timeout = '30s';

-- =============================================================================
-- GROUP 9 — FIDC ADVANCED
-- =============================================================================

-- -----------------------------------------------------------------------------
-- fidc_aging_buckets(p_cnpj, start_date, end_date)
-- Aging bucket evolution for one FIDC over time.
-- Shows how credits migrate into longer-duration delinquency buckets.
-- A growing pct_inad_361_plus is an early stress signal — credits that old
-- are rarely recovered and represent permanent loss embedded in the portfolio.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fidc_aging_buckets(
    p_cnpj     TEXT,
    start_date DATE DEFAULT CURRENT_DATE - INTERVAL '2 years',
    end_date   DATE DEFAULT CURRENT_DATE
)
RETURNS TABLE (
    cnpj              TEXT,
    period            DATE,
    vl_total_inad     NUMERIC,
    pct_inad_0_30     NUMERIC,
    pct_inad_31_90    NUMERIC,
    pct_inad_91_180   NUMERIC,
    pct_inad_181_360  NUMERIC,
    pct_inad_361_plus NUMERIC,
    vl_long_tail      NUMERIC,
    fund_pl           NUMERIC,
    inadimpl_rate     NUMERIC
)
LANGUAGE sql STABLE SECURITY INVOKER
AS $$
    SELECT
        a.cnpj,
        a.period,
        a.vl_total_inad,
        CASE WHEN a.vl_total_inad > 0 THEN
            ROUND(COALESCE(a.vl_inad_30, 0) / a.vl_total_inad * 100, 2)
        END                                                           AS pct_inad_0_30,
        CASE WHEN a.vl_total_inad > 0 THEN
            ROUND(
                (COALESCE(a.vl_inad_60, 0) + COALESCE(a.vl_inad_90, 0)) /
                a.vl_total_inad * 100, 2
            )
        END                                                           AS pct_inad_31_90,
        CASE WHEN a.vl_total_inad > 0 THEN
            ROUND(
                (COALESCE(a.vl_inad_120, 0) + COALESCE(a.vl_inad_150, 0) +
                 COALESCE(a.vl_inad_180, 0)) /
                a.vl_total_inad * 100, 2
            )
        END                                                           AS pct_inad_91_180,
        CASE WHEN a.vl_total_inad > 0 THEN
            ROUND(COALESCE(a.vl_inad_360, 0) / a.vl_total_inad * 100, 2)
        END                                                           AS pct_inad_181_360,
        CASE WHEN a.vl_total_inad > 0 THEN
            ROUND(
                (COALESCE(a.vl_inad_720, 0) + COALESCE(a.vl_inad_1080, 0) +
                 COALESCE(a.vl_inad_maior_1080, 0)) /
                a.vl_total_inad * 100, 2
            )
        END                                                           AS pct_inad_361_plus,
        COALESCE(a.vl_inad_720, 0) + COALESCE(a.vl_inad_1080, 0) +
        COALESCE(a.vl_inad_maior_1080, 0)                            AS vl_long_tail,
        m.vl_patrim_liq                                               AS fund_pl,
        CASE WHEN m.vl_patrim_liq > 0 THEN
            ROUND(a.vl_total_inad / m.vl_patrim_liq * 100, 4)
        END                                                           AS inadimpl_rate
    FROM cvm_fidc_aging a
    LEFT JOIN cvm_fidc_mensal m ON m.cnpj = a.cnpj AND m.period = a.period
    WHERE a.cnpj = p_cnpj
      AND a.period BETWEEN start_date AND end_date
      AND a.vl_total_inad IS NOT NULL
    ORDER BY a.period
$$;


-- -----------------------------------------------------------------------------
-- fidc_aging_universe(p_period, limit_n)
-- Universe screen: ranks FIDCs by concentration of long-tail (360+ day)
-- delinquency relative to total delinquency and PL.
-- Funds with high pct_long_tail are accumulating unrecoverable credit —
-- a risk that headline inadimpl_rate alone does not reveal.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fidc_aging_universe(
    p_period DATE    DEFAULT NULL,
    limit_n  INT     DEFAULT 20
)
RETURNS TABLE (
    cnpj          TEXT,
    fund_name     TEXT,
    period        DATE,
    vl_total_inad NUMERIC,
    inadimpl_rate NUMERIC,
    pct_long_tail NUMERIC,
    vl_long_tail  NUMERIC,
    fund_pl       NUMERIC
)
LANGUAGE sql STABLE SECURITY INVOKER
AS $$
    WITH target_period AS (
        SELECT COALESCE(p_period, MAX(period)) AS period FROM cvm_fidc_aging
    ),
    aging AS (
        SELECT
            a.cnpj,
            a.period,
            a.vl_total_inad,
            COALESCE(a.vl_inad_720, 0) + COALESCE(a.vl_inad_1080, 0) +
            COALESCE(a.vl_inad_maior_1080, 0)                           AS vl_long_tail,
            m.vl_patrim_liq                                              AS fund_pl,
            CASE WHEN m.vl_patrim_liq > 0 THEN
                ROUND(a.vl_total_inad / m.vl_patrim_liq * 100, 4)
            END                                                          AS inadimpl_rate,
            CASE WHEN a.vl_total_inad > 0 THEN
                ROUND(
                    (COALESCE(a.vl_inad_720, 0) + COALESCE(a.vl_inad_1080, 0) +
                     COALESCE(a.vl_inad_maior_1080, 0)) /
                    a.vl_total_inad * 100, 2
                )
            END                                                          AS pct_long_tail
        FROM cvm_fidc_aging a
        JOIN target_period t ON a.period = t.period
        LEFT JOIN cvm_fidc_mensal m ON m.cnpj = a.cnpj AND m.period = a.period
        WHERE a.vl_total_inad > 0
    )
    SELECT
        ag.cnpj,
        d.fund_name,
        ag.period,
        ag.vl_total_inad,
        ag.inadimpl_rate,
        ag.pct_long_tail,
        ag.vl_long_tail,
        ag.fund_pl
    FROM aging ag
    LEFT JOIN dim_fund d ON d.cnpj = ag.cnpj AND d.entity_type = 'fidc'
    ORDER BY ag.pct_long_tail DESC NULLS LAST
    LIMIT limit_n
$$;


-- -----------------------------------------------------------------------------
-- fidc_delinquency_screen(p_period, lookback_months, min_acceleration_pp)
-- Per-fund delinquency acceleration screen across the FIDC universe.
-- Returns funds where inadimpl_rate rose >= min_acceleration_pp percentage
-- points over the lookback window — an early warning before stress is public.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fidc_delinquency_screen(
    p_period            DATE    DEFAULT NULL,
    lookback_months     INT     DEFAULT 3,
    min_acceleration_pp NUMERIC DEFAULT 1.0
)
RETURNS TABLE (
    cnpj               TEXT,
    fund_name          TEXT,
    period_current     DATE,
    period_prior       DATE,
    inadimpl_rate_now  NUMERIC,
    inadimpl_rate_then NUMERIC,
    acceleration_pp    NUMERIC,
    vl_inadimpl_now    NUMERIC,
    fund_pl_now        NUMERIC
)
LANGUAGE sql STABLE SECURITY INVOKER
AS $$
    WITH target AS (
        SELECT COALESCE(p_period, MAX(period)) AS period FROM cvm_fidc_mensal
    ),
    current_snap AS (
        SELECT
            m.cnpj,
            m.period,
            m.vl_inadimpl,
            m.vl_patrim_liq,
            CASE WHEN m.vl_patrim_liq > 0 THEN
                ROUND(m.vl_inadimpl / m.vl_patrim_liq * 100, 4)
            END AS inadimpl_rate
        FROM cvm_fidc_mensal m
        JOIN target t ON m.period = t.period
        WHERE m.vl_inadimpl IS NOT NULL AND m.vl_patrim_liq > 0
    ),
    prior_snap AS (
        SELECT
            m.cnpj,
            m.period,
            CASE WHEN m.vl_patrim_liq > 0 THEN
                ROUND(m.vl_inadimpl / m.vl_patrim_liq * 100, 4)
            END AS inadimpl_rate
        FROM cvm_fidc_mensal m
        JOIN target t
          ON m.period = (t.period - (lookback_months || ' months')::interval)::date
        WHERE m.vl_inadimpl IS NOT NULL AND m.vl_patrim_liq > 0
    )
    SELECT
        c.cnpj,
        d.fund_name,
        c.period                                              AS period_current,
        p.period                                              AS period_prior,
        c.inadimpl_rate                                       AS inadimpl_rate_now,
        p.inadimpl_rate                                       AS inadimpl_rate_then,
        ROUND(c.inadimpl_rate - p.inadimpl_rate, 4)          AS acceleration_pp,
        c.vl_inadimpl                                         AS vl_inadimpl_now,
        c.vl_patrim_liq                                       AS fund_pl_now
    FROM current_snap c
    JOIN prior_snap p ON p.cnpj = c.cnpj
    LEFT JOIN dim_fund d ON d.cnpj = c.cnpj AND d.entity_type = 'fidc'
    WHERE (c.inadimpl_rate - p.inadimpl_rate) >= min_acceleration_pp
    ORDER BY (c.inadimpl_rate - p.inadimpl_rate) DESC
$$;


-- -----------------------------------------------------------------------------
-- fidc_flow_vs_delinquency(p_cnpj, start_date, end_date)
-- Monthly net capital flow (subscriptions minus redemptions across all tranches)
-- alongside delinquency rate for one FIDC.
-- Reveals whether investors are responding to credit stress or still flowing in.
-- tp_oper values matched on CAPT/RESG prefix (CVM convention).
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fidc_flow_vs_delinquency(
    p_cnpj     TEXT,
    start_date DATE DEFAULT CURRENT_DATE - INTERVAL '2 years',
    end_date   DATE DEFAULT CURRENT_DATE
)
RETURNS TABLE (
    cnpj          TEXT,
    period        DATE,
    gross_subscr  NUMERIC,
    gross_redempt NUMERIC,
    net_flow      NUMERIC,
    vl_inadimpl   NUMERIC,
    inadimpl_rate NUMERIC,
    fund_pl       NUMERIC
)
LANGUAGE sql STABLE SECURITY INVOKER
AS $$
    WITH flows AS (
        SELECT
            cnpj,
            period,
            SUM(CASE WHEN UPPER(tp_oper) LIKE '%CAPT%' THEN vl_total ELSE 0 END) AS gross_subscr,
            SUM(CASE WHEN UPPER(tp_oper) LIKE '%RESG%' THEN vl_total ELSE 0 END) AS gross_redempt
        FROM cvm_fidc_tranche_flows
        WHERE cnpj = p_cnpj
          AND period BETWEEN start_date AND end_date
        GROUP BY cnpj, period
    )
    SELECT
        m.cnpj,
        m.period,
        COALESCE(f.gross_subscr,  0)                                  AS gross_subscr,
        COALESCE(f.gross_redempt, 0)                                  AS gross_redempt,
        COALESCE(f.gross_subscr, 0) - COALESCE(f.gross_redempt, 0)   AS net_flow,
        m.vl_inadimpl,
        CASE WHEN m.vl_patrim_liq > 0 THEN
            ROUND(m.vl_inadimpl / m.vl_patrim_liq * 100, 4)
        END                                                            AS inadimpl_rate,
        m.vl_patrim_liq                                                AS fund_pl
    FROM cvm_fidc_mensal m
    LEFT JOIN flows f ON f.cnpj = m.cnpj AND f.period = m.period
    WHERE m.cnpj = p_cnpj
      AND m.period BETWEEN start_date AND end_date
    ORDER BY m.period
$$;


-- -----------------------------------------------------------------------------
-- fidc_senior_vs_benchmark(benchmark_rate, start_date, end_date, limit_n)
-- FIDC senior tranche monthly returns vs a benchmark rate (e.g. CDI % a.a.).
-- Caller provides benchmark_rate as annual %; converted to monthly equivalent.
-- spread_pp = vl_rentab_mes - benchmark_monthly (in percentage points).
-- Outlier filter: ABS(vl_rentab_mes) >= 10 excluded (raw CVM data artifacts).
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fidc_senior_vs_benchmark(
    benchmark_rate NUMERIC DEFAULT NULL,
    start_date     DATE    DEFAULT CURRENT_DATE - INTERVAL '1 year',
    end_date       DATE    DEFAULT CURRENT_DATE,
    limit_n        INT     DEFAULT 50
)
RETURNS TABLE (
    cnpj                 TEXT,
    fund_name            TEXT,
    period               DATE,
    classe_serie         TEXT,
    vl_rentab_mes        NUMERIC,
    benchmark_rate_month NUMERIC,
    spread_pp            NUMERIC,
    fund_pl              NUMERIC,
    fund_inadimpl_rate   NUMERIC
)
LANGUAGE sql STABLE SECURITY INVOKER
AS $$
    WITH bm AS (
        SELECT CASE WHEN benchmark_rate IS NOT NULL THEN
            ROUND(((1.0 + benchmark_rate / 100.0) ^ (1.0 / 12.0) - 1.0) * 100.0, 6)
        END AS monthly_rate
    )
    SELECT
        t.cnpj,
        d.fund_name,
        t.period,
        t.classe_serie,
        t.vl_rentab_mes,
        bm.monthly_rate                                                  AS benchmark_rate_month,
        CASE WHEN benchmark_rate IS NOT NULL AND t.vl_rentab_mes IS NOT NULL THEN
            ROUND(t.vl_rentab_mes - bm.monthly_rate, 6)
        END                                                              AS spread_pp,
        m.vl_patrim_liq                                                  AS fund_pl,
        CASE WHEN m.vl_patrim_liq > 0 THEN
            ROUND(m.vl_inadimpl / m.vl_patrim_liq * 100, 4)
        END                                                              AS fund_inadimpl_rate
    FROM cvm_fidc_tranche t
    CROSS JOIN bm
    LEFT JOIN cvm_fidc_mensal m ON m.cnpj = t.cnpj AND m.period = t.period
    LEFT JOIN dim_fund d         ON d.cnpj  = t.cnpj AND d.entity_type = 'fidc'
    WHERE t.period BETWEEN start_date AND end_date
      AND t.vl_rentab_mes IS NOT NULL
      AND ABS(t.vl_rentab_mes) < 10
      AND (
          t.classe_serie ILIKE '%Senior%'
          OR t.classe_serie ILIKE '%Sênior%'
      )
    ORDER BY t.period DESC, t.cnpj, t.classe_serie
    LIMIT limit_n
$$;

COMMIT;
