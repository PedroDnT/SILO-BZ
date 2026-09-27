-- 48_rates_market_data.sql — DI1 futures, B3 reference curves, global market series.
--
-- Three tables, mirrored verbatim into schema.sql (which stays canonical).
-- Idempotent (IF NOT EXISTS + named UNIQUE constraints) and psql-clean: CI
-- applies with -v ON_ERROR_STOP=1. Source decisions, coverage and the
-- point-in-time rules: docs/research/dustin_br_data_sources.md.
--
-- b3_futures_settlement — B3 Price Report (BVBG.086.01), one row per
--   (session, outright futures ticker); DI1 only by default. Values AS
--   PUBLISHED: for DI1 the price columns are RATES (% a.a.), settlement_price
--   is the PU and settlement_rate the settlement rate. An untraded contract
--   keeps NULL prices and still carries settlement and open interest. The
--   ticker is the natural key and is not decomposed (INSTRUMENTS.md).
--   History: the Price Report begins 2018-01-02 (measured).
--
-- b3_reference_rate — B3 TaxaSwap reference rates, one row per (session,
--   curve, vertex in calendar days). PRE (DI x pré, 252 business-day basis:
--   its moving vertices sit on every DI1 maturity at that contract's
--   settlement rate, measured 2026-09-25) and DOC (clean onshore dollar
--   coupon). maturity = trade_date + calendar_days. History from 2008-01-02.
--
-- mkt_series — non-Brazilian daily series from their primary publishers,
--   long: U.S. Treasury par yields (source us_treasury), Cboe VIX OHLC
--   (cboe), EIA Brent spot (eia). A new series or source is new rows, not a
--   migration. first_seen_at is never sent by the upsert, so it keeps SILO's
--   first sighting of the value: the vintage for every row fetched daily from
--   now on (a backfilled row's first_seen_at is the backfill, not the
--   publication — see the research doc §8 for the rules used for history).
--
-- None of the three is served through schema api: the prefixes b3_ and mkt_
-- are in 12_grants_and_rls.sql's revoke sweep.

CREATE TABLE IF NOT EXISTS b3_futures_settlement (
    id                            BIGSERIAL    PRIMARY KEY,
    trade_date                    DATE         NOT NULL,
    ticker                        TEXT         NOT NULL,
    instrument_id                 BIGINT,
    trades                        INT,
    contracts                     BIGINT,
    notional_brl                  NUMERIC,
    open_interest                 BIGINT,
    open_px                       NUMERIC,
    low_px                        NUMERIC,
    high_px                       NUMERIC,
    avg_px                        NUMERIC,
    close_px                      NUMERIC,
    best_bid                      NUMERIC,
    best_ask                      NUMERIC,
    settlement_price              NUMERIC      NOT NULL CHECK (settlement_price > 0),
    settlement_rate               NUMERIC,
    settlement_status             TEXT,
    prev_settlement_price         NUMERIC,
    prev_settlement_rate          NUMERIC,
    prev_settlement_status        TEXT,
    variation_points              NUMERIC,
    settlement_value_per_contract NUMERIC,
    report_created_at             TIMESTAMP,
    raw                           JSONB        NOT NULL,
    fetched_at                    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_b3_futures_settlement UNIQUE (trade_date, ticker)
);
CREATE INDEX IF NOT EXISTS idx_b3_futures_settlement_ticker_date
    ON b3_futures_settlement (ticker, trade_date DESC);

CREATE TABLE IF NOT EXISTS b3_reference_rate (
    id             BIGSERIAL    PRIMARY KEY,
    trade_date     DATE         NOT NULL,
    curve          TEXT         NOT NULL,
    curve_desc     TEXT,
    calendar_days  INT          NOT NULL CHECK (calendar_days > 0),
    business_days  INT          NOT NULL CHECK (business_days >= 0),
    rate           NUMERIC      NOT NULL,
    vertex_type    CHAR(1)      NOT NULL CHECK (vertex_type IN ('F', 'M')),
    vertex_code    TEXT,
    fetched_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_b3_reference_rate UNIQUE (curve, trade_date, calendar_days)
);
CREATE INDEX IF NOT EXISTS idx_b3_reference_rate_date
    ON b3_reference_rate (trade_date DESC);

CREATE TABLE IF NOT EXISTS mkt_series (
    id                BIGSERIAL    PRIMARY KEY,
    source            TEXT         NOT NULL,
    series_id         TEXT         NOT NULL,
    observation_date  DATE         NOT NULL,
    value             NUMERIC      NOT NULL,
    unit              TEXT         NOT NULL,
    first_seen_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_mkt_series UNIQUE (source, series_id, observation_date)
);
CREATE INDEX IF NOT EXISTS idx_mkt_series_series_date
    ON mkt_series (series_id, observation_date DESC);
