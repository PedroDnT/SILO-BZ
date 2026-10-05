-- =============================================================================
-- 32_api_trade_consolidated.sql
-- B3's consolidated trade file, segment FORWARD, served through schema `api`
-- (catalog v65; research #606, docs/reference/research/portfolio-return-coverage.md):
--
--   api.trade_consolidated_history   daily prints of one FORWARD ticker, as published
--
-- WHY A SEPARATE FUNCTION. The 46 Brazilian fixed-income ETFs (IMAB11,
-- B5P211, IRFM11, LFTS11, ...) are not in COTAHIST: B3 lists them in segment
-- FORWARD, market FIXED INCOME, which the COTAHIST files do not carry, so
-- quote_history has nothing for them. Migration 57 lands their prints from
-- B3's TradeInformationConsolidatedFile in public.b3_trade_consolidated
-- (FORWARD only: the 46 ETFs plus 21 other tickers, 67 on 2026-09-29). Until
-- this function no api.* read served that table, so no return could be
-- computed for a fixed-income ETF (#606).
--
-- THE ACCEPTED TICKERS ARE THE TICKERS HELD. A ticker that is not in the
-- table is refused with 22023, saying that this function holds only the
-- FORWARD segment and that COTAHIST tickers are in quote_history. An unknown
-- ticker never gets an empty set, which would read as "no trades".
--
-- AS PUBLISHED, AND WHAT IS NOT THERE:
--   * The close is last_price. ref_price is B3's reference price: not a
--     trade and never a close. A session with no trade carries only ref_price,
--     and last_price (with min, max, avg, trade_count, quantity, notional_brl)
--     is NULL there, never 0 and never filled from ref_price.
--   * There is NO opening price. The file has none, so there is no open
--     column, and none may ever be filled from another source.
--   * notional_brl is this file's NtlFinVol. It is not comparable with
--     COTAHIST's VOLTOT or B3's BDI (migration 57: BOVA11 on 2026-09-29 is
--     R$587,459,700.14 here against R$588,765,462.41 in COTAHIST).
--   * Prices are NOT adjusted for distributions. A return from last_price is
--     a price-only return: for an ETF that distributes income (many
--     fixed-income ETFs pay coupons) it understates the real return; for one
--     that reinvests, the difference is small. There is no adjusted or return
--     column.
--   * Retention: the source's oldest session was 2025-06-10 when checked on
--     2026-09-30, so history starts there and cannot be extended backwards.
--
-- The page is 1000 rows and the function pages with the shared date cursor,
-- like quote_history and index_history.
-- =============================================================================

BEGIN;
SET statement_timeout = '5min';

CREATE OR REPLACE FUNCTION api.trade_consolidated_history(
    p_ticker TEXT,
    p_from   DATE DEFAULT (CURRENT_DATE - 365),
    p_to     DATE DEFAULT CURRENT_DATE,
    -- NULL = whole result (refuses over 1000 rows); '' = first page;
    -- 'YYYY-MM-DD' = the page after that trade_date.
    p_after  TEXT DEFAULT NULL
)
RETURNS TABLE (
    ticker          TEXT,
    trade_date      DATE,
    isin            TEXT,
    segment         TEXT,
    min_price       NUMERIC,
    max_price       NUMERIC,
    avg_price       NUMERIC,
    last_price      NUMERIC,
    ref_price       NUMERIC,
    oscillation_pct NUMERIC,
    trade_count     BIGINT,
    quantity        BIGINT,
    notional_brl    NUMERIC,
    file_status     TEXT,
    source          TEXT
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $fn$
#variable_conflict use_column
DECLARE
    v_ticker TEXT := upper(btrim(p_ticker));
BEGIN
    IF v_ticker IS NULL OR NOT EXISTS (
        SELECT 1 FROM public.b3_trade_consolidated t WHERE t.ticker = v_ticker
    ) THEN
        RAISE EXCEPTION
            'trade_consolidated_history: % is not a ticker SILO holds in B3''s consolidated trade file. This function holds only B3''s FORWARD segment (the fixed-income ETFs COTAHIST does not carry, such as IMAB11, B5P211, IRFM11, LFTS11); a COTAHIST ticker (shares, units, FIIs, equity ETFs) is in quote_history.',
            COALESCE(p_ticker, 'NULL')
            USING ERRCODE = '22023';
    END IF;
    IF p_from IS NULL OR p_to IS NULL THEN
        RAISE EXCEPTION
            'trade_consolidated_history: p_from and p_to must be dates (they default to the last 365 days and today); a NULL window would return nothing and look like no data'
            USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    WITH params AS (
        SELECT c.paging, c.after_date
        FROM api.parse_date_cursor(p_after, 'trade_consolidated_history') c
    ),
    -- One page + one. The 1001st row is what makes "over the page"
    -- detectable; assert_row_cap then REFUSES (22023) instead of handing back
    -- a truncated series that looks complete.
    page AS (
        SELECT t.ticker, t.trade_date, t.isin, t.segment,
               t.min_price, t.max_price, t.avg_price, t.last_price, t.ref_price,
               t.oscillation_pct, t.trade_count, t.quantity, t.notional_brl,
               t.file_status, t.source
        FROM public.b3_trade_consolidated t
        JOIN params pp ON TRUE
        WHERE t.ticker = v_ticker
          AND t.trade_date BETWEEN p_from AND p_to
          AND (pp.after_date IS NULL OR t.trade_date > pp.after_date)
        ORDER BY t.trade_date
        LIMIT 1001
    )
    SELECT g.ticker, g.trade_date, g.isin, g.segment,
           g.min_price::numeric, g.max_price::numeric, g.avg_price::numeric,
           g.last_price::numeric, g.ref_price::numeric, g.oscillation_pct::numeric,
           g.trade_count, g.quantity, g.notional_brl::numeric,
           g.file_status, g.source
    FROM page g
    WHERE api.assert_row_cap((SELECT count(*) FROM page),
                             (SELECT pp.paging FROM params pp), 'trade_consolidated_history')
    ORDER BY 2
    LIMIT 1000;
END;
$fn$;

COMMENT ON FUNCTION api.trade_consolidated_history(TEXT, DATE, DATE, TEXT) IS
    'Daily prints of one ticker of B3''s consolidated trade file (TradeInformationConsolidatedFile), segment FORWARD only, as published, oldest first: the 46 Brazilian fixed-income ETFs COTAHIST does not carry (IMAB11, B5P211, IRFM11, LFTS11, ...) and 21 other FORWARD tickers. A ticker not held raises 22023 (this function holds only the FORWARD segment; a COTAHIST ticker is in quote_history), never an empty set. The close is last_price. ref_price is B3''s reference price, NOT a trade and NEVER a close: a session with no trade carries only ref_price, and last_price (with min_price, max_price, avg_price, trade_count, quantity and notional_brl) is NULL there. There is NO opening price: the file has none and none is filled from another source. notional_brl is this file''s volume and is not comparable with COTAHIST''s or B3''s BDI (BOVA11 on 2026-09-29: R$587,459,700.14 here, R$588,765,462.41 in COTAHIST). Prices are NOT adjusted for distributions: a return from last_price is a price-only return, which understates the real return of an ETF that distributes income (many fixed-income ETFs pay coupons); for one that reinvests the difference is small. Retention: the source''s oldest session was 2025-06-10 when checked on 2026-09-30, so history starts there. Row cap: more than 1000 rows RAISES 22023 (never trimmed) unless p_after pages: '''' = first page, then the last row''s trade_date as ''YYYY-MM-DD''; a page shorter than 1000 is the last. Or narrow p_from/p_to. Depth is in api.coverage().';

REVOKE ALL ON FUNCTION api.trade_consolidated_history(TEXT, DATE, DATE, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.trade_consolidated_history(TEXT, DATE, DATE, TEXT) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION api.trade_consolidated_history(TEXT, DATE, DATE, TEXT) TO silo_api;

COMMIT;
