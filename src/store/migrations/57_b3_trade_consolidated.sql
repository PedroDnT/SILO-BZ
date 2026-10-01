-- Migration 57: B3's consolidated trade file, fixed income ETF segment.
--
-- WHY. The 46 ETFs cvm_etf_registry labels fixed_income_br (IMAB11, B5P211,
-- IRFM11, LFTS11, BLFT11, ...) have never had a row in b3_cotahist. B3 does
-- not put them in COTAHIST: checked 2026-09-30 against the daily files of
-- 2026-01-02, 2026-09-01 and 2026-09-29 and the 2024 yearly file. B3's own
-- instrument file lists them in segment FORWARD, market FIXED INCOME, which
-- the COTAHIST series does not cover. The parser filters nothing; the rows
-- are simply not in the file.
--
-- SOURCE. B3's TradeInformationConsolidatedFile, the "Negócios consolidados
-- do pregão" file, one CSV per session:
--
--   GET https://arquivos.b3.com.br/api/download/requestname
--       ?fileName=TradeInformationConsolidatedFile&date=YYYY-MM-DD&recaptchaToken=
--   -> {"redirectUrl": "~/download?token=..."}
--   GET https://arquivos.b3.com.br/api/download/?token=...
--   -> "Status do Arquivo: Final", then a ';' header row
--      RptDt;TckrSymb;ISIN;SgmtNm;MinPric;MaxPric;TradAvrgPric;LastPric;
--      OscnPctg;AdjstdQt;AdjstdQtTax;RefPric;TradQty;FinInstrmQty;NtlFinVol
--
-- Checked against COTAHIST on 2026-09-29: BOVA11's min, max, average, last,
-- trade count and quantity match to the cent and the unit. Its NtlFinVol
-- (R$587,459,700.14) does NOT match COTAHIST's VOLTOT (R$588,765,462.41),
-- and B3's BDI export says R$588,029,283.44. Volume is stored as this file
-- publishes it and is not comparable across the three sources.
--
-- The file has NO opening price, so this table has none. Never fill one from
-- another source.
--
-- SCOPE. Segment FORWARD only (src/pipeline/ingest_b3_trade_consolidated.py,
-- SEGMENTS): every other segment of the file is already in b3_cotahist or out
-- of scope. FORWARD held 67 tickers on 2026-09-29, all 46 of the registry's
-- fixed_income_br ETFs plus 21 the registry does not list (NTNF11, SELI11,
-- XB3011, ...). The table keys on what B3 published, not on the registry.
--
-- RETENTION AND CALENDAR. On 2026-09-30 the oldest session the endpoint
-- served was 2025-06-10: a weekday before it gets a token and an EMPTY body.
-- A weekend, a holiday (2026-09-07) or a future date gets HTTP 400 at the
-- token step. Both are logged `skipped`, never stored as a row. Whether the
-- retention edge moves forward every day, as the BDI tables' does, was not
-- yet known.

BEGIN;

CREATE TABLE IF NOT EXISTS b3_trade_consolidated (
    trade_date       DATE        NOT NULL,   -- RptDt
    ticker           TEXT        NOT NULL,   -- TckrSymb
    isin             TEXT,                   -- ISIN
    segment          TEXT        NOT NULL,   -- SgmtNm, as published
    min_price        NUMERIC(20, 8) CHECK (min_price > 0),
    max_price        NUMERIC(20, 8) CHECK (max_price > 0),
    avg_price        NUMERIC(20, 8) CHECK (avg_price > 0),
    last_price       NUMERIC(20, 8) CHECK (last_price > 0),
    oscillation_pct  NUMERIC(20, 8),         -- OscnPctg, percent as published
    adjusted_qty     NUMERIC(24, 8),         -- AdjstdQt
    adjusted_qty_tax NUMERIC(24, 8),         -- AdjstdQtTax
    -- RefPric: B3's reference price. Not a trade; a session with no trade
    -- carries only this, and it is never a close.
    ref_price        NUMERIC(20, 8),
    trade_count      BIGINT      CHECK (trade_count >= 0),   -- TradQty
    quantity         BIGINT      CHECK (quantity >= 0),      -- FinInstrmQty
    notional_brl     NUMERIC(24, 2) CHECK (notional_brl >= 0), -- NtlFinVol
    -- The file's own "Status do Arquivo" line. Only 'Final' is stored.
    file_status      TEXT        NOT NULL,
    source           TEXT        NOT NULL DEFAULT 'b3_trade_consolidated_file',
    fetched_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_b3_trade_consolidated UNIQUE (ticker, trade_date)
);

CREATE INDEX IF NOT EXISTS ix_b3_trade_consolidated_date
    ON b3_trade_consolidated (trade_date);

-- Close the window before the analytical apply's sweep: Supabase's default
-- privileges grant every new public table to anon/authenticated. Landing
-- tables carry no client grant (12_grants_and_rls.sql).
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon')
       AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        EXECUTE 'REVOKE ALL ON b3_trade_consolidated FROM anon, authenticated';
    END IF;
END $$;

COMMENT ON TABLE b3_trade_consolidated IS
    'B3 TradeInformationConsolidatedFile rows for segment FORWARD (fixed income ETFs, which COTAHIST does not carry), one row per ticker and session, as published. No opening price exists in the source. ref_price is a reference, not a trade. notional_brl is this file''s volume and differs from COTAHIST''s VOLTOT for the same session.';

COMMIT;
