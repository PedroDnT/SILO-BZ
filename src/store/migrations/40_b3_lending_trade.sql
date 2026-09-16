-- 40_b3_lending_trade.sql — individual securities-lending trades, with the broker on each leg.
--
-- Completes the lending group from migration 39. Idempotent (IF NOT EXISTS +
-- a named UNIQUE constraint) and psql-clean: CI applies with -v ON_ERROR_STOP=1.
-- The same DDL is mirrored into schema.sql, which stays canonical.

-- ---------------------------------------------------------------------------
-- B3 securities-lending trades, one row per individual trade (BTBTrade).
--
-- The other lending tables say how much is on loan and at what rate.
-- This one says WHO traded it: every trade carries the brokerage on each leg.
--
-- READ THIS BEFORE INFERRING ANYTHING DIRECTIONAL
-- -----------------------------------------------
-- `doador` and `tomador` are BROKERAGES, not beneficial owners. Verified on
-- 2026-09-10: the whole session names only 33 distinct participants, and
-- 32,197 of 43,165 trades (74.6%) carry the SAME code on both legs — the
-- broker intermediating its own clients' book. So "XP borrowed 2m shares"
-- means XP's clients were net borrowers through XP, not that XP is short.
-- Anything published off this table has to say so, which is why
-- fact_lending_participant_daily carries `internal_trades` beside the totals
-- rather than quietly netting them away.
--
-- SIZE AND WHY IT IS PARTITIONED
-- ------------------------------
-- ~43k rows per session, ~5.9 MB of CSV — roughly 10M rows a year, an order
-- of magnitude more than every other table in migration 39 combined. Ranged
-- by trade_date like b3_cotahist so a year can be detached or vacuumed on its
-- own. Partitions run to 2029; beyond that rows land in `_future` and the
-- yearly rollover in docs/DATABASE_MAINTENANCE.md §6 applies to this table
-- too.
--
-- Same ~21-business-day retention and the same ratchet as migration 39: a
-- session not captured is gone. Worse here, because there is no aggregate to
-- fall back on — b3_lending_rate keeps the session's average rate, but the
-- individual trades behind it exist nowhere else.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS b3_lending_trade (
    id                BIGSERIAL,
    trade_date        DATE         NOT NULL,
    -- "Número do negócio". Unique within a session (verified: 0 duplicates in
    -- 43,165 rows), so it keys the row with its date. B3 publishes it with
    -- thousand separators ("113.392.202"); stored as the integer it is.
    numero_negocio    BIGINT       NOT NULL,
    codneg            TEXT         NOT NULL,
    quantidade        NUMERIC(28, 4),
    -- Annualized, in percentage points as published (40,00% -> 40.00), the
    -- same convention as b3_lending_rate.taxa_*.
    taxa_pct          NUMERIC(12, 4),
    -- Balcão | Eletrônico D+1 | Eletrônico D0. NOTE these labels differ from
    -- b3_lending_open_position.mercado ("Registro", "Neg. Eletrônica D+1"):
    -- B3 names the same venues differently across its own exports, so do not
    -- join the two on this column.
    mercado           TEXT,
    -- Wall clock as published. B3 names no timezone on this export, so the
    -- date and time stay separate rather than being fused into a timestamptz
    -- whose offset we would have had to invent.
    hora              TEXT,
    acao_atualizacao  TEXT,        -- "Novo (0)"; the field exists for amendments
    tipo_sessao       TEXT,        -- "Regular (1)"
    doador_codigo     TEXT,        -- lender leg: B3 participant code
    doador_nome       TEXT,
    tomador_codigo    TEXT,        -- borrower leg
    tomador_nome      TEXT,
    source            TEXT         NOT NULL DEFAULT 'b3_bdi',
    -- NO `raw` COLUMN, deliberately. Most landing tables here keep one because
    -- their CSV has dozens of columns and the field map selects a subset, so
    -- raw is where the rest survives. This export publishes exactly 13 columns
    -- and all 13 are typed above, making raw a re-encoding of the same values:
    -- measured at 324 of 506 bytes per row, 64% of the heap, ~4 GB a year for
    -- no information. cvm_fidc_cedente, cvm_fidc_sacado, bacen_sgs and four
    -- others omit it on the same grounds.
    --
    -- What raw would otherwise have caught — B3 adding a column — is caught
    -- instead by the parser, which logs every unmapped header label loudly
    -- rather than dropping it silently. Detection without the storage.
    fetched_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_b3_lending_trade UNIQUE (trade_date, numero_negocio)
) PARTITION BY RANGE (trade_date);

-- This table can only ever hold what the daily job has captured, and capture
-- starts the day it is deployed — so there is no history before 2026. The
-- MINVALUE partition exists anyway: a backfilled or mis-dated row must land
-- somewhere rather than abort the insert.
CREATE TABLE IF NOT EXISTS b3_lending_trade_pre2026 PARTITION OF b3_lending_trade
    FOR VALUES FROM (MINVALUE) TO ('2026-01-01');
CREATE TABLE IF NOT EXISTS b3_lending_trade_2026 PARTITION OF b3_lending_trade
    FOR VALUES FROM ('2026-01-01') TO ('2027-01-01');
CREATE TABLE IF NOT EXISTS b3_lending_trade_2027 PARTITION OF b3_lending_trade
    FOR VALUES FROM ('2027-01-01') TO ('2028-01-01');
CREATE TABLE IF NOT EXISTS b3_lending_trade_2028 PARTITION OF b3_lending_trade
    FOR VALUES FROM ('2028-01-01') TO ('2029-01-01');
CREATE TABLE IF NOT EXISTS b3_lending_trade_2029 PARTITION OF b3_lending_trade
    FOR VALUES FROM ('2029-01-01') TO ('2030-01-01');
CREATE TABLE IF NOT EXISTS b3_lending_trade_future PARTITION OF b3_lending_trade
    FOR VALUES FROM ('2030-01-01') TO (MAXVALUE);

CREATE INDEX IF NOT EXISTS idx_b3_lending_trade_codneg
    ON b3_lending_trade (codneg, trade_date DESC);
CREATE INDEX IF NOT EXISTS idx_b3_lending_trade_date
    ON b3_lending_trade (trade_date DESC);
-- The question this table exists to answer: what did one broker do.
CREATE INDEX IF NOT EXISTS idx_b3_lending_trade_tomador
    ON b3_lending_trade (tomador_codigo, trade_date DESC);
CREATE INDEX IF NOT EXISTS idx_b3_lending_trade_doador
    ON b3_lending_trade (doador_codigo, trade_date DESC);

COMMENT ON TABLE b3_lending_trade IS
    'Individual B3 securities-lending trades (BTBTrade): ticker, quantity, annualized rate, venue, time, and the brokerage on each leg. doador/tomador are BROKERS intermediating, not beneficial owners — ~75% of trades carry the same code on both legs. ~43k rows/session; same ~21-business-day source retention as the rest of the lending group, and no aggregate preserves the individual trades, so an uncaptured session is unrecoverable.';
