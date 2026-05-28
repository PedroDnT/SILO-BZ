-- FIDC advanced analytics: aging buckets, delinquency acceleration, flow correlation
-- psql $DATABASE_URL -f scripts/queries/10_fidc_advanced.sql

-- =============================================================================
-- 1. UNIVERSE AGING SCREEN
-- Rank FIDCs by long-tail (360+ day) delinquency concentration.
-- Funds with high pct_long_tail carry embedded losses the headline rate hides.
-- =============================================================================
SELECT
    cnpj,
    fund_name,
    period,
    ROUND(inadimpl_rate, 2)  AS inadimpl_rate_pct,
    ROUND(pct_long_tail, 1)  AS pct_361_plus,
    vl_total_inad,
    vl_long_tail,
    fund_pl
FROM fidc_aging_universe(NULL, 20)
ORDER BY pct_long_tail DESC;


-- =============================================================================
-- 2. DELINQUENCY ACCELERATION SCREEN
-- Funds where inadimpl_rate rose >= 1pp over the last 3 months.
-- Increase lookback_months to 6 for a slower signal with fewer false positives.
-- =============================================================================
SELECT
    cnpj,
    fund_name,
    inadimpl_rate_now,
    inadimpl_rate_then,
    ROUND(acceleration_pp, 2)  AS acceleration_pp,
    ROUND(fund_pl_now / 1e6, 1) AS fund_pl_m
FROM fidc_delinquency_screen(
    NULL,   -- p_period: NULL = latest available
    3,      -- lookback_months
    1.0     -- min_acceleration_pp
)
ORDER BY acceleration_pp DESC
LIMIT 25;


-- =============================================================================
-- 3. COMBINED STRESS SIGNAL
-- FIDCs flagged by BOTH accelerating delinquency AND high long-tail concentration.
-- The intersection is the highest-conviction watch list.
-- =============================================================================
SELECT
    sc.cnpj,
    sc.fund_name,
    sc.inadimpl_rate_now,
    sc.acceleration_pp,
    au.pct_long_tail,
    au.vl_long_tail,
    ROUND(sc.fund_pl_now / 1e6, 1) AS fund_pl_m
FROM fidc_delinquency_screen(NULL, 3, 0.5) sc
JOIN fidc_aging_universe(NULL, 500) au ON au.cnpj = sc.cnpj
WHERE au.pct_long_tail > 30
ORDER BY sc.acceleration_pp DESC;


-- =============================================================================
-- 4. SINGLE-FUND AGING BUCKET EVOLUTION
-- Track how delinquency migrates into longer buckets over time for one FIDC.
-- Replace CNPJ before running.
-- =============================================================================
SELECT
    period,
    ROUND(inadimpl_rate, 2)    AS inadimpl_rate_pct,
    vl_total_inad,
    pct_inad_0_30,
    pct_inad_31_90,
    pct_inad_91_180,
    pct_inad_181_360,
    pct_inad_361_plus,
    vl_long_tail,
    ROUND(fund_pl / 1e6, 1)   AS fund_pl_m
FROM fidc_aging_buckets(
    '07727002000126',          -- replace with target CNPJ
    CURRENT_DATE - 730,
    CURRENT_DATE
)
ORDER BY period;


-- =============================================================================
-- 5. NET FLOW vs DELINQUENCY
-- Monthly subscriptions minus redemptions alongside delinquency rate.
-- Negative net_flow + rising inadimpl_rate = investors are leaving.
-- Positive net_flow + rising inadimpl_rate = investors still flowing in blind.
-- Replace CNPJ before running.
-- =============================================================================
SELECT
    period,
    ROUND(gross_subscr  / 1e6, 2) AS subscr_m,
    ROUND(gross_redempt / 1e6, 2) AS redempt_m,
    ROUND(net_flow      / 1e6, 2) AS net_flow_m,
    ROUND(inadimpl_rate, 2)       AS inadimpl_rate_pct,
    ROUND(fund_pl       / 1e6, 1) AS fund_pl_m
FROM fidc_flow_vs_delinquency(
    '07727002000126',              -- replace with target CNPJ
    CURRENT_DATE - 730,
    CURRENT_DATE
)
ORDER BY period;


-- =============================================================================
-- 6. SENIOR TRANCHE RETURNS vs CDI
-- Update benchmark_rate to current CDI a.a. before running.
-- spread_pp > 0 = outperforming benchmark on that month.
-- Also surfaces fund_inadimpl_rate so you can see if yield is risk-adjusted.
-- =============================================================================
SELECT
    period,
    cnpj,
    fund_name,
    classe_serie,
    ROUND(vl_rentab_mes, 4)        AS rentab_mes_pct,
    ROUND(benchmark_rate_month, 4) AS cdi_month_pct,
    ROUND(spread_pp, 4)            AS spread_pp,
    ROUND(fund_inadimpl_rate, 2)   AS inadimpl_rate_pct,
    ROUND(fund_pl / 1e6, 1)       AS fund_pl_m
FROM fidc_senior_vs_benchmark(
    10.75,                         -- CDI a.a. — update to current rate
    CURRENT_DATE - 365,
    CURRENT_DATE,
    100
)
ORDER BY period DESC, spread_pp DESC;


-- =============================================================================
-- 7. MARKET-WIDE DELINQUENCY TREND (existing function, included for context)
-- =============================================================================
SELECT
    period,
    n_funds,
    ROUND(avg_inadimpl_rate, 4) AS avg_inadimpl_rate_pct,
    total_inadimpl,
    pct_funds_delinquent,
    pct_funds_high_delinq,
    mom_change
FROM fidc_delinquency_trend(CURRENT_DATE - 730, CURRENT_DATE)
ORDER BY period DESC;
