-- Migration 55: daily levels of B3's published indices (#412), served by
-- api.index_history (#415). The benchmark a market-neutral research caller
-- needs: BOVA11 and IBOV11 are NOT the index (IBOV11 is the options settlement
-- leg, and prints only on expiry days), and BACEN's SGS 7 stopped in 2019.
--
-- SOURCE. B3's index statistics proxy, the JSON the index page calls:
--
--   GET https://sistemaswebb3-listados.b3.com.br/indexStatisticsProxy/
--       IndexCall/GetPortfolioDay/{base64 {"index":"IBOV","language":"pt-br","year":"2025"}}
--
-- One call is one calendar YEAR, as a 31 x 12 grid (`day` by `rateValue1..12`
-- for the months), with Brazilian decimals ("161.125,37"). A null cell is a
-- day with no session (weekend, holiday, a 30th of February). The published
-- IBOV 2025-12-30 is 161,125.37, the figure in B3's year-end news item.
--
-- LEVELS ARE STORED AS PUBLISHED. B3 re-scales the series from time to time,
-- and the published history is NOT adjusted across it, so a level ratio
-- across one of those sessions is not a return. `divisor_step` marks the
-- first session on the new scale. There are 11 for IBOV, all found on
-- 2026-09-30 in the full 1968-2026 series by a one-session level ratio of
-- about 1/10 (1/100 on 1983-10-04): 1983-10-04, 1985-12-03, 1988-08-30,
-- 1989-04-18, 1990-01-15, 1991-05-29, 1992-01-22, 1993-01-27, 1993-08-30,
-- 1994-02-10 and 1997-03-03. The list lives in the ingest
-- (src/pipeline/ingest_b3_index.py), which refuses any other one-session
-- move beyond a factor of two: a new step is reviewed, never silently served
-- as a return. 1991-02-04 (+36%) is a real move, not a step.
--
-- An ingest that runs while the session is open can store an intraday level;
-- the nightly run, which refetches every year, overwrites it.

BEGIN;

CREATE TABLE IF NOT EXISTS b3_index_level (
    -- B3's index code (IBOV). Not a ticker: no BOVA11, no IBOV11.
    index_code   TEXT        NOT NULL,
    trade_date   DATE        NOT NULL,
    -- Points, as published. Not adjusted for a divisor step.
    level        NUMERIC(24, 6) NOT NULL CHECK (level > 0),
    -- TRUE on the first session after B3 re-scaled the series.
    divisor_step BOOLEAN     NOT NULL DEFAULT FALSE,
    source       TEXT        NOT NULL DEFAULT 'b3_index_statistics',
    -- When the row was first stored.
    fetched_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_b3_index_level UNIQUE (index_code, trade_date)
);

COMMENT ON TABLE b3_index_level IS
    'Daily levels of B3-published indices (IBOV from 1968-01-02), as published by B3''s index statistics proxy, one row per index and session. divisor_step marks the first session after B3 re-scaled the series: the level is not adjusted, so a ratio across a step is not a return. Served by api.index_history.';

COMMIT;
