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
--   • fraud_screen_dormant_funds(lookback_months)          — dashboard/pages/dormant.md
--   • fraud_screen_dormant_trend(lookback_months, history_months)
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

-- ---------------------------------------------------------------------------
-- Dormant funds — FI classes that file every month and through which nothing
-- moves: zero subscriptions, zero redemptions, for p_lookback_months straight.
--
-- Two populations, told apart by the quotaholder count over the same window:
--   empty_shell     — no investor at all. A registered, filing vehicle holding
--                     nobody's money; the "CNPJ parado" waiting to be used.
--   parked_capital  — investors present, but no money in or out. Exclusive and
--                     closed structures look like this; so does capital that has
--                     simply stopped moving.
--
-- Measured 2026-09-02 (health diagnostic 16, jun–aug 2026, daily grain): 61
-- shells and 8,257 parked-capital classes out of 25,974 filing. This function
-- reads fact_fund_monthly instead of the daily tape, so it is cheap enough for
-- a dashboard build; the window is anchored on latest_complete_period('fi'),
-- never CURRENT_DATE, so a partially-filed month cannot read as "no flow".
--
-- NULL is not zero. A month whose flows or quotaholders were not reported is
-- unknown, and an unknown month disqualifies the fund from the screen rather
-- than being coalesced into stillness. A fund must also be present in EVERY
-- month of the window — a fund that filed once and was silent is "not filing",
-- a different condition that /ops owns.
--
-- FI only, on purpose: fact_fund_monthly carries captc_mes/resg_mes for the
-- open-ended family alone (NULL for fidc/fii/fip/fiagro), and "subscription"
-- is not the same act in a closed-end listed vehicle.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fraud_screen_dormant_funds(
    p_lookback_months INT DEFAULT 3
)
RETURNS TABLE (
    cnpj            TEXT,
    fund_name       TEXT,
    admin_name      TEXT,
    window_from     DATE,
    window_to       DATE,
    months_observed BIGINT,
    max_investors   INT,
    last_pl         NUMERIC,
    dormancy        TEXT
)
LANGUAGE sql STABLE SECURITY INVOKER
AS $$
    WITH bounds AS (
        SELECT latest_complete_period('fi')                                                   AS win_to,
               (latest_complete_period('fi') - (p_lookback_months - 1) * INTERVAL '1 month')::date AS win_from
    ),
    per_fund AS (
        SELECT
            f.cnpj,
            COUNT(*)                                                        AS months_observed,
            BOOL_AND(f.captc_mes IS NOT NULL AND f.resg_mes IS NOT NULL)    AS flows_reported,
            BOOL_AND(f.nr_cotst IS NOT NULL)                                AS investors_reported,
            SUM(f.captc_mes)                                                AS captacao,
            SUM(f.resg_mes)                                                 AS resgate,
            MAX(f.nr_cotst)                                                 AS max_investors,
            (ARRAY_AGG(f.vl_patrim_liq ORDER BY f.period DESC))[1]          AS last_pl
        FROM fact_fund_monthly f
        CROSS JOIN bounds b
        WHERE f.entity_type = 'fi'
          AND f.period BETWEEN b.win_from AND b.win_to
        GROUP BY f.cnpj
    )
    SELECT
        p.cnpj,
        COALESCE(r.fund_name, p.cnpj)                        AS fund_name,
        r.admin_name,
        b.win_from                                           AS window_from,
        b.win_to                                             AS window_to,
        p.months_observed,
        p.max_investors,
        p.last_pl,
        CASE WHEN p.max_investors = 0 THEN 'empty_shell'
             ELSE 'parked_capital' END                       AS dormancy
    FROM per_fund p
    CROSS JOIN bounds b
    LEFT JOIN cvm_fund_registry r ON r.cnpj = p.cnpj AND r.entity_type = 'fi'
    WHERE p.months_observed = p_lookback_months
      AND p.flows_reported
      AND p.investors_reported
      AND p.captacao = 0
      AND p.resgate  = 0
    ORDER BY p.last_pl DESC NULLS LAST
$$;

-- ---------------------------------------------------------------------------
-- Dormant trend — the same screen evaluated at every month-end over
-- p_history_months, each month looking back p_lookback_months. A RANGE frame
-- over the period date (not ROWS) so a fund missing a month has a short frame
-- and drops out, rather than three non-adjacent rows passing as three months.
-- parked_pl is the net assets sitting in parked_capital funds at that month.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fraud_screen_dormant_trend(
    p_lookback_months INT DEFAULT 3,
    p_history_months  INT DEFAULT 36
)
RETURNS TABLE (
    period          DATE,
    funds_filing    BIGINT,
    empty_shells    BIGINT,
    parked_capital  BIGINT,
    parked_pl       NUMERIC
)
LANGUAGE sql STABLE SECURITY INVOKER
AS $$
    WITH bounds AS (
        SELECT latest_complete_period('fi')                                                     AS win_to,
               (latest_complete_period('fi') - (p_history_months - 1) * INTERVAL '1 month')::date AS emit_from,
               -- the earliest emitted month still needs a full lookback frame behind it
               (latest_complete_period('fi')
                  - (p_history_months + p_lookback_months - 2) * INTERVAL '1 month')::date     AS read_from
    ),
    rows_in AS (
        SELECT f.cnpj, f.period, f.captc_mes, f.resg_mes, f.nr_cotst, f.vl_patrim_liq
        FROM fact_fund_monthly f
        CROSS JOIN bounds b
        WHERE f.entity_type = 'fi'
          AND f.period BETWEEN b.read_from AND b.win_to
    ),
    rolled AS (
        SELECT
            cnpj,
            period,
            vl_patrim_liq,
            COUNT(*)                                                     OVER w AS months_observed,
            BOOL_AND(captc_mes IS NOT NULL AND resg_mes IS NOT NULL)     OVER w AS flows_reported,
            BOOL_AND(nr_cotst IS NOT NULL)                               OVER w AS investors_reported,
            SUM(captc_mes)                                               OVER w AS captacao,
            SUM(resg_mes)                                                OVER w AS resgate,
            MAX(nr_cotst)                                                OVER w AS max_investors
        FROM rows_in
        WINDOW w AS (
            PARTITION BY cnpj
            ORDER BY period
            RANGE BETWEEN (p_lookback_months - 1) * INTERVAL '1 month' PRECEDING AND CURRENT ROW
        )
    ),
    classified AS (
        SELECT
            period,
            vl_patrim_liq,
            max_investors,
            (months_observed = p_lookback_months
             AND flows_reported AND investors_reported
             AND captacao = 0 AND resgate = 0)                           AS dormant
        FROM rolled
    )
    SELECT
        c.period,
        COUNT(*)                                                          AS funds_filing,
        COUNT(*)           FILTER (WHERE c.dormant AND c.max_investors = 0) AS empty_shells,
        COUNT(*)           FILTER (WHERE c.dormant AND c.max_investors > 0) AS parked_capital,
        SUM(c.vl_patrim_liq) FILTER (WHERE c.dormant AND c.max_investors > 0) AS parked_pl
    FROM classified c
    CROSS JOIN bounds b
    WHERE c.period >= b.emit_from
    GROUP BY c.period
    ORDER BY c.period
$$;

GRANT EXECUTE ON FUNCTION fraud_screen_dormant_funds(INT)                          TO anon, authenticated;
GRANT EXECUTE ON FUNCTION fraud_screen_dormant_trend(INT, INT)                     TO anon, authenticated;
GRANT EXECUTE ON FUNCTION fraud_screen_zombie_growth(DATE, NUMERIC, NUMERIC)      TO anon, authenticated;
GRANT EXECUTE ON FUNCTION fraud_screen_captive_vehicles(INT, INT, NUMERIC)        TO anon, authenticated;
GRANT EXECUTE ON FUNCTION fraud_screen_evergreen_aging(INT, NUMERIC, NUMERIC)     TO anon, authenticated;
GRANT EXECUTE ON FUNCTION fraud_screen_overdue_securit(NUMERIC)                   TO anon, authenticated;

COMMIT;
