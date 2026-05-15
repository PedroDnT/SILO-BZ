-- =============================================================================
-- 03_fact_bacen_monthly.sql
-- Materialized view: fact_bacen_monthly
-- Daily bacen_sgs and bacen_ptax rolled up to monthly grain.
--
-- Aggregation rules:
--   SELIC (11) / CDI (12) : cumulative monthly return via log-sum of daily pct rates
--   All other series       : last value of the month (DISTINCT ON latest date)
--   USD/BRL (series 999)   : average mid-rate over the last business day of each month
--                            (approximated as MAX(reference_date) per month)
--
-- Idempotent: DROP + re-CREATE is wrapped in the transaction so repeated runs are safe.
-- =============================================================================

BEGIN;
SET statement_timeout = '15min';

-- Drop and recreate so the definition is always in sync with this file.
DROP MATERIALIZED VIEW IF EXISTS fact_bacen_monthly;

CREATE MATERIALIZED VIEW fact_bacen_monthly AS

  -- -------------------------------------------------------------------------
  -- Segment 1: SELIC (11) and CDI (12)
  -- Daily rates are expressed as % (e.g. 0.0433 for ~1.06 % monthly).
  -- Compound: ∏(1 + r/100) - 1  →  result stored as percent (× 100).
  -- -------------------------------------------------------------------------
  SELECT
    date_trunc('month', reference_date)::date AS period,
    series_code,
    (EXP(SUM(LN(1 + value / 100.0))) - 1) * 100.0 AS value
  FROM bacen_sgs
  WHERE series_code IN (11, 12)
    AND value IS NOT NULL
    AND value > -100                          -- guard against corrupt zeros
  GROUP BY
    date_trunc('month', reference_date)::date,
    series_code

  UNION ALL

  -- -------------------------------------------------------------------------
  -- Segment 2: All other tracked series (IPCA 433, IGP-M 189, etc.)
  -- Take the last published value within each calendar month.
  -- -------------------------------------------------------------------------
  SELECT DISTINCT ON (date_trunc('month', reference_date)::date, series_code)
    date_trunc('month', reference_date)::date AS period,
    series_code,
    value
  FROM bacen_sgs
  WHERE series_code NOT IN (11, 12)
    AND value IS NOT NULL
  ORDER BY
    date_trunc('month', reference_date)::date,
    series_code,
    reference_date DESC

  UNION ALL

  -- -------------------------------------------------------------------------
  -- Segment 3: USD/BRL from bacen_ptax (internal series_code = 999)
  -- End-of-month rate: average mid-rate on the last available reference_date
  -- of the month (MAX date = last business day in monotonically loaded data).
  -- bacen_ptax schema: buy_rate, sell_rate (no cotacao* columns).
  -- -------------------------------------------------------------------------
  SELECT
    date_trunc('month', reference_date)::date                AS period,
    999                                                       AS series_code,
    AVG((buy_rate + sell_rate) / 2.0)                        AS value
  FROM bacen_ptax
  WHERE buy_rate IS NOT NULL
    AND sell_rate IS NOT NULL
    AND reference_date IN (
      -- last available trading day per month
      SELECT MAX(reference_date)
      FROM bacen_ptax
      WHERE buy_rate IS NOT NULL
      GROUP BY date_trunc('month', reference_date)
    )
  GROUP BY
    date_trunc('month', reference_date)::date
;

-- Unique index: enforces one row per (period, series_code)
CREATE UNIQUE INDEX ix_fact_bacen_monthly_pk
  ON fact_bacen_monthly (period, series_code);

CREATE INDEX ix_fact_bacen_monthly_period
  ON fact_bacen_monthly (period);

-- -------------------------------------------------------------------------
-- Smoke check
-- NOTICE (not EXCEPTION): BACEN data may not be populated on a fresh DB.
-- -------------------------------------------------------------------------
DO $$
DECLARE
  v_count BIGINT;
BEGIN
  SELECT COUNT(*) INTO v_count FROM fact_bacen_monthly;
  IF v_count = 0 THEN
    RAISE NOTICE 'fact_bacen_monthly empty — no BACEN data yet; run BacenIngestor then REFRESH MATERIALIZED VIEW fact_bacen_monthly';
  ELSE
    RAISE NOTICE 'fact_bacen_monthly smoke check OK: % rows', v_count;
  END IF;
END $$;

COMMIT;
