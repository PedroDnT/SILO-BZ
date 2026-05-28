-- =============================================================================
-- SUSPICIOUS DEAL SCREENS
-- Patterns that can obscure actual financial health:
--   1. Cross-fund circular holdings (FoF masking AUM)
--   2. Zombie funds: AUM grows while delinquency accelerates
--   3. Pre-disclosure redemption spikes
--   4. Captive vehicles (high AUM, almost no investors)
--   5. Evergreen aging (credits never migrating to longer buckets)
--   6. Subordination erosion (junior being wiped, senior still priced fine)
--   7. Senior tranche yield decoupled from fund stress
--   8. Securit series overdue but still "em curso"
-- =============================================================================


-- =============================================================================
-- 1. CROSS-FUND CIRCULAR HOLDINGS
-- FI funds whose portfolio is >50% invested in other funds (tp_aplic = 'FI*').
-- These FoF chains can inflate industry AUM and hide the ultimate underlying asset.
-- Use raw JSONB when tp_aplic label varies — check your actual CVM coding first.
-- =============================================================================
WITH latest_cda AS (
    SELECT cnpj, MAX(period) AS max_period
    FROM cvm_fi_cda
    GROUP BY cnpj
),
fund_on_fund AS (
    SELECT
        c.cnpj,
        c.period,
        SUM(c.vl_merc_pos_final)
            FILTER (WHERE c.tp_ativo ILIKE 'FUNDO%' OR c.tp_aplic ILIKE '%fundo%')
            AS vl_in_funds,
        SUM(c.vl_merc_pos_final) AS vl_total_portfolio
    FROM cvm_fi_cda c
    JOIN latest_cda lc ON lc.cnpj = c.cnpj AND lc.max_period = c.period
    GROUP BY c.cnpj, c.period
)
SELECT
    f.cnpj,
    f.period,
    ROUND(f.vl_in_funds / 1e6, 2)       AS vl_in_funds_m,
    ROUND(f.vl_total_portfolio / 1e6, 2) AS vl_portfolio_m,
    ROUND(100.0 * f.vl_in_funds / NULLIF(f.vl_total_portfolio, 0), 1) AS pct_in_funds,
    d.vl_patrim_liq / 1e6                AS fund_pl_m
FROM fund_on_fund f
JOIN cvm_fi_diario d ON d.cnpj = f.cnpj
    AND d.dt_comptc = (
        SELECT MAX(dt_comptc) FROM cvm_fi_diario WHERE cnpj = f.cnpj
    )
WHERE f.vl_in_funds / NULLIF(f.vl_total_portfolio, 0) > 0.5
  AND f.vl_total_portfolio > 10e6   -- ignore tiny funds
ORDER BY pct_in_funds DESC
LIMIT 30;


-- =============================================================================
-- 2. ZOMBIE FUNDS — PL growing while delinquency accelerates
-- New capital flowing into a distressed FIDC masks embedded losses.
-- Signal: inadimpl_rate rose >= 2pp over 6 months AND net AUM grew.
-- =============================================================================
WITH periods AS (
    SELECT DISTINCT period FROM cvm_fidc_mensal
    ORDER BY period DESC LIMIT 7  -- last 6 months + current
),
bounds AS (
    SELECT MAX(period) AS t_now, MIN(period) AS t_then FROM periods
),
snapshot AS (
    SELECT
        m.cnpj,
        m.period,
        m.vl_patrim_liq,
        m.vl_inadimpl,
        ROUND(100.0 * m.vl_inadimpl / NULLIF(m.vl_patrim_liq, 0), 2) AS inadimpl_rate
    FROM cvm_fidc_mensal m, bounds b
    WHERE m.period IN (b.t_now, b.t_then)
)
SELECT
    now_.cnpj,
    now_.period                                        AS period_now,
    then_.period                                       AS period_then,
    ROUND(now_.inadimpl_rate, 2)                       AS inadimpl_now_pct,
    ROUND(then_.inadimpl_rate, 2)                      AS inadimpl_then_pct,
    ROUND(now_.inadimpl_rate - then_.inadimpl_rate, 2) AS acceleration_pp,
    ROUND(now_.vl_patrim_liq / 1e6, 1)                AS pl_now_m,
    ROUND(then_.vl_patrim_liq / 1e6, 1)               AS pl_then_m,
    ROUND((now_.vl_patrim_liq - then_.vl_patrim_liq) / 1e6, 1) AS pl_delta_m
FROM snapshot now_
JOIN snapshot then_ ON then_.cnpj = now_.cnpj
JOIN bounds b ON now_.period = b.t_now AND then_.period = b.t_then
WHERE now_.inadimpl_rate - then_.inadimpl_rate >= 2.0   -- 2pp acceleration
  AND now_.vl_patrim_liq > then_.vl_patrim_liq          -- AUM still grew
  AND now_.vl_patrim_liq > 50e6                          -- material size
ORDER BY acceleration_pp DESC
LIMIT 25;


-- =============================================================================
-- 3. PRE-DISCLOSURE REDEMPTION SPIKE
-- Large redemption surge in FI funds in the month before a FIDC delinquency jump.
-- Pattern: smart money (insiders?) exits just before bad data appears in CVM.
-- Works for FI funds that invest in FIDCs — crosses cvm_fi_diario + cvm_fidc_mensal.
-- =============================================================================
WITH fidc_delinq_jump AS (
    -- FIDCs where delinquency rose sharply month-over-month
    SELECT
        cnpj,
        period,
        vl_inadimpl,
        vl_patrim_liq,
        ROUND(100.0 * vl_inadimpl / NULLIF(vl_patrim_liq, 0), 2)         AS inadimpl_rate,
        ROUND(100.0 * LAG(vl_inadimpl / NULLIF(vl_patrim_liq, 0))
                       OVER (PARTITION BY cnpj ORDER BY period), 2)        AS inadimpl_prev,
        ROUND(100.0 * (
            vl_inadimpl / NULLIF(vl_patrim_liq, 0)
          - LAG(vl_inadimpl / NULLIF(vl_patrim_liq, 0))
              OVER (PARTITION BY cnpj ORDER BY period)
        ), 2)                                                               AS jump_pp
    FROM cvm_fidc_mensal
    WHERE vl_patrim_liq > 0
),
big_jumps AS (
    SELECT cnpj AS fidc_cnpj, period AS jump_period, jump_pp, inadimpl_rate
    FROM fidc_delinq_jump
    WHERE jump_pp >= 3.0  -- 3pp single-month jump
),
fi_redemptions AS (
    -- FI funds: total redemptions in the month BEFORE the FIDC jump
    SELECT
        d.cnpj               AS fi_cnpj,
        DATE_TRUNC('month', d.dt_comptc)::DATE AS month,
        SUM(d.resg_dia)      AS total_redemption,
        SUM(d.captc_dia)     AS total_subscription,
        SUM(d.resg_dia - d.captc_dia) AS net_outflow
    FROM cvm_fi_diario d
    GROUP BY 1, 2
)
-- Cross-reference: FI funds that had large outflows the month before a FIDC jump.
-- The join on CDA (portfolio holdings) is ideal but expensive; this version shows
-- the universe-level signal. Filter by fi_cnpj if you know which FIs hold FIDCs.
SELECT
    j.fidc_cnpj,
    j.jump_period,
    ROUND(j.jump_pp, 2)        AS delinq_jump_pp,
    ROUND(j.inadimpl_rate, 2)  AS inadimpl_rate_pct,
    r.fi_cnpj,
    ROUND(r.net_outflow / 1e6, 2) AS fi_net_outflow_m
FROM big_jumps j
JOIN fi_redemptions r
    ON r.month = DATE_TRUNC('month', j.jump_period - INTERVAL '1 month')::DATE
WHERE r.net_outflow > 5e6      -- material outflow
ORDER BY j.jump_pp DESC, r.net_outflow DESC
LIMIT 40;


-- =============================================================================
-- 4. CAPTIVE VEHICLES — high AUM, almost no investors
-- Funds with < 10 cotistas but > R$ 100M in AUM suggest proprietary or
-- related-party captive structures, not arm's-length market vehicles.
-- =============================================================================
SELECT
    d.cnpj,
    d.dt_comptc,
    d.tp_fundo,
    d.nr_cotst,
    ROUND(d.vl_patrim_liq / 1e6, 1)          AS pl_m,
    ROUND(d.vl_patrim_liq / NULLIF(d.nr_cotst, 0) / 1e6, 2) AS pl_per_cotista_m
FROM cvm_fi_diario d
WHERE d.dt_comptc = (SELECT MAX(dt_comptc) FROM cvm_fi_diario)
  AND d.nr_cotst BETWEEN 1 AND 10
  AND d.vl_patrim_liq > 100e6
ORDER BY d.vl_patrim_liq DESC
LIMIT 30;


-- =============================================================================
-- 5. EVERGREEN AGING — credits never migrating to longer delinquency buckets
-- A healthy FIDC should see credits move through aging buckets over time.
-- Suspect: fund has large vl_inad_30 every month but long-tail never grows →
-- credits are being restructured / "evergreened" before hitting 31+ day bucket.
-- =============================================================================
WITH aging_trend AS (
    SELECT
        cnpj,
        period,
        vl_inad_30,
        vl_inad_60,
        vl_inad_90,
        vl_inad_360,
        vl_inad_maior_1080,
        vl_total_inad,
        -- Pct of total delinquency that stays in 0-30 bucket
        ROUND(100.0 * vl_inad_30 / NULLIF(vl_total_inad, 0), 1) AS pct_short_bucket,
        -- Pct of total delinquency that reaches 360+ days
        ROUND(100.0 * (COALESCE(vl_inad_360, 0) + COALESCE(vl_inad_maior_1080, 0))
              / NULLIF(vl_total_inad, 0), 1) AS pct_long_tail
    FROM cvm_fidc_aging
    WHERE vl_total_inad > 1e6   -- only meaningful delinquency
),
fund_avg AS (
    SELECT
        cnpj,
        COUNT(period)                   AS months_observed,
        AVG(pct_short_bucket)           AS avg_pct_short,
        STDDEV(pct_short_bucket)        AS stddev_pct_short,
        AVG(pct_long_tail)              AS avg_pct_long_tail,
        MAX(period)                     AS latest_period
    FROM aging_trend
    WHERE period >= CURRENT_DATE - INTERVAL '18 months'
    GROUP BY cnpj
    HAVING COUNT(period) >= 6   -- need at least 6 months of data
)
SELECT
    fa.cnpj,
    fa.months_observed,
    ROUND(fa.avg_pct_short, 1)     AS avg_pct_short_bucket,
    ROUND(fa.stddev_pct_short, 1)  AS stddev_short,   -- low stddev = suspiciously stable
    ROUND(fa.avg_pct_long_tail, 1) AS avg_pct_long_tail,
    fa.latest_period,
    m.vl_patrim_liq / 1e6         AS fund_pl_m
FROM fund_avg fa
JOIN cvm_fidc_mensal m ON m.cnpj = fa.cnpj AND m.period = fa.latest_period
WHERE fa.avg_pct_short > 70          -- 70%+ delinquency always in short bucket
  AND fa.stddev_pct_short < 10       -- and it barely moves (< 10pp std)
  AND fa.avg_pct_long_tail < 5       -- almost nothing reaches long tail
ORDER BY avg_pct_short DESC
LIMIT 25;


-- =============================================================================
-- 6. SUBORDINATION EROSION
-- Junior quota declining while senior stays flat = credit losses being absorbed
-- before they show up in headline delinquency figures.
-- Uses cvm_fidc_tranche: junior vs. senior quota over time.
-- =============================================================================
WITH tranche_classified AS (
    SELECT
        cnpj,
        period,
        classe_serie,
        qt_cota,
        vl_cota,
        CASE
            WHEN LOWER(classe_serie) LIKE '%junior%' OR LOWER(classe_serie) LIKE '%júnior%'
              THEN 'junior'
            WHEN LOWER(classe_serie) LIKE '%senior%' OR LOWER(classe_serie) LIKE '%sênior%'
              THEN 'senior'
            WHEN LOWER(classe_serie) LIKE '%mezanino%' OR LOWER(classe_serie) LIKE '%mez%'
              THEN 'mezanino'
            ELSE 'other'
        END AS tranche_type,
        qt_cota * vl_cota AS nav_tranche
    FROM cvm_fidc_tranche
    WHERE vl_cota > 0 AND qt_cota > 0
),
fund_nav_split AS (
    SELECT
        cnpj, period,
        SUM(nav_tranche) FILTER (WHERE tranche_type = 'senior')  AS nav_senior,
        SUM(nav_tranche) FILTER (WHERE tranche_type = 'junior')  AS nav_junior,
        SUM(nav_tranche)                                          AS nav_total
    FROM tranche_classified
    GROUP BY cnpj, period
),
subordination AS (
    SELECT
        cnpj, period,
        ROUND(100.0 * nav_junior / NULLIF(nav_total, 0), 2) AS subord_pct,
        LAG(ROUND(100.0 * nav_junior / NULLIF(nav_total, 0), 2))
            OVER (PARTITION BY cnpj ORDER BY period) AS subord_prev
    FROM fund_nav_split
    WHERE nav_total > 10e6
)
SELECT
    cnpj,
    period,
    subord_pct,
    subord_prev,
    ROUND(subord_pct - subord_prev, 2) AS subord_delta_pp
FROM subordination
WHERE subord_prev IS NOT NULL
  AND subord_pct - subord_prev <= -3   -- junior shrinking >= 3pp in one month
ORDER BY subord_delta_pp ASC
LIMIT 30;


-- =============================================================================
-- 7. SENIOR TRANCHE YIELD DECOUPLED FROM FUND STRESS
-- If the fund's delinquency is high but senior tranches are still showing
-- positive (or even high) returns, something unusual is going on:
-- interest is being manufactured, or reporting is lagged.
-- =============================================================================
WITH fund_delinq AS (
    SELECT
        cnpj,
        period,
        ROUND(100.0 * vl_inadimpl / NULLIF(vl_patrim_liq, 0), 2) AS inadimpl_rate
    FROM cvm_fidc_mensal
    WHERE vl_patrim_liq > 50e6   -- material size
),
senior_return AS (
    SELECT
        cnpj,
        period,
        AVG(vl_rentab_mes) FILTER (
            WHERE LOWER(classe_serie) LIKE '%senior%'
               OR LOWER(classe_serie) LIKE '%sênior%'
        ) AS avg_senior_return,
        COUNT(*) FILTER (
            WHERE LOWER(classe_serie) LIKE '%senior%'
               OR LOWER(classe_serie) LIKE '%sênior%'
        ) AS n_senior_tranches
    FROM cvm_fidc_tranche
    WHERE vl_rentab_mes BETWEEN -0.1 AND 0.1   -- exclude garbage outliers (raw CVM)
    GROUP BY cnpj, period
)
SELECT
    d.cnpj,
    d.period,
    d.inadimpl_rate,
    ROUND(sr.avg_senior_return * 100, 4) AS senior_return_pct,
    sr.n_senior_tranches
FROM fund_delinq d
JOIN senior_return sr ON sr.cnpj = d.cnpj AND sr.period = d.period
WHERE d.inadimpl_rate > 15              -- heavily stressed fund
  AND sr.avg_senior_return > 0          -- but senior still showing positive return
ORDER BY d.inadimpl_rate DESC, sr.avg_senior_return DESC
LIMIT 30;


-- =============================================================================
-- 8. OVERDUE SECURIT SERIES STILL "EM CURSO"
-- CRI/CRA series past their maturity date (data_vencimento) but with
-- situacao NOT 'liquidado' / 'vencido'. Possible evergreen extension or
-- failure to close out.
-- =============================================================================
SELECT
    instrument_type,
    cnpj_securit,
    codigo_identificacao,
    codigo_isin,
    numero_serie,
    data_vencimento,
    situacao,
    ROUND(valor_total_integralizado / 1e6, 2)  AS integralizado_m,
    ROUND(valor_certificados / 1e6, 2)         AS valor_certificados_m,
    classificacao_risco_atual,
    data_referencia                            AS last_report_date
FROM cvm_securit_serie
WHERE data_vencimento < CURRENT_DATE
  AND data_vencimento IS NOT NULL
  AND situacao IS NOT NULL
  AND LOWER(situacao) NOT IN ('liquidado', 'vencido', 'cancelado', 'encerrado')
  AND data_referencia = (
      SELECT MAX(data_referencia)
      FROM cvm_securit_serie s2
      WHERE s2.cnpj_securit = cvm_securit_serie.cnpj_securit
        AND s2.codigo_identificacao = cvm_securit_serie.codigo_identificacao
  )
ORDER BY data_vencimento ASC
LIMIT 40;


-- =============================================================================
-- BONUS: COMBINED RED-FLAG WATCHLIST
-- Funds that appear in MULTIPLE screens above (stress + inflow + aging anomaly).
-- Uses CTEs from screens 2 (zombie) and 5 (evergreen) side by side.
-- =============================================================================
WITH zombie AS (
    WITH periods AS (
        SELECT DISTINCT period FROM cvm_fidc_mensal ORDER BY period DESC LIMIT 7
    ),
    bounds AS (SELECT MAX(period) AS t_now, MIN(period) AS t_then FROM periods),
    snap AS (
        SELECT cnpj, period,
               ROUND(100.0 * vl_inadimpl / NULLIF(vl_patrim_liq, 0), 2) AS inadimpl_rate,
               vl_patrim_liq
        FROM cvm_fidc_mensal, bounds
        WHERE period IN (t_now, t_then) AND vl_patrim_liq > 0
    )
    SELECT now_.cnpj,
           now_.inadimpl_rate - then_.inadimpl_rate AS accel,
           now_.vl_patrim_liq - then_.vl_patrim_liq AS pl_growth
    FROM snap now_
    JOIN snap then_ ON then_.cnpj = now_.cnpj
    JOIN bounds b ON now_.period = b.t_now AND then_.period = b.t_then
    WHERE now_.inadimpl_rate - then_.inadimpl_rate >= 1.5
      AND now_.vl_patrim_liq > then_.vl_patrim_liq
      AND now_.vl_patrim_liq > 50e6
),
evergreen AS (
    SELECT cnpj
    FROM (
        SELECT cnpj,
               AVG(100.0 * vl_inad_30 / NULLIF(vl_total_inad, 0)) AS avg_short,
               STDDEV(100.0 * vl_inad_30 / NULLIF(vl_total_inad, 0)) AS sd_short
        FROM cvm_fidc_aging
        WHERE vl_total_inad > 1e6
          AND period >= CURRENT_DATE - INTERVAL '18 months'
        GROUP BY cnpj HAVING COUNT(*) >= 6
    ) t
    WHERE avg_short > 70 AND sd_short < 10
),
subord_erosion AS (
    SELECT DISTINCT cnpj
    FROM (
        SELECT cnpj, period,
               ROUND(100.0 * SUM(qt_cota * vl_cota) FILTER (
                   WHERE LOWER(classe_serie) LIKE '%junior%'
                      OR LOWER(classe_serie) LIKE '%júnior%'
               ) / NULLIF(SUM(qt_cota * vl_cota), 0), 2) AS subord_pct,
               LAG(ROUND(100.0 * SUM(qt_cota * vl_cota) FILTER (
                   WHERE LOWER(classe_serie) LIKE '%junior%'
                      OR LOWER(classe_serie) LIKE '%júnior%'
               ) / NULLIF(SUM(qt_cota * vl_cota), 0), 2))
                   OVER (PARTITION BY cnpj ORDER BY period) AS subord_prev
        FROM cvm_fidc_tranche
        WHERE vl_cota > 0 AND qt_cota > 0
        GROUP BY cnpj, period
    ) s
    WHERE subord_pct - subord_prev <= -3
)
SELECT
    m.cnpj,
    ROUND(m.vl_patrim_liq / 1e6, 1) AS pl_m,
    ROUND(m.vl_inadimpl / NULLIF(m.vl_patrim_liq, 0) * 100, 2) AS inadimpl_rate_pct,
    z.accel IS NOT NULL   AS flag_zombie,
    e.cnpj IS NOT NULL    AS flag_evergreen,
    se.cnpj IS NOT NULL   AS flag_subord_erosion,
    (  (z.accel IS NOT NULL)::int
     + (e.cnpj IS NOT NULL)::int
     + (se.cnpj IS NOT NULL)::int
    )                     AS flag_count
FROM cvm_fidc_mensal m
LEFT JOIN zombie z ON z.cnpj = m.cnpj
LEFT JOIN evergreen e ON e.cnpj = m.cnpj
LEFT JOIN subord_erosion se ON se.cnpj = m.cnpj
WHERE m.period = (SELECT MAX(period) FROM cvm_fidc_mensal)
  AND (z.accel IS NOT NULL OR e.cnpj IS NOT NULL OR se.cnpj IS NOT NULL)
ORDER BY flag_count DESC, m.vl_patrim_liq DESC
LIMIT 30;
