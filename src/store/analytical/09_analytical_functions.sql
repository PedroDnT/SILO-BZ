-- =============================================================================
-- 09_analytical_functions.sql
-- ~20 analytical SQL functions callable via supabase.rpc().
--
-- Style contract:
--   - CREATE OR REPLACE FUNCTION
--   - LANGUAGE sql STABLE SECURITY INVOKER
--   - Returns TABLE(...) with fully typed columns
--   - All parameters have DEFAULT values (nothing required by caller)
--   - NULL parameter → "all" (no filter applied)
--   - benchmark_rate NUMERIC DEFAULT NULL → spread columns NULL when omitted
--   - Wrapped in BEGIN / SET statement_timeout / COMMIT for idempotent apply
--
-- Groups:
--   1  Discovery      — fund_profile, search_funds, new_funds_per_period
--   2  Time Series    — fund_nav_series, fund_flow_trend, industry_aum_trend
--   3  Cross-Sectional— yield_distribution, fund_ranking, market_concentration
--   4  Trend & Sector — entity_monthly_stats, cross_entity_comparison,
--                       quotaholder_trend
--   5  FIDC           — fidc_tranche_performance, fidc_delinquency_trend,
--                       fidc_subordination_trend
--   6  SECURIT        — security_issuance_trend, security_maturity_ladder,
--                       distressed_securities
--   7  Cross-Domain   — yield_universe
--   8  Data Quality   — data_coverage, ingest_log_summary
-- =============================================================================

BEGIN;
SET statement_timeout = '30s';

-- =============================================================================
-- GROUP 1 — DISCOVERY
-- =============================================================================

-- -----------------------------------------------------------------------------
-- fund_profile(p_cnpj)
-- Single-fund summary: entity type, reporting span, peak / latest AUM,
-- active flag (last report within 90 days of today).
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fund_profile(
    p_cnpj TEXT
)
RETURNS TABLE (
    cnpj                TEXT,
    entity_type         TEXT,
    fund_name           TEXT,
    status              TEXT,
    first_period        DATE,
    last_period         DATE,
    n_months_reported   BIGINT,
    peak_aum            NUMERIC,
    latest_aum          NUMERIC,
    is_active           BOOLEAN
)
LANGUAGE sql STABLE SECURITY INVOKER
AS $$
    SELECT
        d.cnpj,
        d.entity_type,
        d.fund_name,
        d.status,
        d.first_period,
        d.last_period,
        d.n_reports                                         AS n_months_reported,
        agg.peak_aum,
        agg.latest_aum,
        d.last_period >= CURRENT_DATE - INTERVAL '90 days' AS is_active
    FROM dim_fund d
    JOIN (
        SELECT
            cnpj,
            MAX(vl_patrim_liq)                              AS peak_aum,
            -- latest AUM: value at the highest period with non-null PL
            MAX(vl_patrim_liq) FILTER (
                WHERE period = (
                    SELECT MAX(f2.period)
                    FROM fact_fund_monthly f2
                    WHERE f2.cnpj = fact_fund_monthly.cnpj
                      AND f2.vl_patrim_liq IS NOT NULL
                )
            )                                               AS latest_aum
        FROM fact_fund_monthly
        WHERE cnpj = p_cnpj
        GROUP BY cnpj
    ) agg ON agg.cnpj = d.cnpj
    WHERE d.cnpj = p_cnpj
$$;


-- -----------------------------------------------------------------------------
-- search_funds(query, p_entity_type, limit_n)
-- Partial CNPJ match with optional entity-type filter and latest AUM lookup.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION search_funds(
    query         TEXT    DEFAULT '',
    p_entity_type TEXT    DEFAULT NULL,
    limit_n       INT     DEFAULT 50
)
RETURNS TABLE (
    cnpj         TEXT,
    entity_type  TEXT,
    fund_name    TEXT,
    first_period DATE,
    last_period  DATE,
    latest_aum   NUMERIC
)
LANGUAGE sql STABLE SECURITY INVOKER
AS $$
    SELECT
        d.cnpj,
        d.entity_type,
        d.fund_name,
        d.first_period,
        d.last_period,
        aum.vl_patrim_liq AS latest_aum
    FROM dim_fund d
    LEFT JOIN LATERAL (
        SELECT f.vl_patrim_liq
        FROM fact_fund_monthly f
        WHERE f.cnpj = d.cnpj
          AND f.vl_patrim_liq IS NOT NULL
        ORDER BY f.period DESC
        LIMIT 1
    ) aum ON TRUE
    WHERE (
        d.cnpj ILIKE '%' || query || '%'
        OR d.fund_name ILIKE '%' || query || '%'
    )
    AND (p_entity_type IS NULL OR d.entity_type = p_entity_type)
    ORDER BY aum.vl_patrim_liq DESC NULLS LAST
    LIMIT limit_n
$$;


-- -----------------------------------------------------------------------------
-- new_funds_per_period(entity_types, start_date, end_date)
-- Count of funds whose first_period falls in each calendar month.
-- entity_types NULL → all types.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION new_funds_per_period(
    entity_types TEXT[]  DEFAULT NULL,
    start_date   DATE    DEFAULT '2019-01-01',
    end_date     DATE    DEFAULT CURRENT_DATE
)
RETURNS TABLE (
    period      DATE,
    entity_type TEXT,
    n_new       BIGINT
)
LANGUAGE sql STABLE SECURITY INVOKER
AS $$
    SELECT
        date_trunc('month', first_period)::date AS period,
        entity_type,
        COUNT(*)                                AS n_new
    FROM dim_fund
    WHERE first_period BETWEEN start_date AND end_date
      AND (entity_types IS NULL OR entity_type = ANY(entity_types))
    GROUP BY
        date_trunc('month', first_period)::date,
        entity_type
    ORDER BY period, entity_type
$$;


-- =============================================================================
-- GROUP 2 — TIME SERIES
-- =============================================================================

-- -----------------------------------------------------------------------------
-- fund_nav_series(p_cnpj, start_date, end_date)
-- Full fact_fund_monthly row set for one fund over a date range.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fund_nav_series(
    p_cnpj     TEXT,
    start_date DATE DEFAULT '2019-01-01',
    end_date   DATE DEFAULT CURRENT_DATE
)
RETURNS TABLE (
    cnpj          TEXT,
    period        DATE,
    entity_type   TEXT,
    vl_patrim_liq NUMERIC,
    vl_quota      NUMERIC,
    nr_cotst      INT,
    vl_inadimpl   NUMERIC,
    pct_yield_mes NUMERIC,
    captc_mes     NUMERIC,
    resg_mes      NUMERIC,
    vl_ativo      NUMERIC
)
LANGUAGE sql STABLE SECURITY INVOKER
AS $$
    SELECT
        cnpj,
        period,
        entity_type,
        vl_patrim_liq,
        vl_quota,
        nr_cotst,
        vl_inadimpl,
        pct_yield_mes,
        captc_mes,
        resg_mes,
        vl_ativo
    FROM fact_fund_monthly
    WHERE cnpj = p_cnpj
      AND period BETWEEN start_date AND end_date
    ORDER BY period
$$;


-- -----------------------------------------------------------------------------
-- fund_flow_trend(p_cnpj, start_date, end_date)
-- Monthly flow decomposition with running cumulative net-flow and
-- redemption-pressure ratio. FI-only columns (captc/resg) may be NULL for
-- FIDC/FII/etc. — caller should filter on entity_type='fi'.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fund_flow_trend(
    p_cnpj     TEXT,
    start_date DATE DEFAULT '2019-01-01',
    end_date   DATE DEFAULT CURRENT_DATE
)
RETURNS TABLE (
    cnpj                  TEXT,
    period                DATE,
    captc_mes             NUMERIC,
    resg_mes              NUMERIC,
    net_flow              NUMERIC,
    cumulative_net_flow   NUMERIC,
    redemption_pressure   NUMERIC
)
LANGUAGE sql STABLE SECURITY INVOKER
AS $$
    SELECT
        cnpj,
        period,
        captc_mes,
        resg_mes,
        captc_mes - resg_mes                          AS net_flow,
        SUM(captc_mes - resg_mes) OVER (
            PARTITION BY cnpj
            ORDER BY period
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        )                                             AS cumulative_net_flow,
        resg_mes / NULLIF(vl_patrim_liq, 0)          AS redemption_pressure
    FROM fact_fund_monthly
    WHERE cnpj = p_cnpj
      AND period BETWEEN start_date AND end_date
    ORDER BY period
$$;


-- -----------------------------------------------------------------------------
-- industry_aum_trend(entity_types, start_date, end_date)
-- Aggregate AUM, fund count, and net flow per (period, entity_type).
-- entity_types NULL → all.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION industry_aum_trend(
    entity_types TEXT[]  DEFAULT NULL,
    start_date   DATE    DEFAULT '2019-01-01',
    end_date     DATE    DEFAULT CURRENT_DATE
)
RETURNS TABLE (
    period      DATE,
    entity_type TEXT,
    total_aum   NUMERIC,
    n_funds     BIGINT,
    net_flow    NUMERIC
)
LANGUAGE sql STABLE SECURITY INVOKER
AS $$
    SELECT
        period,
        entity_type,
        SUM(vl_patrim_liq)                        AS total_aum,
        COUNT(DISTINCT cnpj)                       AS n_funds,
        SUM(captc_mes - resg_mes)                  AS net_flow
    FROM fact_fund_monthly
    WHERE period BETWEEN start_date AND end_date
      AND (entity_types IS NULL OR entity_type = ANY(entity_types))
    GROUP BY period, entity_type
    ORDER BY period, entity_type
$$;


-- =============================================================================
-- GROUP 3 — CROSS-SECTIONAL
-- =============================================================================

-- -----------------------------------------------------------------------------
-- yield_distribution(p_entity_type, p_period, benchmark_rate)
-- Percentile distribution of monthly yield for one entity type and one period.
-- benchmark_rate NULL → n_above_benchmark and spread_p50 return NULL.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION yield_distribution(
    p_entity_type  TEXT,
    p_period       DATE,
    benchmark_rate NUMERIC DEFAULT NULL
)
RETURNS TABLE (
    p10                NUMERIC,
    p25                NUMERIC,
    median             NUMERIC,
    p75                NUMERIC,
    p90                NUMERIC,
    mean               NUMERIC,
    stddev             NUMERIC,
    n_funds            BIGINT,
    n_above_benchmark  BIGINT,
    spread_p50         NUMERIC
)
LANGUAGE sql STABLE SECURITY INVOKER
AS $$
    SELECT
        PERCENTILE_CONT(0.10) WITHIN GROUP (ORDER BY pct_yield_mes) AS p10,
        PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY pct_yield_mes) AS p25,
        PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY pct_yield_mes) AS median,
        PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY pct_yield_mes) AS p75,
        PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY pct_yield_mes) AS p90,
        AVG(pct_yield_mes)                                           AS mean,
        STDDEV(pct_yield_mes)                                        AS stddev,
        COUNT(*)                                                     AS n_funds,
        COUNT(*) FILTER (
            WHERE benchmark_rate IS NOT NULL
              AND pct_yield_mes > benchmark_rate
        )                                                            AS n_above_benchmark,
        CASE
            WHEN benchmark_rate IS NOT NULL
            THEN PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY pct_yield_mes)
                 - benchmark_rate
        END                                                          AS spread_p50
    FROM fact_fund_monthly
    WHERE entity_type = p_entity_type
      AND period = p_period
      AND pct_yield_mes IS NOT NULL
$$;


-- -----------------------------------------------------------------------------
-- fund_ranking(p_entity_type, p_metric, p_period, p_limit)
-- Rank funds within an entity type on a chosen metric for one period.
-- p_period NULL → latest available period for the entity type.
-- Supported metrics: aum, yield, net_flow, cotistas, inadimpl_rate,
--                    redemption_pressure.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fund_ranking(
    p_entity_type TEXT,
    p_metric      TEXT    DEFAULT 'aum',
    p_period      DATE    DEFAULT NULL,
    p_limit       INT     DEFAULT 20
)
RETURNS TABLE (
    cnpj         TEXT,
    period       DATE,
    metric_value NUMERIC,
    rank_pos     BIGINT
)
LANGUAGE sql STABLE SECURITY INVOKER
AS $$
    WITH resolved_period AS (
        SELECT COALESCE(
            p_period,
            (SELECT MAX(period) FROM fact_fund_monthly WHERE entity_type = p_entity_type)
        ) AS eff_period
    ),
    ranked AS (
        SELECT
            f.cnpj,
            f.period,
            CASE p_metric
                WHEN 'aum'                 THEN f.vl_patrim_liq
                WHEN 'yield'               THEN f.pct_yield_mes
                WHEN 'net_flow'            THEN f.captc_mes - f.resg_mes
                WHEN 'cotistas'            THEN f.nr_cotst::NUMERIC
                WHEN 'inadimpl_rate'       THEN f.vl_inadimpl / NULLIF(f.vl_patrim_liq, 0)
                WHEN 'redemption_pressure' THEN f.resg_mes   / NULLIF(f.vl_patrim_liq, 0)
                ELSE f.vl_patrim_liq
            END                            AS metric_value,
            RANK() OVER (
                ORDER BY
                    CASE p_metric
                        WHEN 'aum'                 THEN f.vl_patrim_liq
                        WHEN 'yield'               THEN f.pct_yield_mes
                        WHEN 'net_flow'            THEN f.captc_mes - f.resg_mes
                        WHEN 'cotistas'            THEN f.nr_cotst::NUMERIC
                        WHEN 'inadimpl_rate'       THEN f.vl_inadimpl / NULLIF(f.vl_patrim_liq, 0)
                        WHEN 'redemption_pressure' THEN f.resg_mes   / NULLIF(f.vl_patrim_liq, 0)
                        ELSE f.vl_patrim_liq
                    END DESC NULLS LAST
            )                              AS rank_pos
        FROM fact_fund_monthly f, resolved_period rp
        WHERE f.entity_type = p_entity_type
          AND f.period = rp.eff_period
    )
    SELECT cnpj, period, metric_value, rank_pos
    FROM ranked
    WHERE rank_pos <= p_limit
    ORDER BY rank_pos
$$;


-- -----------------------------------------------------------------------------
-- market_concentration(p_entity_type, p_period)
-- HHI and top-N AUM share for one entity type and one period.
-- p_period NULL → latest period for the entity type.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION market_concentration(
    p_entity_type TEXT,
    p_period      DATE DEFAULT NULL
)
RETURNS TABLE (
    period       DATE,
    entity_type  TEXT,
    hhi          NUMERIC,
    top5_share   NUMERIC,
    top10_share  NUMERIC,
    top20_share  NUMERIC,
    n_funds      BIGINT
)
LANGUAGE sql STABLE SECURITY INVOKER
AS $$
    WITH resolved_period AS (
        SELECT COALESCE(
            p_period,
            (SELECT MAX(f.period)
             FROM fact_fund_monthly f
             WHERE f.entity_type = p_entity_type)
        ) AS eff_period
    ),
    base AS (
        SELECT
            f.cnpj,
            f.period,
            f.vl_patrim_liq,
            SUM(f.vl_patrim_liq) OVER () AS total_aum,
            COUNT(*) OVER ()              AS n_funds,
            RANK() OVER (ORDER BY f.vl_patrim_liq DESC NULLS LAST) AS rnk
        FROM fact_fund_monthly f, resolved_period rp
        WHERE f.entity_type = p_entity_type
          AND f.period = rp.eff_period
          AND f.vl_patrim_liq IS NOT NULL
    )
    SELECT
        MAX(period)                                                    AS period,
        p_entity_type                                                  AS entity_type,
        SUM(POWER(vl_patrim_liq / NULLIF(total_aum, 0), 2)) * 10000  AS hhi,
        SUM(vl_patrim_liq) FILTER (WHERE rnk <= 5)
            / NULLIF(MAX(total_aum), 0)                               AS top5_share,
        SUM(vl_patrim_liq) FILTER (WHERE rnk <= 10)
            / NULLIF(MAX(total_aum), 0)                               AS top10_share,
        SUM(vl_patrim_liq) FILTER (WHERE rnk <= 20)
            / NULLIF(MAX(total_aum), 0)                               AS top20_share,
        MAX(n_funds)                                                   AS n_funds
    FROM base
$$;


-- =============================================================================
-- GROUP 4 — TREND & SECTOR
-- =============================================================================

-- -----------------------------------------------------------------------------
-- entity_monthly_stats(p_entity_type, start_date, end_date)
-- Monthly sector-level summary for one entity type: AUM, yield percentiles,
-- delinquency, and net flows.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION entity_monthly_stats(
    p_entity_type TEXT,
    start_date    DATE DEFAULT '2019-01-01',
    end_date      DATE DEFAULT CURRENT_DATE
)
RETURNS TABLE (
    period         DATE,
    total_aum      NUMERIC,
    n_funds        BIGINT,
    avg_aum        NUMERIC,
    median_yield   NUMERIC,
    p90_yield      NUMERIC,
    total_inadimpl NUMERIC,
    net_flow       NUMERIC
)
LANGUAGE sql STABLE SECURITY INVOKER
AS $$
    SELECT
        period,
        SUM(vl_patrim_liq)                                                     AS total_aum,
        COUNT(DISTINCT cnpj)                                                   AS n_funds,
        AVG(vl_patrim_liq)                                                     AS avg_aum,
        PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY pct_yield_mes)            AS median_yield,
        PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY pct_yield_mes)            AS p90_yield,
        SUM(vl_inadimpl)                                                       AS total_inadimpl,
        SUM(captc_mes - resg_mes)                                              AS net_flow
    FROM fact_fund_monthly
    WHERE entity_type = p_entity_type
      AND period BETWEEN start_date AND end_date
    GROUP BY period
    ORDER BY period
$$;


-- -----------------------------------------------------------------------------
-- cross_entity_comparison(entity_types, p_metric, start_date, end_date)
-- Side-by-side time series of a single metric across multiple entity types.
-- Supported metrics: aum, yield, net_flow.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION cross_entity_comparison(
    entity_types TEXT[],
    p_metric     TEXT    DEFAULT 'aum',
    start_date   DATE    DEFAULT '2019-01-01',
    end_date     DATE    DEFAULT CURRENT_DATE
)
RETURNS TABLE (
    period      DATE,
    entity_type TEXT,
    agg_value   NUMERIC,
    n_funds     BIGINT
)
LANGUAGE sql STABLE SECURITY INVOKER
AS $$
    SELECT
        period,
        entity_type,
        CASE p_metric
            WHEN 'aum'      THEN SUM(vl_patrim_liq)
            WHEN 'yield'    THEN PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY pct_yield_mes)
            WHEN 'net_flow' THEN SUM(captc_mes - resg_mes)
            ELSE SUM(vl_patrim_liq)
        END                       AS agg_value,
        COUNT(DISTINCT cnpj)      AS n_funds
    FROM fact_fund_monthly
    WHERE entity_type = ANY(entity_types)
      AND period BETWEEN start_date AND end_date
    GROUP BY period, entity_type
    ORDER BY period, entity_type
$$;


-- -----------------------------------------------------------------------------
-- quotaholder_trend(p_entity_type, start_date, end_date)
-- Monthly quotaholder count aggregated by entity type.
-- p_entity_type NULL → all entity types.
-- Only includes rows where nr_cotst IS NOT NULL.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION quotaholder_trend(
    p_entity_type TEXT  DEFAULT NULL,
    start_date    DATE  DEFAULT '2019-01-01',
    end_date      DATE  DEFAULT CURRENT_DATE
)
RETURNS TABLE (
    period                DATE,
    entity_type           TEXT,
    total_cotistas        BIGINT,
    avg_cotistas_per_fund NUMERIC,
    n_funds_with_data     BIGINT
)
LANGUAGE sql STABLE SECURITY INVOKER
AS $$
    SELECT
        period,
        entity_type,
        SUM(nr_cotst)::BIGINT         AS total_cotistas,
        AVG(nr_cotst::NUMERIC)        AS avg_cotistas_per_fund,
        COUNT(DISTINCT cnpj)          AS n_funds_with_data
    FROM fact_fund_monthly
    WHERE nr_cotst IS NOT NULL
      AND period BETWEEN start_date AND end_date
      AND (p_entity_type IS NULL OR entity_type = p_entity_type)
    GROUP BY period, entity_type
    ORDER BY period, entity_type
$$;


-- =============================================================================
-- GROUP 5 — FIDC
-- =============================================================================

-- -----------------------------------------------------------------------------
-- fidc_tranche_performance(p_cnpj, start_date, end_date)
-- Tranche-level time series for a single FIDC with performance gap
-- (actual minus expected delinquency performance).
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fidc_tranche_performance(
    p_cnpj     TEXT,
    start_date DATE DEFAULT '2019-01-01',
    end_date   DATE DEFAULT CURRENT_DATE
)
RETURNS TABLE (
    cnpj              TEXT,
    period            DATE,
    classe_serie      TEXT,
    qt_cota           NUMERIC,
    vl_cota           NUMERIC,
    vl_rentab_mes     NUMERIC,
    pr_desemp_esperado NUMERIC,
    pr_desemp_real    NUMERIC,
    fund_pl           NUMERIC,
    fund_inadimpl     NUMERIC,
    performance_gap   NUMERIC
)
LANGUAGE sql STABLE SECURITY INVOKER
AS $$
    SELECT
        cnpj,
        period,
        classe_serie,
        qt_cota,
        vl_cota,
        vl_rentab_mes,
        pr_desemp_esperado,
        pr_desemp_real,
        fund_pl,
        fund_inadimpl,
        pr_desemp_real - pr_desemp_esperado AS performance_gap
    FROM vw_fidc_tranche_detail
    WHERE cnpj = p_cnpj
      AND period BETWEEN start_date AND end_date
    ORDER BY period, classe_serie
$$;


-- -----------------------------------------------------------------------------
-- fidc_delinquency_trend(start_date, end_date, p_cnpj)
-- Monthly delinquency statistics across the FIDC universe (or one fund).
-- p_cnpj NULL → all FIDCs.
-- mom_change: month-over-month delta of avg_inadimpl_rate.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fidc_delinquency_trend(
    start_date DATE    DEFAULT '2019-01-01',
    end_date   DATE    DEFAULT CURRENT_DATE,
    p_cnpj     TEXT    DEFAULT NULL
)
RETURNS TABLE (
    period                 DATE,
    n_funds                BIGINT,
    avg_inadimpl_rate      NUMERIC,
    total_inadimpl         NUMERIC,
    pct_funds_delinquent   NUMERIC,
    pct_funds_high_delinq  NUMERIC,
    mom_change             NUMERIC
)
LANGUAGE sql STABLE SECURITY INVOKER
AS $$
    WITH base AS (
        SELECT
            period,
            COUNT(DISTINCT cnpj)                                        AS n_funds,
            AVG(vl_inadimpl / NULLIF(vl_patrim_liq, 0))                AS avg_inadimpl_rate,
            SUM(vl_inadimpl)                                            AS total_inadimpl,
            AVG(
                CASE WHEN vl_inadimpl > 0 THEN 1.0 ELSE 0.0 END
            )                                                           AS pct_funds_delinquent,
            AVG(
                CASE
                    WHEN (vl_inadimpl / NULLIF(vl_patrim_liq, 0)) > 0.05
                    THEN 1.0
                    ELSE 0.0
                END
            )                                                           AS pct_funds_high_delinq
        FROM fact_fund_monthly
        WHERE entity_type = 'fidc'
          AND period BETWEEN start_date AND end_date
          AND (p_cnpj IS NULL OR cnpj = p_cnpj)
        GROUP BY period
    )
    SELECT
        period,
        n_funds,
        avg_inadimpl_rate,
        total_inadimpl,
        pct_funds_delinquent,
        pct_funds_high_delinq,
        avg_inadimpl_rate - LAG(avg_inadimpl_rate) OVER (ORDER BY period) AS mom_change
    FROM base
    ORDER BY period
$$;


-- -----------------------------------------------------------------------------
-- fidc_subordination_trend(p_cnpj, start_date, end_date)
-- Monthly tranche structure for one FIDC: senior vs. subordinated quota counts
-- and the subordination ratio.
--
-- Senior detection: classe_serie CONTAINS 'senior'/'sênior' (not a prefix
-- match). CVM-175 (2025+) filings label every tranche "Subclasse Senior ..." /
-- "Classe Sênior ...", not a bare "Senior ..." — verified against the live
-- 2025-06 tab_X_2 file, where a prefix match ('Senior%') matched 0 of 10,760
-- rows while a substring match caught 5,355. The prefix version silently
-- classified every current-regime senior tranche as subordinated, which is
-- also why it always reported subordination_ratio = 1.0 (100%) for the
-- current period across the whole universe.
--
-- subordination_ratio is excluded (NULL), not fabricated, when qt_total is
-- non-positive or the raw ratio falls outside [0,1] — a quota-count share
-- outside that range is not a valid capital-structure reading, it means
-- qt_cota carries a dirty/outlier value for that month (schema.sql documents
-- raw TAB_X_QT_COTA reaching 6.9e13). This is what produced the >1000%
-- readings seen on historical (pre-2025) months in the trend chart.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fidc_subordination_trend(
    p_cnpj     TEXT,
    start_date DATE DEFAULT '2019-01-01',
    end_date   DATE DEFAULT CURRENT_DATE
)
RETURNS TABLE (
    period              DATE,
    cnpj                TEXT,
    n_senior_series     BIGINT,
    n_subordinada_series BIGINT,
    qt_total            NUMERIC,
    qt_senior           NUMERIC,
    qt_subordinada      NUMERIC,
    subordination_ratio NUMERIC
)
LANGUAGE sql STABLE SECURITY INVOKER
AS $$
    WITH agg AS (
        SELECT
            period,
            cnpj,
            COUNT(*) FILTER (
                WHERE classe_serie ILIKE '%senior%'
                   OR classe_serie ILIKE '%sênior%'
            )                                                               AS n_senior_series,
            COUNT(*) FILTER (
                WHERE classe_serie NOT ILIKE '%senior%'
                  AND classe_serie NOT ILIKE '%sênior%'
            )                                                               AS n_subordinada_series,
            SUM(qt_cota)                                                    AS qt_total,
            SUM(qt_cota) FILTER (
                WHERE classe_serie ILIKE '%senior%'
                   OR classe_serie ILIKE '%sênior%'
            )                                                               AS qt_senior,
            SUM(qt_cota) FILTER (
                WHERE classe_serie NOT ILIKE '%senior%'
                  AND classe_serie NOT ILIKE '%sênior%'
            )                                                               AS qt_subordinada
        FROM cvm_fidc_tranche
        WHERE cnpj = p_cnpj
          AND period BETWEEN start_date AND end_date
        GROUP BY period, cnpj
    )
    SELECT
        period,
        cnpj,
        n_senior_series,
        n_subordinada_series,
        qt_total,
        qt_senior,
        qt_subordinada,
        CASE
            WHEN qt_total > 0 AND qt_subordinada / qt_total BETWEEN 0 AND 1
                THEN qt_subordinada / qt_total
            ELSE NULL
        END AS subordination_ratio
    FROM agg
    ORDER BY period
$$;


-- =============================================================================
-- GROUP 6 — SECURIT
-- =============================================================================

-- -----------------------------------------------------------------------------
-- security_issuance_trend(p_instrument_type, start_date, end_date)
-- Monthly issuance / status snapshot per instrument type.
-- p_instrument_type NULL → all types.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION security_issuance_trend(
    p_instrument_type TEXT  DEFAULT NULL,
    start_date        DATE  DEFAULT '2021-01-01',
    end_date          DATE  DEFAULT CURRENT_DATE
)
RETURNS TABLE (
    period           DATE,
    instrument_type  TEXT,
    n_series         BIGINT,
    total_value      NUMERIC,
    n_adimplente     BIGINT,
    n_inadimplente   BIGINT
)
LANGUAGE sql STABLE SECURITY INVOKER
AS $$
    SELECT
        period,
        instrument_type,
        COUNT(*)                                                AS n_series,
        SUM(valor_certificados)                                 AS total_value,
        COUNT(*) FILTER (WHERE situacao_mes = 'Adimplente')     AS n_adimplente,
        COUNT(*) FILTER (WHERE situacao_mes = 'Inadimplente')   AS n_inadimplente
    FROM fact_security_monthly
    WHERE period BETWEEN start_date AND end_date
      AND (p_instrument_type IS NULL OR instrument_type = p_instrument_type)
    GROUP BY period, instrument_type
    ORDER BY period, instrument_type
$$;


-- -----------------------------------------------------------------------------
-- security_maturity_ladder(p_instrument_type, as_of)
-- Bucket outstanding securities by time to maturity as of a reference date.
-- p_instrument_type NULL → all types.
-- Buckets: 0-1yr, 1-3yr, 3-5yr, 5yr+, perpetual (data_vencimento IS NULL).
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION security_maturity_ladder(
    p_instrument_type TEXT  DEFAULT NULL,
    as_of             DATE  DEFAULT CURRENT_DATE
)
RETURNS TABLE (
    instrument_type TEXT,
    maturity_bucket TEXT,
    n_series        BIGINT,
    total_value     NUMERIC
)
LANGUAGE sql STABLE SECURITY INVOKER
AS $$
    SELECT
        instrument_type,
        CASE
            WHEN data_vencimento IS NULL
                THEN 'perpetual'
            WHEN data_vencimento <= as_of + INTERVAL '1 year'
                THEN '0-1yr'
            WHEN data_vencimento <= as_of + INTERVAL '3 years'
                THEN '1-3yr'
            WHEN data_vencimento <= as_of + INTERVAL '5 years'
                THEN '3-5yr'
            ELSE '5yr+'
        END                     AS maturity_bucket,
        COUNT(*)                AS n_series,
        -- dim_security does not carry valor_certificados directly;
        -- use n_reports as a proxy weight (value not available in dim layer).
        -- Callers needing total_value should use fact_security_monthly instead.
        NULL::NUMERIC           AS total_value
    FROM dim_security
    WHERE (p_instrument_type IS NULL OR instrument_type = p_instrument_type)
    GROUP BY instrument_type, maturity_bucket
    ORDER BY instrument_type, maturity_bucket
$$;


-- -----------------------------------------------------------------------------
-- distressed_securities(p_instrument_type, as_of_period)
-- All fact_security_monthly rows in distressed status for a given period.
-- as_of_period NULL → MAX(period) in fact_security_monthly.
-- Distressed statuses: Inadimplente, Em atraso, Cancelado.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION distressed_securities(
    p_instrument_type TEXT  DEFAULT NULL,
    as_of_period      DATE  DEFAULT NULL
)
RETURNS TABLE (
    cnpj_securit             TEXT,
    codigo_identificacao     TEXT,
    instrument_type          TEXT,
    period                   DATE,
    situacao_mes             TEXT,
    rentabilidade_mes        NUMERIC,
    numero_serie             INT,
    data_vencimento          DATE,
    valor_certificados       NUMERIC,
    quantidade_certificados  NUMERIC,
    recebimentos_mes         NUMERIC,
    pgt_senior_mes           NUMERIC,
    pgt_mezanino_mes         NUMERIC,
    pgt_junior_mes           NUMERIC,
    pgt_despesas_mes         NUMERIC,
    variacao_caixa_mes       NUMERIC
)
LANGUAGE sql STABLE SECURITY INVOKER
AS $$
    WITH resolved_period AS (
        SELECT COALESCE(
            as_of_period,
            (SELECT MAX(period) FROM fact_security_monthly)
        ) AS eff_period
    )
    SELECT
        s.cnpj_securit,
        s.codigo_identificacao,
        s.instrument_type,
        s.period,
        s.situacao_mes,
        s.rentabilidade_mes,
        s.numero_serie,
        s.data_vencimento,
        s.valor_certificados,
        s.quantidade_certificados,
        s.recebimentos_mes,
        s.pgt_senior_mes,
        s.pgt_mezanino_mes,
        s.pgt_junior_mes,
        s.pgt_despesas_mes,
        s.variacao_caixa_mes
    FROM fact_security_monthly s, resolved_period rp
    WHERE s.period = rp.eff_period
      AND s.situacao_mes IN ('Inadimplente', 'Em atraso', 'Cancelado')
      AND (p_instrument_type IS NULL OR s.instrument_type = p_instrument_type)
    ORDER BY s.instrument_type, s.cnpj_securit, s.codigo_identificacao
$$;


-- =============================================================================
-- GROUP 7 — CROSS-DOMAIN
-- =============================================================================

-- -----------------------------------------------------------------------------
-- yield_universe(entity_types, instrument_types, start_date, end_date,
--               benchmark_rate)
-- Unified yield table spanning fund and security universes.
-- spread_vs_benchmark is NULL when benchmark_rate is not provided.
-- entity_types  NULL → defaults to {fii, fiagro}.
-- instrument_types NULL → defaults to {cra_mensal, cri_mensal}.
--
-- The instrument_types default used to be {cra_classe, cri_classe} and matched
-- ZERO rows: 'cra_classe'/'cri_classe' are CVM doc_type names, and
-- src/pipeline/ingest_securit.py::_DOC_TO_INSTRUMENT rewrites them to
-- 'cra_mensal'/'cri_mensal' before upsert, so those are the only values that
-- ever reach cvm_securit_serie and therefore fact_security_monthly. Calling
-- yield_universe() with no arguments silently returned the fund side only.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION yield_universe(
    entity_types     TEXT[]  DEFAULT ARRAY['fii', 'fiagro'],
    instrument_types TEXT[]  DEFAULT ARRAY['cra_mensal', 'cri_mensal'],
    start_date       DATE    DEFAULT '2021-01-01',
    end_date         DATE    DEFAULT CURRENT_DATE,
    benchmark_rate   NUMERIC DEFAULT NULL
)
RETURNS TABLE (
    domain              TEXT,
    instrument          TEXT,
    identifier          TEXT,
    period              DATE,
    yield_mes           NUMERIC,
    aum                 NUMERIC,
    spread_vs_benchmark NUMERIC
)
LANGUAGE sql STABLE SECURITY INVOKER
AS $$
    -- Fund side: FII / FIAGRO (or caller-specified entity types)
    SELECT
        'fund'                                          AS domain,
        f.entity_type                                   AS instrument,
        f.cnpj                                          AS identifier,
        f.period,
        f.pct_yield_mes                                 AS yield_mes,
        f.vl_patrim_liq                                 AS aum,
        CASE
            WHEN benchmark_rate IS NOT NULL
            THEN f.pct_yield_mes - benchmark_rate
        END                                             AS spread_vs_benchmark
    FROM fact_fund_monthly f
    WHERE f.entity_type = ANY(entity_types)
      AND f.pct_yield_mes IS NOT NULL
      AND f.period BETWEEN start_date AND end_date

    UNION ALL

    -- Security side: CRA / CRI (or caller-specified instrument types)
    SELECT
        'security'                                      AS domain,
        s.instrument_type                               AS instrument,
        s.cnpj_securit || ':' || s.codigo_identificacao AS identifier,
        s.period,
        s.rentabilidade_mes                             AS yield_mes,
        s.valor_certificados                            AS aum,
        CASE
            WHEN benchmark_rate IS NOT NULL
            THEN s.rentabilidade_mes - benchmark_rate
        END                                             AS spread_vs_benchmark
    FROM fact_security_monthly s
    WHERE s.instrument_type = ANY(instrument_types)
      AND s.rentabilidade_mes IS NOT NULL
      AND s.period BETWEEN start_date AND end_date

    ORDER BY period, domain, instrument
$$;


-- =============================================================================
-- GROUP 8 — DATA QUALITY
-- =============================================================================

-- -----------------------------------------------------------------------------
-- data_coverage(p_entity_type, start_date, end_date)
-- Per-(period, entity_type) fund count and staleness indicator.
-- months_since_last_report: how many months ago the period's latest report was,
-- measured from today (useful for detecting ingestion gaps).
-- p_entity_type NULL → all entity types.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION data_coverage(
    p_entity_type TEXT  DEFAULT NULL,
    start_date    DATE  DEFAULT '2019-01-01',
    end_date      DATE  DEFAULT CURRENT_DATE
)
RETURNS TABLE (
    period                  DATE,
    entity_type             TEXT,
    n_funds                 BIGINT,
    latest_report           DATE,
    months_since_last_report INT
)
LANGUAGE sql STABLE SECURITY INVOKER
AS $$
    SELECT
        period,
        entity_type,
        COUNT(DISTINCT cnpj)                                            AS n_funds,
        MAX(period)                                                     AS latest_report,
        EXTRACT(MONTH FROM AGE(CURRENT_DATE, MAX(period)))::INT         AS months_since_last_report
    FROM fact_fund_monthly
    WHERE period BETWEEN start_date AND end_date
      AND (p_entity_type IS NULL OR entity_type = p_entity_type)
    GROUP BY period, entity_type
    ORDER BY period, entity_type
$$;


-- -----------------------------------------------------------------------------
-- ingest_log_summary(start_date, end_date)
-- Aggregated run statistics from cvm_ingest_log over a date window.
-- Default window: last 7 days.
-- Returns one row per (entity, doc_type) with run counts, row totals,
-- last run timestamp, and the most recent error message (if any).
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION ingest_log_summary(
    start_date DATE DEFAULT CURRENT_DATE - 7,
    end_date   DATE DEFAULT CURRENT_DATE
)
RETURNS TABLE (
    entity         TEXT,
    doc_type       TEXT,
    n_runs         BIGINT,
    n_ok           BIGINT,
    n_error        BIGINT,
    total_rows     BIGINT,
    last_run       TIMESTAMPTZ,
    last_error_msg TEXT
)
LANGUAGE sql STABLE SECURITY INVOKER
AS $$
    SELECT
        entity,
        doc_type,
        COUNT(*)                                                AS n_runs,
        COUNT(*) FILTER (WHERE status = 'ok')                  AS n_ok,
        COUNT(*) FILTER (WHERE status = 'error')               AS n_error,
        SUM(rows_upserted)::BIGINT                             AS total_rows,
        MAX(started_at)                                        AS last_run,
        MAX(error_msg) FILTER (WHERE status = 'error')         AS last_error_msg
    FROM cvm_ingest_log
    WHERE started_at >= start_date::TIMESTAMPTZ
      AND started_at <  (end_date + 1)::TIMESTAMPTZ
    GROUP BY entity, doc_type
    ORDER BY entity, doc_type
$$;

COMMIT;
