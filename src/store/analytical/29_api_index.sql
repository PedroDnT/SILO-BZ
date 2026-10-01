-- =============================================================================
-- 29_api_index.sql
-- The benchmark index, served through schema `api` (catalog v45; the
-- research-seam spec, docs/planning/RESEARCH_SEAM.md §5; tickets #412, #415):
--
--   api.index_history   daily levels of a B3-published index, as published
--
-- WHY THIS IS NOT quote_history('IBOV11'). IBOV11 is the Ibovespa OPTIONS
-- settlement code: each print is that session's settlement index, never the
-- official close (in 2026 none of its 181 prints equals the close; they differ
-- by 0.18% on average and by up to 1.07%). It printed on expiry days only
-- through 2024, weekly in 2025 and on nearly every session since December
-- 2025, so a dense IBOV11 series is not a sign that it is the index.
-- BOVA11 is an ETF. Neither may stand in for the index,
-- so this function takes an INDEX CODE and refuses everything else, which makes
-- the substitution impossible by construction instead of by a warning.
--
-- THE ACCEPTED CODES ARE THE CODES HELD. They are the distinct index_code
-- values in b3_index_level, which src/pipeline/ingest_b3_index.py fills from a
-- closed list (IBOV today). A ticker is never in the table, so it is refused;
-- an index that has not been loaded yet is refused too, and the message lists
-- what is held (nothing, before the first ingest), which is honest.
--
-- LEVELS ARE AS PUBLISHED AND THE SERIES IS NOT ADJUSTED. B3 re-scaled IBOV
-- eleven times (÷100 on 1983-10-04, ÷10 on ten other sessions, the last on
-- 1997-03-03), and divisor_step is TRUE on the first session after each. A
-- level ratio across a step is not a return. There is no return, adjusted or
-- total-return column: this is a price index, never labelled as anything else.
--
-- The page is 1000 rows and the function pages with a date cursor, like
-- quote_history: IBOV from 1968 is 14,489 rows. The tape-start refusal of
-- quote_history does not apply; the depth per index is in api.coverage().
-- =============================================================================

BEGIN;
SET statement_timeout = '5min';

CREATE OR REPLACE FUNCTION api.index_history(
    p_index TEXT,
    p_from  DATE DEFAULT (CURRENT_DATE - 365),
    p_to    DATE DEFAULT CURRENT_DATE,
    -- NULL = whole result (refuses over 1000 rows); '' = first page;
    -- 'YYYY-MM-DD' = the page after that trade_date.
    p_after TEXT DEFAULT NULL
)
RETURNS TABLE (
    index_code   TEXT,
    trade_date   DATE,
    level        NUMERIC,
    divisor_step BOOLEAN,
    source       TEXT
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $fn$
#variable_conflict use_column
DECLARE
    v_code  TEXT := upper(btrim(p_index));
    v_held  TEXT;
BEGIN
    SELECT string_agg(h.code, ', ' ORDER BY h.code) INTO v_held
    FROM (SELECT DISTINCT l.index_code AS code FROM public.b3_index_level l) h;

    IF v_code IS NULL OR NOT EXISTS (
        SELECT 1 FROM public.b3_index_level l WHERE l.index_code = v_code
    ) THEN
        RAISE EXCEPTION
            'index_history: p_index must be a B3 index code SILO holds (%), got %. A ticker such as BOVA11 (an ETF) or IBOV11 (the index options settlement leg) is not an index level and never substitutes for one.',
            COALESCE(v_held, 'none loaded yet'), COALESCE(p_index, 'NULL')
            USING ERRCODE = '22023';
    END IF;
    IF p_from IS NULL OR p_to IS NULL THEN
        RAISE EXCEPTION
            'index_history: p_from and p_to must be dates (they default to the last 365 days and today); a NULL window would return nothing and look like no data'
            USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    WITH params AS (
        SELECT c.paging, c.after_date
        FROM api.parse_date_cursor(p_after, 'index_history') c
    ),
    -- One page + one. The 1001st row is what makes "over the page"
    -- detectable; assert_row_cap then REFUSES (22023) instead of handing back
    -- a truncated series that looks complete.
    page AS (
        SELECT l.index_code, l.trade_date, l.level, l.divisor_step, l.source
        FROM public.b3_index_level l
        JOIN params pp ON TRUE
        WHERE l.index_code = v_code
          AND l.trade_date BETWEEN p_from AND p_to
          AND (pp.after_date IS NULL OR l.trade_date > pp.after_date)
        ORDER BY l.trade_date
        LIMIT 1001
    )
    SELECT g.index_code, g.trade_date, g.level, g.divisor_step, g.source
    FROM page g
    WHERE api.assert_row_cap((SELECT count(*) FROM page),
                             (SELECT pp.paging FROM params pp), 'index_history')
    ORDER BY 2
    LIMIT 1000;
END;
$fn$;

COMMENT ON FUNCTION api.index_history(TEXT, DATE, DATE, TEXT) IS
    'Daily levels of one B3-published index (IBOV from 1968-01-02), as published, oldest first. p_index is an INDEX CODE: a ticker, including BOVA11 and IBOV11, raises 22023 naming the codes held, so the options settlement leg or an ETF can never stand in for the index. The series is NOT adjusted: B3 re-scaled it eleven times (divisor 100 on 1983-10-04, 10 on ten other sessions, the last 1997-03-03) and divisor_step is TRUE on the first session after each, where a level ratio is not a return. A price index only: no return, adjusted or total-return column. Row cap: more than 1000 rows RAISES 22023 (never trimmed) unless p_after pages: '''' = first page, then the last row''s trade_date as ''YYYY-MM-DD''; a page shorter than 1000 is the last. Or narrow p_from/p_to. Depth per index is in api.coverage().';

REVOKE ALL ON FUNCTION api.index_history(TEXT, DATE, DATE, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.index_history(TEXT, DATE, DATE, TEXT) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION api.index_history(TEXT, DATE, DATE, TEXT) TO silo_api;

COMMIT;
