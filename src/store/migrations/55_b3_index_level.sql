-- =============================================================================
-- Migration 55 — b3_index_level: B3's published daily index closes (#412)
--
-- The research seam's benchmark (RESEARCH_SEAM.md §5) is the index level as
-- its administrator publishes it. BACEN SGS 7 stopped on 2019-09-30, and the
-- tape's IBOV11 is the options settlement index, printed on expiry days only;
-- BOVA11 is an ETF. Neither may stand in for the index.
--
-- Source: B3's index-statistics proxy, one call per index and year
-- (src/fetchers/b3_index_level_fetcher.py). Levels are stored exactly as
-- published, two decimals, keyed on (index_code, trade_date). A day with no
-- published level has no row: B3 publishes none on a non-session day.
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS b3_index_level (
    -- B3's own index code as the endpoint takes it (IBOV).
    index_code  TEXT          NOT NULL,
    trade_date  DATE          NOT NULL,
    -- The closing level, index points, as published ("161.125,37").
    level       NUMERIC(18,2) NOT NULL CHECK (level > 0),
    source      TEXT          NOT NULL DEFAULT 'b3_index_statistics',
    -- The exact request that returned the row (index and year in its token).
    source_url  TEXT,
    fetched_at  TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_b3_index_level UNIQUE (index_code, trade_date)
);

COMMENT ON TABLE b3_index_level IS
    'B3 index closing levels as published by the index administrator (indexStatisticsProxy GetPortfolioDay, one call per index and year). One row per (index_code, trade_date) with a published level; no row on a non-session day. Served by api.index_history.';

COMMIT;
