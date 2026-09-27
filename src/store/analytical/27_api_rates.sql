-- =============================================================================
-- 27_api_rates.sql
-- The Brazilian rate curve, served through schema `api` (catalog v42;
-- INSTRUMENTS.md phases B and C; OPEN_ITEMS B8):
--
--   api.future_curve   every DI1 contract on one B3 session, nearest first
--   api.future_series  one DI1 contract through time
--   api.curve          one B3 reference curve (PRE, DOC, DPL) on one session
--   api.curve_history  one of B3's FIXED vertices of a curve through time
--
-- Sources (migration 48; docs/research/dustin_br_data_sources.md):
-- b3_futures_settlement is B3's Price Report (BVBG.086.01), one row per
-- session and outright DI1 contract, from 2018-01-02 (older reports are
-- empty); b3_reference_rate is B3's reference-rate file (TaxaSwap.txt), one
-- row per session, curve and vertex, from 2008-01-02.
--
-- NOTHING IS DERIVED, with one labelled exception: contract_month, the month
-- the ticker names, read with B3's own month letters (F = January … Z =
-- December, the DI1 contract specification). A DI1 contract matures on that
-- month's first business day; the business days to maturity are neither
-- stored nor computed here. DI1 is QUOTED IN RATE: open/low/high/avg/close_px
-- and settlement_rate are % a.a. on 252 business days, so the low rate is the
-- high price, and settlement_price is the PU (R$ per contract, 100,000 at
-- maturity). Everything is served as B3 published it.
--
-- B3 EXTRAPOLATES THE LONG END OF EVERY CURVE. Manual de Curvas v21
-- (2025-12-12): past the last maturity of the contract that anchors a curve
-- (DI1 for PRE, DDI for DOC, DAP for DPL) B3 extends the last segment's
-- forward rate, so those vertices are B3's extrapolation, not prices. They
-- are served as published, and the comments below say so; where the tail
-- starts is analysis (research_examples/dustin_br finds it for PRE).
-- Rate conventions differ by curve (api.curve_registry, rate_basis on every
-- row): PRE and DPL compound on 252 business days; DOC is LINEAR on 360
-- calendar days, factor 1 + rate * calendar_days / 36000 (Manual §4.5).
--
-- Fixed and moving vertices. B3 publishes every curve on one vertex grid:
-- FIXED vertices (vertex_type F) at nominal tenors carried in vertex_code
-- (00001, 00030, … 10800 days; the actual calendar_days drift a day or two
-- with the calendar, measured: code 00030 was 30 days on 2008-01-02 and 31
-- on 2026-09-25) and MOVING vertices (M) at the maturities of B3's
-- contracts. curve_history serves a fixed vertex only: a constant tenor as
-- B3 publishes it, never an interpolation.
--
-- PRIVILEGES, ROW CAP: 26's. SECURITY DEFINER with an empty pinned
-- search_path, every relation schema-qualified; EXECUTE revoked from PUBLIC,
-- granted to anon / authenticated and to silo_api. One page plus one row,
-- then api.assert_row_cap REFUSES with 22023 above 1000 — never trimmed, no
-- cursor: narrow the window.
--
-- Ordering: after 19 (api.assert_row_cap). The guard fails the apply loudly
-- if it or the landing tables are missing.
-- =============================================================================

BEGIN;
SET statement_timeout = '30s';

DO $guard$
BEGIN
    IF to_regprocedure('api.assert_row_cap(bigint, boolean, text)') IS NULL THEN
        RAISE EXCEPTION '27_api_rates.sql needs api.assert_row_cap from 19_api_contract.sql; apply 19 first';
    END IF;
    IF to_regclass('public.b3_futures_settlement') IS NULL
       OR to_regclass('public.b3_reference_rate') IS NULL THEN
        RAISE EXCEPTION '27_api_rates.sql serves b3_futures_settlement and b3_reference_rate; apply the schema and migrations first (migration 48)';
    END IF;
END
$guard$;

-- ---------------------------------------------------------------------------
-- curve_registry — the curves held, with their rate conventions.
-- Internal (no client grant). Mirrors DEFAULT_CURVES in
-- src/parsers/b3_taxa_swap.py (tests/test_rates_contract.py pins the two).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION api.curve_registry()
RETURNS TABLE (curve TEXT, name TEXT, rate_basis TEXT, anchored_on TEXT)
LANGUAGE sql
IMMUTABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    SELECT * FROM (VALUES
        ('PRE', 'DI x pré',                          'exp_252',    'DI1 futures'),
        ('DOC', 'cupom cambial limpo (DI x dólar)',  'linear_360', 'DDI futures'),
        ('DPL', 'cupom limpo de IPCA',               'exp_252',    'DAP futures, then ANBIMA NTN-B indicative rates')
    ) AS r(curve, name, rate_basis, anchored_on);
$$;

REVOKE ALL ON FUNCTION api.curve_registry() FROM PUBLIC;

COMMENT ON FUNCTION api.curve_registry() IS
    'Internal. The B3 reference curves api.curve and api.curve_history serve, mirrored from DEFAULT_CURVES in src/parsers/b3_taxa_swap.py. rate_basis: exp_252 = % a.a. compounded on 252 business days, factor (1 + rate/100)^(business_days/252); linear_360 = % a.a. linear on 360 calendar days, factor 1 + rate * calendar_days / 36000 (B3 Manual de Curvas v21 §2.1, §3.2, §4.5). anchored_on names the contracts B3 fits the curve to; past their last maturity B3 extrapolates.';

-- ---------------------------------------------------------------------------
-- future_curve — every DI1 contract on one session, nearest maturity first
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION api.future_curve(
    p_root       TEXT DEFAULT 'DI1',   -- the contract root; only DI1 is held
    p_trade_date DATE DEFAULT NULL     -- a B3 session; NULL = the newest session held
)
RETURNS TABLE (
    trade_date           DATE,
    ticker               TEXT,      -- B3's code, e.g. DI1F27
    contract_month       DATE,      -- first day of the month the code names (B3's month letters)
    settlement_rate      NUMERIC,   -- % a.a., 252 business days (AdjstdQtTax)
    settlement_price     NUMERIC,   -- PU, R$ (AdjstdQt)
    prev_settlement_rate NUMERIC,   -- the previous session's settlement rate, as B3 prints it
    open_interest        BIGINT,
    contracts            BIGINT,    -- contracts traded in the session
    trades               INT,
    notional_brl         NUMERIC,
    open_px              NUMERIC,   -- DI1 is quoted in rate: % a.a.
    low_px               NUMERIC,
    high_px              NUMERIC,
    avg_px               NUMERIC,
    close_px             NUMERIC,
    settlement_status    TEXT,
    source               TEXT
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $fn$
#variable_conflict use_column
DECLARE
    v_root TEXT := upper(btrim(COALESCE(p_root, '')));
    v_date DATE := p_trade_date;
BEGIN
    IF v_root <> 'DI1' THEN
        RAISE EXCEPTION
            'future_curve: root % is not held; b3_futures_settlement holds DI1 (B3 Price Report, outright contracts, from 2018-01-02)',
            COALESCE(p_root, 'NULL')
            USING ERRCODE = '22023';
    END IF;

    IF v_date IS NULL THEN
        SELECT f.trade_date INTO v_date
          FROM public.b3_futures_settlement f
         WHERE f.trade_date <= CURRENT_DATE
         ORDER BY f.trade_date DESC
         LIMIT 1;
    END IF;

    RETURN QUERY
    -- One page + one, then assert_row_cap REFUSES (22023). No cursor.
    WITH page AS (
        SELECT f.trade_date AS d, f.ticker AS t,
               make_date(2000 + substr(f.ticker, 5, 2)::int,
                         strpos('FGHJKMNQUVXZ', substr(f.ticker, 4, 1)), 1) AS m,
               f.settlement_rate, f.settlement_price, f.prev_settlement_rate,
               f.open_interest, f.contracts, f.trades, f.notional_brl,
               f.open_px, f.low_px, f.high_px, f.avg_px, f.close_px,
               f.settlement_status
        FROM public.b3_futures_settlement f
        WHERE f.trade_date = v_date
          AND f.ticker ~ '^DI1[FGHJKMNQUVXZ][0-9]{2}$'
        ORDER BY m
        LIMIT 1001
    )
    SELECT g.d, g.t, g.m, g.settlement_rate, g.settlement_price, g.prev_settlement_rate,
           g.open_interest, g.contracts, g.trades, g.notional_brl,
           g.open_px, g.low_px, g.high_px, g.avg_px, g.close_px,
           g.settlement_status, 'b3_price_report'::text
    FROM page g
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'future_curve')
    ORDER BY g.m
    LIMIT 1000;
END;
$fn$;

REVOKE ALL ON FUNCTION api.future_curve(TEXT, DATE) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.future_curve(TEXT, DATE) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION api.future_curve(TEXT, DATE) TO silo_api;

COMMENT ON FUNCTION api.future_curve(TEXT, DATE) IS
    'Every outright DI1 futures contract on one B3 session (B3 Price Report BVBG.086.01, b3_futures_settlement), nearest maturity first, as published: settlement_rate (% a.a., 252 business days) and settlement_price (the PU, R$; 100,000 at maturity), the previous settlement rate, open_interest, contracts traded, trades, notional_brl and the session''s open/low/high/avg/close — which for DI1 are RATES, because B3 quotes DI1 in rate (the low rate is the high price). contract_month is the one derived column: the first day of the month the ticker names, read with B3''s month letters (F = January … Z = December); the contract matures on that month''s first business day. p_root is DI1 (the only root held); p_trade_date NULL = the newest session held, and a date with no session (a holiday, or before 2018-01-02, when B3''s Price Report history starts) returns no rows. More than 1000 rows RAISES 22023 (never trimmed); one session holds about 50.';

-- ---------------------------------------------------------------------------
-- future_series — one DI1 contract through time
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION api.future_series(
    p_ticker TEXT,                -- an outright DI1 code, e.g. DI1F27 (future_curve lists a session's)
    p_from   DATE DEFAULT NULL,   -- NULL = 12 months before p_to
    p_to     DATE DEFAULT NULL    -- NULL = today
)
RETURNS TABLE (
    trade_date           DATE,
    ticker               TEXT,
    contract_month       DATE,
    settlement_rate      NUMERIC,
    settlement_price     NUMERIC,
    prev_settlement_rate NUMERIC,
    open_interest        BIGINT,
    contracts            BIGINT,
    trades               INT,
    notional_brl         NUMERIC,
    open_px              NUMERIC,
    low_px               NUMERIC,
    high_px              NUMERIC,
    avg_px               NUMERIC,
    close_px             NUMERIC,
    settlement_status    TEXT,
    source               TEXT
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $fn$
#variable_conflict use_column
DECLARE
    v_ticker TEXT := upper(btrim(COALESCE(p_ticker, '')));
    v_to     DATE := COALESCE(p_to, CURRENT_DATE);
    v_from   DATE;
BEGIN
    IF v_ticker !~ '^DI1[FGHJKMNQUVXZ][0-9]{2}$' THEN
        RAISE EXCEPTION
            'future_series needs an outright DI1 code such as DI1F27 (root, B3 month letter, two-digit year), got %; future_curve lists the contracts of a session',
            COALESCE(p_ticker, 'NULL')
            USING ERRCODE = '22023';
    END IF;

    v_from := COALESCE(p_from, (v_to - INTERVAL '12 months')::date);
    IF v_from > v_to THEN
        RAISE EXCEPTION 'future_series: p_from (%) is after p_to (%)', v_from, v_to
            USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    -- One page + one, then assert_row_cap REFUSES (22023). No cursor.
    WITH page AS (
        SELECT f.trade_date AS d, f.ticker AS t,
               make_date(2000 + substr(f.ticker, 5, 2)::int,
                         strpos('FGHJKMNQUVXZ', substr(f.ticker, 4, 1)), 1) AS m,
               f.settlement_rate, f.settlement_price, f.prev_settlement_rate,
               f.open_interest, f.contracts, f.trades, f.notional_brl,
               f.open_px, f.low_px, f.high_px, f.avg_px, f.close_px,
               f.settlement_status
        FROM public.b3_futures_settlement f
        WHERE f.ticker = v_ticker
          AND f.trade_date BETWEEN v_from AND v_to
        ORDER BY f.trade_date
        LIMIT 1001
    )
    SELECT g.d, g.t, g.m, g.settlement_rate, g.settlement_price, g.prev_settlement_rate,
           g.open_interest, g.contracts, g.trades, g.notional_brl,
           g.open_px, g.low_px, g.high_px, g.avg_px, g.close_px,
           g.settlement_status, 'b3_price_report'::text
    FROM page g
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'future_series')
    ORDER BY g.d
    LIMIT 1000;
END;
$fn$;

REVOKE ALL ON FUNCTION api.future_series(TEXT, DATE, DATE) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.future_series(TEXT, DATE, DATE) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION api.future_series(TEXT, DATE, DATE) TO silo_api;

COMMENT ON FUNCTION api.future_series(TEXT, DATE, DATE) IS
    'One DI1 futures contract through time, oldest session first, with the same columns as api.future_curve (B3 Price Report, b3_futures_settlement, from 2018-01-02): settlement rate and PU, open interest, volume and the session''s quotes, which for DI1 are RATES (% a.a., 252 business days). p_ticker is an outright code such as DI1F27 — root, B3 month letter (F = January … Z = December), two-digit year — and anything else raises 22023; future_curve lists the contracts of a session. A contract is listed years before it matures and stops at maturity, so a window outside its life returns no rows. Nothing is rolled, spliced or made continuous: a constant-maturity rate is B3''s own curve (api.curve, api.curve_history). Default window the 12 months before p_to or today. More than 1000 rows RAISES 22023 (never trimmed): narrow p_from/p_to.';

-- ---------------------------------------------------------------------------
-- curve — one B3 reference curve on one session, shortest vertex first
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION api.curve(
    p_curve      TEXT DEFAULT 'PRE',  -- PRE, DOC or DPL (api.curve_registry)
    p_trade_date DATE DEFAULT NULL    -- a B3 session; NULL = the newest session held for the curve
)
RETURNS TABLE (
    trade_date    DATE,
    curve         TEXT,
    calendar_days INT,
    business_days INT,
    rate          NUMERIC,   -- % a.a., in rate_basis
    rate_basis    TEXT,      -- exp_252 (PRE, DPL) or linear_360 (DOC)
    vertex_type   TEXT,      -- F fixed (nominal tenor in vertex_code) or M moving (a contract maturity)
    vertex_code   TEXT,
    source        TEXT
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $fn$
#variable_conflict use_column
DECLARE
    v_curve TEXT := upper(btrim(COALESCE(p_curve, '')));
    v_basis TEXT;
    v_date  DATE := p_trade_date;
    v_known TEXT;
BEGIN
    SELECT reg.rate_basis INTO v_basis FROM api.curve_registry() reg WHERE reg.curve = v_curve;
    IF v_basis IS NULL THEN
        SELECT string_agg(reg.curve || ' (' || reg.name || ')', ', ' ORDER BY reg.curve)
          INTO v_known FROM api.curve_registry() reg;
        RAISE EXCEPTION 'unknown reference curve %; curve serves: %', COALESCE(p_curve, 'NULL'), v_known
            USING ERRCODE = '22023';
    END IF;

    IF v_date IS NULL THEN
        SELECT r.trade_date INTO v_date
          FROM public.b3_reference_rate r
         WHERE r.curve = v_curve AND r.trade_date <= CURRENT_DATE
         ORDER BY r.trade_date DESC
         LIMIT 1;
    END IF;

    RETURN QUERY
    -- One page + one, then assert_row_cap REFUSES (22023). No cursor.
    WITH page AS (
        SELECT r.trade_date AS d, r.calendar_days AS cd, r.business_days AS bd,
               r.rate AS v, r.vertex_type::text AS vt, r.vertex_code AS vc
        FROM public.b3_reference_rate r
        WHERE r.curve = v_curve
          AND r.trade_date = v_date
        ORDER BY r.calendar_days
        LIMIT 1001
    )
    SELECT g.d, v_curve, g.cd, g.bd, g.v, v_basis, g.vt, g.vc, 'b3_taxa_swap'::text
    FROM page g
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'curve')
    ORDER BY g.cd
    LIMIT 1000;
END;
$fn$;

REVOKE ALL ON FUNCTION api.curve(TEXT, DATE) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.curve(TEXT, DATE) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION api.curve(TEXT, DATE) TO silo_api;

COMMENT ON FUNCTION api.curve(TEXT, DATE) IS
    'One B3 reference curve on one session (B3 reference rates, TaxaSwap.txt, b3_reference_rate, from 2008-01-02), shortest vertex first, every vertex as published: calendar_days, business_days, rate, and whether the vertex is FIXED (vertex_type F, its nominal tenor in vertex_code) or MOVING (M, a contract maturity). PRE is DI x pré (% a.a., compounded on 252 business days; its moving vertices include every DI1 maturity at that contract''s settlement rate); DOC is the clean onshore dollar coupon (% a.a., LINEAR on 360 calendar days); DPL is the clean IPCA coupon, a real rate (% a.a., 252 business days), and B3''s implied inflation is (1 + PRE) / (1 + DPL) − 1 at the same tenor. rate_basis rides on every row. PAST THE LAST MATURITY OF THE CONTRACT THAT ANCHORS A CURVE (DI1 for PRE, DDI for DOC, DAP for DPL) B3 EXTRAPOLATES the last forward rate, so the long vertices are not prices (B3 Manual de Curvas v21). DPL''s shortest vertices lean on the current month''s IPCA projection. p_curve is PRE, DOC or DPL and anything else raises 22023 listing them; p_trade_date NULL = the newest session held, and a date with no session returns no rows. Nothing is interpolated. More than 1000 rows RAISES 22023; a session holds about 300 vertices per curve.';

-- ---------------------------------------------------------------------------
-- curve_history — one FIXED vertex of a curve through time
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION api.curve_history(
    p_curve      TEXT,               -- PRE, DOC or DPL
    p_tenor_days INT,                -- a fixed vertex's nominal tenor in calendar days (30, 90, 360, 720, 1800 …)
    p_from       DATE DEFAULT NULL,  -- NULL = 12 months before p_to
    p_to         DATE DEFAULT NULL   -- NULL = today
)
RETURNS TABLE (
    trade_date    DATE,
    curve         TEXT,
    tenor_days    INT,       -- the nominal tenor asked for (B3's vertex_code)
    calendar_days INT,       -- the vertex's actual calendar days that session
    business_days INT,
    rate          NUMERIC,
    rate_basis    TEXT,
    source        TEXT
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $fn$
#variable_conflict use_column
DECLARE
    v_curve TEXT := upper(btrim(COALESCE(p_curve, '')));
    v_basis TEXT;
    v_code  TEXT;
    v_to    DATE := COALESCE(p_to, CURRENT_DATE);
    v_from  DATE;
    v_last  DATE;
    v_known TEXT;
BEGIN
    SELECT reg.rate_basis INTO v_basis FROM api.curve_registry() reg WHERE reg.curve = v_curve;
    IF v_basis IS NULL THEN
        SELECT string_agg(reg.curve || ' (' || reg.name || ')', ', ' ORDER BY reg.curve)
          INTO v_known FROM api.curve_registry() reg;
        RAISE EXCEPTION 'unknown reference curve %; curve_history serves: %', COALESCE(p_curve, 'NULL'), v_known
            USING ERRCODE = '22023';
    END IF;
    IF p_tenor_days IS NULL OR p_tenor_days < 1 OR p_tenor_days > 99999 THEN
        RAISE EXCEPTION 'curve_history needs p_tenor_days, the nominal tenor of one of B3''s fixed vertices in calendar days (e.g. 360)'
            USING ERRCODE = '22023';
    END IF;
    v_code := lpad(p_tenor_days::text, 5, '0');

    v_from := COALESCE(p_from, (v_to - INTERVAL '12 months')::date);
    IF v_from > v_to THEN
        RAISE EXCEPTION 'curve_history: p_from (%) is after p_to (%)', v_from, v_to
            USING ERRCODE = '22023';
    END IF;

    -- A tenor that is not one of B3's fixed vertices is refused with the
    -- list, never interpolated. An empty curve (nothing loaded yet) is an
    -- empty result, not an error.
    IF NOT EXISTS (SELECT 1 FROM public.b3_reference_rate r
                   WHERE r.curve = v_curve AND r.vertex_type = 'F' AND r.vertex_code = v_code) THEN
        SELECT r.trade_date INTO v_last
          FROM public.b3_reference_rate r
         WHERE r.curve = v_curve
         ORDER BY r.trade_date DESC
         LIMIT 1;
        IF v_last IS NOT NULL THEN
            SELECT string_agg(ltrim(r.vertex_code, '0'), ', ' ORDER BY r.vertex_code)
              INTO v_known
              FROM public.b3_reference_rate r
             WHERE r.curve = v_curve AND r.trade_date = v_last AND r.vertex_type = 'F';
            RAISE EXCEPTION
                'curve_history: % days is not one of B3''s fixed % vertices; on % they were: % (a moving vertex or any other tenor is analysis: read api.curve and interpolate in the notebook)',
                p_tenor_days, v_curve, v_last, COALESCE(v_known, '(none)')
                USING ERRCODE = '22023';
        END IF;
    END IF;

    RETURN QUERY
    -- One page + one, then assert_row_cap REFUSES (22023). No cursor.
    WITH page AS (
        SELECT r.trade_date AS d, r.calendar_days AS cd, r.business_days AS bd, r.rate AS v
        FROM public.b3_reference_rate r
        WHERE r.curve = v_curve
          AND r.vertex_type = 'F'
          AND r.vertex_code = v_code
          AND r.trade_date BETWEEN v_from AND v_to
        ORDER BY r.trade_date
        LIMIT 1001
    )
    SELECT g.d, v_curve, p_tenor_days, g.cd, g.bd, g.v, v_basis, 'b3_taxa_swap'::text
    FROM page g
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'curve_history')
    ORDER BY g.d
    LIMIT 1000;
END;
$fn$;

REVOKE ALL ON FUNCTION api.curve_history(TEXT, INT, DATE, DATE) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.curve_history(TEXT, INT, DATE, DATE) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION api.curve_history(TEXT, INT, DATE, DATE) TO silo_api;

COMMENT ON FUNCTION api.curve_history(TEXT, INT, DATE, DATE) IS
    'One of B3''s FIXED vertices of a reference curve through time, oldest session first (b3_reference_rate, from 2008-01-02): a constant tenor exactly as B3 publishes it, never an interpolation. p_curve is PRE, DOC or DPL (see api.curve for what each is and its rate_basis, which rides on every row); p_tenor_days is the vertex''s NOMINAL tenor in calendar days (B3''s vertex_code: 1, 30, 60, 90 … 360 … 720 … 1800 … 10800), and calendar_days is its actual length that session, a day or two longer when the nominal date is not a business day. A tenor that is not one of B3''s fixed vertices raises 22023 listing the fixed tenors of the newest session; any other tenor is analysis — read api.curve and interpolate in the notebook. Long tenors sit in B3''s EXTRAPOLATED tail (past the last anchoring contract; B3 Manual de Curvas v21), which moves as contracts list and expire, so a long vertex can be extrapolation on one date and anchored on another. Default window the 12 months before p_to or today. More than 1000 rows RAISES 22023 (never trimmed): narrow p_from/p_to.';

COMMIT;
