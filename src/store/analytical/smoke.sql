-- =============================================================================
-- analytical_smoke.sql
-- End-to-end smoke queries for the iliquid_nightly analytical layer.
-- Each query is self-contained, returns rows on a populated DB, and is
-- annotated with the category it tests.
--
-- Run order: assumes 01–08 DDL has been applied and at least one ingest
-- cycle has completed.
--
-- Execute: psql $DATABASE_URL -f scripts/analytical_smoke.sql
-- =============================================================================

-- ---------------------------------------------------------------------------
-- A — Industry totals
-- Tests: fact_fund_monthly aggregated across all entity types per month.
-- Expected: one row per (period, entity_type) with total AUM.
-- ---------------------------------------------------------------------------
-- A1: Total AUM by entity type and month (last 6 months)
SELECT
  period,
  entity_type,
  COUNT(DISTINCT cnpj)    AS n_funds,
  SUM(vl_patrim_liq)      AS total_aum,
  AVG(vl_patrim_liq)      AS avg_aum
FROM fact_fund_monthly
WHERE period >= date_trunc('month', NOW() - INTERVAL '6 months')::date
GROUP BY period, entity_type
ORDER BY period DESC, entity_type;

-- A2: Industry-wide monthly net flows for FI (captc - resg)
SELECT
  period,
  SUM(captc_mes)                      AS total_inflows,
  SUM(resg_mes)                       AS total_outflows,
  SUM(captc_mes) - SUM(resg_mes)      AS net_flow
FROM fact_fund_monthly
WHERE entity_type = 'fi'
  AND period >= date_trunc('month', NOW() - INTERVAL '12 months')::date
GROUP BY period
ORDER BY period DESC;

-- ---------------------------------------------------------------------------
-- B — Entity aggregates
-- Tests: per-fund summary statistics at a point in time.
-- Expected: one row per fund for the most recent period.
-- ---------------------------------------------------------------------------
-- B1: Top 20 FI funds by AUM as of most recent period
SELECT
  cnpj,
  period,
  vl_patrim_liq,
  vl_quota,
  nr_cotst
FROM fact_fund_monthly
WHERE entity_type = 'fi'
  AND period = (SELECT MAX(period) FROM fact_fund_monthly WHERE entity_type = 'fi')
ORDER BY vl_patrim_liq DESC NULLS LAST
LIMIT 20;

-- B2: All FIDC funds with non-zero delinquency in latest period
SELECT
  cnpj,
  period,
  vl_patrim_liq,
  vl_inadimpl,
  ROUND(vl_inadimpl / NULLIF(vl_patrim_liq, 0) * 100, 2) AS pct_inadimpl
FROM fact_fund_monthly
WHERE entity_type = 'fidc'
  AND vl_inadimpl > 0
  AND period = (SELECT MAX(period) FROM fact_fund_monthly WHERE entity_type = 'fidc')
ORDER BY pct_inadimpl DESC NULLS LAST
LIMIT 20;

-- ---------------------------------------------------------------------------
-- C — Per-fund time series
-- Tests: time-series query for a single fund.
-- Expected: multiple rows (one per month) for any given cnpj.
-- ---------------------------------------------------------------------------
-- C1: Monthly AUM and quota time series for a sample FI fund
--     (uses the fund with the most months of data as a deterministic sample)
SELECT
  f.cnpj,
  f.period,
  f.vl_patrim_liq,
  f.vl_quota,
  f.nr_cotst,
  f.captc_mes,
  f.resg_mes
FROM fact_fund_monthly f
JOIN (
  SELECT cnpj
  FROM fact_fund_monthly
  WHERE entity_type = 'fi'
  GROUP BY cnpj
  ORDER BY COUNT(*) DESC
  LIMIT 1
) top_fund ON top_fund.cnpj = f.cnpj
WHERE f.entity_type = 'fi'
ORDER BY f.period;

-- C2: Quota return (month-over-month % change) for same fund
SELECT
  period,
  vl_quota,
  LAG(vl_quota) OVER (ORDER BY period)  AS vl_quota_prev,
  ROUND(
    (vl_quota / NULLIF(LAG(vl_quota) OVER (ORDER BY period), 0) - 1) * 100,
    4
  )                                      AS quota_return_pct
FROM fact_fund_monthly
WHERE cnpj = (
  SELECT cnpj FROM fact_fund_monthly
  WHERE entity_type = 'fi'
  GROUP BY cnpj ORDER BY COUNT(*) DESC LIMIT 1
)
  AND entity_type = 'fi'
ORDER BY period;

-- ---------------------------------------------------------------------------
-- D — Peer ranking
-- Tests: RANK() / NTILE() window functions over fact_fund_monthly.
-- Expected: percentile rank for each FII fund in latest period.
-- ---------------------------------------------------------------------------
-- D1: FII peer ranking by pct_yield_mes (latest period)
SELECT
  cnpj,
  period,
  pct_yield_mes,
  vl_patrim_liq,
  RANK()   OVER (ORDER BY pct_yield_mes DESC NULLS LAST)        AS rank_yield,
  NTILE(4) OVER (ORDER BY pct_yield_mes DESC NULLS LAST)        AS quartile_yield,
  NTILE(4) OVER (ORDER BY vl_patrim_liq   DESC NULLS LAST)      AS quartile_aum
FROM fact_fund_monthly
WHERE entity_type = 'fii'
  AND period = (SELECT MAX(period) FROM fact_fund_monthly WHERE entity_type = 'fii')
  AND pct_yield_mes IS NOT NULL
ORDER BY rank_yield;

-- D2: FIDC peer ranking by delinquency ratio (lower = better)
SELECT
  cnpj,
  period,
  vl_patrim_liq,
  vl_inadimpl,
  ROUND(vl_inadimpl / NULLIF(vl_patrim_liq, 0) * 100, 4) AS delinq_ratio,
  RANK() OVER (
    ORDER BY vl_inadimpl / NULLIF(vl_patrim_liq, 0) ASC NULLS LAST
  ) AS rank_delinq
FROM fact_fund_monthly
WHERE entity_type = 'fidc'
  AND period = (SELECT MAX(period) FROM fact_fund_monthly WHERE entity_type = 'fidc')
ORDER BY delinq_ratio NULLS LAST
LIMIT 30;

-- ---------------------------------------------------------------------------
-- E — Cross-entity fund comparison
-- Tests: vw_fii_vs_fiagro — union of FII and FIAGRO entity types.
-- Expected: rows with entity_type = 'fii' or 'fiagro'.
-- ---------------------------------------------------------------------------
-- E1: FII vs FIAGRO — average yield and AUM per entity type per month
SELECT
  period,
  entity_type,
  COUNT(DISTINCT cnpj)        AS n_funds,
  AVG(pct_yield_mes)          AS avg_yield_mes,
  MEDIAN(pct_yield_mes)       AS median_yield_mes,
  SUM(vl_patrim_liq)          AS total_pl,
  SUM(nr_cotst)               AS total_cotistas
FROM vw_fii_vs_fiagro
WHERE period >= date_trunc('month', NOW() - INTERVAL '12 months')::date
GROUP BY period, entity_type
ORDER BY period DESC, entity_type;

-- E2: FIP annual PL trend
SELECT
  period,
  COUNT(DISTINCT cnpj)  AS n_fips,
  SUM(vl_patrim_liq)    AS total_pl
FROM fact_fund_monthly
WHERE entity_type = 'fip'
ORDER BY period;

-- ---------------------------------------------------------------------------
-- F — FIDC tranche detail
-- Tests: vw_fidc_tranche_detail — tranche + fund join.
-- Expected: rows with classe_serie, vl_rentab_mes, fund_pl, fund_inadimpl.
-- ---------------------------------------------------------------------------
-- F1: Top 10 tranches by absolute monthly return (latest period, sanity filter)
SELECT
  cnpj,
  period,
  classe_serie,
  vl_cota,
  -- Filter outlier raw CVM values
  CASE WHEN ABS(vl_rentab_mes) < 100 THEN vl_rentab_mes END  AS vl_rentab_mes_clean,
  fund_pl,
  fund_inadimpl
FROM vw_fidc_tranche_detail
WHERE period = (SELECT MAX(period) FROM cvm_fidc_tranche)
  AND vl_rentab_mes IS NOT NULL
  AND ABS(vl_rentab_mes) < 100   -- exclude obvious CVM data errors
ORDER BY vl_rentab_mes DESC NULLS LAST
LIMIT 10;

-- F2: Number of active tranches per FIDC fund (latest period)
SELECT
  cnpj,
  period,
  COUNT(DISTINCT classe_serie)  AS n_tranches,
  SUM(qt_cota)                  AS total_cotas,
  fund_pl
FROM vw_fidc_tranche_detail
WHERE period = (SELECT MAX(period) FROM cvm_fidc_tranche)
GROUP BY cnpj, period, fund_pl
ORDER BY n_tranches DESC
LIMIT 20;

-- ---------------------------------------------------------------------------
-- G — Aging / delinquency
-- Tests: cvm_fidc_aging — bucket-level delinquency.
-- Expected: rows with vl_total_inad and aging bucket values.
-- ---------------------------------------------------------------------------
-- G1: Industry delinquency aging profile — latest available period
SELECT
  period,
  SUM(vl_inad_30)                     AS inad_30d,
  SUM(vl_inad_60)                     AS inad_60d,
  SUM(vl_inad_90)                     AS inad_90d,
  SUM(vl_inad_120)                    AS inad_120d,
  SUM(vl_inad_180)                    AS inad_180d,
  SUM(vl_inad_360)                    AS inad_360d,
  SUM(vl_inad_maior_1080)             AS inad_over_1080d,
  SUM(vl_total_inad)                  AS total_inad
FROM cvm_fidc_aging
WHERE period = (SELECT MAX(period) FROM cvm_fidc_aging)
GROUP BY period;

-- G2: FIDC funds with growing delinquency (last 3 months, month-over-month)
SELECT
  cnpj,
  period,
  vl_inadimpl,
  LAG(vl_inadimpl, 1) OVER (PARTITION BY cnpj ORDER BY period) AS prev_inadimpl,
  vl_inadimpl - LAG(vl_inadimpl, 1) OVER (PARTITION BY cnpj ORDER BY period) AS delta_inadimpl
FROM fact_fund_monthly
WHERE entity_type = 'fidc'
  AND period >= date_trunc('month', NOW() - INTERVAL '3 months')::date
ORDER BY delta_inadimpl DESC NULLS LAST
LIMIT 20;

-- ---------------------------------------------------------------------------
-- H — Benchmark overlay
-- Tests: vw_fund_vs_benchmark — join to fact_bacen_monthly for SELIC/CDI/IPCA.
-- Expected: cdi_mes, selic_mes, ipca_mes populated where bacen data exists.
-- ---------------------------------------------------------------------------
-- H1: CDI and SELIC monthly rates for last 12 months
SELECT
  period,
  series_code,
  value AS monthly_rate_pct
FROM fact_bacen_monthly
WHERE series_code IN (11, 12, 433, 189, 999)
  AND period >= date_trunc('month', NOW() - INTERVAL '12 months')::date
ORDER BY period DESC, series_code;

-- H2: FII funds with positive spread vs CDI (latest period)
SELECT
  cnpj,
  period,
  entity_type,
  pct_yield_mes,
  cdi_mes,
  spread_vs_cdi,
  real_return
FROM vw_fund_vs_benchmark
WHERE entity_type = 'fii'
  AND spread_vs_cdi > 0
  AND period = (
    SELECT MAX(period) FROM fact_fund_monthly WHERE entity_type = 'fii'
  )
ORDER BY spread_vs_cdi DESC
LIMIT 20;

-- H3: Benchmark time series (all tracked series, 24 months)
SELECT
  period,
  MAX(CASE WHEN series_code = 12  THEN value END)  AS cdi_mes,
  MAX(CASE WHEN series_code = 11  THEN value END)  AS selic_mes,
  MAX(CASE WHEN series_code = 433 THEN value END)  AS ipca_mes,
  MAX(CASE WHEN series_code = 189 THEN value END)  AS igpm_mes,
  MAX(CASE WHEN series_code = 999 THEN value END)  AS usdbrl_eom
FROM fact_bacen_monthly
WHERE period >= date_trunc('month', NOW() - INTERVAL '24 months')::date
GROUP BY period
ORDER BY period DESC;

-- ---------------------------------------------------------------------------
-- I — Security issuance
-- Tests: vw_securit_emission_trend — monthly count and value of series.
-- Expected: n_series and total_value per (period, instrument_type).
-- ---------------------------------------------------------------------------
-- I1: Monthly issuance trend by instrument type (last 24 months)
SELECT
  period,
  instrument_type,
  n_series,
  total_value
FROM vw_securit_emission_trend
WHERE period >= date_trunc('month', NOW() - INTERVAL '24 months')::date
ORDER BY period DESC, instrument_type;

-- I2: Active vs matured securities breakdown (latest reporting date)
SELECT
  instrument_type,
  situacao_mes,
  COUNT(*)              AS n_series,
  SUM(valor_certificados) AS total_value
FROM fact_security_monthly
WHERE period = (SELECT MAX(period) FROM fact_security_monthly)
GROUP BY instrument_type, situacao_mes
ORDER BY instrument_type, n_series DESC;

-- I3: Top 10 securitisers by outstanding value (latest period)
SELECT
  cnpj_securit,
  instrument_type,
  COUNT(DISTINCT codigo_identificacao)  AS n_series,
  SUM(valor_certificados)               AS total_outstanding
FROM fact_security_monthly
WHERE period = (SELECT MAX(period) FROM fact_security_monthly)
GROUP BY cnpj_securit, instrument_type
ORDER BY total_outstanding DESC NULLS LAST
LIMIT 10;

-- ---------------------------------------------------------------------------
-- J — Cross-domain fund + security yield
-- Tests: vw_fund_security_yield — union of funds and securities.
-- Expected: rows with domain = 'fund' and domain = 'security'.
-- ---------------------------------------------------------------------------
-- J1: Yield universe — top 20 instruments by spread vs CDI (latest month)
SELECT
  domain,
  instrument,
  identifier,
  period,
  yield_mes,
  cdi_mes,
  spread_vs_cdi,
  vl_patrim_liq
FROM vw_fund_security_yield
WHERE period = (
  SELECT MAX(period)
  FROM vw_fund_security_yield
  WHERE cdi_mes IS NOT NULL
)
ORDER BY spread_vs_cdi DESC NULLS LAST
LIMIT 20;

-- J2: Yield distribution by domain and instrument type (last 12 months)
SELECT
  domain,
  instrument,
  period,
  COUNT(*)            AS n_instruments,
  AVG(yield_mes)      AS avg_yield,
  MIN(yield_mes)      AS min_yield,
  MAX(yield_mes)      AS max_yield,
  AVG(spread_vs_cdi)  AS avg_spread_vs_cdi
FROM vw_fund_security_yield
WHERE period >= date_trunc('month', NOW() - INTERVAL '12 months')::date
GROUP BY domain, instrument, period
ORDER BY period DESC, domain, instrument;

-- ---------------------------------------------------------------------------
-- K — Data quality / coverage
-- Tests: completeness and freshness of ingest pipeline.
-- Expected: recent rows in cvm_ingest_log; no large gap between
--           last ingested period and current date.
-- ---------------------------------------------------------------------------
-- K1: Ingest log — last successful run per entity/doc_type
SELECT
  entity,
  doc_type,
  MAX(period_year)   AS latest_year,
  MAX(period_month)  AS latest_month,
  MAX(finished_at)   AS last_run_at,
  SUM(rows_upserted) AS total_rows_upserted
FROM cvm_ingest_log
WHERE status = 'ok'
GROUP BY entity, doc_type
ORDER BY entity, doc_type;

-- K2: Data freshness — latest period per analytical fact table
SELECT 'fact_fund_monthly'     AS table_name, entity_type,
       MAX(period)             AS latest_period,
       COUNT(DISTINCT cnpj)    AS n_cnpjs,
       COUNT(*)                AS total_rows
FROM fact_fund_monthly
GROUP BY entity_type

UNION ALL

SELECT 'fact_security_monthly' AS table_name,
       instrument_type         AS entity_type,
       MAX(period)             AS latest_period,
       COUNT(DISTINCT cnpj_securit) AS n_cnpjs,
       COUNT(*)                AS total_rows
FROM fact_security_monthly
GROUP BY instrument_type

UNION ALL

SELECT 'fact_bacen_monthly'    AS table_name,
       series_code::text       AS entity_type,
       MAX(period)             AS latest_period,
       1                       AS n_cnpjs,
       COUNT(*)                AS total_rows
FROM fact_bacen_monthly
GROUP BY series_code

ORDER BY table_name, entity_type;

-- K3: Coverage gap — funds present in dim_fund but missing from fact_fund_monthly
--     (could indicate ingest ran but analytical layer was not refreshed)
SELECT
  d.entity_type,
  COUNT(DISTINCT d.cnpj)  AS in_dim,
  COUNT(DISTINCT f.cnpj)  AS in_fact,
  COUNT(DISTINCT d.cnpj) - COUNT(DISTINCT f.cnpj) AS gap
FROM dim_fund d
LEFT JOIN fact_fund_monthly f
  ON  f.cnpj        = d.cnpj
  AND f.entity_type = d.entity_type
GROUP BY d.entity_type
ORDER BY d.entity_type;

-- K4: Ingest errors in last 30 days
SELECT
  entity,
  doc_type,
  status,
  error_msg,
  started_at
FROM cvm_ingest_log
WHERE status != 'ok'
  AND started_at >= NOW() - INTERVAL '30 days'
ORDER BY started_at DESC;

-- K5: Null rate audit for key columns in fact_fund_monthly (latest period)
SELECT
  entity_type,
  COUNT(*)                                                    AS n_rows,
  COUNT(*) FILTER (WHERE vl_patrim_liq IS NULL)              AS null_pl,
  COUNT(*) FILTER (WHERE vl_quota IS NULL)                   AS null_quota,
  COUNT(*) FILTER (WHERE nr_cotst IS NULL)                   AS null_cotst,
  ROUND(
    COUNT(*) FILTER (WHERE vl_patrim_liq IS NULL)::numeric /
    NULLIF(COUNT(*), 0) * 100, 1
  )                                                          AS pct_null_pl
FROM fact_fund_monthly
WHERE period = (SELECT MAX(period) FROM fact_fund_monthly)
GROUP BY entity_type
ORDER BY entity_type;

-- ---------------------------------------------------------------------------
-- L — Classification, administrator/gestor rankings, fraud screens
-- Tests: 13_dim_classification, 14_ranking_functions, 15_fraud_screens.
-- Expected: rows once registry admin/gestor columns and facts are populated.
-- ---------------------------------------------------------------------------
-- L1: Asset-class distribution (conformed buckets across entity types)
SELECT asset_class, COUNT(*) AS n_funds
FROM dim_fund_category
GROUP BY asset_class
ORDER BY n_funds DESC;

-- L2: Top 20 administrators by AUM (latest period)
SELECT admin_name, n_funds, total_aum, rank_pos
FROM administrator_rankings(NULL, 'aum', 20);

-- L3: Top 20 gestores by funds under management (latest period)
SELECT gestor_name, n_funds, total_aum, rank_pos
FROM gestor_rankings(NULL, 'n_funds', 20);

-- L4: Asset-class performance vs a CDI proxy (last 24 months)
SELECT period, asset_class, n_funds, total_aum, median_yield, yield_spread_pp
FROM asset_class_performance(
       (date_trunc('month', NOW() - INTERVAL '24 months'))::date,
       CURRENT_DATE, 1.0)
ORDER BY period DESC, asset_class
LIMIT 50;

-- L5: Investor growth by asset class (nr_cotst rolled up)
SELECT period, asset_class, total_cotistas, n_funds_with_data
FROM quotaholder_trend_by_class(
       (date_trunc('month', NOW() - INTERVAL '24 months'))::date, CURRENT_DATE)
ORDER BY period DESC, asset_class
LIMIT 50;

-- L6: Fraud screens — each returns a (possibly empty) signal set
SELECT 'zombie_growth'    AS screen, COUNT(*) AS n_hits FROM fraud_screen_zombie_growth(NULL, 5, 1e6)
UNION ALL
SELECT 'captive_vehicles', COUNT(*) FROM fraud_screen_captive_vehicles(3, 10, 5e7)
UNION ALL
SELECT 'evergreen_aging',  COUNT(*) FROM fraud_screen_evergreen_aging(12, 70, 10)
UNION ALL
SELECT 'overdue_securit',  COUNT(*) FROM fraud_screen_overdue_securit(1e5);
