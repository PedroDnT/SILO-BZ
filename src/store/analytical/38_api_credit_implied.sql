-- =============================================================================
-- 38_api_credit_implied.sql
-- api.credit_implied_rate: the CALCULATED yield of each B3 traded debenture
-- average PU, served through schema `api` (catalog v79, #1007, ADR 0004).
--
-- It is not an observation. b3_credit_implied_rate holds the yield that
-- discounts a bond's published agenda to that PU (method_version says how);
-- every row says is_calculated = TRUE and carries the B3 capture it came from.
-- The source rows of api.credit_market_history are never changed.
--
-- THE CHECK TAGS. confidence, outlier and thin_trade come from
-- public.credit_implied_vs_anbima (37_credit_implied_check.sql). The function
-- returns the tags only. ANBIMA's own indicative rate and the gap to it stay in
-- the private view: ANBIMA data is collected here, not republished.
--   confidence  checked    ANBIMA's indicative rate of the same code and day is
--                          within 1 pp of the calculated rate
--               divergent  it differs by more than 1 pp
--               unchecked  no comparable ANBIMA rate (none that day, or pct_di)
--   outlier     divergent by more than 5 pp
--   thin_trade  traded volume under BRL 20 thousand
-- 'unchecked' is not 'good': it means no check was possible.
--
-- PRIVILEGES, ROW CAP: 33's. The tables carry no client grant. The function is
-- SECURITY DEFINER with an empty pinned search_path; EXECUTE revoked from PUBLIC,
-- granted to anon / authenticated and to silo_api. One page plus one row, then
-- api.assert_row_cap REFUSES with 22023 above 1000, never trimmed, no cursor:
-- narrow p_from / p_to.
-- =============================================================================

BEGIN;

DO $guard$
BEGIN
    IF to_regprocedure('api.assert_row_cap(bigint, boolean, text)') IS NULL THEN
        RAISE EXCEPTION '38_api_credit_implied.sql needs api.assert_row_cap from 19_api_contract.sql; apply 19 first';
    END IF;
    IF to_regclass('public.credit_implied_vs_anbima') IS NULL
       OR to_regclass('public.b3_credit_implied_rate') IS NULL THEN
        RAISE EXCEPTION '38_api_credit_implied.sql reads credit_implied_vs_anbima (37) and b3_credit_implied_rate; apply them first';
    END IF;
END
$guard$;

CREATE OR REPLACE FUNCTION api.credit_implied_rate(
    p_code TEXT,
    p_from DATE DEFAULT (CURRENT_DATE - 365),
    p_to DATE DEFAULT CURRENT_DATE
)
RETURNS TABLE (
    instrument_code TEXT,
    trade_date DATE,
    settlement_date DATE,
    trade_classification TEXT,
    method_version TEXT,
    is_calculated BOOLEAN,
    pu_brl NUMERIC,
    quantity NUMERIC,
    volume_brl NUMERIC,
    trade_count INTEGER,
    indexador TEXT,
    forma_remuneracao TEXT,
    contract_rate_pct NUMERIC,
    implied_rate_pct NUMERIC,
    rate_basis TEXT,
    flows_used INTEGER,
    confidence TEXT,
    outlier BOOLEAN,
    thin_trade BOOLEAN,
    b3_capture_id UUID,
    computed_at TIMESTAMPTZ,
    source TEXT
)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = ''
AS $fn$
#variable_conflict use_column
DECLARE
    v_code TEXT := upper(btrim(p_code));
BEGIN
    IF v_code IS NULL OR v_code !~ '^[A-Z0-9]{4,12}$' THEN
        RAISE EXCEPTION 'credit_implied_rate: p_code must be a debenture instrument code'
            USING ERRCODE = '22023';
    END IF;
    IF p_from IS NULL OR p_to IS NULL OR p_from > p_to THEN
        RAISE EXCEPTION 'credit_implied_rate: require an ordered date window'
            USING ERRCODE = '22023';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.b3_credit_implied_rate r WHERE r.codigo = v_code
    ) THEN
        RAISE EXCEPTION 'credit_implied_rate: no calculated rate for code: %', v_code
            USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    WITH page AS MATERIALIZED (
        SELECT r.codigo, r.trade_date, r.settlement_date, r.trade_classification,
               r.method_version, r.is_calculated, r.pu_brl, r.quantity, r.volume_brl,
               r.trade_count, r.indexador, r.forma_remuneracao, r.contract_rate_pct,
               r.implied_rate_pct, r.rate_basis, r.flows_used,
               v.confidence, v.outlier, v.thin_trade, r.b3_capture_id, r.computed_at
        FROM public.b3_credit_implied_rate r
        JOIN public.credit_implied_vs_anbima v
          ON v.codigo = r.codigo AND v.trade_date = r.trade_date
         AND v.settlement_date = r.settlement_date
         AND v.trade_classification = r.trade_classification
         AND v.method_version = r.method_version
        WHERE r.codigo = v_code AND r.trade_date BETWEEN p_from AND p_to
        ORDER BY r.trade_date, r.settlement_date, r.trade_classification, r.method_version
        LIMIT 1001
    )
    SELECT g.codigo, g.trade_date, g.settlement_date, g.trade_classification,
           g.method_version, g.is_calculated, g.pu_brl, g.quantity, g.volume_brl,
           g.trade_count, g.indexador, g.forma_remuneracao, g.contract_rate_pct,
           g.implied_rate_pct, g.rate_basis, g.flows_used,
           g.confidence, g.outlier, g.thin_trade, g.b3_capture_id, g.computed_at,
           'b3_traded_pu_calculated'::text
    FROM page g
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'credit_implied_rate')
    ORDER BY g.trade_date, g.settlement_date, g.trade_classification, g.method_version
    LIMIT 1000;
END;
$fn$;

COMMENT ON FUNCTION api.credit_implied_rate(TEXT, DATE, DATE) IS
    'CALCULATED, not observed: the yield that discounts a debenture''s published agenda (coupons, amortisation, maturity) to the average PU of a B3 trade group (api.credit_market_history avg_price), one row per trade_date, settlement_date, trade_classification and method_version, oldest first. is_calculated is always true; method_version says how (v1: 252 business days, ANBIMA holiday table, flat-forward pre curve from B3 TaxaSwap). rate_basis says what implied_rate_pct is: pre_aa, ipca_real_aa and di_spread_aa are percent a year; pct_di is a percent of DI. contract_rate_pct is the contracted rate for comparison. The PU is read as dirty; the average PU of a group mixes the trades of the day, and a yield of an average is not an average of yields. A trade group the method cannot price has no row (the daily log counts why), never a guess. Check tags: confidence is checked, divergent or unchecked against ANBIMA''s indicative rate of the same code and day (within 1 pp, more than 1 pp, or no comparable rate); outlier is divergent by more than 5 pp; thin_trade is volume under BRL 20 thousand. unchecked means no check was possible, not that the row is good. ANBIMA''s own rate and the gap to it are not served. In the first run (2026-10-01 to 10-26) the median absolute gap to ANBIMA was 0.13 pp; the worst gaps were thin trades. Unknown code (no calculated rate) raises 22023; a known code with no rows in the window returns an empty set. Row cap: more than 1000 rows RAISES 22023, never trimmed; narrow p_from/p_to. No cursor.';

REVOKE ALL ON FUNCTION api.credit_implied_rate(TEXT, DATE, DATE) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.credit_implied_rate(TEXT, DATE, DATE) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION api.credit_implied_rate(TEXT, DATE, DATE) TO silo_api;

COMMIT;
