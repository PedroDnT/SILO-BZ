-- 30 — mv_b3_monthly_activity: stop re-reading the whole tape for ~100 rows
--
-- WHY
-- On 2026-08-28 the PRODUCTION dashboard build failed (Vercel deployment
-- dpl_7KGd3f6ryn3NcikxdBpTSzwuR9D8, commit 815c8bd). Its log stops immediately
-- before `b3_monthly_volume`, which was measured running for 26 minutes against
-- production, and the build hit Vercel's 45-minute ceiling. The site never
-- rebuilt.
--
-- Five dashboard sources aggregate the FULL 2019-2026 COTAHIST tape on every
-- build, each to produce about ninety rows:
--
--   b3_monthly_volume, b3_options_activity, b3_asset_class_volume,
--   etf_market_series, b3_market_overview
--
-- Timings from that failed build: aum_by_entity 3.5 min, b3_asset_class_volume
-- 8 min, b3_market_overview 4.4 min, b3_monthly_volume never finished.
--
-- The same scans are why two schema applies died the same day with
-- "canceling statement due to lock timeout": an Evidence build holding
-- AccessShareLock on b3_cotahist for tens of minutes outlasts any DDL retry.
-- One cause, three symptoms — slow builds, failed deploys, a stale site.
--
-- WHAT
-- One pass over the tape per day instead of five per build. GROUPING SETS
-- because COUNT(DISTINCT ...) is NOT re-aggregatable: summing per-subtype
-- ticker counts to a per-type total double-counts anything that appears under
-- both, so each grain computes its own exact distinct count rather than being
-- derived from a finer one.
--
-- `grain` is an explicit label, not an inference from NULLs, because a NULL
-- here is genuinely ambiguous: instrument_subtype IS NULL means "rolled up"
-- in one row and "this instrument has no subtype" (an equity) in another.
-- Consumers filter on grain and are never asked to tell those apart.
--
-- Created WITH NO DATA and populated by a separate REFRESH — migration 27 held
-- pg_type uncommitted for a whole tape scan and blocked concurrent schema
-- applies (PR #137). Same guard here: relispopulated, not a SELECT, because an
-- unpopulated matview raises rather than returning zero rows.

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_b3_monthly_activity AS
WITH src AS (
    SELECT
        date_trunc('month', v.trade_date)::date AS period,
        v.trade_date,
        v.codneg,
        v.tpmerc,
        v.instrument_type,
        v.instrument_subtype,
        v.volume,
        v.preco_fechamento,
        CASE
            WHEN v.tpmerc IN ('010', '020', '021') THEN 'cash'
            WHEN v.tpmerc IN ('070', '080')        THEN 'option'
            WHEN v.tpmerc IN ('012', '013')        THEN 'option_exercise'
            WHEN v.tpmerc = '030'                  THEN 'forward'
            WHEN v.tpmerc = '017'                  THEN 'auction'
            ELSE 'other'
        END AS market_segment
    FROM vw_b3_instrument_typed v
)
SELECT
    CASE
        WHEN GROUPING(s.instrument_subtype) = 0 THEN 'subtype'
        WHEN GROUPING(s.instrument_type)    = 0 THEN 'type'
        WHEN GROUPING(s.tpmerc)             = 0 THEN 'tpmerc'
        ELSE                                         'segment'
    END                                                              AS grain,
    s.period,
    s.market_segment,
    s.tpmerc,
    s.instrument_type,
    s.instrument_subtype,
    SUM(s.volume)                                                    AS volume,
    COUNT(DISTINCT s.codneg)                                         AS n_tickers,
    COUNT(DISTINCT s.trade_date)                                     AS n_sessions,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY s.preco_fechamento)  AS median_close
FROM src s
GROUP BY GROUPING SETS (
    -- monthly volume by board code, and the option call/put split
    (s.period, s.market_segment, s.tpmerc),
    -- distinct series across a whole segment: a call and a put are different
    -- codneg, but that is a fact about B3's naming, not something to lean on
    (s.period, s.market_segment),
    -- volume and ticker counts per instrument type (cash boards)
    (s.period, s.market_segment, s.tpmerc, s.instrument_type),
    -- ETF/FII splits and the ETF median close
    (s.period, s.market_segment, s.tpmerc, s.instrument_type, s.instrument_subtype)
)
WITH NO DATA;

-- REFRESH ... CONCURRENTLY (pg_cron, 08_cron_schedules.sql) requires a unique
-- index. NULLS NOT DISTINCT: the rolled-up grains carry NULLs in the columns
-- they roll up, and without it those rows would not be unique to the index.
CREATE UNIQUE INDEX IF NOT EXISTS uq_b3_monthly_activity
    ON mv_b3_monthly_activity (grain, period, market_segment, tpmerc,
                               instrument_type, instrument_subtype)
    NULLS NOT DISTINCT;

CREATE INDEX IF NOT EXISTS idx_b3_monthly_activity_grain
    ON mv_b3_monthly_activity (grain, period);

DO $silo_refresh_mv_b3_monthly_activity$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relname = 'mv_b3_monthly_activity'
      AND c.relkind = 'm'
      AND NOT c.relispopulated
  ) THEN
    REFRESH MATERIALIZED VIEW mv_b3_monthly_activity;
  END IF;
END
$silo_refresh_mv_b3_monthly_activity$;

COMMENT ON MATERIALIZED VIEW mv_b3_monthly_activity IS
  'Monthly COTAHIST aggregates at four grains (see the grain column). Exists so the dashboard stops scanning the full tape on every build — that cost a production deploy on 2026-08-28. Refreshed daily by pg_cron; filter on grain, never on NULL.';
