-- =============================================================================
-- Pipeline verification & analytical queries
-- Run these in Supabase SQL editor or any Postgres client after ingesting data.
-- =============================================================================


-- ---------------------------------------------------------------------------
-- 1. DATA PRESENCE  — are all tables populated with recent data?
-- ---------------------------------------------------------------------------

SELECT
    tbl                    AS table_name,
    row_count,
    earliest_period,
    latest_period,
    ROUND(100.0 * populated / NULLIF(row_count, 0), 1) AS pl_populated_pct
FROM (
    SELECT 'cvm_fi_diario'     AS tbl, COUNT(*) AS row_count,
           MIN(dt_comptc)::text AS earliest_period,
           MAX(dt_comptc)::text AS latest_period,
           COUNT(*) FILTER (WHERE vl_patrim_liq IS NOT NULL) AS populated
    FROM cvm_fi_diario
    UNION ALL
    SELECT 'cvm_fidc_mensal', COUNT(*), MIN(period)::text, MAX(period)::text,
           COUNT(*) FILTER (WHERE vl_patrim_liq IS NOT NULL)
    FROM cvm_fidc_mensal
    UNION ALL
    SELECT 'cvm_fii_mensal (complemento)', COUNT(*), MIN(period)::text, MAX(period)::text,
           COUNT(*) FILTER (WHERE vl_patrim_liq IS NOT NULL)
    FROM cvm_fii_mensal WHERE doc_subtype = 'complemento'
    UNION ALL
    SELECT 'cvm_fip_periodic', COUNT(*), MIN(period_year)::text, MAX(period_year)::text,
           COUNT(*) FILTER (WHERE vl_patrim_liq IS NOT NULL)
    FROM cvm_fip_periodic
    UNION ALL
    SELECT 'cvm_securit_mensal', COUNT(*), MIN(period_year)::text, MAX(period_year)::text,
           COUNT(*) FILTER (WHERE vl_emissao IS NOT NULL)
    FROM cvm_securit_mensal
) t
ORDER BY tbl;


-- ---------------------------------------------------------------------------
-- 2. DATA QUALITY  — null rates on key financial fields after pipeline fixes
-- Expected: FIDC vl_patrim_liq and SECURIT vl_emissao should be near 0% null.
-- ---------------------------------------------------------------------------

SELECT check_name, null_pct || '%' AS null_rate FROM (
    SELECT 'FI      vl_patrim_liq' AS check_name,
           ROUND(100.0 * COUNT(*) FILTER (WHERE vl_patrim_liq IS NULL) / COUNT(*), 1) AS null_pct
    FROM cvm_fi_diario
    UNION ALL
    SELECT 'FIDC    vl_patrim_liq (tab_IV fix)',
           ROUND(100.0 * COUNT(*) FILTER (WHERE vl_patrim_liq IS NULL) / COUNT(*), 1)
    FROM cvm_fidc_mensal
    UNION ALL
    SELECT 'FII complemento vl_patrim_liq',
           ROUND(100.0 * COUNT(*) FILTER (WHERE vl_patrim_liq IS NULL) / COUNT(*), 1)
    FROM cvm_fii_mensal WHERE doc_subtype = 'complemento'
    UNION ALL
    SELECT 'SECURIT vl_emissao (Valor_Atualizado_Emissao fix)',
           ROUND(100.0 * COUNT(*) FILTER (WHERE vl_emissao IS NULL) / COUNT(*), 1)
    FROM cvm_securit_mensal
    UNION ALL
    SELECT 'SECURIT vl_total (Ativo fix)',
           ROUND(100.0 * COUNT(*) FILTER (WHERE vl_total IS NULL) / COUNT(*), 1)
    FROM cvm_securit_mensal
) t
ORDER BY null_pct DESC;


-- ---------------------------------------------------------------------------
-- 3. FI  — How is a specific fund's NAV (PL) performing? (last 90 days)
-- Replace <CNPJ_14_DIGITS> with a real CNPJ, e.g. '97929213000140'
-- ---------------------------------------------------------------------------

SELECT
    dt_comptc,
    vl_patrim_liq,
    vl_quota,
    nr_cotst,
    captc_dia,
    resg_dia,
    captc_dia - resg_dia                                              AS net_flow,
    vl_patrim_liq
        - LAG(vl_patrim_liq) OVER (ORDER BY dt_comptc)               AS pl_delta,
    ROUND(100.0 * (
        vl_patrim_liq - FIRST_VALUE(vl_patrim_liq) OVER (ORDER BY dt_comptc)
    ) / NULLIF(FIRST_VALUE(vl_patrim_liq) OVER (ORDER BY dt_comptc), 0), 2)  AS pl_return_pct
FROM cvm_fi_diario
WHERE cnpj = '<CNPJ_14_DIGITS>'
  AND dt_comptc >= CURRENT_DATE - INTERVAL '90 days'
ORDER BY dt_comptc DESC;


-- ---------------------------------------------------------------------------
-- 4. FI  — Industry-wide daily net inflow vs. redemption by month
-- ---------------------------------------------------------------------------

SELECT
    DATE_TRUNC('month', dt_comptc)          AS month,
    COUNT(DISTINCT cnpj)                    AS active_funds,
    SUM(vl_patrim_liq)                      AS total_industry_pl,
    SUM(captc_dia)                          AS total_inflow,
    SUM(resg_dia)                           AS total_redemption,
    SUM(captc_dia) - SUM(resg_dia)          AS net_flow
FROM cvm_fi_diario
GROUP BY 1
ORDER BY 1 DESC
LIMIT 12;


-- ---------------------------------------------------------------------------
-- 5. FIDC  — Monthly industry PL and delinquency rate
-- ---------------------------------------------------------------------------

SELECT
    period,
    COUNT(DISTINCT cnpj)                                                       AS num_funds,
    ROUND(SUM(vl_patrim_liq) / 1e9, 2)                                        AS total_pl_bn,
    ROUND(SUM(vl_inadimpl) / 1e9, 2)                                          AS total_inadimpl_bn,
    ROUND(100.0 * SUM(vl_inadimpl) / NULLIF(SUM(vl_patrim_liq), 0), 2)       AS delinquency_pct
FROM cvm_fidc_mensal
GROUP BY 1
ORDER BY 1 DESC
LIMIT 24;


-- ---------------------------------------------------------------------------
-- 6. FIDC  — What is the PL inflow for FIDC funds in a specific month?
-- Replace '2025-03-01' with the target period.
-- ---------------------------------------------------------------------------

SELECT
    cnpj,
    period,
    vl_patrim_liq,
    vl_patrim_liq - prev.prev_pl         AS pl_change,
    ROUND(100.0 * (vl_patrim_liq - prev.prev_pl)
          / NULLIF(prev.prev_pl, 0), 2)  AS pl_growth_pct
FROM cvm_fidc_mensal curr
LEFT JOIN LATERAL (
    SELECT vl_patrim_liq AS prev_pl
    FROM cvm_fidc_mensal
    WHERE cnpj = curr.cnpj
      AND period < curr.period
    ORDER BY period DESC
    LIMIT 1
) prev ON true
WHERE curr.period = '2025-03-01'
  AND curr.vl_patrim_liq IS NOT NULL
ORDER BY vl_patrim_liq DESC
LIMIT 20;


-- ---------------------------------------------------------------------------
-- 7. FII  — Top 10 FIIs by latest NAV (complemento file)
-- ---------------------------------------------------------------------------

SELECT
    m.cnpj,
    m.period,
    ROUND(m.vl_patrim_liq / 1e6, 2)  AS pl_mm
FROM cvm_fii_mensal m
WHERE m.doc_subtype = 'complemento'
  AND m.period = (
      SELECT MAX(period)
      FROM cvm_fii_mensal
      WHERE doc_subtype = 'complemento'
  )
  AND m.vl_patrim_liq IS NOT NULL
ORDER BY m.vl_patrim_liq DESC
LIMIT 10;


-- ---------------------------------------------------------------------------
-- 8. FII  — Monthly NAV evolution for a specific fund
-- Replace <CNPJ_14_DIGITS> with a real FII CNPJ.
-- ---------------------------------------------------------------------------

SELECT
    period,
    vl_patrim_liq,
    vl_patrim_liq
        - LAG(vl_patrim_liq) OVER (ORDER BY period)   AS pl_delta,
    ROUND(100.0 * (
        vl_patrim_liq - LAG(vl_patrim_liq) OVER (ORDER BY period)
    ) / NULLIF(LAG(vl_patrim_liq) OVER (ORDER BY period), 0), 2) AS mom_return_pct
FROM cvm_fii_mensal
WHERE cnpj       = '<CNPJ_14_DIGITS>'
  AND doc_subtype = 'complemento'
ORDER BY period DESC
LIMIT 24;


-- ---------------------------------------------------------------------------
-- 9. SECURIT  — CRA emission volume by year; verify vl_emissao is populated
-- ---------------------------------------------------------------------------

SELECT
    period_year,
    instrument_type,
    COUNT(DISTINCT cnpj_securit)           AS issuers,
    COUNT(*)                               AS records,
    ROUND(SUM(vl_emissao) / 1e9, 2)       AS total_emissao_bn,
    ROUND(SUM(vl_total)   / 1e9, 2)       AS total_assets_bn
FROM cvm_securit_mensal
GROUP BY 1, 2
ORDER BY 1 DESC, 2;


-- ---------------------------------------------------------------------------
-- 10. FIP  — Year-end PL trend across all private equity funds
-- ---------------------------------------------------------------------------

SELECT
    period_year,
    COUNT(DISTINCT cnpj)               AS num_funds,
    ROUND(SUM(vl_patrim_liq) / 1e9, 2) AS total_pl_bn
FROM cvm_fip_periodic
WHERE vl_patrim_liq IS NOT NULL
GROUP BY 1
ORDER BY 1 DESC;


-- ---------------------------------------------------------------------------
-- 11. INGEST LOG  — recent runs, error check
-- ---------------------------------------------------------------------------

SELECT
    entity,
    doc_type,
    period_year,
    period_month,
    status,
    rows_upserted,
    ROUND(EXTRACT(EPOCH FROM (finished_at - started_at))::numeric, 1) AS duration_s,
    started_at
FROM cvm_ingest_log
ORDER BY started_at DESC
LIMIT 30;
