-- =============================================================================
-- 19_api_contract.sql
-- Public read contract in schema `api`.
--
-- Users think in tickers (PETR4) and CNPJs, not landing-table names. This
-- schema is the only surface a client should query. Landing tables stay in
-- `public` for ingest; Evidence dashboards may keep reading dim_/fact_*.
--
-- Privilege model (SERVING.md Step 6):
--   * Views are owner-privileged (security_invoker = false, set explicitly
--     below) so GRANT SELECT on api.* never requires a grant on
--     b3_cotahist / vw_b3_quote_vista / cvm_* / dim_fund. The view's own grant
--     list IS the boundary; the blast radius of a leak is exactly the columns
--     each view selects, nothing else.
--   * Every data-reading function is SECURITY DEFINER with an empty pinned
--     search_path (all relations schema-qualified), because DEFINER is the
--     mechanism that lets callers read without landing-table grants. INVOKER
--     would force granting anon / silo_api SELECT on the landing tables —
--     exactly the door Step 6 closes — so no function that touches a relation
--     is INVOKER. Sole exception: api.catalog(), which reads nothing (it
--     returns a constant), so it stays INVOKER — minimal privilege. EXECUTE
--     is revoked from PUBLIC then granted to anon/authenticated and silo_api.
--   * silo_api (created in 12_grants_and_rls.sql, which applies first) is the
--     read bundle serve/ connects through. It gets schema api only.
--
-- Row caps (SERVING.md Step 3, SQL half). ONE page size, 1000 rows, which is
-- PostgREST's db-max-rows. Every set-returning function below fetches one page
-- plus one row (LIMIT 1001) and then calls api.assert_row_cap, which RAISES
-- 22023 rather than returning the page:
--   * the 1001st row is what makes "over the page" observable at all;
--   * a result trimmed to fit looks exactly like a complete one, and integrity
--     rule 1 forbids handing back a series the caller cannot tell is partial.
-- This replaced the old cap+1 sentinels (5001 on the series functions, 100001
-- on the panel). They were unobservable in production: PostgREST cuts every
-- response at 1000 rows long before 5001 is reached, so an anonymous caller
-- silently received the OLDEST 1000 with a 200 and no way to learn the rest
-- existed (measured 2026-08-28 on quote_history from 2019). The panel lost its
-- sentinel in v24; the series and statement functions lose theirs here.
-- quote_history and fund_nav additionally page with p_after; the rest ask the
-- caller to narrow the window. serve/app.py pages the SQL itself and keeps
-- _MAX_POINTS/_MAX_PANEL for its own envelope — those are the adapter's
-- limits, not the server's.
-- option_chain is page-shaped, not series-shaped: its own clamp (1..2000) is
-- documented at the function. Discovery functions are already bounded:
-- lookup <= 20, search_funds <= 200 (tiered), quote_latest = 1, coverage = one
-- row per dataset plus one per fund family (~11 rows). (universe was dropped in v15.)
--
-- Never fabricate: a ticker with no rows returns zero rows (HTTP 404 at serve/);
-- quote_history refuses an unknown ticker or a window outside its coverage.
-- Stored prices are unadjusted. quote_history and panel serve close_adj (splits,
-- groupings, bonus shares) by default for shares and units, never the raw close
-- under that name; every view keeps adjusted = FALSE.
-- =============================================================================

BEGIN;
-- Apply-time guard only: protects this DDL transaction. The *runtime* timeout
-- for API callers is a property of the role (ALTER ROLE silo_api SET
-- statement_timeout = '15s' in 12_grants_and_rls.sql), not of this session.
SET statement_timeout = '30s';

CREATE SCHEMA IF NOT EXISTS api;
GRANT USAGE ON SCHEMA api TO anon, authenticated;

-- ---------------------------------------------------------------------------
-- Caller tiers
--
-- Anonymous access stays free and is deliberately small: enough to discover
-- what exists and sample it, not enough to pull the warehouse through the
-- front door. Signing in (GitHub, via Supabase Auth) raises the
-- limits to something a person or an agent can actually work with — a handful
-- of instruments over real history.
--
-- What a login can and cannot buy is set by the platform, and it is worth
-- being exact about it rather than implying more:
--
--   * Rows per response CANNOT differ by tier. PostgREST's db-max-rows is a
--     global server setting (1000), applied identically to every caller.
--   * Query time DOES differ, for free: Supabase gives `anon` a 3s
--     statement_timeout and `authenticated` 8s.
--   * The caps written in THIS file are ours, so those are the ones we tier.
--
-- Detection reads the request's JWT claims, which PostgREST sets per request.
-- That GUC is session-scoped and therefore survives the SECURITY DEFINER
-- switch — `current_user` inside these functions is the owner, so it cannot be
-- used to identify the caller.
--
-- Fail CLOSED: a missing, empty or unparseable claim yields 'anon'. The worst
-- case is a signed-in caller getting anonymous limits, which is a support
-- question. The reverse — anonymous callers silently getting signed-in limits
-- — would be a hole, so it is unreachable by construction.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION api.caller_tier()
RETURNS TEXT
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_claims TEXT;
    v_role   TEXT;
BEGIN
    v_claims := current_setting('request.jwt.claims', true);
    IF v_claims IS NULL OR btrim(v_claims) = '' THEN
        RETURN 'anon';
    END IF;
    BEGIN
        v_role := v_claims::jsonb ->> 'role';
    EXCEPTION WHEN others THEN
        -- Malformed claims are not a reason to fail the request; they are a
        -- reason not to trust them.
        RETURN 'anon';
    END;
    IF v_role = 'authenticated' THEN
        RETURN 'authenticated';
    END IF;
    RETURN 'anon';
END;
$$;

COMMENT ON FUNCTION api.caller_tier() IS
    'Returns ''authenticated'' for a signed-in caller, ''anon'' otherwise. Fails closed: any missing or unparseable JWT claim yields ''anon''.';

-- Per-tier ceiling on how many ids one panel call may mix.
--
-- This is the cap that actually bounds work: every id adds an arm to the
-- panel union. Until now it existed ONLY in the local Flask adapter
-- (serve/app.py _MAX_IDS), so the deployed PostgREST path had no limit at all
-- and a single anonymous request could ask for thousands of instruments.
--
-- Called from api.panel in argument position, which always evaluates, so the
-- raise is guaranteed without converting that function to plpgsql.
CREATE OR REPLACE FUNCTION api.assert_panel_ids(p_ids TEXT[])
RETURNS TEXT[]
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_tier  TEXT := api.caller_tier();
    v_max   INT;
    v_count INT := COALESCE(array_length(p_ids, 1), 0);
BEGIN
    v_max := CASE v_tier WHEN 'authenticated' THEN 50 ELSE 3 END;
    IF v_count > v_max THEN
        IF v_tier = 'authenticated' THEN
            RAISE EXCEPTION
                'panel accepts at most % ids per call; % were given. Split the request.',
                v_max, v_count
                USING ERRCODE = '22023';
        ELSE
            RAISE EXCEPTION
                'panel accepts at most % ids per call for anonymous callers; % were given. Sign in to raise this to 50, or split the request.',
                v_max, v_count
                USING ERRCODE = '22023';
        END IF;
    END IF;
    RETURN p_ids;
END;
$$;

COMMENT ON FUNCTION api.assert_panel_ids(TEXT[]) IS
    'Caps the number of ids one api.panel call may mix: 3 anonymous, 50 signed in. Raises 22023 naming the limit rather than truncating, so a caller never receives a silently shortened panel.';

REVOKE ALL ON FUNCTION api.caller_tier() FROM PUBLIC;
REVOKE ALL ON FUNCTION api.assert_panel_ids(TEXT[]) FROM PUBLIC;

-- The row cap refuses instead of trimming.
--
-- PostgREST cuts every response at db-max-rows = 1000 and answers 200 with
-- the OLDEST rows, so a panel over the cap looked exactly like a complete
-- one; the only signal was the Content-Range header, and a caller who did
-- not read it analysed a fabricated series. An external cross-check
-- (2026-09-15) read the header on all 912 batches because the docs said to;
-- an agent that skims will not. So the function now counts its own result
-- and raises 22023 whenever it would exceed the page, unless the caller is
-- paging with p_after — the same argument-position trick as
-- assert_panel_ids, so the capped functions stay LANGUAGE sql.
--
-- 1000 is the ONE page size: PostgREST db-max-rows, the SDK's
-- SERVER_ROW_CAP and catalog().limits.page.size — tests/test_api_contract_sql.py
-- pins them to each other.
--
-- "Error with error why" (v34, owner decision 2026-09-24): the refusal is the
-- only thing a caller sees, so it carries both the WHY and the HOW. The
-- MESSAGE alone says both (a client that surfaces only `message` still learns
-- what to do); DETAIL restates the why and HINT the fix, which PostgREST
-- returns as `details` / `hint`. The fix differs by function — three take a
-- p_after cursor, the FIDC concentration trio narrow months and take an
-- explicit p_limit head, a screen narrows by its thresholds — so the hint is chosen
-- here, centrally, from p_fn, and every raise-only function inherits it. The
-- phrase "more than 1000 rows" is load-bearing: the SDK's SiloOverCap matches
-- on it (sdk/silo_client/client.py).
CREATE OR REPLACE FUNCTION api.assert_row_cap(p_n BIGINT, p_paging BOOLEAN, p_fn TEXT)
RETURNS BOOLEAN
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_why TEXT;
    v_how TEXT;
BEGIN
    IF NOT COALESCE(p_paging, FALSE) AND p_n > 1000 THEN
        v_why := 'Every response is one page of at most 1000 rows (PostgREST db-max-rows), '
              || 'and a result cut to fit that page looks exactly like a complete one. '
              || 'SILO never returns a silently truncated result, so it refuses instead.';
        v_how := CASE
            WHEN p_fn = 'panel' THEN
                'Page with the cursor: send p_after = '''' for the first page, then the last row''s '
                || 'date|id|metric|asset_class; a page shorter than 1000 rows is the last. '
                || 'Or narrow p_from/p_to, p_ids or p_metrics.'
            WHEN p_fn = 'quote_history' THEN
                'Page with the cursor: send p_after = '''' for the first page, then the last row''s '
                || 'trade_date as YYYY-MM-DD; a page shorter than 1000 rows is the last. '
                || 'Or narrow p_from/p_to.'
            WHEN p_fn = 'index_history' THEN
                'Page with the cursor: send p_after = '''' for the first page, then the last row''s '
                || 'trade_date as YYYY-MM-DD; a page shorter than 1000 rows is the last. '
                || 'Or narrow p_from/p_to.'
            -- v65 (32_api_trade_consolidated.sql): one FORWARD ticker per call,
            -- one row per session from 2025-06-10, so a page is about four years.
            WHEN p_fn = 'trade_consolidated_history' THEN
                'Page with the cursor: send p_after = '''' for the first page, then the last row''s '
                || 'trade_date as YYYY-MM-DD; a page shorter than 1000 rows is the last. '
                || 'Or narrow p_from/p_to.'
            WHEN p_fn = 'credit_market_history' THEN
                'This function has no cursor. Narrow p_from/p_to: several settlement/classification groups can share a trade date.'
            WHEN p_fn = 'fund_nav' THEN
                'Page with the cursor: send p_after = '''' for the first page, then the last row''s '
                || 'period as YYYY-MM-DD, and pass p_entity_type (paging requires one family); '
                || 'a page shorter than 1000 rows is the last. Or narrow p_from/p_to.'
            WHEN p_fn = 'fidc_cedentes' THEN
                -- p_cnpj and p_cedente are exclusive, so "pin a fund" is not
                -- advice a p_cedente caller can take: the window is the lever.
                'This function has no cursor. Narrow the window with p_from/p_to (one fund files at most '
                || '18 slots a month; an originator looked up by p_cedente can span many funds, so it needs '
                || 'fewer months), or ask explicitly for the newest N rows with p_limit (1..1000).'
            WHEN p_fn IN ('fidc_sacados', 'fidc_portfolio') THEN
                'This function has no cursor. Narrow the window with p_from/p_to'
                || CASE WHEN p_fn = 'fidc_portfolio' THEN ', pin one p_kind' ELSE '' END
                || ', or ask explicitly for the newest N rows with p_limit (1..1000).'
            WHEN p_fn IN ('fund_holdings', 'fund_debentures') THEN
                -- p_cnpj and p_ticker / p_issuer are exclusive, so the window
                -- is the lever for both directions.
                'This function has no cursor. Narrow the window with p_from/p_to (a ticker or issuer '
                || 'looked up across funds spans many funds, so it needs fewer months than one fund''s '
                || 'own holdings), or ask explicitly for the newest N rows with p_limit (1..1000).'
            WHEN p_fn = 'research_universe' THEN
                -- No parameter narrows it and it has no cursor, so "narrow the
                -- window" would be advice nobody can take. It is 639 pairs
                -- today; past one page it needs a cursor, which is a change to
                -- the function, not something a caller can work around.
                'This function has no cursor and no narrowing parameter: the research universe has '
                || 'outgrown one 1000-row page. Ask for a p_after cursor on (ticker, isin) to be added.'
            WHEN p_fn = 'portfolio_resolve' THEN
                -- No window and no cursor: the lever is how many statement lines one call carries.
                'This function has no cursor and no window. Send at most 200 statement lines per call '
                || '(up to 5 candidates each must fit one page) and split a longer statement across calls.'
            WHEN p_fn = 'portfolio_instruments' THEN
                -- No window and no cursor: one code can match several series, so the lever
                -- is how many codes one call carries.
                'This function has no cursor and no window. Send fewer instrument codes per call '
                || '(a CETIP code can match several series) and split the statement across calls.'
            WHEN p_fn IN ('portfolio_fees', 'portfolio_lookthrough', 'portfolio_movement',
                          'portfolio_fund_terms', 'portfolio_fee_peers') THEN
                -- A set of funds is the request: the lever is how many funds one call carries, and,
                -- for the look-through, how many quota levels it follows.
                'This function has no cursor and no window. Send fewer CNPJs per call'
                || CASE WHEN p_fn = 'portfolio_lookthrough'
                        THEN ', or lower p_max_depth (it follows fund quotas level by level)' ELSE '' END
                || '; split the portfolio across calls and add the rows up yourself.'
            WHEN p_fn = 'portfolio_equivalents' THEN
                -- A set of classes is the request: the lever is how many classes one call carries.
                'This function has no cursor and no window. Send fewer ANBIMA classes per call '
                || 'and split the set across calls.'
            WHEN p_fn = 'class_return_distribution' THEN
                -- Two rows (12 and 6 months) for one class: it cannot reach the cap.
                'This function returns two rows for one class and has no cursor; ask for one class '
                || 'and FUNDO_COTAS flag per call.'
            WHEN left(p_fn, 7) = 'screen_' THEN
                'Screens do not page. Raise the screen''s thresholds or pin its output filter '
                || '(see catalog().screens) so the list fits one page.'
            ELSE
                'This function has no cursor. Narrow the window with p_from/p_to, or pin the '
                || 'function''s own filters, until the result fits one page.'
        END;
        RAISE EXCEPTION
            '%: refused, this request would return more than 1000 rows. % To fix: %',
            p_fn, v_why, v_how
            USING ERRCODE = '22023',
                  DETAIL  = v_why,
                  HINT    = v_how;
    END IF;
    RETURN TRUE;
END;
$$;

COMMENT ON FUNCTION api.assert_row_cap(BIGINT, BOOLEAN, TEXT) IS
    'Internal. Raises 22023 when a capped function would return more than the 1000-row page and the caller is not paging with p_after. The message says WHY (one 1000-row page; SILO never returns a silently truncated result) and HOW to fix it for that function (page with p_after, narrow p_from/p_to, take an explicit p_limit head, raise a screen''s thresholds); DETAIL and HINT carry the two halves separately. Nothing is ever trimmed to fit.';

REVOKE ALL ON FUNCTION api.assert_row_cap(BIGINT, BOOLEAN, TEXT) FROM PUBLIC;

-- Cursor for api.panel's paging mode. Transparent on purpose so an agent can
-- build it from the last row it received: 'date|id|metric|asset_class'.
--   NULL  → whole-result mode (assert_row_cap raises above 1000 rows)
--   ''    → first page of paging mode
--   key   → the page after that key, ordered (date, id, metric, asset_class)
-- asset_class is part of the key because a CNPJ can file under two families
-- in one month (385 do, fi + fidc), so (id, date, metric) alone is not unique
-- and a 3-part cursor could skip or repeat a row at a page edge.
CREATE OR REPLACE FUNCTION api.parse_panel_cursor(p_after TEXT)
RETURNS TABLE (paging BOOLEAN, after_date DATE, after_id TEXT, after_metric TEXT, after_class TEXT)
LANGUAGE plpgsql
IMMUTABLE
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_parts TEXT[];
BEGIN
    IF p_after IS NULL THEN
        RETURN QUERY SELECT FALSE, NULL::date, NULL::text, NULL::text, NULL::text;
        RETURN;
    END IF;
    IF btrim(p_after) = '' THEN
        RETURN QUERY SELECT TRUE, NULL::date, NULL::text, NULL::text, NULL::text;
        RETURN;
    END IF;
    v_parts := string_to_array(p_after, '|');
    IF array_length(v_parts, 1) <> 4 OR v_parts[1] !~ '^\d{4}-\d{2}-\d{2}$' THEN
        RAISE EXCEPTION
            'panel: p_after must be '''' (first page) or ''<date>|<id>|<metric>|<asset_class>'' copied from the last row of the previous page; got %',
            p_after
            USING ERRCODE = '22023';
    END IF;
    RETURN QUERY SELECT TRUE, v_parts[1]::date, v_parts[2], v_parts[3], v_parts[4];
END;
$$;

COMMENT ON FUNCTION api.parse_panel_cursor(TEXT) IS
    'Internal. Parses api.panel''s p_after cursor: NULL = whole result (refuses over 1000 rows), '''' = first page, ''date|id|metric|asset_class'' = the page after that key. Malformed → 22023.';

REVOKE ALL ON FUNCTION api.parse_panel_cursor(TEXT) FROM PUBLIC;

-- Cursor for the date-ordered series functions (quote_history, fund_nav).
-- Simpler than parse_panel_cursor because those series carry one date per row
-- within a single subject -- one ticker, or one CNPJ within one family:
--   NULL  -> whole-result mode (assert_row_cap raises above 1000 rows)
--   ''    -> first page of paging mode
--   date  -> the page after that date, as YYYY-MM-DD
-- p_fn names the caller so the 22023 points at the function the agent called.
CREATE OR REPLACE FUNCTION api.parse_date_cursor(p_after TEXT, p_fn TEXT)
RETURNS TABLE (paging BOOLEAN, after_date DATE)
LANGUAGE plpgsql
IMMUTABLE
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    IF p_after IS NULL THEN
        RETURN QUERY SELECT FALSE, NULL::date;
        RETURN;
    END IF;
    IF btrim(p_after) = '' THEN
        RETURN QUERY SELECT TRUE, NULL::date;
        RETURN;
    END IF;
    IF btrim(p_after) !~ '^\d{4}-\d{2}-\d{2}$' THEN
        RAISE EXCEPTION
            '%: p_after must be '''' (first page) or the last row''s date as YYYY-MM-DD, copied from the previous page; got %',
            p_fn, p_after
            USING ERRCODE = '22023';
    END IF;
    RETURN QUERY SELECT TRUE, btrim(p_after)::date;
END;
$$;

COMMENT ON FUNCTION api.parse_date_cursor(TEXT, TEXT) IS
    'Internal. Parses the date cursor used by api.quote_history and api.fund_nav: NULL = whole result (refuses over 1000 rows), '''' = first page, ''YYYY-MM-DD'' = the page after that date. Malformed -> 22023 naming the calling function.';

REVOKE ALL ON FUNCTION api.parse_date_cursor(TEXT, TEXT) FROM PUBLIC;

-- fund_nav's cursor is a bare period, and a period is unique only WITHIN one
-- family: 385 CNPJs file under two families (fi + fidc) in the same month, so
-- a two-family result holds two rows sharing a period and a bare-date cursor
-- would skip or repeat one at a page edge. Widening the cursor to
-- (period, entity_type) was rejected -- more surface for the same result --
-- so paging REQUIRES p_entity_type instead: the page is then always within
-- one family and the period is unique again. Whole-result mode is unaffected
-- and still serves both families (the caller reads entity_type per row).
CREATE OR REPLACE FUNCTION api.assert_fund_nav_cursor(p_paging BOOLEAN, p_entity_type TEXT)
RETURNS BOOLEAN
LANGUAGE plpgsql
IMMUTABLE
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    IF COALESCE(p_paging, FALSE)
       AND NULLIF(btrim(COALESCE(p_entity_type, '')), '') IS NULL THEN
        RAISE EXCEPTION
            'fund_nav: paging with p_after requires p_entity_type, because one CNPJ can file under two families in the same month and the cursor is a bare period. Pass p_entity_type (fi, fidc, fii, fip or fiagro) with p_after, or drop p_after and narrow p_from/p_to instead.'
            USING ERRCODE = '22023';
    END IF;
    RETURN TRUE;
END;
$$;

COMMENT ON FUNCTION api.assert_fund_nav_cursor(BOOLEAN, TEXT) IS
    'Internal. Raises 22023 when api.fund_nav is asked to page without p_entity_type: the cursor is a bare period, which is unique only within one family (385 CNPJs file under two in the same month).';

REVOKE ALL ON FUNCTION api.assert_fund_nav_cursor(BOOLEAN, TEXT) FROM PUBLIC;

-- Universe mode: p_ids empty, p_entity_type names the family. The panel then
-- selects the family's funds itself (a filter on published values — latest
-- NAV, observation count — never a rank; reductions stay in the notebook).
-- Signed-in only (decision 2026-09-15): every page re-scans a whole family's
-- window, and the tier header above says anonymous access is sized for
-- discovery, not for pulling the warehouse through the front door. The
-- explicit-ids path is unchanged for both tiers.
CREATE OR REPLACE FUNCTION api.assert_panel_universe(p_n_ids INT, p_entity_type TEXT)
RETURNS TEXT
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_type    TEXT := NULLIF(lower(btrim(p_entity_type)), '');
    -- Universe pages per call by tier: the lockstep test reads this CASE.
    v_allowed INT  := CASE api.caller_tier() WHEN 'authenticated' THEN 1 ELSE 0 END;
BEGIN
    IF v_type IS NOT NULL AND v_type NOT IN ('fi', 'fidc', 'fii', 'fip', 'fiagro') THEN
        RAISE EXCEPTION
            'panel: p_entity_type must be one of fi, fidc, fii, fip, fiagro; got %', v_type
            USING ERRCODE = '22023';
    END IF;
    IF COALESCE(p_n_ids, 0) = 0 THEN
        IF v_type IS NULL THEN
            RAISE EXCEPTION
                'panel: no ids were given. Pass p_ids, or pass p_entity_type (fi|fidc|fii|fip|fiagro) to walk a whole family (universe mode, signed-in callers only).'
                USING ERRCODE = '22023';
        END IF;
        IF v_allowed = 0 THEN
            RAISE EXCEPTION
                'panel: universe mode (p_ids empty + p_entity_type) is available to signed-in callers only; anonymous callers pass explicit ids (up to 3 per call). Sign in at https://silo-bz-deloslabs.vercel.app/signin.html.'
                USING ERRCODE = '22023';
        END IF;
    END IF;
    RETURN v_type;
END;
$$;

COMMENT ON FUNCTION api.assert_panel_universe(INT, TEXT) IS
    'Internal. Validates p_entity_type (fi|fidc|fii|fip|fiagro) and gates api.panel''s universe mode (no ids + a family) to the authenticated tier (1 signed in, 0 anonymous).';

REVOKE ALL ON FUNCTION api.assert_panel_universe(INT, TEXT) FROM PUBLIC;

-- ---------------------------------------------------------------------------
-- Quotes (B3 COTAHIST cash market)
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW api.quotes AS
SELECT
    v.codneg            AS ticker,
    v.trade_date,
    v.codbdi            AS board,
    v.prazot            AS term_days,
    v.nome_resumido     AS short_name,
    v.especi            AS spec,
    COALESCE(v.moeda, 'R$') AS currency,
    v.preco_abertura    AS open,
    v.preco_maximo      AS high,
    v.preco_minimo      AS low,
    v.preco_medio       AS average,
    v.preco_fechamento  AS close,
    v.oferta_compra     AS bid,
    v.oferta_venda      AS ask,
    v.negocios          AS trades,
    v.quantidade        AS quantity,
    v.volume,
    v.isin,
    v.fator_cotacao     AS quotation_factor,
    FALSE               AS adjusted,
    v.source,
    v.fetched_at,
    v.instrument_type   AS asset_class,
    -- Price per SINGLE quoted unit: COTAHIST quotes some papers per lot (the
    -- published FATCOT is the number of shares the price refers to, 1 or 1000),
    -- so `close` alone is not comparable across papers or across a factor
    -- change. This is division by a published field, not an adjustment: raw
    -- `close` and `quotation_factor` stay untouched beside it. It does NOT
    -- account for splits, groupings or bonuses - that needs the corporate-event
    -- table, and until that exists `adjusted` stays FALSE.
    v.preco_fechamento / NULLIF(v.fator_cotacao, 0) AS close_unit,
    v.tpmerc AS market,
    v.preco_exercicio AS contract_price,
    v.data_vencimento AS contract_expiry,
    v.raw ->> 'indopc' AS contract_correction,
    CASE WHEN v.raw ->> 'ptoexe' ~ '^[0-9]{13}$' THEN NULLIF((v.raw ->> 'ptoexe')::NUMERIC, 0) / 1e6 END AS contract_points,
    v.raw ->> 'ptoexe' AS contract_points_raw,
    v.raw ->> 'dismes' AS distribution_number
FROM public.vw_b3_instrument_typed v
WHERE v.tpmerc = '010';

COMMENT ON VIEW api.quotes IS
    'Unadjusted B3 cash quotes (tpmerc=010), classified from published TPMERC/ESPECI. fund_quota does not guess ETF versus FII. Grain (ticker, trade_date, board, term_days). BDI board varies by instrument type.';

-- Deliberately owner-privileged (Step 6 decision): with security_invoker=false
-- a SELECT here runs with the view owner's rights, so no client role needs (or
-- gets) a grant on public.vw_b3_instrument_typed / b3_cotahist. Set explicitly so a
-- future CREATE OR REPLACE cannot silently flip the boundary.
ALTER VIEW api.quotes SET (security_invoker = false);

GRANT SELECT ON api.quotes TO anon, authenticated;

-- ---------------------------------------------------------------------------
-- One endpoint per cash instrument type
-- ---------------------------------------------------------------------------
-- api.quotes is the whole cash tape. These five views are the same rows split
-- by the instrument_type vw_b3_instrument_typed derives from published
-- TPMERC/ESPECI, so PostgREST exposes each as its own resource:
--
--     GET /rest/v1/equities?ticker=eq.PETR4
--     GET /rest/v1/bdrs?order=volume.desc&limit=20
--
-- Views, not functions, and no logic of their own: one WHERE clause each. The
-- caps, grain and column set stay defined in exactly one place, so these cannot
-- drift from api.quotes.
--
-- Why the SERIES stays unified: a codneg belongs to exactly one instrument_type,
-- so quote_history('PETR4') is already unambiguous. A typed history would make
-- the caller determine the type *before* they could ask for a price — worse for
-- a human and worse for an agent. Split the cross-section, keep what is keyed
-- by id. (Same two-layer rule as INSTRUMENTS.md.)
--
-- LOT: unlike api.quotes these carry both lot sizes, with `lot` derived from
-- the published tpmerc. Odd lot is not a rounding error — measured 2026-08-27,
-- equities have MORE odd-lot rows than standard-lot (153,072 vs 140,227; 496
-- vs 476 codnegs). Hiding it would misrepresent the tape. api.quotes is left
-- exactly as it was (tpmerc 010 only), so nothing already published moves;
-- these are additive, and a caller who wants only round lots adds
-- ?lot=eq.standard.
--
-- GRAIN is therefore (ticker, trade_date, board, term_days, lot) — one column
-- wider than api.quotes. Say so in every COMMENT: a query that ignores `lot`
-- sees what look like duplicate dates.

CREATE OR REPLACE VIEW api.equities AS
SELECT
    v.codneg            AS ticker,
    v.trade_date,
    v.codbdi            AS board,
    CASE v.tpmerc WHEN '010' THEN 'standard' WHEN '020' THEN 'odd' WHEN '021' THEN 'block' END AS lot,
    v.prazot            AS term_days,
    v.nome_resumido     AS short_name,
    v.especi            AS spec,
    COALESCE(v.moeda, 'R$') AS currency,
    v.preco_abertura    AS open,
    v.preco_maximo      AS high,
    v.preco_minimo      AS low,
    v.preco_medio       AS average,
    v.preco_fechamento  AS close,
    v.oferta_compra     AS bid,
    v.oferta_venda      AS ask,
    v.negocios          AS trades,
    v.quantidade        AS quantity,
    v.volume,
    v.isin,
    v.fator_cotacao     AS quotation_factor,
    FALSE               AS adjusted,
    v.source,
    v.fetched_at,
    -- Trailing additions (migration 23): the class token and listing segment
    -- parsed from published ESPECI (class cross-checked against the ISIN class
    -- code with zero disagreements). ON=ordinary, PN/PNA/PNB/PNC/PND=preferred.
    v.share_class,
    v.governance_segment,
    -- Price per SINGLE quoted unit: COTAHIST quotes some papers per lot (the
    -- published FATCOT is the number of shares the price refers to, 1 or 1000),
    -- so `close` alone is not comparable across papers or across a factor
    -- change. This is division by a published field, not an adjustment: raw
    -- `close` and `quotation_factor` stay untouched beside it. It does NOT
    -- account for splits, groupings or bonuses - that needs the corporate-event
    -- table, and until that exists `adjusted` stays FALSE.
    v.preco_fechamento / NULLIF(v.fator_cotacao, 0) AS close_unit,
    v.tpmerc AS market,
    v.preco_exercicio AS contract_price,
    v.data_vencimento AS contract_expiry,
    v.raw ->> 'indopc' AS contract_correction,
    CASE WHEN v.raw ->> 'ptoexe' ~ '^[0-9]{13}$' THEN NULLIF((v.raw ->> 'ptoexe')::NUMERIC, 0) / 1e6 END AS contract_points,
    v.raw ->> 'ptoexe' AS contract_points_raw,
    v.raw ->> 'dismes' AS distribution_number
FROM public.vw_b3_instrument_typed v
WHERE v.instrument_type = 'equity'
  AND v.tpmerc IN ('010', '020', '021');

COMMENT ON VIEW api.equities IS
    'Unadjusted B3 cash quotes for equity: ordinary and preferred shares (ESPECI ON*/PN*). Grain (ticker, trade_date, board, term_days, lot) — lot is standard (tpmerc 010) or odd (020) or block (021), so filter lot=eq.standard for round lots only. share_class (ON|PN|PNA|PNB|PNC|PND) and governance_segment (NM|N1|N2|MA|M2|MB) are parsed from published ESPECI, never from the ticker suffix. Classified from published TPMERC/ESPECI; never inferred.';

ALTER VIEW api.equities SET (security_invoker = false);
GRANT SELECT ON api.equities TO anon, authenticated;

CREATE OR REPLACE VIEW api.bdrs AS
SELECT
    v.codneg            AS ticker,
    v.trade_date,
    v.codbdi            AS board,
    CASE v.tpmerc WHEN '010' THEN 'standard' WHEN '020' THEN 'odd' WHEN '021' THEN 'block' END AS lot,
    v.prazot            AS term_days,
    v.nome_resumido     AS short_name,
    v.especi            AS spec,
    COALESCE(v.moeda, 'R$') AS currency,
    v.preco_abertura    AS open,
    v.preco_maximo      AS high,
    v.preco_minimo      AS low,
    v.preco_medio       AS average,
    v.preco_fechamento  AS close,
    v.oferta_compra     AS bid,
    v.oferta_venda      AS ask,
    v.negocios          AS trades,
    v.quantidade        AS quantity,
    v.volume,
    v.isin,
    v.fator_cotacao     AS quotation_factor,
    FALSE               AS adjusted,
    v.source,
    v.fetched_at,
    -- Price per SINGLE quoted unit: COTAHIST quotes some papers per lot (the
    -- published FATCOT is the number of shares the price refers to, 1 or 1000),
    -- so `close` alone is not comparable across papers or across a factor
    -- change. This is division by a published field, not an adjustment: raw
    -- `close` and `quotation_factor` stay untouched beside it. It does NOT
    -- account for splits, groupings or bonuses - that needs the corporate-event
    -- table, and until that exists `adjusted` stays FALSE.
    v.preco_fechamento / NULLIF(v.fator_cotacao, 0) AS close_unit,
    v.tpmerc AS market,
    v.preco_exercicio AS contract_price,
    v.data_vencimento AS contract_expiry,
    v.raw ->> 'indopc' AS contract_correction,
    CASE WHEN v.raw ->> 'ptoexe' ~ '^[0-9]{13}$' THEN NULLIF((v.raw ->> 'ptoexe')::NUMERIC, 0) / 1e6 END AS contract_points,
    v.raw ->> 'ptoexe' AS contract_points_raw,
    v.raw ->> 'dismes' AS distribution_number
FROM public.vw_b3_instrument_typed v
WHERE v.instrument_type = 'bdr'
  AND v.tpmerc IN ('010', '020', '021');

COMMENT ON VIEW api.bdrs IS
    'Unadjusted B3 cash quotes for bdr: Brazilian Depositary Receipts (ESPECI DR*). Grain (ticker, trade_date, board, term_days, lot) — lot is standard (tpmerc 010) or odd (020) or block (021), so filter lot=eq.standard for round lots only. Classified from published TPMERC/ESPECI; never inferred.';

ALTER VIEW api.bdrs SET (security_invoker = false);
GRANT SELECT ON api.bdrs TO anon, authenticated;

CREATE OR REPLACE VIEW api.units AS
SELECT
    v.codneg            AS ticker,
    v.trade_date,
    v.codbdi            AS board,
    CASE v.tpmerc WHEN '010' THEN 'standard' WHEN '020' THEN 'odd' WHEN '021' THEN 'block' END AS lot,
    v.prazot            AS term_days,
    v.nome_resumido     AS short_name,
    v.especi            AS spec,
    COALESCE(v.moeda, 'R$') AS currency,
    v.preco_abertura    AS open,
    v.preco_maximo      AS high,
    v.preco_minimo      AS low,
    v.preco_medio       AS average,
    v.preco_fechamento  AS close,
    v.oferta_compra     AS bid,
    v.oferta_venda      AS ask,
    v.negocios          AS trades,
    v.quantidade        AS quantity,
    v.volume,
    v.isin,
    v.fator_cotacao     AS quotation_factor,
    FALSE               AS adjusted,
    v.source,
    v.fetched_at,
    -- Price per SINGLE quoted unit: COTAHIST quotes some papers per lot (the
    -- published FATCOT is the number of shares the price refers to, 1 or 1000),
    -- so `close` alone is not comparable across papers or across a factor
    -- change. This is division by a published field, not an adjustment: raw
    -- `close` and `quotation_factor` stay untouched beside it. It does NOT
    -- account for splits, groupings or bonuses - that needs the corporate-event
    -- table, and until that exists `adjusted` stays FALSE.
    v.preco_fechamento / NULLIF(v.fator_cotacao, 0) AS close_unit,
    v.tpmerc AS market,
    v.preco_exercicio AS contract_price,
    v.data_vencimento AS contract_expiry,
    v.raw ->> 'indopc' AS contract_correction,
    CASE WHEN v.raw ->> 'ptoexe' ~ '^[0-9]{13}$' THEN NULLIF((v.raw ->> 'ptoexe')::NUMERIC, 0) / 1e6 END AS contract_points,
    v.raw ->> 'ptoexe' AS contract_points_raw,
    v.raw ->> 'dismes' AS distribution_number
FROM public.vw_b3_instrument_typed v
WHERE v.instrument_type = 'unit'
  AND v.tpmerc IN ('010', '020', '021');

COMMENT ON VIEW api.units IS
    'Unadjusted B3 cash quotes for unit: units — bundled share packages (ESPECI UNT*). Grain (ticker, trade_date, board, term_days, lot) — lot is standard (tpmerc 010) or odd (020) or block (021), so filter lot=eq.standard for round lots only. Classified from published TPMERC/ESPECI; never inferred.';

ALTER VIEW api.units SET (security_invoker = false);
GRANT SELECT ON api.units TO anon, authenticated;

CREATE OR REPLACE VIEW api.fund_quotas AS
SELECT
    v.codneg            AS ticker,
    v.trade_date,
    v.codbdi            AS board,
    CASE v.tpmerc WHEN '010' THEN 'standard' WHEN '020' THEN 'odd' WHEN '021' THEN 'block' END AS lot,
    v.prazot            AS term_days,
    v.nome_resumido     AS short_name,
    v.especi            AS spec,
    COALESCE(v.moeda, 'R$') AS currency,
    v.preco_abertura    AS open,
    v.preco_maximo      AS high,
    v.preco_minimo      AS low,
    v.preco_medio       AS average,
    v.preco_fechamento  AS close,
    v.oferta_compra     AS bid,
    v.oferta_venda      AS ask,
    v.negocios          AS trades,
    v.quantidade        AS quantity,
    v.volume,
    v.isin,
    v.fator_cotacao     AS quotation_factor,
    FALSE               AS adjusted,
    v.source,
    v.fetched_at,
    -- Trailing addition (migration 23): the fund family from B3's published
    -- CODBDI board code (14 etf / 05,12 fii / 13 fiagro; validated against
    -- cvm_etf_registry). NULL on boards with no family signal (odd lot) —
    -- never guessed from the ticker.
    v.instrument_subtype AS fund_type,
    -- Price per SINGLE quoted unit: COTAHIST quotes some papers per lot (the
    -- published FATCOT is the number of shares the price refers to, 1 or 1000),
    -- so `close` alone is not comparable across papers or across a factor
    -- change. This is division by a published field, not an adjustment: raw
    -- `close` and `quotation_factor` stay untouched beside it. It does NOT
    -- account for splits, groupings or bonuses - that needs the corporate-event
    -- table, and until that exists `adjusted` stays FALSE.
    v.preco_fechamento / NULLIF(v.fator_cotacao, 0) AS close_unit,
    v.tpmerc AS market,
    v.preco_exercicio AS contract_price,
    v.data_vencimento AS contract_expiry,
    v.raw ->> 'indopc' AS contract_correction,
    CASE WHEN v.raw ->> 'ptoexe' ~ '^[0-9]{13}$' THEN NULLIF((v.raw ->> 'ptoexe')::NUMERIC, 0) / 1e6 END AS contract_points,
    v.raw ->> 'ptoexe' AS contract_points_raw,
    v.raw ->> 'dismes' AS distribution_number
FROM public.vw_b3_instrument_typed v
WHERE v.instrument_type = 'fund_quota'
  AND v.tpmerc IN ('010', '020', '021');

COMMENT ON VIEW api.fund_quotas IS
    'Unadjusted B3 cash quotes for fund_quota: listed fund quotas (CI*/FIDC* paper). fund_type splits the family from B3''s published CODBDI board code: etf | fii | fidc | fiagro, NULL when the board carries no signal (odd lot) — filter fund_type=eq.etf for ETFs only. Grain (ticker, trade_date, board, term_days, lot) — lot is standard (tpmerc 010) or odd (020) or block (021), so filter lot=eq.standard for round lots only. Classified from published TPMERC/CODBDI/ESPECI; never inferred.';

ALTER VIEW api.fund_quotas SET (security_invoker = false);
GRANT SELECT ON api.fund_quotas TO anon, authenticated;

CREATE OR REPLACE VIEW api.cash_securities AS
SELECT
    v.codneg            AS ticker,
    v.trade_date,
    v.codbdi            AS board,
    CASE v.tpmerc WHEN '010' THEN 'standard' WHEN '020' THEN 'odd' WHEN '021' THEN 'block' END AS lot,
    v.prazot            AS term_days,
    v.nome_resumido     AS short_name,
    v.especi            AS spec,
    COALESCE(v.moeda, 'R$') AS currency,
    v.preco_abertura    AS open,
    v.preco_maximo      AS high,
    v.preco_minimo      AS low,
    v.preco_medio       AS average,
    v.preco_fechamento  AS close,
    v.oferta_compra     AS bid,
    v.oferta_venda      AS ask,
    v.negocios          AS trades,
    v.quantidade        AS quantity,
    v.volume,
    v.isin,
    v.fator_cotacao     AS quotation_factor,
    FALSE               AS adjusted,
    v.source,
    v.fetched_at,
    -- Price per SINGLE quoted unit: COTAHIST quotes some papers per lot (the
    -- published FATCOT is the number of shares the price refers to, 1 or 1000),
    -- so `close` alone is not comparable across papers or across a factor
    -- change. This is division by a published field, not an adjustment: raw
    -- `close` and `quotation_factor` stay untouched beside it. It does NOT
    -- account for splits, groupings or bonuses - that needs the corporate-event
    -- table, and until that exists `adjusted` stays FALSE.
    v.preco_fechamento / NULLIF(v.fator_cotacao, 0) AS close_unit,
    v.tpmerc AS market,
    v.preco_exercicio AS contract_price,
    v.data_vencimento AS contract_expiry,
    v.raw ->> 'indopc' AS contract_correction,
    CASE WHEN v.raw ->> 'ptoexe' ~ '^[0-9]{13}$' THEN NULLIF((v.raw ->> 'ptoexe')::NUMERIC, 0) / 1e6 END AS contract_points,
    v.raw ->> 'ptoexe' AS contract_points_raw,
    v.raw ->> 'dismes' AS distribution_number
FROM public.vw_b3_instrument_typed v
WHERE v.instrument_type = 'cash_security'
  AND v.tpmerc IN ('010', '020', '021');

COMMENT ON VIEW api.cash_securities IS
    'Unadjusted B3 cash quotes for cash_security: everything else on the cash board — subscription rights, receipts, and other non-share paper. Grain (ticker, trade_date, board, term_days, lot) — lot is standard (tpmerc 010) or odd (020) or block (021), so filter lot=eq.standard for round lots only. Classified from published TPMERC/ESPECI; never inferred.';

ALTER VIEW api.cash_securities SET (security_invoker = false);
GRANT SELECT ON api.cash_securities TO anon, authenticated;


-- ---------------------------------------------------------------------------
-- The research price series: api.quote_history (RESEARCH_SEAM.md §3)
-- ---------------------------------------------------------------------------
-- One ticker per call, one JSON object per session, oldest first. Only the
-- fields the caller selects come back: the default is ticker, trade_date and
-- close_adj, and the raw close, OHLC and volume are one explicit selection away
-- (p_fields). A function's columns cannot vary per call, so the rows are jsonb;
-- api.quote_history_fields() below is the one list of what can be selected, and
-- scripts/gen_openapi.py reads its types from it.
--
-- The series is keyed on the ISIN, not on a board. It used to follow only the
-- ticker's latest board (codbdi), which cut ETER3 at 2024-08-12, the day it left
-- board 08 for 02, and dropped its 1,396 earlier sessions without a word.
-- Measured 2026-09-30: 62 share/unit tickers changed board since 2019, and no
-- ticker ever printed two cash rows on one session. A second row on a session,
-- or a second ISIN inside the window (a receipt ticker is reused by every new
-- issue, ABCB10 by seven), is refused, never chosen between or joined.

-- Internal. The selectable fields, their JSON types and meaning. is_default marks
-- what an omitted p_fields returns. ticker and trade_date are in every row.
CREATE OR REPLACE FUNCTION api.quote_history_fields()
RETURNS TABLE (field TEXT, json_type TEXT, is_default BOOLEAN, description TEXT)
LANGUAGE sql
IMMUTABLE
SET search_path = ''
AS $$
    VALUES
        ('ticker',           'string',  TRUE,  'B3 trading code (CODNEG), as asked, upper-cased. In every row.'),
        ('trade_date',       'date',    TRUE,  'Session date. In every row.'),
        ('close_adj',        'number',  TRUE,  'Close per single share, backward-adjusted for splits (DESDOBRAMENTO), groupings (GRUPAMENTO) and bonus shares (BONIFICACAO) and anchored to the instrument''s latest session; rounded to 6 decimal places. No dividend, JCP or subscription-right adjustment. Shares and units only. Null only when the session has no close; a window it cannot adjust is refused, never filled with the raw close.'),
        ('close',            'number',  FALSE, 'RAW close as traded, per quotation unit (see quotation_factor). Never adjusted.'),
        ('open',             'number',  FALSE, 'Raw opening price.'),
        ('high',             'number',  FALSE, 'Raw high.'),
        ('low',              'number',  FALSE, 'Raw low.'),
        ('average',          'number',  FALSE, 'Raw average traded price.'),
        ('bid',              'number',  FALSE, 'Best bid at the close.'),
        ('ask',              'number',  FALSE, 'Best ask at the close.'),
        ('close_unit',       'number',  FALSE, 'Raw close divided by quotation_factor: the price of one share, not adjusted for corporate events.'),
        ('trades',           'integer', FALSE, 'Number of trades.'),
        ('quantity',         'number',  FALSE, 'Quantity traded.'),
        ('volume',           'number',  FALSE, 'Financial volume in currency.'),
        ('quotation_factor', 'integer', FALSE, 'FATCOT: how many shares the quoted prices refer to (1 or 1000).'),
        ('board',            'string',  FALSE, 'BDI board code (CODBDI) the session printed on; 02 is the standard lot.'),
        ('isin',             'string',  FALSE, 'ISIN of the instrument this row printed under. One ISIN per series, except across an ISIN change the ticker''s lineage splices (api.ticker_lineage), where each row keeps its own.'),
        ('short_name',       'string',  FALSE, 'Issuer short name as printed.'),
        ('spec',             'string',  FALSE, 'Share specification (ESPECI) as printed.'),
        ('currency',         'string',  FALSE, 'Price currency.'),
        ('asset_class',      'string',  FALSE, 'Instrument class from published TPMERC/ESPECI.'),
        ('source',           'string',  FALSE, 'Source file of the row.'),
        ('coverage_start',   'date',    FALSE, 'First session of the series on the tape: this ticker under this ISIN, or the oldest instrument of its spliced lineage when the window reaches back to it (the tape starts 2019-01-02).'),
        ('coverage_end',     'date',    FALSE, 'Last session of the series on the tape (the current instrument''s last print).'),
        ('prior_no_trade_sessions', 'integer', FALSE, 'Market sessions (days the B3 cash tape printed) since this ticker''s previous row in which it printed nothing. COTAHIST lists only papers that traded, so a missing session is a session with no trade; holidays are not sessions.'),
        ('events_proven_at', 'string',  FALSE, 'When the issuer''s corporate-event history was last proven complete (b3_corporate_event_sweep), ISO 8601 UTC. Null outside shares and units or when not proven.'),
        ('data_revision',    'string',  FALSE, 'Revision of the data behind this response: the latest successful load of the B3 cash tape, the corporate events or their proof, ISO 8601 UTC. It changes when adjusted levels can change; pages with different revisions must not be combined.'),
        ('close_total_return', 'number', FALSE, 'close_adj with cash distributions reinvested at the ex-date close (#418): divided by the product of (1 + cash / ex-session close) over later distributions (DIVIDENDO, JRS CAP PROPRIO gross of tax, RENDIMENTO, REST CAP DIN from B3''s full history, ISIN proven against the tape). 6 decimal places. NULL, with close_total_return_null_reason, where it cannot be valued.'),
        ('close_total_return_null_reason', 'string', FALSE, 'Why close_total_return is NULL on the session; null when it has a value.'),
        ('market', 'string', FALSE, 'Original TPMERC code, preserved as text. Cash history is 010 only.'),
        ('term_days', 'string', FALSE, 'PRAZOT as published; blank for spot. Part of the source natural key.'),
        ('contract_price', 'number', FALSE, 'PREEXE as published; exercise price or secondary-forward contract value, not a yield.'),
        ('contract_expiry', 'date', FALSE, 'DATVEN; source sentinel 99991231 is null.'),
        ('contract_correction', 'string', FALSE, 'Original INDOPC code; consult the dated COTAHIST reference in catalog.'),
        ('contract_points', 'number', FALSE, 'PTOEXE decoded with six implied decimals; zero filler or unreadable points become null.'),
        ('contract_points_raw', 'string', FALSE, 'Original PTOEXE text, retaining zero filler and leading zeros.'),
        ('distribution_number', 'string', FALSE, 'DISMES source sequence code, not a dividend amount.'),
        ('fetched_at', 'string', FALSE, 'Warehouse timestamp, not original publication time or an as-known source vintage.')
$$;

COMMENT ON FUNCTION api.quote_history_fields() IS
    'Internal. The fields api.quote_history can return (p_fields), with JSON type, default flag and meaning.';

REVOKE ALL ON FUNCTION api.quote_history_fields() FROM PUBLIC;

-- Internal. Revision of the data a price response is built from. Global and
-- cheap on purpose: the newest successful B3 cash-tape or corporate-event load
-- that wrote rows, or the newest sweep proof. Any of them can move an adjusted
-- level (a new session can take an event ex; a proof can make a stretch
-- adjustable), so a caller that sees two revisions across its pages restarts.
CREATE OR REPLACE FUNCTION api.quote_data_revision()
RETURNS TEXT
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    SELECT to_char(
        GREATEST(
            (SELECT max(l.finished_at)
             FROM public.cvm_ingest_log l
             WHERE l.entity = 'b3'
               AND l.doc_type IN ('cotahist_daily', 'cotahist_yearly', 'corporate_events')
               AND l.status = 'ok'
               AND COALESCE(l.rows_upserted, 0) > 0),
            (SELECT max(s.proven_at) FROM public.b3_corporate_event_sweep s)
        ) AT TIME ZONE 'UTC',
        'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
    );
$$;

COMMENT ON FUNCTION api.quote_data_revision() IS
    'Internal. The data revision served by api.quote_history and api.panel: the newest successful B3 cash-tape or corporate-event load, or corporate-event sweep proof, ISO 8601 UTC.';

REVOKE ALL ON FUNCTION api.quote_data_revision() FROM PUBLIC;

-- Internal. Whether and how one instrument's closes can be adjusted: the
-- anchor (its latest session on the tape, every board), the sweep proof, and
-- the last day of the stretch no adjustment may cover.
--
-- B3's rule (options Caderno de Formulas, verified in #372 on 161 of 165
-- events): DESDOBRAMENTO and BONIFICACAO multiply the share count by
-- 1 + factor/100, GRUPAMENTO by factor, and distinct events on one ISIN and
-- date multiply together. B3's cash class (DIVIDENDO, JRS CAP PROPRIO,
-- RENDIMENTO, AMORTIZACAO RF, JUROS RF, REST CAP DIN) and its subscription
-- class (SUBSCRICAO, SUBS C/ RENUNC, PRIORIDADE SUBS: a right that moves value
-- to holders the way a distribution does and changes no share count; owner,
-- 2026-09-30) are outside this price-only adjustment and block nothing. EVERY
-- other stock label (CIS RED CAP, INCORPORACAO, REST CAP ACOES, RESG TOTAL
-- RV, ..., and any label B3 adds later)
-- moves the price in a way this version does not adjust, so it blocks the
-- stretch on or before its last_date_prior. So do an unreadable factor, one
-- label on one date republished with two different factors (two events or a
-- correction: the rows cannot say which), and one label on one date paid in two
-- assets (migration 72 stores both rows, #353; which share count each changes is
-- not verified, so it is refused rather than counted once or twice). An event whose last_date_prior is on
-- or after the anchor has not gone ex and neither adjusts nor blocks.
CREATE OR REPLACE FUNCTION api.close_adj_status(p_isin TEXT, p_ticker TEXT)
RETURNS TABLE (
    anchor         DATE,
    in_universe    BOOLEAN,
    proven_at      TIMESTAMPTZ,
    block_through  DATE,
    block_reason   TEXT
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    WITH a AS (
        SELECT max(b.trade_date) AS anchor
        FROM public.b3_cotahist b
        WHERE b.isin = p_isin AND b.tpmerc = '010'
    ),
    ev AS (
        SELECT DISTINCT e.label, e.last_date_prior, e.factor, e.asset_issued
        FROM public.b3_corporate_event e, a
        WHERE e.isin = p_isin
          AND e.last_date_prior < a.anchor
          AND e.event_class = 'stock'
    ),
    blocking AS (
        SELECT ev.last_date_prior,
               CASE
                   WHEN ev.label NOT IN ('DESDOBRAMENTO', 'GRUPAMENTO', 'BONIFICACAO')
                       THEN 'unsupported corporate event ' || ev.label
                   WHEN ev.factor IS NULL
                     OR (CASE ev.label WHEN 'GRUPAMENTO' THEN ev.factor
                                       ELSE 1 + ev.factor / 100 END) <= 0
                       THEN 'unreadable factor on ' || ev.label
                   WHEN count(*) OVER (PARTITION BY ev.label, ev.last_date_prior, ev.factor) > 1
                       THEN 'ambiguous ' || ev.label || ' paid in two assets'
                   WHEN count(*) OVER (PARTITION BY ev.label, ev.last_date_prior) > 1
                       THEN 'ambiguous ' || ev.label || ' published with two factors'
               END AS reason
        FROM ev
    )
    SELECT
        a.anchor,
        COALESCE(
            substr(p_isin, 7, 3) = 'ACN'
            OR (substr(p_isin, 7, 3) IN ('CDA', 'UNT') AND p_ticker LIKE '%11'),
            FALSE
        ),
        (SELECT s.proven_at FROM public.b3_corporate_event_sweep s
         WHERE s.issuing_company = substr(p_isin, 3, 4)),
        (SELECT max(bl.last_date_prior) FROM blocking bl WHERE bl.reason IS NOT NULL),
        (SELECT bl.reason || ' with last cum date ' || bl.last_date_prior
         FROM blocking bl WHERE bl.reason IS NOT NULL
         ORDER BY bl.last_date_prior DESC, bl.reason LIMIT 1)
    FROM a;
$$;

COMMENT ON FUNCTION api.close_adj_status(TEXT, TEXT) IS
    'Internal. For one ISIN (and the ticker asked, for the unit rule): its anchor session, research-universe membership, sweep proof time, and the last session no adjustment may cover (block_through) with the reason. Shared by api.quote_history and api.panel.';

REVOKE ALL ON FUNCTION api.close_adj_status(TEXT, TEXT) FROM PUBLIC;

-- Internal. The price-adjustment divisor for one session of one ISIN: the
-- product of the share ratios of every supported event that goes ex after the
-- session and before the anchor. 1 when there is none. Callers check
-- close_adj_status first; this function does not decide availability.
CREATE OR REPLACE FUNCTION api.close_adj_ratio(p_isin TEXT, p_trade_date DATE, p_anchor DATE)
RETURNS NUMERIC
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    SELECT COALESCE(exp(sum(ln(x.share_ratio))), 1)
    FROM (
        -- DISTINCT: a republished event can come back as a second row that
        -- differs only in approved_on; it is still one event.
        SELECT DISTINCT
            e.label,
            e.last_date_prior,
            CASE e.label WHEN 'GRUPAMENTO' THEN e.factor ELSE 1 + e.factor / 100 END AS share_ratio
        FROM public.b3_corporate_event e
        WHERE e.isin = p_isin
          AND e.label IN ('DESDOBRAMENTO', 'GRUPAMENTO', 'BONIFICACAO')
          AND e.last_date_prior >= p_trade_date
          AND e.last_date_prior < p_anchor
    ) x
    WHERE x.share_ratio > 0;
$$;

COMMENT ON FUNCTION api.close_adj_ratio(TEXT, DATE, DATE) IS
    'Internal. Product of the share ratios (1 + factor/100 for DESDOBRAMENTO and BONIFICACAO, factor for GRUPAMENTO) of every event on the ISIN that goes ex after p_trade_date and before p_anchor. The adjusted close is close_unit divided by it.';

REVOKE ALL ON FUNCTION api.close_adj_ratio(TEXT, DATE, DATE) FROM PUBLIC;

-- Internal. Raises 22023 when close_adj cannot cover [p_from, p_to] for the
-- instrument. Shared by quote_history and panel so both refuse alike.
CREATE OR REPLACE FUNCTION api.assert_close_adj(
    p_fn TEXT, p_ticker TEXT, p_isin TEXT, p_from DATE, p_to DATE
)
RETURNS BOOLEAN
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    s    RECORD;
    v_how TEXT := 'Select close explicitly for the raw close ('
                  || CASE p_fn WHEN 'panel' THEN 'p_metrics' ELSE 'p_fields' END
                  || ' = {close}), or narrow the window to sessions after the stretch.';
BEGIN
    SELECT * INTO s FROM api.close_adj_status(p_isin, p_ticker);
    IF NOT s.in_universe THEN
        RAISE EXCEPTION '%: refused, close_adj is not available for % (%): it is defined for shares (ISIN code ACN) and units (CDA/UNT with a ticker ending 11) only. To fix: %',
            p_fn, p_ticker, p_isin, v_how
            USING ERRCODE = '22023', DETAIL = 'reason=adjustment_unavailable; cause=outside research universe',
                  HINT = v_how;
    END IF;
    IF s.proven_at IS NULL THEN
        RAISE EXCEPTION '%: refused, close_adj is not available for % from % to %: the corporate events of issuer % are not proven complete (no sweep proof), so an adjustment could be missing. To fix: %',
            p_fn, p_ticker, p_from, p_to, substr(p_isin, 3, 4), v_how
            USING ERRCODE = '22023', DETAIL = 'reason=adjustment_unavailable; cause=issuer corporate events not proven swept',
                  HINT = v_how;
    END IF;
    IF (s.proven_at AT TIME ZONE 'America/Sao_Paulo')::date < s.anchor THEN
        RAISE EXCEPTION '%: refused, close_adj is not available for % from % to %: the corporate-event proof for issuer % dates from % but the instrument printed through %, so an event after the proof could be missing. To fix: %',
            p_fn, p_ticker, p_from, p_to, substr(p_isin, 3, 4),
            (s.proven_at AT TIME ZONE 'America/Sao_Paulo')::date, s.anchor, v_how
            USING ERRCODE = '22023', DETAIL = 'reason=adjustment_unavailable; cause=corporate-event proof older than the last session',
                  HINT = v_how;
    END IF;
    IF s.block_through IS NOT NULL AND p_from <= s.block_through THEN
        RAISE EXCEPTION '%: refused, close_adj is not available for % from % to %: %, which this version does not adjust. To fix: %',
            p_fn, p_ticker, p_from, LEAST(p_to, s.block_through), s.block_reason, v_how
            USING ERRCODE = '22023', DETAIL = 'reason=adjustment_unavailable; cause=' || s.block_reason,
                  HINT = v_how;
    END IF;
    RETURN TRUE;
END;
$$;

COMMENT ON FUNCTION api.assert_close_adj(TEXT, TEXT, TEXT, DATE, DATE) IS
    'Internal. Raises 22023 (DETAIL reason=adjustment_unavailable; cause=...) naming ticker, period and cause when close_adj cannot cover the window: outside shares/units, issuer events not proven swept, proof older than the last session, or an unsupported stock event (spin-off, merger, capital restitution in shares, ...), an unreadable factor or an ambiguous event after the window start. Never falls back to the raw close.';

REVOKE ALL ON FUNCTION api.assert_close_adj(TEXT, TEXT, TEXT, DATE, DATE) FROM PUBLIC;

-- Internal. TOTAL RETURN (#418), unchanged in meaning from catalog v46: the
-- cash distributions that went ex after the session and before the anchor,
-- from mv_b3_cash_event (migration 56). The total-return level is close_adj
-- divided by exp(log_cash_factor), the product of (1 + D / ex-session close)
-- over those events. An event it cannot value blocks the level, never counts
-- as zero:
--   unresolved  no proven ISIN: blocks THIS issuer's same share class (B3's
--               typeStock = the first word of ESPECI), by the ticker prefix
--               the issuer has used, never by a guessed ISIN
--   pending     B3's supplement lists it for this ISIN, the history does not
--   no_ex_close resolved, but no ex-session close or no readable amount
-- The ISIN must also have at least one resolved distribution: an ISIN the
-- history never saw paying is reported as that, not as a price return.
CREATE OR REPLACE FUNCTION api.close_total_return_cash(
    p_isin TEXT, p_ticker TEXT, p_spec TEXT, p_trade_date DATE, p_anchor DATE
)
RETURNS TABLE (
    has_cash_evidence BOOLEAN,
    n_unresolved      BIGINT,
    n_pending         BIGINT,
    n_no_ex_close     BIGINT,
    log_cash_factor   NUMERIC
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    SELECT
        COALESCE(bool_or(m.isin = p_isin AND m.kind IN ('cash', 'no_ex_close')), FALSE),
        count(*) FILTER (
            WHERE m.kind = 'unresolved'
              AND m.event_date >= p_trade_date AND m.event_date < p_anchor
              AND m.type_stock = split_part(btrim(p_spec), ' ', 1)
        ),
        count(*) FILTER (
            WHERE m.kind = 'pending' AND m.isin = p_isin
              AND m.event_date >= p_trade_date AND m.event_date < p_anchor
        ),
        count(*) FILTER (
            WHERE m.kind = 'no_ex_close' AND m.isin = p_isin
              AND m.event_date >= p_trade_date AND m.event_date < p_anchor
        ),
        sum(ln(m.factor)) FILTER (
            WHERE m.kind = 'cash' AND m.isin = p_isin
              AND m.event_date >= p_trade_date AND m.event_date < p_anchor
        )
    FROM public.mv_b3_cash_event m
    WHERE m.isin = p_isin
       OR (m.kind = 'unresolved' AND m.stems @> ARRAY[left(p_ticker, 4)]);
$$;

COMMENT ON FUNCTION api.close_total_return_cash(TEXT, TEXT, TEXT, DATE, DATE) IS
    'Internal. For one session of one ISIN: whether B3''s cash history resolves any distribution for it, the counts of later distributions it cannot value (unresolved for the share class, pending, no ex-date close), and the log of the product of (1 + cash / ex-session close) over later valued ones. Feeds quote_history''s close_total_return.';

REVOKE ALL ON FUNCTION api.close_total_return_cash(TEXT, TEXT, TEXT, DATE, DATE) FROM PUBLIC;

-- Signature change (p_fields, and rows become jsonb): CREATE OR REPLACE can
-- change neither, and PostgREST resolves an RPC by argument names, so no older
-- shape may survive as an overload.
DROP FUNCTION IF EXISTS api.quote_history(TEXT, DATE, DATE, TEXT);
DROP FUNCTION IF EXISTS api.quote_history(TEXT, DATE, DATE, TEXT, TEXT);

-- Internal. The instruments a ticker's history runs through (#381 follow-up,
-- owner decision 2026-10-04, docs/adr/0002-ticker-activity-and-lineage.md).
-- A ticker can follow an older instrument when a company changes its trading
-- code or B3 issues a new ISIN (VIIA3 BRVIIAACNOR7, last session 2023-09-19 at
-- 0.75, then BHIA3 BRBHIAACNOR1, first session 2023-09-20 at 0.75). An older
-- (ticker, ISIN) is spliced in front of the current one only when ALL hold:
--   1. same company: it is the same ticker, or CVM's FCA map (cia_ticker)
--      lists both tickers under one company CNPJ;
--   2. same share class: ISIN characters 7-11 match (type + class, e.g. ACNOR);
--   3. adjacent: its last cash session is the cash session immediately before
--      the newer instrument's first one (no session in between);
--   4. no overlap: the older ISIN never prints on or after that first session;
--   5. no stock corporate event on either ISIN goes ex at the boundary
--      (last_date_prior from the older last session to the day before the
--      newer first one), so nothing at the seam needs an adjustment;
--   6. exactly one candidate qualifies; two or more is ambiguous and stops.
-- Anything else stops the chain: the history is refused there, never guessed.
-- Each row keeps its own ticker and ISIN. seq 1 is the oldest instrument; the
-- last row is the ticker's current instrument (its latest cash print). At most
-- 10 instruments. Nothing is matched by name.
CREATE OR REPLACE FUNCTION api.ticker_lineage(p_ticker TEXT)
RETURNS TABLE (seq INT, ticker TEXT, isin TEXT, first_session DATE, last_session DATE)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_t   TEXT := upper(btrim(COALESCE(p_ticker, '')));
    v_i   TEXT;
    v_f   DATE;
    v_l   DATE;
    v_ct  TEXT[] := '{}';
    v_ci  TEXT[] := '{}';
    v_cf  DATE[] := '{}';
    v_cl  DATE[] := '{}';
    v_n   INT;
    c_t   TEXT;
    c_i   TEXT;
    c_l   DATE;
BEGIN
    SELECT b.isin, b.trade_date INTO v_i, v_l
    FROM public.b3_cotahist b
    WHERE b.codneg = v_t AND b.tpmerc = '010'
    ORDER BY b.trade_date DESC
    LIMIT 1;
    IF v_i IS NULL THEN
        RETURN;
    END IF;
    SELECT min(b.trade_date) INTO v_f
    FROM public.b3_cotahist b
    WHERE b.codneg = v_t AND b.tpmerc = '010' AND b.isin = v_i;

    LOOP
        v_ct := v_t || v_ct;
        v_ci := v_i || v_ci;
        v_cf := v_f || v_cf;
        v_cl := v_l || v_cl;
        EXIT WHEN cardinality(v_ct) >= 10;

        SELECT count(*), min(x.codneg), min(x.isin), min(x.last_print)
        INTO v_n, c_t, c_i, c_l
        FROM (
            SELECT cand.codneg, p.isin, p.trade_date AS last_print
            FROM (
                SELECT v_t AS codneg
                UNION
                SELECT o.codneg
                FROM public.cia_ticker o
                WHERE o.codneg IS NOT NULL
                  AND o.cnpj_cia IN (SELECT x.cnpj_cia FROM public.cia_ticker x WHERE x.codneg = v_t)
            ) cand
            CROSS JOIN LATERAL (
                SELECT b.isin, b.trade_date
                FROM public.b3_cotahist b
                WHERE b.codneg = cand.codneg AND b.tpmerc = '010' AND b.trade_date < v_f
                ORDER BY b.trade_date DESC
                LIMIT 1
            ) p
            WHERE p.isin IS NOT NULL
              AND p.isin <> v_i
              AND substr(p.isin, 7, 5) = substr(v_i, 7, 5)
              AND NOT EXISTS (
                  SELECT 1 FROM public.b3_cotahist s
                  WHERE s.tpmerc = '010' AND s.trade_date > p.trade_date AND s.trade_date < v_f)
              AND NOT EXISTS (
                  SELECT 1 FROM public.b3_cotahist o
                  WHERE o.isin = p.isin AND o.tpmerc = '010' AND o.trade_date >= v_f)
              AND NOT EXISTS (
                  SELECT 1 FROM public.b3_corporate_event e
                  WHERE e.isin IN (p.isin, v_i)
                    AND e.event_class = 'stock'
                    AND e.last_date_prior >= p.trade_date
                    AND e.last_date_prior < v_f)
        ) x;
        EXIT WHEN v_n <> 1;
        EXIT WHEN c_i = ANY (v_ci);

        v_t := c_t;
        v_i := c_i;
        v_l := c_l;
        SELECT min(b.trade_date) INTO v_f
        FROM public.b3_cotahist b
        WHERE b.codneg = v_t AND b.tpmerc = '010' AND b.isin = v_i;
    END LOOP;

    RETURN QUERY
    SELECT g.n::int, v_ct[g.n], v_ci[g.n], v_cf[g.n], v_cl[g.n]
    FROM generate_subscripts(v_ct, 1) AS g(n)
    ORDER BY g.n;
END;
$$;

COMMENT ON FUNCTION api.ticker_lineage(TEXT) IS
    'Internal. The (ticker, ISIN) instruments a ticker''s history runs through, oldest first, spliced only when they are the same company (same ticker, or one CNPJ in CVM''s FCA map), the same share class (ISIN characters 7-11), adjacent sessions with no overlap, no stock event at the seam, and exactly one candidate (docs/adr/0002-ticker-activity-and-lineage.md). Used by api.quote_history.';

REVOKE ALL ON FUNCTION api.ticker_lineage(TEXT) FROM PUBLIC;

CREATE OR REPLACE FUNCTION api.quote_history(
    p_ticker TEXT,
    -- NULL = from the instrument's first session on the tape.
    p_from   DATE DEFAULT (CURRENT_DATE - 365),
    p_to     DATE DEFAULT CURRENT_DATE,
    -- NULL = every board (the series follows the ISIN); a code restricts it.
    p_board  TEXT DEFAULT NULL,
    -- NULL = whole result (refuses over 1000 rows); '' = first page;
    -- 'YYYY-MM-DD' = the page after that trade_date.
    p_after  TEXT DEFAULT NULL,
    -- NULL = ticker, trade_date, close_adj. Names from api.quote_history_fields().
    p_fields TEXT[] DEFAULT NULL
)
RETURNS SETOF jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_ticker    TEXT := upper(btrim(COALESCE(p_ticker, '')));
    v_board     TEXT := NULLIF(btrim(COALESCE(p_board, '')), '');
    v_to        DATE := COALESCE(p_to, CURRENT_DATE);
    v_from      DATE := p_from;
    v_fields    TEXT[];
    v_keep      TEXT[];
    v_bad       TEXT;
    v_valid     TEXT;
    v_paging    BOOLEAN;
    v_after     DATE;
    v_n         INT;
    v_spans     TEXT;
    v_boards    TEXT;
    v_isin      TEXT;
    v_cov_start DATE;
    v_cov_end   DATE;
    v_tape_start DATE;
    v_dup       TEXT;
    v_adj       BOOLEAN;
    v_anchor    DATE;
    v_proven    TIMESTAMPTZ;
    v_rev       TEXT;
    v_tr        BOOLEAN;
    v_status    RECORD;
    -- The instruments the window runs through (api.ticker_lineage, #381):
    -- one entry per (ticker, ISIN), oldest first. One entry unless the
    -- window reaches back across a spliced ISIN change.
    v_lin_t     TEXT[];
    v_lin_i     TEXT[];
    v_lin_f     DATE[];
    v_lin_l     DATE[];
    v_seg_t     TEXT[];
    v_seg_i     TEXT[];
    v_seg_f     DATE[];
    v_seg_l     DATE[];
    v_seg_anchor DATE[] := '{}';
    v_seg_tail  NUMERIC[] := '{}';
    v_tail      NUMERIC := 1;
    v_k         INT;
    v_lineage   BOOLEAN := FALSE;
    v_cur_first DATE;
BEGIN
    -- 1. The selection. An unknown name refuses; nothing is silently dropped.
    SELECT string_agg(f.field, ', ' ORDER BY f.field) INTO v_valid
    FROM api.quote_history_fields() f;
    IF p_fields IS NULL THEN
        v_fields := ARRAY['close_adj'];
    ELSE
        v_fields := ARRAY(SELECT DISTINCT lower(btrim(x)) FROM unnest(p_fields) x
                          WHERE btrim(COALESCE(x, '')) <> '');
        IF cardinality(v_fields) = 0 THEN
            RAISE EXCEPTION 'quote_history: refused, p_fields is empty. To fix: omit it for ticker, trade_date, close_adj, or name fields from: %', v_valid
                USING ERRCODE = '22023', DETAIL = 'reason=invalid_field', HINT = 'Valid fields: ' || v_valid;
        END IF;
        SELECT string_agg(x, ', ' ORDER BY x) INTO v_bad
        FROM unnest(v_fields) x
        WHERE x NOT IN (SELECT f.field FROM api.quote_history_fields() f);
        IF v_bad IS NOT NULL THEN
            RAISE EXCEPTION 'quote_history: refused, unknown field(s) %. To fix: name fields from: %', v_bad, v_valid
                USING ERRCODE = '22023', DETAIL = 'reason=invalid_field', HINT = 'Valid fields: ' || v_valid;
        END IF;
    END IF;
    v_keep := ARRAY['ticker', 'trade_date'] || v_fields;
    v_adj  := 'close_adj' = ANY (v_fields);
    v_tr   := v_fields && ARRAY['close_total_return', 'close_total_return_null_reason'];

    SELECT c.paging, c.after_date INTO v_paging, v_after
    FROM api.parse_date_cursor(p_after, 'quote_history') c;

    -- 2. The ticker and its instruments. One span per ISIN it printed under.
    IF v_ticker = '' THEN
        RAISE EXCEPTION 'quote_history: refused, p_ticker is required.'
            USING ERRCODE = '22023', DETAIL = 'reason=unknown_ticker';
    END IF;
    SELECT count(*), string_agg(format('%s %s..%s', COALESCE(s.isin, 'no ISIN'), s.f, s.l), '; ' ORDER BY s.f)
    INTO v_n, v_spans
    FROM (
        SELECT b.isin, min(b.trade_date) AS f, max(b.trade_date) AS l
        FROM public.b3_cotahist b
        WHERE b.codneg = v_ticker AND b.tpmerc = '010'
          AND (v_board IS NULL OR b.codbdi = v_board)
        GROUP BY b.isin
    ) s;
    IF v_n = 0 THEN
        IF v_board IS NOT NULL THEN
            SELECT string_agg(DISTINCT b.codbdi, ', ') INTO v_boards
            FROM public.b3_cotahist b WHERE b.codneg = v_ticker AND b.tpmerc = '010';
        END IF;
        IF v_boards IS NOT NULL THEN
            RAISE EXCEPTION 'quote_history: refused, % never printed on board %; it printed on board(s) %. To fix: omit p_board to follow the instrument across boards.', v_ticker, v_board, v_boards
                USING ERRCODE = '22023', DETAIL = 'reason=unknown_ticker';
        END IF;
        RAISE EXCEPTION 'quote_history: refused, unknown ticker %: it never printed on the B3 cash tape (tpmerc 010), which starts 2019-01-02. To fix: check the code with api.lookup.', v_ticker
            USING ERRCODE = '22023', DETAIL = 'reason=unknown_ticker';
    END IF;

    -- 3. Coverage. Exactly one ISIN may meet the window, and the window may not
    -- start before that ISIN's first session on the tape, unless the window
    -- reaches back across an ISIN change api.ticker_lineage splices (#381):
    -- then the series runs through each instrument in turn, and every row
    -- keeps its own ticker and ISIN. With p_board, no splice is attempted.
    -- Only a window that starts before the current instrument's first session
    -- can reach a splice, so the lineage is looked up only then.
    IF v_board IS NULL AND v_from IS NOT NULL THEN
        SELECT min(b.trade_date) INTO v_cur_first
        FROM public.b3_cotahist b
        WHERE b.codneg = v_ticker AND b.tpmerc = '010'
          AND b.isin IS NOT DISTINCT FROM (
              SELECT b2.isin FROM public.b3_cotahist b2
              WHERE b2.codneg = v_ticker AND b2.tpmerc = '010'
              ORDER BY b2.trade_date DESC LIMIT 1);
    END IF;
    IF v_board IS NULL AND (v_from IS NULL OR v_from < v_cur_first) THEN
        SELECT array_agg(l.ticker ORDER BY l.seq), array_agg(l.isin ORDER BY l.seq),
               array_agg(l.first_session ORDER BY l.seq), array_agg(l.last_session ORDER BY l.seq)
        INTO v_lin_t, v_lin_i, v_lin_f, v_lin_l
        FROM api.ticker_lineage(v_ticker) l;
        v_lineage := cardinality(v_lin_t) > 1
                     AND (v_from IS NULL OR v_from < v_lin_f[cardinality(v_lin_f)]);
    END IF;

    IF v_lineage THEN
        v_spans := (SELECT string_agg(format('%s %s %s..%s', v_lin_t[g], v_lin_i[g], v_lin_f[g], v_lin_l[g]), '; ' ORDER BY g)
                    FROM generate_subscripts(v_lin_t, 1) g);
        -- An instrument of this ticker outside the splice still refuses.
        SELECT count(*) INTO v_n
        FROM (
            SELECT b.isin, min(b.trade_date) AS f, max(b.trade_date) AS l
            FROM public.b3_cotahist b
            WHERE b.codneg = v_ticker AND b.tpmerc = '010'
            GROUP BY b.isin
        ) s
        WHERE s.f <= v_to AND (v_from IS NULL OR s.l >= v_from)
          AND NOT (s.isin IS NOT NULL AND s.isin = ANY (v_lin_i));
        IF v_n > 0 THEN
            RAISE EXCEPTION 'quote_history: refused, from % to % % printed under an ISIN its lineage does not splice (%). A new ISIN is joined to the old one only by the lineage rule. To fix: narrow p_from/p_to to one ISIN''s span.', COALESCE(v_from::text, 'the start'), v_to, v_ticker, v_spans
                USING ERRCODE = '22023', DETAIL = 'reason=isin_change', HINT = 'Coverage: ' || v_spans;
        END IF;
        v_cov_start := v_lin_f[1];
        v_cov_end   := v_lin_l[cardinality(v_lin_l)];
        v_isin      := v_lin_i[cardinality(v_lin_i)];
    ELSE
        SELECT count(*), max(s.isin), min(s.f), max(s.l)
        INTO v_n, v_isin, v_cov_start, v_cov_end
        FROM (
            SELECT b.isin, min(b.trade_date) AS f, max(b.trade_date) AS l
            FROM public.b3_cotahist b
            WHERE b.codneg = v_ticker AND b.tpmerc = '010'
              AND (v_board IS NULL OR b.codbdi = v_board)
            GROUP BY b.isin
        ) s
        WHERE s.f <= v_to AND (v_from IS NULL OR s.l >= v_from);
        IF v_n = 0 THEN
            RAISE EXCEPTION 'quote_history: refused, % has no coverage from % to %. Its coverage: %. To fix: ask for a window inside it.', v_ticker, COALESCE(v_from::text, 'the start'), v_to, v_spans
                USING ERRCODE = '22023', DETAIL = 'reason=outside_coverage', HINT = 'Coverage: ' || v_spans;
        END IF;
        IF v_n > 1 THEN
            RAISE EXCEPTION 'quote_history: refused, from % to % % printed under more than one ISIN (%). A new ISIN is joined to the old one only when api.ticker_lineage splices them, and these are not spliced. To fix: narrow p_from/p_to to one ISIN''s span.', COALESCE(v_from::text, 'the start'), v_to, v_ticker, v_spans
                USING ERRCODE = '22023', DETAIL = 'reason=isin_change', HINT = 'Coverage: ' || v_spans;
        END IF;
    END IF;
    IF v_from IS NULL THEN
        v_from := v_cov_start;
    ELSIF v_from > v_to THEN
        RAISE EXCEPTION 'quote_history: refused, p_from % is after p_to %.', v_from, v_to
            USING ERRCODE = '22023', DETAIL = 'reason=invalid_window';
    ELSIF v_from < v_cov_start THEN
        SELECT min(b.trade_date) INTO v_tape_start
        FROM public.b3_cotahist b WHERE b.tpmerc = '010';
        RAISE EXCEPTION 'quote_history: refused, the window starts % but % (%) is covered only from %. To fix: start the window on or after %.',
            v_from, v_ticker, v_isin,
            v_cov_start || CASE WHEN v_cov_start = v_tape_start THEN ' (the tape starts ' || v_tape_start || ')' ELSE '' END,
            v_cov_start
            USING ERRCODE = '22023', DETAIL = 'reason=outside_coverage', HINT = 'Coverage: ' || v_spans;
    END IF;

    -- The instruments the series runs through, oldest first: the whole
    -- lineage when the window reaches back across a splice (rows outside the
    -- window are filtered later; later instruments still adjust earlier rows),
    -- else the one instrument the window meets.
    IF v_lineage THEN
        v_seg_t := v_lin_t;
        v_seg_i := v_lin_i;
        v_seg_f := v_lin_f;
        v_seg_l := v_lin_l;
    ELSE
        v_seg_t := ARRAY[v_ticker];
        v_seg_i := ARRAY[v_isin];
        v_seg_f := ARRAY[v_cov_start];
        v_seg_l := ARRAY[v_cov_end];
    END IF;

    -- 4. One row per session, or a refusal.
    FOR v_k IN 1 .. cardinality(v_seg_t) LOOP
        CONTINUE WHEN v_seg_f[v_k] > v_to OR v_seg_l[v_k] < v_from;
        SELECT string_agg(format('%s (boards %s)', d.trade_date, d.boards), ', ' ORDER BY d.trade_date)
        INTO v_dup
        FROM (
            SELECT b.trade_date, string_agg(b.codbdi, '/' ORDER BY b.codbdi) AS boards
            FROM public.b3_cotahist b
            WHERE b.codneg = v_seg_t[v_k] AND b.tpmerc = '010' AND b.isin IS NOT DISTINCT FROM v_seg_i[v_k]
              AND (v_board IS NULL OR b.codbdi = v_board)
              AND b.trade_date BETWEEN GREATEST(v_from, v_seg_f[v_k]) AND LEAST(v_to, v_seg_l[v_k])
            GROUP BY b.trade_date
            HAVING count(*) > 1
            ORDER BY b.trade_date
            LIMIT 5
        ) d;
        IF v_dup IS NOT NULL THEN
            RAISE EXCEPTION 'quote_history: refused, % printed more than one row on a session: %. SILO does not choose between them. To fix: pass p_board to pick one board.', v_seg_t[v_k], v_dup
                USING ERRCODE = '22023', DETAIL = 'reason=ambiguous_session';
        END IF;
    END LOOP;

    -- 5. The adjusted close, or a refusal naming ticker, period and cause.
    -- Each instrument is checked on its own stretch of the window, and every
    -- later instrument on its whole span, because its share-count events
    -- divide the earlier rows too. A row is divided by its own ISIN's later
    -- share ratios up to that ISIN's last session, times every later
    -- instrument's (v_seg_tail); the lineage rule leaves no stock event at a
    -- seam.
    FOR v_k IN 1 .. cardinality(v_seg_t) LOOP
        IF v_adj AND v_seg_l[v_k] >= v_from THEN
            PERFORM api.assert_close_adj('quote_history', v_seg_t[v_k], v_seg_i[v_k],
                                         GREATEST(v_from, v_seg_f[v_k]),
                                         CASE WHEN v_seg_f[v_k] > v_to THEN v_seg_l[v_k]
                                              ELSE LEAST(v_to, v_seg_l[v_k]) END);
        END IF;
        SELECT * INTO v_status FROM api.close_adj_status(v_seg_i[v_k], v_seg_t[v_k]);
        v_seg_anchor := v_seg_anchor || v_status.anchor;
    END LOOP;
    -- The current instrument's status drives events_proven_at and the total return.
    v_anchor := v_status.anchor;
    v_proven := v_status.proven_at;
    v_seg_tail := array_fill(1::numeric, ARRAY[cardinality(v_seg_t)]);
    FOR v_k IN REVERSE cardinality(v_seg_t) .. 1 LOOP
        v_seg_tail[v_k] := v_tail;
        IF v_k > 1 AND v_adj THEN
            v_tail := v_tail * api.close_adj_ratio(v_seg_i[v_k], v_seg_f[v_k], v_seg_anchor[v_k]);
        END IF;
    END LOOP;

    v_rev := api.quote_data_revision();
    -- Also on every response as a header, for callers that keep only rows.
    PERFORM set_config('response.headers',
                       json_build_array(json_build_object('X-Silo-Data-Revision', COALESCE(v_rev, '')))::text,
                       TRUE);

    RETURN QUERY
    WITH RECURSIVE seg AS (
        SELECT g AS k, v_seg_t[g] AS t, v_seg_i[g] AS i, v_seg_f[g] AS f, v_seg_l[g] AS l,
               v_seg_anchor[g] AS anchor, v_seg_tail[g] AS tail,
               g = cardinality(v_seg_t) AS is_current
        FROM generate_subscripts(v_seg_t, 1) g
    ),
    page AS (
        SELECT q.*, s.i AS seg_isin, s.anchor AS seg_anchor, s.tail AS seg_tail, s.is_current
        FROM seg s
        JOIN api.quotes q
          ON q.ticker = s.t
         AND q.isin IS NOT DISTINCT FROM s.i
         AND q.trade_date BETWEEN s.f AND s.l
        WHERE (v_board IS NULL OR q.board = v_board)
          AND q.trade_date BETWEEN v_from AND v_to
          AND (v_after IS NULL OR q.trade_date > v_after)
        ORDER BY q.trade_date
        -- One page + one: the 1001st row is what makes "over the page"
        -- detectable, and assert_row_cap then refuses instead of trimming.
        LIMIT 1001
    ),
    -- The previous print of the same series: across a spliced seam when the
    -- window runs through a lineage, else the same (ticker, ISIN) as before.
    prev AS (
        SELECT max(b.trade_date) AS d
        FROM public.b3_cotahist b
        JOIN generate_subscripts(CASE WHEN v_lineage THEN v_lin_t ELSE v_seg_t END, 1) g ON TRUE
        WHERE 'prior_no_trade_sessions' = ANY (v_fields)
          AND b.codneg = (CASE WHEN v_lineage THEN v_lin_t ELSE v_seg_t END)[g]
          AND b.isin IS NOT DISTINCT FROM (CASE WHEN v_lineage THEN v_lin_i ELSE v_seg_i END)[g]
          AND b.tpmerc = '010'
          AND (v_board IS NULL OR b.codbdi = v_board)
          AND b.trade_date < (SELECT min(g2.trade_date) FROM page g2)
    ),
    -- The market calendar over the page (sessions = days the cash tape
    -- printed), by skip scan: one index probe per session, ~34 ms for the
    -- whole tape measured 2026-09-30, instead of counting tape rows per gap.
    -- Built only when prior_no_trade_sessions is asked for.
    cal_span AS (
        SELECT COALESCE((SELECT p.d FROM prev p), (SELECT min(g.trade_date) FROM page g)) AS d0,
               (SELECT max(g.trade_date) FROM page g) AS d1
        WHERE 'prior_no_trade_sessions' = ANY (v_fields)
    ),
    cal AS (
        SELECT c.d0 AS d FROM cal_span c WHERE c.d0 IS NOT NULL
        UNION ALL
        SELECT (SELECT min(b.trade_date) FROM public.b3_cotahist b
                WHERE b.tpmerc = '010' AND b.trade_date > cal.d)
        FROM cal, cal_span c
        WHERE cal.d < c.d1
    ),
    cal_ord AS (
        SELECT cal.d, row_number() OVER (ORDER BY cal.d) AS n
        FROM cal WHERE cal.d IS NOT NULL
    ),
    r_all AS (
        SELECT g.*,
               lag(g.trade_date) OVER (ORDER BY g.trade_date) AS prev_date,
               tr.reason   AS tr_reason,
               tr.log_cash AS tr_log_cash
        FROM page g
        -- Total return, only when asked for: the price adjustment must be
        -- servable for the session (the same status close_adj checks, per
        -- session instead of refusing), then every later distribution valued.
        LEFT JOIN LATERAL (
            SELECT
                CASE
                    WHEN NOT g.is_current
                        THEN 'before an ISIN change the ticker''s lineage splices; the total return is not computed across it'
                    WHEN NOT v_status.in_universe THEN 'outside research universe'
                    WHEN v_status.proven_at IS NULL THEN 'issuer corporate events not proven swept'
                    WHEN (v_status.proven_at AT TIME ZONE 'America/Sao_Paulo')::date < v_status.anchor
                        THEN 'corporate-event proof older than the last session'
                    WHEN v_status.block_through IS NOT NULL AND g.trade_date <= v_status.block_through
                        THEN v_status.block_reason
                    WHEN g.close_unit IS NULL THEN 'no close on the session'
                    WHEN NOT c.has_cash_evidence THEN 'no cash distribution resolved for this ISIN in B3''s history'
                    WHEN c.n_unresolved > 0 THEN 'a later distribution of this issuer''s share class has no proven ISIN'
                    WHEN c.n_pending > 0 THEN 'a later distribution B3 lists is missing from its cash history'
                    WHEN c.n_no_ex_close > 0 THEN 'a later distribution has no ex-date close within 7 days'
                END AS reason,
                c.log_cash_factor AS log_cash
            FROM api.close_total_return_cash(v_isin, v_ticker, g.spec, g.trade_date, v_anchor) c
            WHERE v_tr
        ) tr ON TRUE
    )
    SELECT (
        SELECT jsonb_object_agg(kv.key, kv.value)
        FROM jsonb_each(jsonb_build_object(
            'ticker',           r.ticker,
            'trade_date',       r.trade_date,
            'close_adj',        CASE WHEN v_adj THEN
                                    round(r.close_unit / (api.close_adj_ratio(r.seg_isin, r.trade_date, r.seg_anchor) * r.seg_tail), 6)
                                END,
            'close',            r.close,
            'open',             r.open,
            'high',             r.high,
            'low',              r.low,
            'average',          r.average,
            'bid',              r.bid,
            'ask',              r.ask,
            'close_unit',       r.close_unit,
            'trades',           r.trades,
            'quantity',         r.quantity,
            'volume',           r.volume,
            'quotation_factor', r.quotation_factor,
            'board',            r.board,
            'isin',             r.isin,
            'short_name',       r.short_name,
            'spec',             r.spec,
            'currency',         r.currency,
            'asset_class',      r.asset_class,
            'source',           r.source,
            'market', r.market,
            'term_days', r.term_days,
            'contract_price', r.contract_price,
            'contract_expiry', r.contract_expiry,
            'contract_correction', r.contract_correction,
            'contract_points', r.contract_points,
            'contract_points_raw', r.contract_points_raw,
            'distribution_number', r.distribution_number,
            'fetched_at', r.fetched_at,
            'coverage_start',   v_cov_start,
            'coverage_end',     v_cov_end,
            -- Every printed row is a session, and so is the previous one, so
            -- the sessions strictly between them are an ordinal difference.
            'prior_no_trade_sessions', CASE WHEN 'prior_no_trade_sessions' = ANY (v_fields) THEN
                (SELECT c.n FROM cal_ord c WHERE c.d = r.trade_date)
              - (SELECT c.n FROM cal_ord c
                 WHERE c.d = COALESCE(r.prev_date, (SELECT p.d FROM prev p), r.trade_date))
              - CASE WHEN COALESCE(r.prev_date, (SELECT p.d FROM prev p)) IS NULL THEN 0 ELSE 1 END
            END,
            'events_proven_at', to_char(v_proven AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
            'data_revision',    v_rev,
            'close_total_return', CASE WHEN v_tr AND r.tr_reason IS NULL THEN
                round(r.close_unit / api.close_adj_ratio(v_isin, r.trade_date, v_anchor)
                      / exp(COALESCE(r.tr_log_cash, 0)), 6)
            END,
            'close_total_return_null_reason', CASE WHEN v_tr THEN r.tr_reason END
        )) kv
        WHERE kv.key = ANY (v_keep)
    )
    FROM r_all r
    WHERE api.assert_row_cap((SELECT count(*) FROM page), v_paging, 'quote_history')
    ORDER BY r.trade_date
    LIMIT 1000;
END;
$$;

COMMENT ON FUNCTION api.quote_history(TEXT, DATE, DATE, TEXT, TEXT, TEXT[]) IS
    'Daily price series for one ticker, oldest first, one JSON object per session holding only the selected fields. Default (p_fields omitted): ticker, trade_date, close_adj. close_adj is the close per single share, backward-adjusted for splits, groupings and bonus shares by B3''s rule and anchored to the instrument''s latest session (past levels change when an event lands; returns do not); no dividend, JCP or subscription-right adjustment; shares and units only; 6 decimal places. It is never null and never the raw close: a window it cannot cover is REFUSED (22023, DETAIL reason=adjustment_unavailable) naming ticker, period and cause. The raw close, OHLC and volume are an explicit selection (p_fields = {close, ...}); fields are listed in catalog(). The series follows the ISIN across boards; p_board restricts it. Refusals (22023, DETAIL reason=...): unknown_ticker; outside_coverage (a window with no coverage, or starting before the instrument''s first session; the tape starts 2019-01-02); isin_change (two ISINs in the window that the ticker''s lineage does not splice); ambiguous_session (two rows on one session); invalid_field; adjustment_unavailable. A session missing inside the coverage is a session with no trade (prior_no_trade_sessions counts them); a field with no value is a null. A ticker whose company changed its trading code or ISIN runs through its older instrument (ticker lineage, #381): an older (ticker, ISIN) is spliced in front only when it is the same company (the same ticker, or one CNPJ in CVM''s FCA map), the same share class (ISIN characters 7-11), its last cash session is the one right before the newer first session with no overlap, no stock event goes ex at the seam, and exactly one candidate qualifies; every row keeps its own ticker and ISIN, close_adj divides older rows by the later instruments'' share ratios too, and close_total_return is NULL before a seam (VIIA3 BRVIIAACNOR7 to BHIA3 BRBHIAACNOR1 on 2023-09-20). close_total_return (with close_total_return_null_reason) is selectable too: close_adj with B3''s cash distributions reinvested at the ex-date close (#418), NULL with a reason wherever a distribution cannot be valued, never the price return in disguise. data_revision (field, and header X-Silo-Data-Revision) identifies the data; do not combine pages with different revisions. Row cap: more than 1000 rows RAISES 22023 unless p_after pages: '''' = first page, then the last row''s trade_date as ''YYYY-MM-DD''; a page shorter than 1000 is the last.';

REVOKE ALL ON FUNCTION api.quote_history(TEXT, DATE, DATE, TEXT, TEXT, TEXT[]) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.quote_history(TEXT, DATE, DATE, TEXT, TEXT, TEXT[]) TO anon, authenticated;

DROP FUNCTION IF EXISTS api.quote_latest(TEXT, TEXT);
CREATE OR REPLACE FUNCTION api.quote_latest(
    p_ticker TEXT,
    p_board  TEXT DEFAULT NULL
)
RETURNS TABLE (
    ticker            TEXT,
    trade_date        DATE,
    board             TEXT,
    short_name        TEXT,
    spec              TEXT,
    currency          TEXT,
    open              NUMERIC,
    high              NUMERIC,
    low               NUMERIC,
    average           NUMERIC,
    close             NUMERIC,
    bid               NUMERIC,
    ask               NUMERIC,
    trades            INT,
    quantity          NUMERIC,
    volume            NUMERIC,
    isin              TEXT,
    quotation_factor  INT,
    adjusted          BOOLEAN,
    source            TEXT,
    asset_class       TEXT,
    market                TEXT,
    term_days             TEXT,
    contract_price        NUMERIC,
    contract_expiry       DATE,
    contract_correction   TEXT,
    contract_points       NUMERIC,
    contract_points_raw   TEXT,
    distribution_number   TEXT,
    fetched_at            TIMESTAMPTZ
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    SELECT
        q.ticker,
        q.trade_date,
        q.board,
        q.short_name,
        q.spec,
        q.currency,
        q.open,
        q.high,
        q.low,
        q.average,
        q.close,
        q.bid,
        q.ask,
        q.trades,
        q.quantity,
        q.volume,
        q.isin,
        q.quotation_factor,
        q.adjusted,
        q.source,
        q.asset_class,
        q.market,
        q.term_days,
        q.contract_price,
        q.contract_expiry,
        q.contract_correction,
        q.contract_points,
        q.contract_points_raw,
        q.distribution_number,
        q.fetched_at
    FROM api.quotes q
    WHERE q.ticker = upper(btrim(p_ticker))
      AND (p_board IS NULL OR q.board = p_board)
    ORDER BY q.trade_date DESC, q.board
    LIMIT 1;
$$;

REVOKE ALL ON FUNCTION api.quote_latest(TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.quote_latest(TEXT, TEXT) TO anon, authenticated;

-- ---------------------------------------------------------------------------
-- Options & termo (B3 COTAHIST derivative segments; INSTRUMENTS.md Phase A)
-- ---------------------------------------------------------------------------
-- Same landing rows as the cash tape, different tpmerc: calls '070', puts
-- '080', termo '030'. side is derived ONLY from tpmerc — a published B3 code,
-- not a guess.
--
-- underlying_ticker IS a published mapping, not the codneg-root convention:
-- COTAHIST's CODISI on an option row carries the UNDERLYING's ISIN (the rb3
-- reference joins on it). We resolve it to the cash codneg printed on the
-- same session. Measured 2026-08-27 on the full 2026-08-25 session: 14,895 of
-- 14,900 option rows matched, and within tpmerc='010' each ISIN maps to
-- exactly one codneg (the fractional market is a different tpmerc), so the
-- join is 1:1; the tie-break below is a determinism backstop, not a guess.
-- NULL when the underlying had no cash print that session — never fabricated.
-- The codneg-root inference remains the caller's own (integrity rule 3).
-- ---------------------------------------------------------------------------

-- Signature changes below (new OUT columns): CREATE OR REPLACE cannot change
-- a RETURNS TABLE shape, so the old signatures are dropped first.
DROP FUNCTION IF EXISTS api.option_chain(TEXT, DATE, DATE, INT);
DROP FUNCTION IF EXISTS api.option_history(TEXT, DATE, DATE);

CREATE OR REPLACE FUNCTION api.option_chain(
    p_prefix      TEXT,
    p_expiry_from DATE DEFAULT CURRENT_DATE,
    p_trade_date  DATE DEFAULT NULL,
    -- 100, not 500. Measured against production on 2026-08-29 for PETR, the
    -- busiest chain on the tape: 100 rows in 899 ms, 200 rows exceeded the
    -- anon role's 3 s statement_timeout and came back 57014. The old default
    -- of 500 therefore returned a 500 for PETR and BOVA while VALE and ITUB
    -- happened to squeak through — a documented default that fails on the
    -- most-requested underlyings is not a default.
    --
    -- The 1..2000 clamp below is unchanged, so a caller who wants a deeper
    -- page can still ask for one; overreaching on a busy prefix is then their
    -- explicit choice rather than what the docs told them to do. Raising this
    -- back to 500 wants an index or a narrower query shape first, measured.
    p_limit       INT  DEFAULT 100
)
RETURNS TABLE (
    codneg     TEXT,
    side       TEXT,
    strike     NUMERIC,
    expiry     DATE,
    trade_date DATE,
    close      NUMERIC,
    open       NUMERIC,
    high       NUMERIC,
    low        NUMERIC,
    trades     INT,
    quantity   NUMERIC,
    volume     NUMERIC,
    isin       TEXT,
    spec       TEXT,
    underlying_ticker   TEXT,
    strike_points       NUMERIC,
    strike_correction   TEXT,
    distribution_number   TEXT,
    market                TEXT,
    board                 TEXT,
    term_days             TEXT,
    short_name            TEXT,
    currency              TEXT,
    average               NUMERIC,
    bid                   NUMERIC,
    ask                   NUMERIC,
    quotation_factor      INT,
    contract_points_raw   TEXT,
    fetched_at            TIMESTAMPTZ
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_prefix     TEXT := upper(btrim(COALESCE(p_prefix, '')));
    v_trade_date DATE;
BEGIN
    -- The prefix is REQUIRED (INSTRUMENTS.md): a whole-market chain is tens of
    -- thousands of rows — exactly the query the caps exist to stop. RAISE is
    -- the honest analogue of serve/'s 400: PostgREST surfaces it as an error
    -- response instead of a silently narrowed chain.
    IF length(v_prefix) < 3 THEN
        RAISE EXCEPTION
            'option_chain requires p_prefix: a codneg prefix of at least 3 characters (e.g. PETR). An unfiltered whole-market chain is refused.'
            USING ERRCODE = '22023';
    END IF;
    -- NULL p_trade_date = the latest trade_date present among option rows
    -- (the option segment's own latest session — NOT the cash tape's, so a
    -- day where only cash landed never silently serves a stale chain as
    -- "today").
    --
    -- GREATEST of two single-tpmerc maxes, NOT max(...) WHERE tpmerc IN (...).
    -- Postgres rewrites MIN/MAX into an index scan only under a plain equality
    -- qual, so the IN form plans as a seq scan over the option segment — ~89%
    -- of the table, on the DEFAULT code path. Each equality max here becomes
    -- Limit 1 over idx_b3_cotahist_tpmerc_dt (measured: 34k buffers -> 8).
    -- GREATEST ignores NULLs, so a segment with no rows yet is skipped rather
    -- than nulling the whole expression.
    v_trade_date := COALESCE(
        p_trade_date,
        GREATEST(
            (SELECT max(b.trade_date) FROM public.b3_cotahist b WHERE b.tpmerc = '070'),
            (SELECT max(b.trade_date) FROM public.b3_cotahist b WHERE b.tpmerc = '080')
        )
    );
    RETURN QUERY
    SELECT
        b.codneg,
        CASE b.tpmerc WHEN '070' THEN 'call' WHEN '080' THEN 'put' END,
        b.preco_exercicio,
        b.data_vencimento,
        b.trade_date,
        b.preco_fechamento,
        b.preco_abertura,
        b.preco_maximo,
        b.preco_minimo,
        b.negocios,
        b.quantidade,
        b.volume,
        b.isin,
        b.especi,
        u.codneg,
        -- PTOEXE: strike in points (USD-referenced options), 6 implied
        -- decimals per the published layout; 0 is B3's filler for
        -- "not points-referenced", decoded to NULL rather than a fake 0-point
        -- strike. INDOPC / DISMES pass through as published codes.
        CASE WHEN b.raw ->> 'ptoexe' ~ '^[0-9]{13}$' THEN NULLIF((b.raw ->> 'ptoexe')::NUMERIC, 0) / 1e6 END,
        b.raw ->> 'indopc',
        b.raw ->> 'dismes',
        b.tpmerc,
        b.codbdi,
        b.prazot,
        b.nome_resumido,
        b.moeda,
        b.preco_medio,
        b.oferta_compra,
        b.oferta_venda,
        b.fator_cotacao,
        b.raw ->> 'ptoexe',
        b.fetched_at
    FROM public.b3_cotahist b
    LEFT JOIN LATERAL (
        SELECT c.codneg
        FROM public.b3_cotahist c
        WHERE c.tpmerc = '010'
          AND c.isin = b.isin
          AND c.trade_date = b.trade_date
        -- Determinism backstop only (measured 1:1 within tpmerc='010'):
        -- prefer the standard-lot board, then the shortest codneg.
        ORDER BY (c.codbdi = '02') DESC, length(c.codneg), c.codneg
        LIMIT 1
    ) u ON TRUE
    WHERE b.tpmerc IN ('070', '080')
      AND b.trade_date = v_trade_date
      AND b.codneg LIKE v_prefix || '%'
      AND (p_expiry_from IS NULL OR b.data_vencimento >= p_expiry_from)
    ORDER BY b.data_vencimento, b.preco_exercicio, b.tpmerc, b.codneg
    -- Clamp 1..2000. This is a chain-page cap, not the series page: one
    -- underlying's chain on one session is hundreds of series (strike ×
    -- expiry × side), so 2000 comfortably holds any honest single-prefix
    -- chain while an over-broad prefix is cut deterministically (ORDER BY
    -- expiry, strike, side, codneg) at a bounded page.
    -- Ceiling by tier. The default stays 100 for everyone (it is a timeout
    -- budget question, not a permission one); signing in raises only how deep
    -- a caller may deliberately ask.
    LIMIT LEAST(
        GREATEST(COALESCE(p_limit, 100), 1),
        CASE api.caller_tier() WHEN 'authenticated' THEN 2000 ELSE 200 END
    );
END;
$$;

COMMENT ON FUNCTION api.option_chain(TEXT, DATE, DATE, INT) IS
    'One session''s option chain for a REQUIRED codneg prefix (>= 3 chars; else it raises). side = call/put from tpmerc 070/080. p_trade_date NULL = latest option-segment session. underlying_ticker resolves the option row''s ISIN (published: CODISI carries the underlying''s ISIN) to the same session''s cash codneg; NULL when the underlying had no cash print that day. Rows clamped to 1..2000. Original market, board, term and remaining quote/contract fields are preserved; contract_points_raw retains PTOEXE before six-decimal decoding. fetched_at is warehouse time, not a source-publication vintage.';

CREATE OR REPLACE FUNCTION api.option_history(
    p_codneg TEXT,
    p_from   DATE DEFAULT (CURRENT_DATE - 365),
    p_to     DATE DEFAULT CURRENT_DATE
)
RETURNS TABLE (
    codneg            TEXT,
    trade_date        DATE,
    side              TEXT,
    strike            NUMERIC,
    expiry            DATE,
    spec              TEXT,
    currency          TEXT,
    open              NUMERIC,
    high              NUMERIC,
    low               NUMERIC,
    average           NUMERIC,
    close             NUMERIC,
    bid               NUMERIC,
    ask               NUMERIC,
    trades            INT,
    quantity          NUMERIC,
    volume            NUMERIC,
    isin              TEXT,
    quotation_factor  INT,
    adjusted          BOOLEAN,
    source            TEXT,
    underlying_ticker   TEXT,
    strike_points       NUMERIC,
    strike_correction   TEXT,
    distribution_number   TEXT,
    market                TEXT,
    board                 TEXT,
    term_days             TEXT,
    short_name            TEXT,
    contract_points_raw   TEXT,
    fetched_at            TIMESTAMPTZ
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    -- One page + one. The 1001st row is what makes "over the page"
    -- detectable; assert_row_cap then REFUSES (22023) rather than handing
    -- back a truncated series that looks complete. This function has no
    -- cursor, so a caller over the page narrows the window instead.
    -- The explicit column list lets the outer ORDER BY name columns as
    -- declared, which also dodges OUT-parameter ambiguity.
    WITH page (codneg, trade_date, side, strike, expiry, spec, currency, open, high, low, average, close, bid, ask, trades, quantity, volume, isin, quotation_factor, adjusted, source, underlying_ticker, strike_points, strike_correction, distribution_number, market, board, term_days, short_name, contract_points_raw, fetched_at) AS (
        SELECT
            b.codneg,
            b.trade_date,
            CASE b.tpmerc WHEN '070' THEN 'call' WHEN '080' THEN 'put' END,
            b.preco_exercicio,
            b.data_vencimento,
            b.especi,
            COALESCE(b.moeda, 'R$'),
            b.preco_abertura,
            b.preco_maximo,
            b.preco_minimo,
            b.preco_medio,
            b.preco_fechamento,
            b.oferta_compra,
            b.oferta_venda,
            b.negocios,
            b.quantidade,
            b.volume,
            b.isin,
            b.fator_cotacao,
            FALSE,
            b.source,
            u.codneg,
            CASE WHEN b.raw ->> 'ptoexe' ~ '^[0-9]{13}$' THEN NULLIF((b.raw ->> 'ptoexe')::NUMERIC, 0) / 1e6 END,
            b.raw ->> 'indopc',
            b.raw ->> 'dismes',
            b.tpmerc,
            b.codbdi,
            b.prazot,
            b.nome_resumido,
            b.raw ->> 'ptoexe',
            b.fetched_at
        FROM public.b3_cotahist b
        LEFT JOIN LATERAL (
            SELECT c.codneg
            FROM public.b3_cotahist c
            WHERE c.tpmerc = '010'
              AND c.isin = b.isin
              AND c.trade_date = b.trade_date
            ORDER BY (c.codbdi = '02') DESC, length(c.codneg), c.codneg
            LIMIT 1
        ) u ON TRUE
        WHERE b.tpmerc IN ('070', '080')
          AND b.codneg = upper(btrim(p_codneg))
          AND b.trade_date BETWEEN p_from AND p_to
        ORDER BY b.trade_date
        LIMIT 1001
    )
    SELECT g.* FROM page g
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'option_history')
    ORDER BY g.trade_date
    LIMIT 1000;
$$;

COMMENT ON FUNCTION api.option_history(TEXT, DATE, DATE) IS
    'Daily unadjusted series for one option codneg (tpmerc 070/080), quote_history''s shape plus side/strike/expiry and underlying_ticker (resolved per session from the published ISIN mapping; NULL when the underlying had no cash print that day). Row cap: more than 1000 rows RAISES 22023 (never trimmed); narrow p_from/p_to. No cursor — an option series is short-lived, so a window over a page is a mistake, not a walk. Original market, board, term and remaining quote/contract fields are preserved; contract_points_raw retains PTOEXE before six-decimal decoding. fetched_at is warehouse time, not a source-publication vintage.';

-- ---------------------------------------------------------------------------
-- Option exercise events (tpmerc 012/013) and auction prints (tpmerc 017)
-- ---------------------------------------------------------------------------
-- These are EVENTS, not quote series: measured ~1.05 rows per codneg. Serving
-- them as history would invite return math over non-quotes, so they get their
-- own endpoints. side/kind derive only from tpmerc.

-- The 3-argument form is dropped rather than left as an overload: PostgREST
-- resolves an RPC by argument names, and two candidates differing only by an
-- optional p_limit make every call ambiguous.
DROP FUNCTION IF EXISTS api.option_exercises(TEXT, DATE, DATE);

DROP FUNCTION IF EXISTS api.option_exercises(TEXT, DATE, DATE, INT);
CREATE OR REPLACE FUNCTION api.option_exercises(
    p_prefix TEXT,
    p_from   DATE DEFAULT (CURRENT_DATE - 365),
    p_to     DATE DEFAULT CURRENT_DATE,
    p_limit  INT  DEFAULT NULL
)
RETURNS TABLE (
    codneg              TEXT,
    trade_date          DATE,
    side                TEXT,
    strike              NUMERIC,
    expiry              DATE,
    exercise_price      NUMERIC,
    trades              INT,
    quantity            NUMERIC,
    volume              NUMERIC,
    isin                TEXT,
    underlying_ticker   TEXT,
    spec                TEXT,
    source              TEXT,
    market                TEXT,
    board                 TEXT,
    term_days             TEXT,
    short_name            TEXT,
    currency              TEXT,
    open                  NUMERIC,
    high                  NUMERIC,
    low                   NUMERIC,
    average               NUMERIC,
    bid                   NUMERIC,
    ask                   NUMERIC,
    quotation_factor      INT,
    contract_correction   TEXT,
    contract_points       NUMERIC,
    contract_points_raw   TEXT,
    distribution_number   TEXT,
    fetched_at            TIMESTAMPTZ
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_prefix TEXT := upper(btrim(COALESCE(p_prefix, '')));
    v_cap    INT  := CASE api.caller_tier()
                          WHEN 'authenticated' THEN 5000 ELSE 500 END;
BEGIN
    -- Same required-prefix contract as option_chain, same reason.
    IF length(v_prefix) < 3 THEN
        RAISE EXCEPTION
            'option_exercises requires p_prefix: a codneg prefix of at least 3 characters (e.g. PETR).'
            USING ERRCODE = '22023';
    END IF;
    RETURN QUERY
    SELECT
        b.codneg,
        b.trade_date,
        CASE b.tpmerc WHEN '012' THEN 'call' WHEN '013' THEN 'put' END,
        b.preco_exercicio,
        b.data_vencimento,
        b.preco_fechamento,
        b.negocios,
        b.quantidade,
        b.volume,
        b.isin,
        u.codneg,
        b.especi,
        b.source,
        b.tpmerc,
        b.codbdi,
        b.prazot,
        b.nome_resumido,
        b.moeda,
        b.preco_abertura,
        b.preco_maximo,
        b.preco_minimo,
        b.preco_medio,
        b.oferta_compra,
        b.oferta_venda,
        b.fator_cotacao,
        b.raw ->> 'indopc',
            CASE WHEN b.raw ->> 'ptoexe' ~ '^[0-9]{13}$' THEN NULLIF((b.raw ->> 'ptoexe')::NUMERIC, 0) / 1e6 END,
        b.raw ->> 'ptoexe',
        b.raw ->> 'dismes',
        b.fetched_at
    FROM public.b3_cotahist b
    LEFT JOIN LATERAL (
        SELECT c.codneg
        FROM public.b3_cotahist c
        WHERE c.tpmerc = '010'
          AND c.isin = b.isin
          AND c.trade_date = b.trade_date
        ORDER BY (c.codbdi = '02') DESC, length(c.codneg), c.codneg
        LIMIT 1
    ) u ON TRUE
    WHERE b.tpmerc IN ('012', '013')
      AND b.codneg LIKE v_prefix || '%'
      AND b.trade_date BETWEEN p_from AND p_to
    ORDER BY b.trade_date, b.codneg
    -- Ceiling by tier, like every other row-capped function here. The old
    -- hardcoded LIMIT 5001 was a truncation sentinel that no caller could ever
    -- observe: PostgREST caps a response at 1000 rows regardless, so an
    -- anonymous caller silently received 1000 and had no way to learn the
    -- other 4001 existed. A tier ceiling makes the cut deterministic and the
    -- documented number true.
    LIMIT LEAST(
        GREATEST(COALESCE(p_limit, v_cap), 1),
        v_cap
    );
END;
$$;

COMMENT ON FUNCTION api.option_exercises(TEXT, DATE, DATE, INT) IS
    'Option exercise EVENTS (tpmerc 012 call / 013 put) for a REQUIRED codneg prefix (>= 3 chars). One row per exercise print — these are not quotes and carry no return semantics. underlying_ticker per the published ISIN mapping. Rows clamped to 1..500 anonymous, 1..5000 signed in. Original market, board, term and remaining quote/contract fields are preserved; contract_points_raw retains PTOEXE before six-decimal decoding. fetched_at is warehouse time, not a source-publication vintage.';

REVOKE ALL ON FUNCTION api.option_exercises(TEXT, DATE, DATE, INT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.option_exercises(TEXT, DATE, DATE, INT) TO anon, authenticated, silo_api;

-- Auction prints: tpmerc 017 (leilão). 210 rows over the whole 2019-2026 tape,
-- so a plain filterable view is proportionate; no cap needed at this size.
CREATE OR REPLACE VIEW api.auctions AS
SELECT
    v.codneg            AS ticker,
    v.trade_date,
    v.codbdi            AS board,
    v.nome_resumido     AS short_name,
    v.especi            AS spec,
    v.preco_abertura    AS open,
    v.preco_maximo      AS high,
    v.preco_minimo      AS low,
    v.preco_fechamento  AS close,
    v.negocios          AS trades,
    v.quantidade        AS quantity,
    v.volume,
    v.isin,
    v.source,
    v.fetched_at,
    v.tpmerc AS market,
    v.prazot AS term_days,
    v.moeda AS currency,
    v.preco_medio AS average,
    v.oferta_compra AS bid,
    v.oferta_venda AS ask,
    v.preco_exercicio AS contract_price,
    v.data_vencimento AS contract_expiry,
    v.fator_cotacao AS quotation_factor,
    v.raw ->> 'indopc' AS contract_correction,
    CASE WHEN v.raw ->> 'ptoexe' ~ '^[0-9]{13}$' THEN NULLIF((v.raw ->> 'ptoexe')::NUMERIC, 0) / 1e6 END AS contract_points,
    v.raw ->> 'ptoexe' AS contract_points_raw,
    v.raw ->> 'dismes' AS distribution_number
FROM public.vw_b3_instrument_typed v
WHERE v.instrument_type = 'auction';

COMMENT ON VIEW api.auctions IS
    'Auction prints (tpmerc 017, leilão) — one-off event rows, not a quote series. ~210 rows on the whole 2019-2026 tape. Unadjusted, straight from COTAHIST.';

ALTER VIEW api.auctions SET (security_invoker = false);
GRANT SELECT ON api.auctions TO anon, authenticated;

DROP FUNCTION IF EXISTS api.termo_history(TEXT, DATE, DATE);
CREATE OR REPLACE FUNCTION api.termo_history(
    p_codneg TEXT,
    p_from   DATE DEFAULT (CURRENT_DATE - 365),
    p_to     DATE DEFAULT CURRENT_DATE
)
RETURNS TABLE (
    codneg            TEXT,
    trade_date        DATE,
    term_days         TEXT,
    spec              TEXT,
    currency          TEXT,
    open              NUMERIC,
    high              NUMERIC,
    low               NUMERIC,
    average           NUMERIC,
    close             NUMERIC,
    bid               NUMERIC,
    ask               NUMERIC,
    trades            INT,
    quantity          NUMERIC,
    volume            NUMERIC,
    isin              TEXT,
    quotation_factor  INT,
    adjusted          BOOLEAN,
    source            TEXT,
    market                TEXT,
    board                 TEXT,
    short_name            TEXT,
    contract_price        NUMERIC,
    contract_expiry       DATE,
    contract_correction   TEXT,
    contract_points       NUMERIC,
    contract_points_raw   TEXT,
    distribution_number   TEXT,
    fetched_at            TIMESTAMPTZ
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    -- One page + one. The 1001st row is what makes "over the page"
    -- detectable; assert_row_cap then REFUSES (22023) rather than handing
    -- back a truncated series that looks complete. This function has no
    -- cursor, so a caller over the page narrows the window instead.
    -- The explicit column list lets the outer ORDER BY name columns as
    -- declared, which also dodges OUT-parameter ambiguity.
    WITH page (codneg, trade_date, term_days, spec, currency, open, high, low, average, close, bid, ask, trades, quantity, volume, isin, quotation_factor, adjusted, source, market, board, short_name, contract_price, contract_expiry, contract_correction, contract_points, contract_points_raw, distribution_number, fetched_at) AS (
        SELECT
            b.codneg,
            b.trade_date,
            b.prazot,           -- term in days; TEXT as stored (api.quotes precedent)
            b.especi,
            COALESCE(b.moeda, 'R$'),
            b.preco_abertura,
            b.preco_maximo,
            b.preco_minimo,
            b.preco_medio,
            b.preco_fechamento,
            b.oferta_compra,
            b.oferta_venda,
            b.negocios,
            b.quantidade,
            b.volume,
            b.isin,
            b.fator_cotacao,
            FALSE,
            b.source,
            b.tpmerc,
            b.codbdi,
            b.nome_resumido,
            b.preco_exercicio,
            b.data_vencimento,
            b.raw ->> 'indopc',
            CASE WHEN b.raw ->> 'ptoexe' ~ '^[0-9]{13}$' THEN NULLIF((b.raw ->> 'ptoexe')::NUMERIC, 0) / 1e6 END,
            b.raw ->> 'ptoexe',
            b.raw ->> 'dismes',
            b.fetched_at
        FROM public.b3_cotahist b
        WHERE b.tpmerc = '030'
          AND b.codneg = upper(btrim(p_codneg))
          AND b.trade_date BETWEEN p_from AND p_to
        -- Termo grain includes prazot (several terms of one codneg can print on
        -- one session), so order by it too for a deterministic cut. length-then-
        -- text sorts digit strings numerically without a cast that could blow up
        -- on source garbage.
        ORDER BY b.trade_date, b.codbdi, length(b.prazot), b.prazot
        LIMIT 1001
    )
    SELECT g.* FROM page g
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'termo_history')
    ORDER BY g.trade_date, g.board, length(g.term_days), g.term_days
    LIMIT 1000;
$$;

COMMENT ON FUNCTION api.termo_history(TEXT, DATE, DATE) IS
    'Daily unadjusted series for one termo codneg (tpmerc 030), including term_days (prazot). Grain is (codneg, trade_date, market, board, term_days). Row cap: more than 1000 rows RAISES 22023 (never trimmed); narrow p_from/p_to. Original market, board, term and remaining quote/contract fields are preserved; contract_points_raw retains PTOEXE before six-decimal decoding. fetched_at is warehouse time, not a source-publication vintage.';

REVOKE ALL ON FUNCTION api.option_chain(TEXT, DATE, DATE, INT) FROM PUBLIC;
REVOKE ALL ON FUNCTION api.option_history(TEXT, DATE, DATE) FROM PUBLIC;
REVOKE ALL ON FUNCTION api.termo_history(TEXT, DATE, DATE) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.option_chain(TEXT, DATE, DATE, INT) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION api.option_history(TEXT, DATE, DATE) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION api.termo_history(TEXT, DATE, DATE) TO anon, authenticated;

-- ---------------------------------------------------------------------------
-- Funds (dim_fund + existing RPCs)
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW api.funds AS
SELECT
    d.cnpj,
    d.entity_type,
    d.fund_name,
    d.status,
    d.tp_fundo          AS fund_class,
    d.first_period,
    d.last_period,
    d.n_reports
FROM public.dim_fund d;

COMMENT ON VIEW api.funds IS
    'Fund registry (FI/FIDC/FII/FIP/FIAGRO). ETFs are excluded — use etf_* RPCs.';

-- Same Step 6 decision as api.quotes: owner-privileged on purpose, so reading
-- the registry never requires a client grant on public.dim_fund.
ALTER VIEW api.funds SET (security_invoker = false);

GRANT SELECT ON api.funds TO anon, authenticated;

CREATE OR REPLACE FUNCTION api.fund_profile(p_cnpj TEXT)
RETURNS TABLE (
    cnpj              TEXT,
    entity_type       TEXT,
    fund_name         TEXT,
    status            TEXT,
    first_period      DATE,
    last_period       DATE,
    n_months_reported BIGINT,
    peak_aum          NUMERIC,
    latest_aum        NUMERIC,
    is_active         BOOLEAN
)
LANGUAGE sql
STABLE
SECURITY DEFINER
-- search_path is pinned to public (not '') ON PURPOSE: this wrapper
-- delegates to a public.* analytical function whose body resolves relation
-- names unqualified, and search_path propagates down the call stack. An
-- empty pin here broke the call at runtime ("relation does not exist").
-- A per-function pinned GUC still closes the DEFINER hole — the attack is
-- a caller-controlled search_path, and this one is immutable per call.
SET search_path = public, pg_temp
AS $$
    SELECT *
    FROM public.fund_profile(regexp_replace(p_cnpj, '[^0-9]', '', 'g'));
$$;

-- Signature change (trailing p_after cursor) and a new trailing output column
-- (period_month): drop the old shape first.
DROP FUNCTION IF EXISTS api.fund_nav(TEXT, DATE, DATE, TEXT);

CREATE OR REPLACE FUNCTION api.fund_nav(
    p_cnpj        TEXT,
    p_from        DATE DEFAULT '2019-01-01',
    -- NULL (the default) clamps to the fund family's latest COMPLETE period
    -- (mv_period_completeness): a partially-filed trailing month is not
    -- served unless the caller pins p_to explicitly (the escape hatch, which
    -- serves the window verbatim, partial months included).
    p_to          DATE DEFAULT NULL,
    p_entity_type TEXT DEFAULT NULL,
    -- NULL = whole result (refuses over 1000 rows); '' = first page;
    -- 'YYYY-MM-DD' = the page after that period. Paging REQUIRES
    -- p_entity_type -- see api.assert_fund_nav_cursor.
    p_after       TEXT DEFAULT NULL
)
RETURNS TABLE (
    cnpj          TEXT,
    period        DATE,
    entity_type   TEXT,
    nav           NUMERIC,
    quota         NUMERIC,
    quotaholders  INT,
    delinquency   NUMERIC,
    monthly_yield NUMERIC,
    inflows       NUMERIC,
    redemptions   NUMERIC,
    assets        NUMERIC,
    -- period normalised to the first of the month, which is the convention
    -- api.panel serves fund observations on. Published so a caller joining a
    -- nav series to a panel does not have to rediscover that the two differ:
    -- period keeps each family's fact_fund_monthly convention (fi, fii and
    -- fiagro the first of the month, fidc the month-end, fip 31 December),
    -- period_month is the panel's key.
    period_month  DATE
)
LANGUAGE sql
STABLE
SECURITY DEFINER
-- search_path is pinned to public (not '') ON PURPOSE: this wrapper
-- delegates to a public.* analytical function whose body resolves relation
-- names unqualified, and search_path propagates down the call stack. An
-- empty pin here broke the call at runtime ("relation does not exist").
-- A per-function pinned GUC still closes the DEFINER hole -- the attack is
-- a caller-controlled search_path, and this one is immutable per call.
SET search_path = public, pg_temp
AS $$
    WITH params AS (
        SELECT c.paging,
               c.after_date,
               -- Rides the cursor parse so the check happens before any rows
               -- are read: paging a two-family result on a bare period would
               -- skip or repeat a row at a page edge.
               api.assert_fund_nav_cursor(c.paging, p_entity_type) AS checked
        FROM api.parse_date_cursor(p_after, 'fund_nav') c
    ),
    -- One page + one, so the 1001st row makes "over the page" detectable and
    -- assert_row_cap can REFUSE instead of trimming. params drives the join
    -- so the cursor guard is evaluated before the series is walked.
    page AS (
        SELECT
            s.cnpj, s.period, s.entity_type, s.vl_patrim_liq, s.vl_quota,
            s.nr_cotst, s.vl_inadimpl, s.pct_yield_mes, s.captc_mes,
            s.resg_mes, s.vl_ativo
        FROM params pp
        JOIN public.fund_nav_series(
            regexp_replace(p_cnpj, '[^0-9]', '', 'g'),
            p_from,
            COALESCE(p_to, CURRENT_DATE),
            p_entity_type
        ) s ON pp.checked
        -- NULL p_to = clamp each row to its own family's latest complete
        -- period (raw-convention comparison; see api.panel). Explicit p_to =
        -- verbatim.
        WHERE (p_to IS NOT NULL
               OR s.period <= public.latest_complete_period(s.entity_type))
          AND (pp.after_date IS NULL OR s.period > pp.after_date)
        -- Positional, to dodge OUT-parameter name ambiguity.
        ORDER BY 2, 3
        LIMIT 1001
    )
    SELECT
        r.cnpj, r.period, r.entity_type, r.vl_patrim_liq, r.vl_quota,
        r.nr_cotst, r.vl_inadimpl, r.pct_yield_mes, r.captc_mes,
        r.resg_mes, r.vl_ativo,
        date_trunc('month', r.period)::date
    FROM page r
    WHERE api.assert_row_cap((SELECT count(*) FROM page),
                             (SELECT pp.paging FROM params pp), 'fund_nav')
    ORDER BY 2, 3
    LIMIT 1000;
$$;

COMMENT ON FUNCTION api.fund_nav(TEXT, DATE, DATE, TEXT, TEXT) IS
    'Monthly NAV/flows series for one CNPJ, oldest first. Default window (p_to NULL) ends at the family''s latest COMPLETE period per mv_period_completeness; an explicit p_to serves the window verbatim, partial months included. Row cap: more than 1000 rows RAISES 22023 (never trimmed) unless p_after pages: '''' = first page, then the last row''s period as ''YYYY-MM-DD''. PAGING REQUIRES p_entity_type — one CNPJ can file under two families in the same month (385 do), so a bare period is unique only within one family; whole-result mode serves both and labels each row. period keeps each family''s own date convention: fi, fii and fiagro rows are dated the FIRST of the month (an fi row carries the last daily report filed in that month, so 2026-09-01 holds September''s closing NAV), fidc rows the month-END (2026-08-31), fip rows 31 December of the year; the trailing period_month is the same month as api.panel keys it (first of month), equal to period for fi, fii and fiagro. Columns are per family (fact_fund_monthly arms): fi files quota, quotaholders, inflows, redemptions; fidc and fiagro file delinquency; fii files quotaholders, monthly_yield, assets; fip files nav only — a null outside that list is not applicable, not missing (catalog().applicability). fidc delinquency is filed from 2013-01, null for a fund with no tab VI row before 2020-11 and on every row from 2020-11 (regime break; catalog().regime_breaks).';

REVOKE ALL ON FUNCTION api.fund_nav(TEXT, DATE, DATE, TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.fund_nav(TEXT, DATE, DATE, TEXT, TEXT) TO anon, authenticated;

CREATE OR REPLACE FUNCTION api.search_funds(
    p_query       TEXT DEFAULT '',
    p_entity_type TEXT DEFAULT NULL,
    p_limit       INT  DEFAULT 50
)
RETURNS TABLE (
    cnpj         TEXT,
    entity_type  TEXT,
    fund_name    TEXT,
    first_period DATE,
    last_period  DATE,
    latest_aum   NUMERIC
)
LANGUAGE sql
STABLE
SECURITY DEFINER
-- search_path is pinned to public (not '') ON PURPOSE: this wrapper
-- delegates to a public.* analytical function whose body resolves relation
-- names unqualified, and search_path propagates down the call stack. An
-- empty pin here broke the call at runtime ("relation does not exist").
-- A per-function pinned GUC still closes the DEFINER hole — the attack is
-- a caller-controlled search_path, and this one is immutable per call.
SET search_path = public, pg_temp
AS $$
    SELECT *
    FROM public.search_funds(
        p_query,
        p_entity_type,
        LEAST(
            GREATEST(COALESCE(p_limit, 50), 1),
            CASE api.caller_tier() WHEN 'authenticated' THEN 200 ELSE 25 END
        )
    );
$$;

REVOKE ALL ON FUNCTION api.fund_profile(TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION api.search_funds(TEXT, TEXT, INT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.fund_profile(TEXT) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION api.search_funds(TEXT, TEXT, INT) TO anon, authenticated;

-- ---------------------------------------------------------------------------
-- Fund holdings — the fund → ticker edge, made queryable
--
-- cvm_fi_cda_acoes carries CD_ATIVO, the published B3 ticker a fund holds, and
-- cvm_fi_cda_cotas carries the CNPJ of a held fund. Both have been ingested
-- since 2005 and neither was reachable through the API, so the one edge that
-- joins the fund universe to the quote tape existed only as rows in a landing
-- table nobody can read.
--
-- Two directions, one function:
--   p_cnpj   -> what this fund holds
--   p_ticker -> which funds hold this ticker
-- Exactly one must be given; asking for both, or neither, is an error rather
-- than a silently narrowed or unbounded scan.
--
-- Rows are as filed. Values are the fund's own reported position; nothing here
-- is summed across share classes or re-based, because the source publishes one
-- row per (application type, trading intent) and collapsing them is precisely
-- the mistake the holdings key audit exists to prevent.
--
-- Row cap (v41): raise-only on the one 1000-row page, like the FIDC trio since
-- v34. Until v40 this function and fund_debentures were tiered 500 / 5000 and
-- TRIMMED SILENTLY at the tier ceiling: a busy ticker or a long window came
-- back short with a 200 and nothing to say so, and silo-mcp (always anon) was
-- handed the short answer as if it were whole. Now the page CTE fetches 1001
-- and api.assert_row_cap refuses above 1000 with the why and the how. p_limit
-- survives as an EXPLICIT newest-first head (1..1000); NULL or anything above
-- one page is the whole window, served whole or refused; < 1 is 22023.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION api.fund_holdings(
    p_cnpj   TEXT DEFAULT NULL,
    p_ticker TEXT DEFAULT NULL,
    p_from   DATE DEFAULT NULL,
    p_to     DATE DEFAULT NULL,
    p_kind   TEXT DEFAULT 'equity',   -- 'equity' | 'fund'
    p_limit  INT  DEFAULT NULL
)
RETURNS TABLE (
    cnpj              TEXT,
    period            DATE,
    kind              TEXT,
    held_id           TEXT,   -- ticker for equities, CNPJ for fund quotas
    held_name         TEXT,
    tp_aplic          TEXT,
    tp_negoc          TEXT,
    emissor_ligado    TEXT,
    qt_pos_final      NUMERIC,
    vl_merc_pos_final NUMERIC
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $fn$
DECLARE
    v_cnpj   TEXT := NULLIF(regexp_replace(COALESCE(p_cnpj, ''), '\D', '', 'g'), '');
    v_ticker TEXT := NULLIF(upper(btrim(COALESCE(p_ticker, ''))), '');
    v_head   INT;
BEGIN
    IF (v_cnpj IS NULL) = (v_ticker IS NULL) THEN
        RAISE EXCEPTION
            'fund_holdings needs exactly one of p_cnpj (what this fund holds) '
            'or p_ticker (which funds hold this ticker); % were given',
            CASE WHEN v_cnpj IS NULL THEN 'neither' ELSE 'both' END
            USING ERRCODE = '22023';
    END IF;

    IF p_kind IS NOT NULL AND p_kind NOT IN ('equity', 'fund') THEN
        RAISE EXCEPTION
            'p_kind must be equity or fund, got %; equity reads CDA block 4 '
            '(tickers), fund reads block 2 (held funds). Debentures (block 6) '
            'have their own shape — call api.fund_debentures', p_kind
            USING ERRCODE = '22023';
    END IF;

    IF v_ticker IS NOT NULL AND COALESCE(p_kind, 'equity') <> 'equity' THEN
        RAISE EXCEPTION
            'p_ticker only applies to p_kind=equity; a held FUND is identified '
            'by its CNPJ, so search block 2 with p_cnpj instead'
            USING ERRCODE = '22023';
    END IF;

    -- p_limit 1..1000 is an explicit head the caller asked for. Above one
    -- page it cannot be served as a head, so it means the whole window and
    -- the page cap decides. Below 1 is a mistake, refused rather than clamped.
    IF p_limit IS NOT NULL AND p_limit < 1 THEN
        RAISE EXCEPTION
            '%: p_limit must be 1..1000 (the newest N rows, as an explicit request) or NULL for the whole window; got %',
            'fund_holdings', p_limit
            USING ERRCODE = '22023';
    END IF;
    v_head := CASE WHEN p_limit <= 1000 THEN p_limit END;

    IF COALESCE(p_kind, 'equity') = 'equity' THEN
        RETURN QUERY
        -- One page + one (or the caller's explicit head), then assert_row_cap
        -- REFUSES (22023) instead of trimming. No cursor.
        WITH page (cnpj, period, kind, held_id, held_name, tp_aplic, tp_negoc,
                   emissor_ligado, qt_pos_final, vl_merc_pos_final) AS (
        SELECT h.cnpj, h.period, 'equity'::TEXT, h.cd_ativo, h.ds_ativo,
               h.tp_aplic, h.tp_negoc, h.emissor_ligado,
               h.qt_pos_final, h.vl_merc_pos_final
        FROM public.cvm_fi_cda_acoes h
        WHERE (v_cnpj   IS NULL OR h.cnpj     = v_cnpj)
          AND (v_ticker IS NULL OR h.cd_ativo = v_ticker)
          AND (p_from IS NULL OR h.period >= p_from)
          AND (p_to   IS NULL OR h.period <= p_to)
        ORDER BY h.period DESC, h.vl_merc_pos_final DESC NULLS LAST
        LIMIT COALESCE(v_head, 1001)
        )
        SELECT g.* FROM page g
        WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'fund_holdings')
        ORDER BY g.period DESC, g.vl_merc_pos_final DESC NULLS LAST
        LIMIT 1000;
    ELSE
        RETURN QUERY
        WITH page (cnpj, period, kind, held_id, held_name, tp_aplic, tp_negoc,
                   emissor_ligado, qt_pos_final, vl_merc_pos_final) AS (
        SELECT h.cnpj, h.period, 'fund'::TEXT, h.cnpj_cota, h.nm_fundo_cota,
               h.tp_aplic, h.tp_negoc, h.emissor_ligado,
               h.qt_pos_final, h.vl_merc_pos_final
        FROM public.cvm_fi_cda_cotas h
        WHERE h.cnpj = v_cnpj
          AND (p_from IS NULL OR h.period >= p_from)
          AND (p_to   IS NULL OR h.period <= p_to)
        ORDER BY h.period DESC, h.vl_merc_pos_final DESC NULLS LAST
        LIMIT COALESCE(v_head, 1001)
        )
        SELECT g.* FROM page g
        WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'fund_holdings')
        ORDER BY g.period DESC, g.vl_merc_pos_final DESC NULLS LAST
        LIMIT 1000;
    END IF;
END;
$fn$;

REVOKE ALL ON FUNCTION api.fund_holdings(TEXT, TEXT, DATE, DATE, TEXT, INT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.fund_holdings(TEXT, TEXT, DATE, DATE, TEXT, INT)
    TO anon, authenticated;

COMMENT ON FUNCTION api.fund_holdings(TEXT, TEXT, DATE, DATE, TEXT, INT) IS
    'Fund holdings from CDA blocks 4 (equities, by B3 ticker) and 2 (held funds, by CNPJ). Give exactly one of p_cnpj (what this fund holds) or p_ticker (which funds hold this ticker). Rows are as filed; nothing is summed across application types.';

-- ---------------------------------------------------------------------------
-- Fund debenture holdings — CDA block 6, the fund → corporate-credit edge
-- ---------------------------------------------------------------------------
-- Block 6 is not a third p_kind of fund_holdings, on purpose. Blocks 4 and 2
-- identify what is held with one published column (a ticker, a CNPJ); a
-- debenture has no CD_ATIVO and its identity is (issuer, maturity, rate
-- structure) — two series of one issuer maturing the same day at different
-- coupons are different securities holding different money. Forcing that
-- into held_id/held_name would collapse them into indistinguishable rows,
-- which is a wrong number wearing a familiar shape. So it gets its own shape.
--
-- The issuer is the join. cpf_cnpj_emissor is the issuer's OWN CPF/CNPJ as
-- filed (block 6 publishes it; PF_PJ_EMISSOR says which), so "which funds
-- hold this issuer's paper" needs no bridge. p_issuer accepts a listed
-- company's ticker (resolved ONLY through CVM's published FCA map via
-- api.company_ref — never a name), a CVM code, or any CPF/CNPJ, listed or
-- not: most debenture issuers are not listed and a raw CNPJ is the honest way
-- to reach them. issuer_tickers carries the issuer's active listed codes when
-- it has any, from the same map — an array, because one issuer can have
-- PETR3 and PETR4 and picking one would be a guess.
--
-- cpf_cnpj_emissor is stored as published (text, unvalidated — a CPF issuer
-- is a real filing). The lookup matches BOTH the bare digits and CVM's
-- punctuated form through an IN list so the (cpf_cnpj_emissor, period) index
-- is used; a regexp on the column would scan every row a fund ever filed.
--
-- Rows are as filed and never summed: a fund files the same series under
-- several application types and trading intents (the fund_holdings rule).
--
-- Row cap (v41): raise-only on the one 1000-row page, exactly as
-- fund_holdings. Until v40 it was tiered 500 / 5000 and trimmed silently.

CREATE OR REPLACE FUNCTION api.fund_debentures(
    p_cnpj   TEXT DEFAULT NULL,   -- the HOLDER: what this fund holds
    p_issuer TEXT DEFAULT NULL,   -- the ISSUER: ticker / CVM code / CPF-CNPJ — which funds hold its paper
    p_from   DATE DEFAULT NULL,
    p_to     DATE DEFAULT NULL,
    p_limit  INT  DEFAULT NULL
)
RETURNS TABLE (
    cnpj               TEXT,
    period             DATE,
    issuer_id          TEXT,     -- the issuer's CPF/CNPJ, digits only
    issuer_kind        TEXT,     -- PF | PJ, as published
    issuer             TEXT,     -- issuer name, as published
    issuer_tickers     TEXT[],   -- active listed codes from the FCA map; NULL when not listed
    tp_aplic           TEXT,
    tp_ativo           TEXT,
    tp_negoc           TEXT,
    emissor_ligado     TEXT,
    maturity           DATE,
    indexer            TEXT,     -- cd_indexador_posfx: DI1, IPCA, …
    indexer_pct        NUMERIC,  -- % of the indexer
    coupon_pct         NUMERIC,  -- spread over it
    fixed_rate_pct     NUMERIC,  -- pre-fixed rate instead
    titulo_cetip       TEXT,
    qt_pos_final       NUMERIC,
    vl_merc_pos_final  NUMERIC,
    vl_custo_pos_final NUMERIC
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $fn$
DECLARE
    v_cnpj    TEXT := NULLIF(regexp_replace(COALESCE(p_cnpj, ''), '\D', '', 'g'), '');
    v_raw     TEXT := NULLIF(btrim(COALESCE(p_issuer, '')), '');
    v_digits  TEXT;
    v_forms   TEXT[];
    v_head    INT;
BEGIN
    IF (v_cnpj IS NULL) = (v_raw IS NULL) THEN
        RAISE EXCEPTION
            'fund_debentures needs exactly one of p_cnpj (what this fund holds) '
            'or p_issuer (which funds hold this issuer''s debentures); % were given',
            CASE WHEN v_cnpj IS NULL THEN 'neither' ELSE 'both' END
            USING ERRCODE = '22023';
    END IF;

    IF v_raw IS NOT NULL THEN
        v_digits := NULLIF(regexp_replace(v_raw, '\D', '', 'g'), '');
        IF v_digits IS NOT NULL AND length(v_digits) IN (11, 14) AND v_digits = regexp_replace(v_raw, '[.\-/ ]', '', 'g') THEN
            -- A CPF or CNPJ, listed or not: matched as given, no map needed.
            NULL;
        ELSE
            -- A ticker or CVM code: the published FCA map, active listings
            -- only, via the same resolver api.financials uses.
            SELECT r.cnpj INTO v_digits FROM api.company_ref(v_raw) r;
            IF v_digits IS NULL THEN
                RAISE EXCEPTION
                    'unknown issuer %: give a listed company''s ticker or CVM code (resolved through CVM''s published FCA map, active listings only) or the issuer''s CPF/CNPJ — most debenture issuers are not listed and only their CNPJ reaches them',
                    p_issuer
                    USING ERRCODE = '22023';
            END IF;
        END IF;
        -- Bare digits and CVM's punctuated spelling, so the index is used
        -- whichever way the block was published.
        v_forms := CASE length(v_digits)
            WHEN 14 THEN ARRAY[v_digits,
                               substr(v_digits,1,2)||'.'||substr(v_digits,3,3)||'.'||substr(v_digits,6,3)||'/'||substr(v_digits,9,4)||'-'||substr(v_digits,13,2)]
            WHEN 11 THEN ARRAY[v_digits,
                               substr(v_digits,1,3)||'.'||substr(v_digits,4,3)||'.'||substr(v_digits,7,3)||'-'||substr(v_digits,10,2)]
            ELSE ARRAY[v_digits]
        END;
    END IF;

    -- p_limit 1..1000 is an explicit head; NULL or above one page is the
    -- whole window, served whole or refused; below 1 is refused.
    IF p_limit IS NOT NULL AND p_limit < 1 THEN
        RAISE EXCEPTION
            '%: p_limit must be 1..1000 (the newest N rows, as an explicit request) or NULL for the whole window; got %',
            'fund_debentures', p_limit
            USING ERRCODE = '22023';
    END IF;
    v_head := CASE WHEN p_limit <= 1000 THEN p_limit END;

    RETURN QUERY
    -- One page + one (or the caller's explicit head), then assert_row_cap
    -- REFUSES (22023) instead of trimming. No cursor.
    WITH page (cnpj, period, issuer_id, issuer_kind, issuer, issuer_tickers,
               tp_aplic, tp_ativo, tp_negoc, emissor_ligado, maturity, indexer,
               indexer_pct, coupon_pct, fixed_rate_pct, titulo_cetip,
               qt_pos_final, vl_merc_pos_final, vl_custo_pos_final) AS (
    SELECT h.cnpj,
           h.period,
           regexp_replace(h.cpf_cnpj_emissor, '\D', '', 'g'),
           h.pf_pj_emissor,
           h.emissor,
           t.tickers,
           h.tp_aplic,
           h.tp_ativo,
           h.tp_negoc,
           h.emissor_ligado,
           h.dt_venc,
           h.cd_indexador_posfx,
           h.pr_indexador_posfx,
           h.pr_cupom_posfx,
           h.pr_taxa_prefx,
           h.titulo_cetip,
           h.qt_pos_final,
           h.vl_merc_pos_final,
           h.vl_custo_pos_final
    FROM public.cvm_fi_cda_debentures h
    LEFT JOIN LATERAL (
        SELECT array_agg(vt.codneg ORDER BY vt.codneg) AS tickers
        FROM public.vw_company_ticker vt
        WHERE vt.is_active
          AND vt.cnpj_cia = regexp_replace(h.cpf_cnpj_emissor, '\D', '', 'g')
    ) t ON TRUE
    WHERE (v_cnpj  IS NULL OR h.cnpj = v_cnpj)
      AND (v_forms IS NULL OR h.cpf_cnpj_emissor = ANY (v_forms))
      AND (p_from IS NULL OR h.period >= p_from)
      AND (p_to   IS NULL OR h.period <= p_to)
    ORDER BY h.period DESC, h.vl_merc_pos_final DESC NULLS LAST, h.dt_venc
    LIMIT COALESCE(v_head, 1001)
    )
    SELECT g.* FROM page g
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'fund_debentures')
    ORDER BY g.period DESC, g.vl_merc_pos_final DESC NULLS LAST, g.maturity
    LIMIT 1000;
END;
$fn$;

REVOKE ALL ON FUNCTION api.fund_debentures(TEXT, TEXT, DATE, DATE, INT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.fund_debentures(TEXT, TEXT, DATE, DATE, INT)
    TO anon, authenticated;

COMMENT ON FUNCTION api.fund_debentures(TEXT, TEXT, DATE, DATE, INT) IS
    'Fund debenture holdings from CDA block 6. Give exactly one of p_cnpj (what this fund holds) or p_issuer (which funds hold this issuer''s paper; a listed ticker/CVM code via the published FCA map, or any CPF/CNPJ). One row per (fund, month, issuer, maturity, rate structure, application type), as filed — never summed. issuer_tickers = the issuer''s active listed codes, NULL when not listed.';

-- ---------------------------------------------------------------------------
-- FIDC concentration — tabs I, VIII, II and X of the informe mensal (mig. 38)
-- ---------------------------------------------------------------------------
-- Three shapes, because the source has three:
--   fidc_cedentes   tab I's cedente slots — the fund → named-ORIGINATOR edge.
--                   The identifier is the cedente's own filed CPF/CNPJ (kept
--                   at ingest only when its check digits verify), so which
--                   funds buy from one originator is answerable by CNPJ with
--                   no name match; a listed originator is also reachable by
--                   ticker through the FCA map, like fund_debentures' issuer.
--                   share_pct is a percent OF THE BLOCK (A = risks retained by
--                   the originator, B = not), not of the fund.
--   fidc_sacados    tab VIII — the 25 largest DEBTORS as (rank, value), with
--                   no identity in the source. seq is CVM's rank as filed and
--                   is never recomputed here.
--   fidc_portfolio  tab II's sector hierarchy and tab X's SCR grade ladders,
--                   long: (kind, code, parent, item, value). The wide tables
--                   are the ingest shape; the long form is what a notebook
--                   pivots. `parent` is what keeps a caller from summing C
--                   and C1 together.
-- Row cap (v34, plan 2e): raise-only on the one 1000-row page, like
-- fidc_tranches. Until v33 these three were tiered 500 / 5000 like
-- fund_holdings and TRIMMED SILENTLY at the tier ceiling — a fund with more
-- rows than the ceiling came back short with a 200 and nothing to say so.
-- Now the page CTE fetches 1001 and api.assert_row_cap refuses above 1000
-- with a message that says why and how to narrow. p_limit survives as an
-- EXPLICIT newest-first head (1..1000): a caller who asks for the newest N
-- rows gets exactly that, because they asked; NULL (or anything above one
-- page) is the whole window, served whole or refused. p_limit < 1 is 22023,
-- no longer clamped to 1. Default windows are verbatim (an explicit range);
-- these tabs are members of the same monthly informe as cvm_fidc_mensal, so
-- coverage()'s fidc_* rows report their completeness.

CREATE OR REPLACE FUNCTION api.fidc_cedentes(
    p_cnpj    TEXT DEFAULT NULL,   -- the FUND: who it buys receivables from
    p_cedente TEXT DEFAULT NULL,   -- the ORIGINATOR: CPF/CNPJ, or a listed ticker / CVM code — which funds buy from it
    p_from    DATE DEFAULT NULL,
    p_to      DATE DEFAULT NULL,
    p_limit   INT  DEFAULT NULL
)
RETURNS TABLE (
    cnpj            TEXT,
    period          DATE,
    bloco           TEXT,     -- A = risks/benefits retained by the cedente; B = not
    seq             INT,      -- CVM's slot 1..9, as filed
    cedente_id      TEXT,     -- the originator's CPF/CNPJ, digits only, checksum-verified at ingest
    cedente_tickers TEXT[],   -- active listed codes from the FCA map; NULL when not listed
    share_pct       NUMERIC   -- percent of the block, as filed
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $fn$
DECLARE
    v_cnpj   TEXT := NULLIF(regexp_replace(COALESCE(p_cnpj, ''), '\D', '', 'g'), '');
    v_raw    TEXT := NULLIF(btrim(COALESCE(p_cedente, '')), '');
    v_digits TEXT;
    v_head   INT;   -- explicit newest-first head; NULL = the whole window
BEGIN
    IF (v_cnpj IS NULL) = (v_raw IS NULL) THEN
        RAISE EXCEPTION
            'fidc_cedentes needs exactly one of p_cnpj (which originators this fund buys from) '
            'or p_cedente (which funds buy from this originator); % were given',
            CASE WHEN v_cnpj IS NULL THEN 'neither' ELSE 'both' END
            USING ERRCODE = '22023';
    END IF;

    IF v_raw IS NOT NULL THEN
        v_digits := NULLIF(regexp_replace(v_raw, '\D', '', 'g'), '');
        IF v_digits IS NOT NULL AND length(v_digits) IN (11, 14) AND v_digits = regexp_replace(v_raw, '[.\-/ ]', '', 'g') THEN
            -- A CPF or CNPJ, listed or not: matched as given. The column
            -- holds digits only (ingest strips and verifies them), so no
            -- punctuated form is needed.
            NULL;
        ELSE
            -- A ticker or CVM code: the published FCA map, active listings
            -- only, via the same resolver api.financials uses.
            SELECT r.cnpj INTO v_digits FROM api.company_ref(v_raw) r;
            IF v_digits IS NULL THEN
                RAISE EXCEPTION
                    'unknown cedente %: give a listed company''s ticker or CVM code (resolved through CVM''s published FCA map, active listings only) or the originator''s CPF/CNPJ — most originators are not listed and only their CNPJ reaches them',
                    p_cedente
                    USING ERRCODE = '22023';
            END IF;
        END IF;
    END IF;

    -- p_limit 1..1000 is an explicit head the caller asked for. Above one
    -- page it cannot be served as a head, so it means the whole window and
    -- the page cap decides. Below 1 is a mistake, refused rather than clamped.
    IF p_limit IS NOT NULL AND p_limit < 1 THEN
        RAISE EXCEPTION
            '%: p_limit must be 1..1000 (the newest N rows, as an explicit request) or NULL for the whole window; got %',
            'fidc_cedentes', p_limit
            USING ERRCODE = '22023';
    END IF;
    v_head := CASE WHEN p_limit <= 1000 THEN p_limit END;

    RETURN QUERY
    -- One page + one (or the caller's explicit head), then assert_row_cap
    -- REFUSES (22023) instead of trimming. No cursor.
    WITH page (cnpj, period, bloco, seq, cedente_id, cedente_tickers, share_pct) AS (
    SELECT c.cnpj,
           c.period,
           c.bloco,
           c.seq,
           c.cpf_cnpj_cedente,
           t.tickers,
           c.pr_cedente
    FROM public.cvm_fidc_cedente c
    LEFT JOIN LATERAL (
        SELECT array_agg(vt.codneg ORDER BY vt.codneg) AS tickers
        FROM public.vw_company_ticker vt
        WHERE vt.is_active
          AND vt.cnpj_cia = c.cpf_cnpj_cedente
    ) t ON TRUE
    WHERE (v_cnpj   IS NULL OR c.cnpj = v_cnpj)
      AND (v_digits IS NULL OR c.cpf_cnpj_cedente = v_digits)
      AND (p_from IS NULL OR c.period >= p_from)
      AND (p_to   IS NULL OR c.period <= p_to)
    ORDER BY c.period DESC, c.cnpj, c.bloco, c.seq
    LIMIT COALESCE(v_head, 1001)
    )
    SELECT g.* FROM page g
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'fidc_cedentes')
    ORDER BY g.period DESC, g.cnpj, g.bloco, g.seq
    LIMIT 1000;
END;
$fn$;

REVOKE ALL ON FUNCTION api.fidc_cedentes(TEXT, TEXT, DATE, DATE, INT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.fidc_cedentes(TEXT, TEXT, DATE, DATE, INT)
    TO anon, authenticated;

COMMENT ON FUNCTION api.fidc_cedentes(TEXT, TEXT, DATE, DATE, INT) IS
    'FIDC named-originator concentration from informe tab I. Give exactly one of p_cnpj (which originators this fund buys from) or p_cedente (which funds buy from this originator: any CPF/CNPJ, or a listed ticker/CVM code via the published FCA map). One row per (fund, month, block, slot) as filed; share_pct is a percent of the BLOCK (A = risks retained by the cedente, B = not), never of the fund. cedente_id was checksum-verified at ingest; cedente_tickers = its active listed codes, NULL when not listed. share_pct is as filed and carries CVM''s percentage-field outliers (9% of slots above 100 in 2026-07) — range-check it, never read it as a fraction. Slots exist from 2019-11. More than 1000 rows RAISES 22023, never trimmed: narrow p_from/p_to (a p_cedente lookup spans many funds, so it needs fewer months than one fund) or ask for the newest N rows with p_limit (1..1000).';

CREATE OR REPLACE FUNCTION api.fidc_sacados(
    p_cnpj  TEXT,
    p_from  DATE DEFAULT NULL,
    p_to    DATE DEFAULT NULL,
    p_limit INT  DEFAULT NULL
)
RETURNS TABLE (
    cnpj   TEXT,
    period DATE,
    seq    INT,      -- CVM's rank 1..25, as filed, never recomputed
    valor  NUMERIC   -- exposure to that (anonymized) debtor
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $fn$
DECLARE
    v_cnpj  TEXT := NULLIF(regexp_replace(COALESCE(p_cnpj, ''), '\D', '', 'g'), '');
    v_head  INT;   -- explicit newest-first head; NULL = the whole window
BEGIN
    IF v_cnpj IS NULL THEN
        RAISE EXCEPTION
            'fidc_sacados needs p_cnpj: tab VIII publishes debtors as anonymized ranks, so there is no debtor-side lookup'
            USING ERRCODE = '22023';
    END IF;

    -- p_limit 1..1000 is an explicit head the caller asked for. Above one
    -- page it cannot be served as a head, so it means the whole window and
    -- the page cap decides. Below 1 is a mistake, refused rather than clamped.
    IF p_limit IS NOT NULL AND p_limit < 1 THEN
        RAISE EXCEPTION
            '%: p_limit must be 1..1000 (the newest N rows, as an explicit request) or NULL for the whole window; got %',
            'fidc_sacados', p_limit
            USING ERRCODE = '22023';
    END IF;
    v_head := CASE WHEN p_limit <= 1000 THEN p_limit END;

    RETURN QUERY
    -- One page + one (or the caller's explicit head), then assert_row_cap
    -- REFUSES (22023) instead of trimming. No cursor.
    WITH page (cnpj, period, seq, valor) AS (
        SELECT k.cnpj, k.period, k.seq, k.valor
        FROM public.cvm_fidc_sacado k
        WHERE k.cnpj = v_cnpj
          AND (p_from IS NULL OR k.period >= p_from)
          AND (p_to   IS NULL OR k.period <= p_to)
        ORDER BY k.period DESC, k.seq
        LIMIT COALESCE(v_head, 1001)
    )
    SELECT g.* FROM page g
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'fidc_sacados')
    ORDER BY g.period DESC, g.seq
    LIMIT 1000;
END;
$fn$;

REVOKE ALL ON FUNCTION api.fidc_sacados(TEXT, DATE, DATE, INT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.fidc_sacados(TEXT, DATE, DATE, INT)
    TO anon, authenticated;

COMMENT ON FUNCTION api.fidc_sacados(TEXT, DATE, DATE, INT) IS
    'The 25 largest debtors of one FIDC from informe tab VIII, as filed: (rank, value), no identity — CVM publishes the concentration anonymized and its dictionary describes neither column. seq is CVM''s rank and is never recomputed from valor; a fund that files fewer than 25 ranks has fewer rows. A concentration ratio is valor / receivables (panel metric) in the notebook. From 2013-01. More than 1000 rows RAISES 22023, never trimmed: narrow p_from/p_to or ask for the newest N rows with p_limit (1..1000).';

CREATE OR REPLACE FUNCTION api.fidc_portfolio(
    p_cnpj  TEXT,
    p_kind  TEXT DEFAULT NULL,   -- sector | scr_debtor | scr_operation | tax_debt; NULL = every kind
    p_from  DATE DEFAULT NULL,
    p_to    DATE DEFAULT NULL,
    p_limit INT  DEFAULT NULL
)
RETURNS TABLE (
    cnpj   TEXT,
    period DATE,
    kind   TEXT,
    code   TEXT,     -- sector: TOTAL, A..K, C1..I4 (CVM's item code); scr: AA..H; tax_debt: DEBITO_TRIBUT
    parent TEXT,     -- the lettered sector a numbered code belongs to; NULL at the top
    item   TEXT,     -- the column's own name, e.g. cred_corp, midmarket
    value  NUMERIC
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $fn$
DECLARE
    v_cnpj  TEXT := NULLIF(regexp_replace(COALESCE(p_cnpj, ''), '\D', '', 'g'), '');
    v_kind  TEXT := NULLIF(lower(btrim(COALESCE(p_kind, ''))), '');
    v_head  INT;   -- explicit newest-first head; NULL = the whole window
BEGIN
    IF v_cnpj IS NULL THEN
        RAISE EXCEPTION 'fidc_portfolio needs p_cnpj' USING ERRCODE = '22023';
    END IF;
    IF v_kind IS NOT NULL AND v_kind NOT IN ('sector', 'scr_debtor', 'scr_operation', 'tax_debt') THEN
        RAISE EXCEPTION
            'unknown p_kind %: one of sector (tab II), scr_debtor, scr_operation (tab X ladders), tax_debt, or NULL for all',
            p_kind
            USING ERRCODE = '22023';
    END IF;

    -- p_limit 1..1000 is an explicit head the caller asked for. Above one
    -- page it cannot be served as a head, so it means the whole window and
    -- the page cap decides. Below 1 is a mistake, refused rather than clamped.
    IF p_limit IS NOT NULL AND p_limit < 1 THEN
        RAISE EXCEPTION
            '%: p_limit must be 1..1000 (the newest N rows, as an explicit request) or NULL for the whole window; got %',
            'fidc_portfolio', p_limit
            USING ERRCODE = '22023';
    END IF;
    v_head := CASE WHEN p_limit <= 1000 THEN p_limit END;

    RETURN QUERY
    -- One page + one (or the caller's explicit head), then assert_row_cap
    -- REFUSES (22023) instead of trimming. No cursor.
    WITH page (cnpj, period, kind, code, parent, item, value) AS (
    SELECT u.cnpj, u.period, u.kind, u.code, u.parent, u.item, u.value
    FROM (
        SELECT s.cnpj, s.period, 'sector'::text AS kind, v.code, v.parent, v.item, v.value
        FROM public.cvm_fidc_setor s
        CROSS JOIN LATERAL (VALUES
            ('TOTAL', NULL, 'carteira',            s.vl_carteira),
            ('A',  NULL, 'indust',                 s.vl_a_indust),
            ('B',  NULL, 'imobil',                 s.vl_b_imobil),
            ('C',  NULL, 'comerc',                 s.vl_c_comerc),
            ('C1', 'C',  'comerc',                 s.vl_c1_comerc),
            ('C2', 'C',  'varejo',                 s.vl_c2_varejo),
            ('C3', 'C',  'arrend',                 s.vl_c3_arrend),
            ('D',  NULL, 'serv',                   s.vl_d_serv),
            ('D1', 'D',  'serv',                   s.vl_d1_serv),
            ('D2', 'D',  'serv_publico',           s.vl_d2_serv_publico),
            ('D3', 'D',  'serv_educ',              s.vl_d3_serv_educ),
            ('D4', 'D',  'entret',                 s.vl_d4_entret),
            ('E',  NULL, 'agroneg',                s.vl_e_agroneg),
            ('F',  NULL, 'financ',                 s.vl_f_financ),
            ('F1', 'F',  'cred_pessoa',            s.vl_f1_cred_pessoa),
            ('F2', 'F',  'cred_pessoa_consig',     s.vl_f2_cred_pessoa_consig),
            ('F3', 'F',  'cred_corp',              s.vl_f3_cred_corp),
            ('F4', 'F',  'midmarket',              s.vl_f4_midmarket),
            ('F5', 'F',  'veiculo',                s.vl_f5_veiculo),
            ('F6', 'F',  'imobil_empresa',         s.vl_f6_imobil_empresa),
            ('F7', 'F',  'imobil_resid',           s.vl_f7_imobil_resid),
            ('F8', 'F',  'outro',                  s.vl_f8_outro),
            ('G',  NULL, 'credito',                s.vl_g_credito),
            ('H',  NULL, 'factor',                 s.vl_h_factor),
            ('H1', 'H',  'pessoa',                 s.vl_h1_pessoa),
            ('H2', 'H',  'corp',                   s.vl_h2_corp),
            ('I',  NULL, 'setor_publico',          s.vl_i_setor_publico),
            ('I1', 'I',  'precat',                 s.vl_i1_precat),
            ('I2', 'I',  'tribut',                 s.vl_i2_tribut),
            ('I3', 'I',  'royalties',              s.vl_i3_royalties),
            ('I4', 'I',  'outro',                  s.vl_i4_outro),
            ('J',  NULL, 'judicial',               s.vl_j_judicial),
            ('K',  NULL, 'marca',                  s.vl_k_marca)
        ) AS v(code, parent, item, value)
        WHERE s.cnpj = v_cnpj
          AND (v_kind IS NULL OR v_kind = 'sector')
          AND (p_from IS NULL OR s.period >= p_from)
          AND (p_to   IS NULL OR s.period <= p_to)
        UNION ALL
        SELECT r.cnpj, r.period, v.kind, v.code, NULL::text, v.item, v.value
        FROM public.cvm_fidc_scr r
        CROSS JOIN LATERAL (VALUES
            ('scr_debtor',    'AA', 'devedor_aa',  r.vl_devedor_aa),
            ('scr_debtor',    'A',  'devedor_a',   r.vl_devedor_a),
            ('scr_debtor',    'B',  'devedor_b',   r.vl_devedor_b),
            ('scr_debtor',    'C',  'devedor_c',   r.vl_devedor_c),
            ('scr_debtor',    'D',  'devedor_d',   r.vl_devedor_d),
            ('scr_debtor',    'E',  'devedor_e',   r.vl_devedor_e),
            ('scr_debtor',    'F',  'devedor_f',   r.vl_devedor_f),
            ('scr_debtor',    'G',  'devedor_g',   r.vl_devedor_g),
            ('scr_debtor',    'H',  'devedor_h',   r.vl_devedor_h),
            ('scr_operation', 'AA', 'oper_aa',     r.vl_oper_aa),
            ('scr_operation', 'A',  'oper_a',      r.vl_oper_a),
            ('scr_operation', 'B',  'oper_b',      r.vl_oper_b),
            ('scr_operation', 'C',  'oper_c',      r.vl_oper_c),
            ('scr_operation', 'D',  'oper_d',      r.vl_oper_d),
            ('scr_operation', 'E',  'oper_e',      r.vl_oper_e),
            ('scr_operation', 'F',  'oper_f',      r.vl_oper_f),
            ('scr_operation', 'G',  'oper_g',      r.vl_oper_g),
            ('scr_operation', 'H',  'oper_h',      r.vl_oper_h),
            ('tax_debt',      'DEBITO_TRIBUT', 'debito_tribut', r.vl_debito_tribut)
        ) AS v(kind, code, item, value)
        WHERE r.cnpj = v_cnpj
          AND (v_kind IS NULL OR v_kind = v.kind)
          AND (p_from IS NULL OR r.period >= p_from)
          AND (p_to   IS NULL OR r.period <= p_to)
    ) u
    ORDER BY u.period DESC, u.kind, u.code
    LIMIT COALESCE(v_head, 1001)
    )
    SELECT g.* FROM page g
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'fidc_portfolio')
    ORDER BY g.period DESC, g.kind, g.code
    LIMIT 1000;
END;
$fn$;

REVOKE ALL ON FUNCTION api.fidc_portfolio(TEXT, TEXT, DATE, DATE, INT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.fidc_portfolio(TEXT, TEXT, DATE, DATE, INT)
    TO anon, authenticated;

COMMENT ON FUNCTION api.fidc_portfolio(TEXT, TEXT, DATE, DATE, INT) IS
    'One FIDC''s receivables book, long: kind=sector is informe tab II (TOTAL, the lettered sectors A..K, and their numbered members — `parent` names the letter a numbered code belongs to; sum leaves or parents, never both); kind=scr_debtor / scr_operation are tab X''s BACEN SCR grade ladders AA..H for the same receivables graded two ways; kind=tax_debt is TAB_X_DEBITO_TRIBUT. Values as filed. tab II from 2013-01; tab X from 2023-10 (earlier months have no scr rows, not zero-graded ones). An unknown p_kind raises 22023. More than 1000 rows RAISES 22023, never trimmed: narrow p_from/p_to, pin one p_kind, or ask for the newest N rows with p_limit (1..1000).';

-- ---------------------------------------------------------------------------
-- FIDC structure — tranches (tabs X_2/X_3/X_6 + X_4) and aging (tab VI)
-- ---------------------------------------------------------------------------
-- Two more members of the same monthly informe, read by /fidc since the start
-- and reachable by no caller until v31 (DATA_INVENTORY.md §3, backlog B3).
--
--   fidc_tranches  one row per (fund, month, tranche): quota count and value,
--                  the month's return, and the PROMISED vs REALISED
--                  performance CVM asks each series to file — all as filed.
--                  The tranche's subscriptions / redemptions / amortizations
--                  (tab X_4) ride along as a `flows` array keyed by CVM's own
--                  TAB_X_TP_OPER label. That label is free text whose
--                  vocabulary has drifted, so nothing here buckets it into
--                  "subscription" or "redemption": a label this file did not
--                  anticipate would silently vanish from a fixed column, and
--                  an array cannot lose one. A series that files flows but no
--                  tranche row still appears (tranche_filed = FALSE), so the
--                  two tabs are never inner-joined away.
--   fidc_aging     tab VI long: one row per (fund, month, bucket) —
--                  to_maturity (credits not yet due, by days to maturity),
--                  overdue (by days past due), and overdue_total, which is
--                  CVM's FILED total, never a sum of the buckets here.
--
-- HISTORY BEGINS IN 2013-01. These tabs are ingested from CVM's yearly HIST
-- archive through 2024-12 and from the monthly informe from 2025-01 (#556,
-- #569); the value columns have the same names in both. coverage()'s
-- fidc_tranches / fidc_aging rows say so.
--
-- Neither function derives anything: no performance gap, no subordination
-- ratio, no bucket sums. vw_fidc_tranche_detail / fidc_tranche_performance
-- (the dashboard's read) compute those on the same rows; a caller does the
-- arithmetic in the notebook, where it can see it. Percent fields are dirty
-- the way CVM's percentage fields are (filed magnitudes of 1e14 and more;
-- migration 70 made the columns unconstrained numeric) —
-- served as filed, never clipped, never nulled.
--
-- Row cap: one page + one, then api.assert_row_cap REFUSES (22023). No
-- cursor: a window over 1000 rows is narrowed by date or p_series, not
-- walked (the history now starts in 2013-01, so a long window can pass one page). Default window verbatim,
-- like the other fidc_* functions.

CREATE OR REPLACE FUNCTION api.fidc_tranches(
    p_cnpj   TEXT,
    p_from   DATE DEFAULT NULL,
    p_to     DATE DEFAULT NULL,
    p_series TEXT DEFAULT NULL    -- one TAB_X_CLASSE_SERIE, matched exactly as filed; NULL = every tranche
)
RETURNS TABLE (
    cnpj                 TEXT,
    period               DATE,
    classe_serie         TEXT,     -- CVM's tranche label, as filed (e.g. 'Subclasse Senior 1')
    quotas               NUMERIC,  -- TAB_X_QT_COTA
    quota_value          NUMERIC,  -- TAB_X_VL_COTA
    return_month         NUMERIC,  -- TAB_X_VL_RENTAB_MES, percent, as filed
    performance_expected NUMERIC,  -- TAB_X_PR_DESEMP_ESPERADO: what the series promised, percent
    performance_realised NUMERIC,  -- TAB_X_PR_DESEMP_REAL: what it delivered, percent
    tranche_filed        BOOLEAN,  -- FALSE = only tab X_4 flows exist for this series and month
    flows                JSONB     -- [{tp_oper, value, quotas}] from tab X_4, labels as filed; NULL = none filed
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $fn$
DECLARE
    v_cnpj   TEXT := NULLIF(regexp_replace(COALESCE(p_cnpj, ''), '\D', '', 'g'), '');
    v_series TEXT := NULLIF(btrim(COALESCE(p_series, '')), '');
BEGIN
    IF v_cnpj IS NULL THEN
        RAISE EXCEPTION
            'fidc_tranches needs p_cnpj: tranches are filed per fund (find one with search_funds or lookup)'
            USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    -- The key set is the UNION of both tabs, so a series filed in only one of
    -- them is still served rather than lost to an inner join.
    WITH keys AS (
        SELECT t.period, t.classe_serie
        FROM public.cvm_fidc_tranche t
        WHERE t.cnpj = v_cnpj
          AND (v_series IS NULL OR t.classe_serie = v_series)
          AND (p_from IS NULL OR t.period >= p_from)
          AND (p_to   IS NULL OR t.period <= p_to)
        UNION
        SELECT f.period, f.classe_serie
        FROM public.cvm_fidc_tranche_flows f
        WHERE f.cnpj = v_cnpj
          AND (v_series IS NULL OR f.classe_serie = v_series)
          AND (p_from IS NULL OR f.period >= p_from)
          AND (p_to   IS NULL OR f.period <= p_to)
    ),
    -- One page + one, then assert_row_cap REFUSES (22023). No cursor.
    page (cnpj, period, classe_serie, quotas, quota_value, return_month,
          performance_expected, performance_realised, tranche_filed, flows) AS (
        SELECT v_cnpj,
               k.period,
               k.classe_serie,
               t.qt_cota,
               t.vl_cota,
               t.vl_rentab_mes,
               t.pr_desemp_esperado,
               t.pr_desemp_real,
               (t.cnpj IS NOT NULL),
               fl.flows
        FROM keys k
        LEFT JOIN public.cvm_fidc_tranche t
               ON t.cnpj = v_cnpj
              AND t.period = k.period
              AND t.classe_serie = k.classe_serie
        LEFT JOIN LATERAL (
            -- jsonb_agg over zero rows is NULL: a tranche with no filed flows
            -- reads null, never an invented empty operation.
            SELECT jsonb_agg(
                       jsonb_build_object(
                           -- ingest stores a blank label as ''; served as null
                           'tp_oper', NULLIF(f.tp_oper, ''),
                           'value',   f.vl_total,
                           'quotas',  f.qt_cota
                       )
                       ORDER BY f.tp_oper
                   ) AS flows
            FROM public.cvm_fidc_tranche_flows f
            WHERE f.cnpj = v_cnpj
              AND f.period = k.period
              AND f.classe_serie = k.classe_serie
        ) fl ON TRUE
        ORDER BY 2, 3
        LIMIT 1001
    )
    SELECT g.* FROM page g
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'fidc_tranches')
    ORDER BY g.period, g.classe_serie
    LIMIT 1000;
END;
$fn$;

REVOKE ALL ON FUNCTION api.fidc_tranches(TEXT, DATE, DATE, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.fidc_tranches(TEXT, DATE, DATE, TEXT)
    TO anon, authenticated;

COMMENT ON FUNCTION api.fidc_tranches(TEXT, DATE, DATE, TEXT) IS
    'One FIDC''s tranches, month by month, oldest first: one row per (fund, month, classe_serie) from informe tabs X_2 / X_3 / X_6 — quotas, quota_value, return_month, and performance_expected vs performance_realised (what the series promised vs delivered, percent) — all AS FILED, with the dirty outliers CVM''s percentage fields carry (never clipped; range-check in the notebook). flows is the tranche''s tab X_4 operations as a JSON array [{tp_oper, value, quotas}], labels verbatim (e.g. Captações no Mês, Resgates no Mês, Amortizações) and never bucketed; NULL when none were filed. tranche_filed = FALSE marks a series with flows but no X_2 row. Nothing is derived: no performance gap, no subordination ratio. HISTORY BEGINS IN 2013-01: CVM''s yearly HIST archive through 2024-12, the monthly informe from 2025-01. p_series pins one tranche label exactly. More than 1000 rows RAISES 22023 (never trimmed): narrow the window.';

CREATE OR REPLACE FUNCTION api.fidc_aging(
    p_cnpj TEXT,
    p_from DATE DEFAULT NULL,
    p_to   DATE DEFAULT NULL
)
RETURNS TABLE (
    cnpj      TEXT,
    period    DATE,
    kind      TEXT,     -- to_maturity | overdue | overdue_total
    bucket    TEXT,     -- '1-30' .. '721-1080', '>1080'; 'TOTAL' on overdue_total
    days_from INT,      -- lower bound of the band, in days; NULL on overdue_total
    days_to   INT,      -- upper bound; NULL on '>1080' and on overdue_total
    item      TEXT,     -- the source column's own name, e.g. vl_inad_90
    value     NUMERIC   -- BRL, as filed
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $fn$
DECLARE
    v_cnpj TEXT := NULLIF(regexp_replace(COALESCE(p_cnpj, ''), '\D', '', 'g'), '');
BEGIN
    IF v_cnpj IS NULL THEN
        RAISE EXCEPTION
            'fidc_aging needs p_cnpj: the aging ladder is filed per fund (find one with search_funds or lookup)'
            USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    -- One page + one, then assert_row_cap REFUSES (22023). No cursor.
    WITH page (cnpj, period, kind, bucket, days_from, days_to, item, value, ord) AS (
        SELECT a.cnpj, a.period, v.kind, v.bucket, v.days_from, v.days_to, v.item, v.value, v.ord
        FROM public.cvm_fidc_aging a
        CROSS JOIN LATERAL (VALUES
            ( 1, 'to_maturity',   '1-30',      1,    30,   'vl_prazo_30',         a.vl_prazo_30),
            ( 2, 'to_maturity',   '31-60',     31,   60,   'vl_prazo_60',         a.vl_prazo_60),
            ( 3, 'to_maturity',   '61-90',     61,   90,   'vl_prazo_90',         a.vl_prazo_90),
            ( 4, 'to_maturity',   '91-120',    91,   120,  'vl_prazo_120',        a.vl_prazo_120),
            ( 5, 'to_maturity',   '121-150',   121,  150,  'vl_prazo_150',        a.vl_prazo_150),
            ( 6, 'to_maturity',   '151-180',   151,  180,  'vl_prazo_180',        a.vl_prazo_180),
            ( 7, 'to_maturity',   '181-360',   181,  360,  'vl_prazo_360',        a.vl_prazo_360),
            ( 8, 'to_maturity',   '361-720',   361,  720,  'vl_prazo_720',        a.vl_prazo_720),
            ( 9, 'to_maturity',   '721-1080',  721,  1080, 'vl_prazo_1080',       a.vl_prazo_1080),
            (10, 'to_maturity',   '>1080',     1081, NULL, 'vl_prazo_maior_1080', a.vl_prazo_maior_1080),
            (11, 'overdue',       '1-30',      1,    30,   'vl_inad_30',          a.vl_inad_30),
            (12, 'overdue',       '31-60',     31,   60,   'vl_inad_60',          a.vl_inad_60),
            (13, 'overdue',       '61-90',     61,   90,   'vl_inad_90',          a.vl_inad_90),
            (14, 'overdue',       '91-120',    91,   120,  'vl_inad_120',         a.vl_inad_120),
            (15, 'overdue',       '121-150',   121,  150,  'vl_inad_150',         a.vl_inad_150),
            (16, 'overdue',       '151-180',   151,  180,  'vl_inad_180',         a.vl_inad_180),
            (17, 'overdue',       '181-360',   181,  360,  'vl_inad_360',         a.vl_inad_360),
            (18, 'overdue',       '361-720',   361,  720,  'vl_inad_720',         a.vl_inad_720),
            (19, 'overdue',       '721-1080',  721,  1080, 'vl_inad_1080',        a.vl_inad_1080),
            (20, 'overdue',       '>1080',     1081, NULL, 'vl_inad_maior_1080',  a.vl_inad_maior_1080),
            -- CVM's own filed total (TAB_VI_B_VL_DIRCRED_INAD), NOT a sum of
            -- the ten overdue buckets above; the two can disagree as filed.
            (21, 'overdue_total', 'TOTAL',     NULL, NULL, 'vl_total_inad',       a.vl_total_inad)
        ) AS v(ord, kind, bucket, days_from, days_to, item, value)
        WHERE a.cnpj = v_cnpj
          AND (p_from IS NULL OR a.period >= p_from)
          AND (p_to   IS NULL OR a.period <= p_to)
        ORDER BY 2, 9
        LIMIT 1001
    )
    SELECT g.cnpj, g.period, g.kind, g.bucket, g.days_from, g.days_to, g.item, g.value
    FROM page g
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'fidc_aging')
    ORDER BY g.period, g.ord
    LIMIT 1000;
END;
$fn$;

REVOKE ALL ON FUNCTION api.fidc_aging(TEXT, DATE, DATE) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.fidc_aging(TEXT, DATE, DATE)
    TO anon, authenticated;

COMMENT ON FUNCTION api.fidc_aging(TEXT, DATE, DATE) IS
    'One FIDC''s receivables aging ladder from informe tab VI, long, oldest first: 21 rows per month — kind=to_maturity (credits not yet due, by days to maturity, ten bands 1-30 .. >1080), kind=overdue (by days past due, the same ten bands), and kind=overdue_total, CVM''s FILED total of overdue credits, which is not a sum of the buckets and can disagree with one. Values in BRL as filed; a blank in the filing is NULL, never 0. item names the source column. Tab VI covers the credits acquired WITHOUT substantial retention of risk by the originator (tab V, the with-risk twin, is not ingested). HISTORY BEGINS IN 2013-01: CVM''s yearly HIST archive through 2024-12, the monthly informe from 2025-01. The panel''s delinquency metric is the fund-level total; this is the ladder under it. More than 1000 rows RAISES 22023 (never trimmed): narrow the window.';

-- ---------------------------------------------------------------------------
-- ANBIMA class aggregates — the industry benchmark series, as published
-- ---------------------------------------------------------------------------
-- anbima_class_monthly is the "Boletim de Fundos de Investimento" read long:
-- one row per (reference_date, category, type, metric, level). Nothing in it
-- is per fund, and nothing in this warehouse maps a fund to its ANBIMA class
-- (CVM's `classe` is CVM's taxonomy, not ANBIMA's), so these rows are served
-- as what they are — industry aggregates — with no id, no panel arm and no
-- name join. Values are R$ milhões and percentage points AS PUBLISHED; `unit`
-- says which, read off the metric name the ingest assigned (brl_mm / pct /
-- count), never off the number.
--
-- `level` is part of the grain because Cambial, FIP and FIAGRO each appear
-- twice in one sheet: as the class aggregate and as an ANBIMA type of the
-- same name. The default serves class aggregates; p_level = 'type' serves the
-- types under a class, 'total' the industry total, NULL every level.
--
-- An unknown category, metric or level RAISES 22023 listing what exists. The
-- alternative — an empty array — is indistinguishable from "ANBIMA published
-- nothing", which is the same silent-miss the catalog warns about for panel
-- metrics. The lists are read from the table (tiny: ~10^4 rows), never
-- hard-coded, so a class ANBIMA adds is accepted the day it lands.
--
-- Default window: p_to NULL = the latest published edition. A boletim month
-- is complete by construction (it is a publication, not a filing cadence), so
-- there is no completeness clamp and coverage() reports both dates equal.

CREATE OR REPLACE FUNCTION api.anbima_classes(
    p_category TEXT DEFAULT NULL,        -- 'Renda Fixa', 'Ações', 'ETF', …; NULL = every class
    p_metric   TEXT DEFAULT NULL,        -- one boletim metric; NULL = every metric
    p_level    TEXT DEFAULT 'category',  -- 'category' | 'type' | 'total'; NULL = every level
    p_from     DATE DEFAULT '2019-01-01',
    p_to       DATE DEFAULT NULL         -- NULL = latest published edition
)
RETURNS TABLE (
    reference_date DATE,
    category       TEXT,
    type_id        INT,
    type_name      TEXT,
    level          TEXT,
    metric         TEXT,
    value          NUMERIC,
    unit           TEXT,
    boletim_ref    TEXT,
    source         TEXT
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $fn$
DECLARE
    v_known TEXT;
BEGIN
    IF p_level IS NOT NULL AND p_level NOT IN ('category', 'type', 'total') THEN
        RAISE EXCEPTION
            'p_level must be category (class aggregate), type (ANBIMA type) or total (industry total); got %',
            p_level
            USING ERRCODE = '22023';
    END IF;

    IF p_category IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM public.anbima_class_monthly a
        WHERE lower(a.anbima_category) = lower(btrim(p_category))
    ) THEN
        SELECT string_agg(DISTINCT a.anbima_category, ', ' ORDER BY a.anbima_category)
          INTO v_known FROM public.anbima_class_monthly a;
        RAISE EXCEPTION
            'unknown ANBIMA category %; the boletim publishes: %', p_category, COALESCE(v_known, '(none loaded)')
            USING ERRCODE = '22023';
    END IF;

    IF p_metric IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM public.anbima_class_monthly a WHERE a.metric = p_metric
    ) THEN
        SELECT string_agg(DISTINCT a.metric, ', ' ORDER BY a.metric)
          INTO v_known FROM public.anbima_class_monthly a;
        RAISE EXCEPTION
            'unknown metric %; anbima_classes serves: %', p_metric, COALESCE(v_known, '(none loaded)')
            USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    -- One page + one. The 1001st row is what makes "over the page"
    -- detectable; assert_row_cap then REFUSES (22023) rather than handing
    -- back a truncated series that looks complete. This function has no
    -- cursor, so a caller over the page narrows the window instead.
    -- The explicit column list lets the outer ORDER BY name columns as
    -- declared, which also dodges OUT-parameter ambiguity.
    WITH page (reference_date, category, type_id, type_name, level, metric, value, unit, boletim_ref, source) AS (
        SELECT a.reference_date,
               a.anbima_category,
               a.anbima_type_id,
               a.anbima_type_name,
               a.level,
               a.metric,
               a.value,
               CASE
                   WHEN a.metric LIKE '%\_brl\_mm' THEN 'brl_mm'
                   WHEN a.metric LIKE '%\_pct'     THEN 'pct'
                   WHEN a.metric = 'fund_count'     THEN 'count'
               END,
               a.boletim_ref,
               'anbima'::text
        FROM public.anbima_class_monthly a
        WHERE (p_category IS NULL OR lower(a.anbima_category) = lower(btrim(p_category)))
          AND (p_metric   IS NULL OR a.metric = p_metric)
          AND (p_level    IS NULL OR a.level  = p_level)
          AND a.reference_date >= p_from
          AND a.reference_date <= COALESCE(p_to, CURRENT_DATE)
        -- Positional inside the page; the outer ORDER BY names the
        -- declared columns.
        ORDER BY 1, 2, 4, 6
        LIMIT 1001
    )
    SELECT g.* FROM page g
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'anbima_classes')
    ORDER BY g.reference_date, g.category, g.type_name, g.metric
    LIMIT 1000;
END;
$fn$;

REVOKE ALL ON FUNCTION api.anbima_classes(TEXT, TEXT, TEXT, DATE, DATE) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.anbima_classes(TEXT, TEXT, TEXT, DATE, DATE) TO anon, authenticated;

COMMENT ON FUNCTION api.anbima_classes(TEXT, TEXT, TEXT, DATE, DATE) IS
    'ANBIMA Boletim de Fundos class series as published: AUM, net flows (month / YTD / 12m), returns (month / YTD / 12m) and fund counts per class, ANBIMA type or industry total (p_level). Industry aggregates — no fund is mapped to a class here, and there is no panel arm. Unknown category/metric/level raises 22023 listing what exists. Row cap: more than 1000 rows RAISES 22023 (never trimmed); narrow p_from/p_to or p_category.';

-- ---------------------------------------------------------------------------
-- inflation — IPCA headline, IPCA-15, the BCB cores, BCB's classifications
-- and IBGE's nine expenditure groups, from BACEN's SGS (bacen_sgs)
-- ---------------------------------------------------------------------------
-- Long: one row per (month, series). The registry of series is the VALUES
-- driver below and is the SAME list as INFLATION_SERIES in
-- src/pipeline/bacen_pipeline.py and the /macro dashboard sources;
-- tests/test_inflation_contract.py pins the three code sets to each other.
-- Only codes in the registry are served — bacen_sgs.series_name is an ingest
-- label, never trusted for naming here.
--
-- `value` is BACEN's number AS PUBLISHED, in percent: the change in the
-- month for everything except IPCA_12M (BACEN's own 12-month accumulation,
-- code 13522) and IPCA_DIFUSAO (the share of items that rose). `unit` says
-- which. Nothing is annualised or rebased.
--
-- `acc_12m` IS DERIVED, and is the one derived number in this function: the
-- trailing twelve monthly changes chained, ((Π(1 + v/100)) − 1) × 100,
-- rounded to BACEN's two decimals. It is NULL unless all twelve months are
-- present and consecutive — a gap yields NULL, never a shorter chain — and
-- NULL on the two series that are not monthly changes. The chain is the
-- index identity, not a model: measured 2026-09-21, chaining 433 reproduces
-- 13522 exactly (4.22 for 2026-08), and 13522 is still served as published
-- so a caller can reconcile the two.
--
-- THE GROUP CODES ARE NOT IN IBGE'S ORDER. 1640 is Comunicação (IBGE group
-- 9), 1641 Saúde (6), 1642 Despesas pessoais (7), 1643 Educação (8) —
-- matched value for value against IBGE SIDRA 7060 on 2026-06, -07 and -08.
-- Group rows are VARIATIONS; the weights, and therefore contributions, are
-- api.inflation_items (IBGE), never a sum of these.
--
-- Default window: the last 36 months (26 series × 36 = 936 rows, under the
-- page). p_from before that must come with p_series or p_family, or the row
-- cap refuses. IPCA runs from 1980-01, the cores and groups from 1991-01,
-- IPCA-15 from 2000-05; earlier dates return what exists.

CREATE OR REPLACE FUNCTION api.inflation(
    p_series TEXT DEFAULT NULL,   -- one series label (IPCA, IPCA_CORE_EX0, IPCA_G_HABITACAO, …); NULL = all
    p_family TEXT DEFAULT NULL,   -- headline | core | classification | diffusion | group; NULL = all
    p_from   DATE DEFAULT NULL,   -- NULL = 36 months before the current month
    p_to     DATE DEFAULT NULL    -- NULL = today
)
RETURNS TABLE (
    reference_date DATE,
    series         TEXT,
    family         TEXT,
    sgs_code       INT,
    value          NUMERIC,
    acc_12m        NUMERIC,
    unit           TEXT,
    source         TEXT
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $fn$
DECLARE
    v_series TEXT := upper(btrim(p_series));
    v_from   DATE := COALESCE(p_from, (date_trunc('month', CURRENT_DATE) - interval '36 months')::date);
    v_known  TEXT;
BEGIN
    IF p_family IS NOT NULL AND p_family NOT IN ('headline', 'core', 'classification', 'diffusion', 'group') THEN
        RAISE EXCEPTION
            'p_family must be headline, core, classification, diffusion or group; got %',
            p_family
            USING ERRCODE = '22023';
    END IF;

    IF v_series IS NOT NULL AND v_series NOT IN (
        SELECT reg.series FROM api.inflation_registry() reg
    ) THEN
        SELECT string_agg(reg.series, ', ' ORDER BY reg.family, reg.series)
          INTO v_known FROM api.inflation_registry() reg;
        RAISE EXCEPTION
            'unknown inflation series %; inflation serves: %', p_series, v_known
            USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    -- One page + one, then assert_row_cap REFUSES (22023) rather than
    -- trimming. No cursor: narrow p_from/p_to, or pin p_series / p_family.
    WITH obs AS (
        -- The 12-month chain is computed over the WHOLE history of each
        -- series, before the window filter, so a window that starts today
        -- still sees its trailing year.
        SELECT reg.series, reg.family, reg.sgs_code, reg.unit,
               b.reference_date, b.value,
               CASE
                   WHEN reg.unit = 'pct_month'
                    AND count(b.value) OVER w = 12
                    AND min(b.reference_date) OVER w = (b.reference_date - interval '11 months')::date
                    AND min(1 + b.value / 100) OVER w > 0
                   THEN round((exp(sum(ln(1 + b.value / 100)) OVER w) - 1) * 100, 2)
               END AS acc_12m
        FROM api.inflation_registry() reg
        JOIN public.bacen_sgs b ON b.series_code = reg.sgs_code
        WINDOW w AS (PARTITION BY reg.sgs_code ORDER BY b.reference_date
                     ROWS BETWEEN 11 PRECEDING AND CURRENT ROW)
    ),
    page (reference_date, series, family, sgs_code, value, acc_12m, unit, source) AS (
        SELECT o.reference_date, o.series, o.family, o.sgs_code, o.value, o.acc_12m, o.unit,
               'bacen_sgs'::text
        FROM obs o
        WHERE (v_series IS NULL OR o.series = v_series)
          AND (p_family IS NULL OR o.family = p_family)
          AND o.reference_date >= v_from
          AND o.reference_date <= COALESCE(p_to, CURRENT_DATE)
        ORDER BY 1, 3, 2
        LIMIT 1001
    )
    SELECT g.* FROM page g
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'inflation')
    ORDER BY g.reference_date, g.family, g.series
    LIMIT 1000;
END;
$fn$;

REVOKE ALL ON FUNCTION api.inflation(TEXT, TEXT, DATE, DATE) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.inflation(TEXT, TEXT, DATE, DATE) TO anon, authenticated;

COMMENT ON FUNCTION api.inflation(TEXT, TEXT, DATE, DATE) IS
    'IPCA as BACEN publishes it, long, one row per (month, series): headline (IPCA, IPCA_12M = BACEN''s own 12-month accumulation, IPCA15), the BCB cores (MS, MA, EX0, EX2, DP), BCB''s classifications (monitorados / livres, comercializáveis / não, duráveis / semi / não / serviços), the diffusion index and IBGE''s nine expenditure groups. value is the change in the month in percent (unit pct_month) except IPCA_12M (pct_12m) and IPCA_DIFUSAO (pct_items). acc_12m is DERIVED — the trailing twelve monthly changes chained, NULL unless all twelve are present and consecutive; it reproduces 13522 exactly for the headline. Group rows are variations, not contributions — weights are api.inflation_items. Unknown series/family raises 22023 listing what exists. Default window 36 months; more than 1000 rows RAISES 22023 (never trimmed): narrow the window or pin p_series / p_family.';

-- The registry, as a function so api.inflation and its validation read ONE
-- list. Internal (no client grant): it carries no data, only labels.
CREATE OR REPLACE FUNCTION api.inflation_registry()
RETURNS TABLE (series TEXT, family TEXT, sgs_code INT, unit TEXT)
LANGUAGE sql
IMMUTABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    SELECT * FROM (VALUES
        ('IPCA',                      'headline',       433,   'pct_month'),
        ('IPCA_12M',                  'headline',       13522, 'pct_12m'),
        ('IPCA15',                    'headline',       7478,  'pct_month'),
        ('IPCA_CORE_MS',              'core',           4466,  'pct_month'),
        ('IPCA_CORE_MA',              'core',           11426, 'pct_month'),
        ('IPCA_CORE_EX0',             'core',           11427, 'pct_month'),
        ('IPCA_CORE_EX2',             'core',           16121, 'pct_month'),
        ('IPCA_CORE_DP',              'core',           16122, 'pct_month'),
        ('IPCA_MONITORADOS',          'classification', 4449,  'pct_month'),
        ('IPCA_LIVRES',               'classification', 11428, 'pct_month'),
        ('IPCA_COMERCIALIZAVEIS',     'classification', 4447,  'pct_month'),
        ('IPCA_NAO_COMERCIALIZAVEIS', 'classification', 4448,  'pct_month'),
        ('IPCA_NAO_DURAVEIS',         'classification', 10841, 'pct_month'),
        ('IPCA_SEMI_DURAVEIS',        'classification', 10842, 'pct_month'),
        ('IPCA_DURAVEIS',             'classification', 10843, 'pct_month'),
        ('IPCA_SERVICOS',             'classification', 10844, 'pct_month'),
        ('IPCA_DIFUSAO',              'diffusion',      21379, 'pct_items'),
        ('IPCA_G_ALIMENTACAO',        'group',          1635,  'pct_month'),
        ('IPCA_G_HABITACAO',          'group',          1636,  'pct_month'),
        ('IPCA_G_ARTIGOS_RESIDENCIA', 'group',          1637,  'pct_month'),
        ('IPCA_G_VESTUARIO',          'group',          1638,  'pct_month'),
        ('IPCA_G_TRANSPORTES',        'group',          1639,  'pct_month'),
        ('IPCA_G_COMUNICACAO',        'group',          1640,  'pct_month'),
        ('IPCA_G_SAUDE',              'group',          1641,  'pct_month'),
        ('IPCA_G_DESPESAS_PESSOAIS',  'group',          1642,  'pct_month'),
        ('IPCA_G_EDUCACAO',           'group',          1643,  'pct_month')
    ) AS r(series, family, sgs_code, unit);
$$;

REVOKE ALL ON FUNCTION api.inflation_registry() FROM PUBLIC;

COMMENT ON FUNCTION api.inflation_registry() IS
    'Internal. The series api.inflation serves — label, family, SGS code, unit — as one list, mirrored from INFLATION_SERIES in src/pipeline/bacen_pipeline.py. Group codes 1640..1643 are Comunicação, Saúde, Despesas pessoais, Educação (measured against IBGE SIDRA, not IBGE''s order).';

-- ---------------------------------------------------------------------------
-- inflation_items — the IPCA item tree with weights and contributions,
-- from IBGE SIDRA (ibge_ipca_item_monthly)
-- ---------------------------------------------------------------------------
-- What moves the index. IBGE publishes, per month and per node of the IPCA
-- tree (general index; 9 groups; 19 subgroups; 51 items; ~377 subitems),
-- the change in the month, the WEIGHT in the basket, the year-to-date and
-- the 12-month change — all four as published, in percent.
--
-- `contribution` is the one derived column: weight × change_month / 100,
-- in percentage points of the headline, rounded to four decimals, NULL when
-- either input is NULL. Summing the nine level-1 contributions reproduces
-- the headline to rounding (the groups partition the basket). Sum ONE level
-- at a time: a group and its subgroups are the same money twice.
--
-- `parent_number` is read off IBGE's own structure number ('1101002' sits
-- under item '1101', subgroup '11', group '1') — deterministic, not
-- inferred. `item_code` is SIDRA's c315 code and CHANGED with the 2020-01
-- structure (table 7060 replaced 1419); `item_number` and names are IBGE's
-- continuity, and sidra_table says which structure a row came from.
--
-- Default: level 1 (the nine groups plus nothing else), last 36 months
-- (9 × 36 = 324 rows). Deeper levels are larger — level 4 is ~377 rows a
-- month — so pin p_item or narrow the window; the row cap refuses above a
-- page rather than trimming. History starts 2012-01 (SIDRA 1419); for the
-- group VARIATIONS before that, api.inflation (BACEN) goes back to 1991.

CREATE OR REPLACE FUNCTION api.inflation_items(
    p_level INT  DEFAULT 1,      -- 0 general index | 1 group | 2 subgroup | 3 item | 4 subitem; NULL = every level
    p_item  TEXT DEFAULT NULL,   -- IBGE structure number ('1', '11', '1101', '1101002') or SIDRA item code ('7170'); NULL = all
    p_from  DATE DEFAULT NULL,   -- NULL = 36 months before the current month
    p_to    DATE DEFAULT NULL    -- NULL = today
)
RETURNS TABLE (
    reference_month DATE,
    item_code       INT,
    item_number     TEXT,
    item_name       TEXT,
    level           SMALLINT,
    parent_number   TEXT,
    weight          NUMERIC,
    change_month    NUMERIC,
    contribution    NUMERIC,
    change_ytd      NUMERIC,
    change_12m      NUMERIC,
    sidra_table     INT,
    source          TEXT
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $fn$
DECLARE
    v_item TEXT := btrim(p_item);
    v_from DATE := COALESCE(p_from, (date_trunc('month', CURRENT_DATE) - interval '36 months')::date);
BEGIN
    IF p_level IS NOT NULL AND p_level NOT BETWEEN 0 AND 4 THEN
        RAISE EXCEPTION
            'p_level must be 0 (general index), 1 (group), 2 (subgroup), 3 (item) or 4 (subitem); got %',
            p_level
            USING ERRCODE = '22023';
    END IF;

    IF v_item IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM public.ibge_ipca_item_monthly i
        WHERE i.item_number = v_item OR i.item_code::text = v_item
    ) THEN
        RAISE EXCEPTION
            'unknown IPCA item %; p_item is IBGE''s structure number (1..9 for the groups, e.g. 1101002 for a subitem) or SIDRA''s item code — list a level with p_level to see them',
            p_item
            USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    -- One page + one, then assert_row_cap REFUSES (22023). No cursor.
    WITH page (reference_month, item_code, item_number, item_name, level, parent_number,
               weight, change_month, contribution, change_ytd, change_12m, sidra_table, source) AS (
        SELECT i.reference_month,
               i.item_code,
               i.item_number,
               i.item_name,
               i.level,
               CASE i.level
                   WHEN 2 THEN left(i.item_number, 1)
                   WHEN 3 THEN left(i.item_number, 2)
                   WHEN 4 THEN left(i.item_number, 4)
               END,
               i.peso_mensal,
               i.variacao_mensal,
               CASE WHEN i.peso_mensal IS NOT NULL AND i.variacao_mensal IS NOT NULL
                    THEN round(i.peso_mensal * i.variacao_mensal / 100, 4)
               END,
               i.variacao_acum_ano,
               i.variacao_acum_12m,
               i.sidra_table,
               'ibge_sidra'::text
        FROM public.ibge_ipca_item_monthly i
        WHERE (p_level IS NULL OR i.level = p_level)
          AND (v_item IS NULL OR i.item_number = v_item OR i.item_code::text = v_item)
          AND i.reference_month >= v_from
          AND i.reference_month <= COALESCE(p_to, CURRENT_DATE)
        ORDER BY 1, 5, 3 NULLS FIRST, 2
        LIMIT 1001
    )
    SELECT g.* FROM page g
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'inflation_items')
    ORDER BY g.reference_month, g.level, g.item_number NULLS FIRST, g.item_code
    LIMIT 1000;
END;
$fn$;

REVOKE ALL ON FUNCTION api.inflation_items(INT, TEXT, DATE, DATE) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.inflation_items(INT, TEXT, DATE, DATE) TO anon, authenticated;

COMMENT ON FUNCTION api.inflation_items(INT, TEXT, DATE, DATE) IS
    'The IPCA item tree from IBGE SIDRA (tables 1419 from 2012-01, 7060 from 2020-01), one row per (month, node): weight in the basket, change in the month, year-to-date and 12-month change AS PUBLISHED (percent), plus contribution = weight × change_month / 100 in percentage points of the headline (the one derived column; NULL when either input is NULL). Levels: 0 general index, 1 the nine groups (default), 2 subgroups, 3 items, 4 subitems. Sum contributions within ONE level only — a group and its subgroups are the same money twice. parent_number is read off IBGE''s structure number. item_code changed with the 2020-01 structure (sidra_table says which); item_number is the continuity. Unknown level/item raises 22023. Default window 36 months; more than 1000 rows RAISES 22023 (never trimmed): narrow the window or pin p_item.';

-- FII property register snapshots. CVM publishes no stable property identifier;
-- id is the stored source-row hash and duplicates at the same filing date are
-- retained. Nullable measurements remain NULL (never converted to zero).
CREATE OR REPLACE FUNCTION api.fii_property_history(
    p_cnpj TEXT,
    p_from DATE DEFAULT (CURRENT_DATE - 1825),
    p_to DATE DEFAULT CURRENT_DATE
)
RETURNS TABLE (
    cnpj TEXT, reference_date DATE, period_year INT, version INT,
    row_hash TEXT, property_class TEXT, property_name TEXT, address TEXT,
    area NUMERIC, units INT, other_characteristics TEXT,
    vacancy_pct NUMERIC, delinquency_pct NUMERIC, revenue_pct NUMERIC,
    rented_pct NUMERIC, sold_pct NUMERIC,
    development_completed_pct NUMERIC, development_expected_pct NUMERIC,
    construction_cost_completed NUMERIC, construction_cost_expected NUMERIC,
    property_total_invested_pct NUMERIC, source TEXT
)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = ''
AS $fn$
BEGIN
    IF p_cnpj IS NULL OR p_cnpj !~ '^[0-9]{14}$' THEN
        RAISE EXCEPTION 'p_cnpj must be a 14-digit FII CNPJ' USING ERRCODE = '22023';
    END IF;
    RETURN QUERY
    WITH page AS (
        SELECT i.cnpj, i.data_referencia, i.period_year, i.versao, i.row_hash,
               i.classe, i.nome_imovel, i.endereco, i.area, i.numero_unidades,
               i.outras_caracteristicas, i.pr_vacancia, i.pr_inadimplencia,
               i.pr_receitas_fii, i.pr_locado, i.pr_vendido,
               i.pr_conclusao_obras_realizado, i.pr_conclusao_obras_previsto,
               i.custo_construcao_realizado, i.custo_construcao_previsto,
               i.pr_imovel_total_investido, 'cvm'::text
        FROM public.cvm_fii_imovel i
        WHERE i.cnpj = p_cnpj
          AND i.data_referencia BETWEEN COALESCE(p_from, CURRENT_DATE - 1825)
                                    AND COALESCE(p_to, CURRENT_DATE)
        ORDER BY i.data_referencia DESC, i.versao DESC NULLS LAST, i.row_hash
        LIMIT 1001
    )
    SELECT page.* FROM page
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'fii_property_history')
    ORDER BY page.data_referencia DESC, page.versao DESC NULLS LAST, page.row_hash
    LIMIT 1000;
END;
$fn$;
REVOKE ALL ON FUNCTION api.fii_property_history(TEXT, DATE, DATE) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.fii_property_history(TEXT, DATE, DATE) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION api.fii_property_history(TEXT, DATE, DATE) TO silo_api;
COMMENT ON FUNCTION api.fii_property_history(TEXT, DATE, DATE) IS
    'CVM FII property-register snapshots, one row per stored source row and reference date. p_cnpj is the exact fund CNPJ. CVM publishes no stable property identifier; row_hash identifies the exact source row only. area and financial/progress fields preserve CVM nulls, not zero. Vacancy, delinquency and other pr_* fields are published percentages; source is cvm. Default date window is five years; more than 1,000 rows raises SQLSTATE 22023 rather than truncating.';

-- Weekly Focus expectation path: successive survey dates are the revisions
-- analysts compare. This does not claim to preserve corrected vintages of an
-- old survey date; the landing table upserts those on its natural key.
CREATE OR REPLACE FUNCTION api.focus_expectations(
    p_endpoint  TEXT,
    p_horizon   TEXT,
    p_indicator TEXT DEFAULT NULL,
    p_from      DATE DEFAULT (CURRENT_DATE - 1825),
    p_to        DATE DEFAULT CURRENT_DATE
)
RETURNS TABLE (
    endpoint_name TEXT, indicator TEXT, survey_date DATE, horizon TEXT,
    median NUMERIC, mean_value NUMERIC, std_dev NUMERIC,
    sample_basis TEXT, smoothing TEXT, source TEXT
)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = ''
AS $fn$
BEGIN
    IF p_endpoint IS NULL OR p_endpoint NOT IN (
        'ExpectativasMercadoAnuais', 'ExpectativaMercadoMensais',
        'ExpectativasMercadoSelic', 'ExpectativasMercadoInflacao12Meses'
    ) THEN
        RAISE EXCEPTION 'unsupported Focus endpoint: %', p_endpoint USING ERRCODE = '22023';
    END IF;
    IF p_horizon IS NULL OR btrim(p_horizon) = '' THEN
        RAISE EXCEPTION 'p_horizon is required and uses CVM/BACEN DataReferencia format' USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    WITH page AS (
        SELECT e.endpoint_name, e.indicador, e.reference_date, e.horizon,
               e.median, e.mean_val,
               e.std_dev,
               'baseCalculo=0 (trailing 30-day sample)'::text,
               CASE WHEN e.endpoint_name = 'ExpectativasMercadoInflacao12Meses'
                    THEN 'N'::text END,
               'bacen_expectativas'::text
        FROM public.bacen_expectativas e
        WHERE e.endpoint_name = p_endpoint
          AND e.horizon = btrim(p_horizon)
          AND (p_indicator IS NULL OR e.indicador = btrim(p_indicator))
          AND e.reference_date BETWEEN COALESCE(p_from, CURRENT_DATE - 1825)
                                   AND COALESCE(p_to, CURRENT_DATE)
          AND e.raw ->> 'baseCalculo' = '0'
          AND (e.endpoint_name <> 'ExpectativasMercadoInflacao12Meses'
               OR e.raw ->> 'Suavizada' = 'N')
        ORDER BY e.reference_date DESC, e.indicador NULLS FIRST
        LIMIT 1001
    )
    SELECT page.* FROM page
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'focus_expectations')
    ORDER BY page.reference_date, page.indicador NULLS FIRST
    LIMIT 1000;
END;
$fn$;
REVOKE ALL ON FUNCTION api.focus_expectations(TEXT, TEXT, TEXT, DATE, DATE) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.focus_expectations(TEXT, TEXT, TEXT, DATE, DATE) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION api.focus_expectations(TEXT, TEXT, TEXT, DATE, DATE) TO silo_api;
COMMENT ON FUNCTION api.focus_expectations(TEXT, TEXT, TEXT, DATE, DATE) IS
    'BCB Focus expectations across survey dates for one required endpoint and horizon, optionally filtered by indicator. Each survey_date is one published survey observation; successive dates form the weekly revision path. Returns median, mean and standard deviation for baseCalculo=0 (trailing 30-day respondent sample); the 12-month inflation endpoint is unsmoothed (Suavizada=N). Horizon preserves DataReferencia exactly (annual year or monthly month/year). source identifies bacen_expectativas. Default date window is five years; more than 1,000 rows raises SQLSTATE 22023. This is not a vintage archive of later corrections to an old survey date. Migration 16 repaired the key but earlier collapsed horizons are not recovered until re-fetched.';

-- ---------------------------------------------------------------------------
-- Coverage — freshness without exposing cvm_ingest_log
-- ---------------------------------------------------------------------------

-- Signature change (complete_through column, per-family rows, notes): drop first.
DROP FUNCTION IF EXISTS api.coverage();

-- Signature change (trailing newest_period, landed_at): drop the old shape.
DROP FUNCTION IF EXISTS api.coverage();

CREATE OR REPLACE FUNCTION api.coverage()
RETURNS TABLE (
    dataset          TEXT,
    as_of            DATE,
    complete_through DATE,
    source           TEXT,
    notes            TEXT,
    newest_period    DATE,
    landed_at        TIMESTAMPTZ,
    landed_git_sha   TEXT
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    -- THREE different questions, which one date used to answer wrongly:
    --   as_of            the newest period that has landed AND has actually
    --                    elapsed -- "data exists through here".
    --   complete_through the newest period classified COMPLETE by
    --                    mv_period_completeness -- what default windows serve.
    --   newest_period    the newest period KEY present, which can be in the
    --                    future, and landed_at, the wall-clock time ingest
    --                    last succeeded for the source.
    --
    -- as_of is bounded by CURRENT_DATE because a period key is not a
    -- statement about elapsed time. FIP files annually and is keyed to
    -- 31-December, so a row filed in March carries period 2026-12-31 and the
    -- blended MAX(last_period) read 2026-12-31 while it was still September --
    -- an agent reading as_of as freshness believed it had Q4. It is not a
    -- fabricated row: the key is CVM's. It is a grain collision, so the fix
    -- publishes both numbers instead of picking one. Measured 2026-09-16:
    -- production coverage() reported funds.as_of = 2026-12-31.
    --
    -- landed_at comes from cvm_ingest_log rows with status='ok' AND a
    -- finished_at: a run still in flight has not landed, and a later FAILED
    -- run must not advance the date (that would report a failure as freshness).
    --
    -- landed_git_sha (v34, lineage, migration 44) is the git_sha OF THAT SAME
    -- RUN — the commit whose code produced the newest landed data, read off
    -- the row that sets landed_at (newest finished_at, id breaking a tie), not
    -- the newest non-null sha. NULL when that run recorded none: a run from
    -- before migration 44, or one started outside GitHub Actions with no
    -- GITHUB_SHA. It is never borrowed from an older run, because an older
    -- run's commit did not produce the newest data.
    --
    -- notes = a caveat the dates cannot carry: a regime boundary where the
    -- series changes meaning mid-stream, or where the columns are per family.
    -- NULL on every row that has none.
    --
    -- HOW EACH DATE IS READ. Every period arm is a scalar subquery of the form
    -- (SELECT MAX(col) FROM t WHERE col <= CURRENT_DATE): with an index on
    -- col that is one backward index probe. The earlier form,
    -- MAX(col) FILTER (WHERE col <= CURRENT_DATE) over FROM t, is an ordinary
    -- aggregate the planner cannot turn into a probe, so it scanned the whole
    -- table — twice per arm, once bounded and once not — and the fund and
    -- lending arms alone (fact_fund_monthly, b3_lending_trade) put the call at
    -- 2.8-3.8 s on production on 2026-09-26, against anon's 3 s statement
    -- timeout: the bootstrap call every agent is told to make first failed
    -- about half the time. Same dates, same rows, same order.
    WITH landed AS (
        SELECT l.entity, MAX(l.finished_at) AS landed_at,
               (array_agg(l.git_sha ORDER BY l.finished_at DESC, l.id DESC))[1] AS landed_git_sha
        FROM public.cvm_ingest_log l
        WHERE l.status = 'ok' AND l.finished_at IS NOT NULL
        GROUP BY l.entity
        UNION ALL
        -- The blended fund rows below span the five families.
        SELECT '*funds*'::text, MAX(l.finished_at),
               (array_agg(l.git_sha ORDER BY l.finished_at DESC, l.id DESC))[1]
        FROM public.cvm_ingest_log l
        WHERE l.status = 'ok' AND l.finished_at IS NOT NULL
          AND l.entity IN ('fi', 'fidc', 'fii', 'fip', 'fiagro')
        UNION ALL
        -- The B3 BDI group logs under entity 'b3', the SAME entity as COTAHIST,
        -- so the plain per-entity row above would report a cotahist run as the
        -- lending group's freshness. For a RATCHET that matters more than
        -- anywhere else in this function: these tables age out of the source in
        -- ~21 business days, so "when did this specific ingest last succeed" is
        -- the question, and a blended b3 timestamp answers a different one.
        -- Split by doc_type, which is what each ingest actually writes.
        SELECT '*b3_lending_balance*'::text, MAX(l.finished_at),
               (array_agg(l.git_sha ORDER BY l.finished_at DESC, l.id DESC))[1]
        FROM public.cvm_ingest_log l
        WHERE l.status = 'ok' AND l.finished_at IS NOT NULL
          AND l.entity = 'b3'
          AND l.doc_type IN ('lending_open_position', 'lending_rate')
        UNION ALL
        SELECT '*b3_lending_trade*'::text, MAX(l.finished_at),
               (array_agg(l.git_sha ORDER BY l.finished_at DESC, l.id DESC))[1]
        FROM public.cvm_ingest_log l
        WHERE l.status = 'ok' AND l.finished_at IS NOT NULL
          AND l.entity = 'b3' AND l.doc_type = 'lending_trade'
        UNION ALL
        SELECT '*b3_investor_flow*'::text, MAX(l.finished_at),
               (array_agg(l.git_sha ORDER BY l.finished_at DESC, l.id DESC))[1]
        FROM public.cvm_ingest_log l
        WHERE l.status = 'ok' AND l.finished_at IS NOT NULL
          AND l.entity = 'b3' AND l.doc_type = 'investor_participation'
        UNION ALL
        -- BACEN logs three doc_types under one entity (sgs, ptax,
        -- expectativas); the inflation row must not report a PTAX success as
        -- the SGS series' freshness.
        SELECT '*bacen_sgs*'::text, MAX(l.finished_at),
               (array_agg(l.git_sha ORDER BY l.finished_at DESC, l.id DESC))[1]
        FROM public.cvm_ingest_log l
        WHERE l.status = 'ok' AND l.finished_at IS NOT NULL
          AND l.entity = 'bacen' AND l.doc_type = 'sgs'
        UNION ALL
        -- FNET logs two doc_types under entity 'fnet': 'register' (the
        -- delivery-day crawl that fills fnet_document) and 'fund_link' (the
        -- fortnightly per-fund sweep). The register row reports the crawl.
        SELECT '*fnet_register*'::text, MAX(l.finished_at),
               (array_agg(l.git_sha ORDER BY l.finished_at DESC, l.id DESC))[1]
        FROM public.cvm_ingest_log l
        WHERE l.status = 'ok' AND l.finished_at IS NOT NULL
          AND l.entity = 'fnet' AND l.doc_type = 'register'
        UNION ALL
        -- v38: cia_aberta logs cad, ipe, fca and the statements under one
        -- entity; the company_events row reports the IPE ingest alone.
        SELECT '*cia_ipe*'::text, MAX(l.finished_at),
               (array_agg(l.git_sha ORDER BY l.finished_at DESC, l.id DESC))[1]
        FROM public.cvm_ingest_log l
        WHERE l.status = 'ok' AND l.finished_at IS NOT NULL
          AND l.entity = 'cia_aberta' AND l.doc_type = 'ipe'
        UNION ALL
        -- v38: the ptax row must not report an SGS success as PTAX freshness
        -- (nor the reverse — macro_series reads '*bacen_sgs*').
        SELECT '*bacen_ptax*'::text, MAX(l.finished_at),
               (array_agg(l.git_sha ORDER BY l.finished_at DESC, l.id DESC))[1]
        FROM public.cvm_ingest_log l
        WHERE l.status = 'ok' AND l.finished_at IS NOT NULL
          AND l.entity = 'bacen' AND l.doc_type = 'ptax'
        UNION ALL
        -- v42 (27_api_rates.sql): the market ingest logs its five sources
        -- under entity 'market' (the B3 Price Report, B3 reference rates,
        -- Treasury, EIA, OFR); each served dataset reports its own source.
        SELECT '*market_price_report*'::text, MAX(l.finished_at),
               (array_agg(l.git_sha ORDER BY l.finished_at DESC, l.id DESC))[1]
        FROM public.cvm_ingest_log l
        WHERE l.status = 'ok' AND l.finished_at IS NOT NULL
          AND l.entity = 'market' AND l.doc_type = 'b3_price_report'
        UNION ALL
        SELECT '*market_reference_rate*'::text, MAX(l.finished_at),
               (array_agg(l.git_sha ORDER BY l.finished_at DESC, l.id DESC))[1]
        FROM public.cvm_ingest_log l
        WHERE l.status = 'ok' AND l.finished_at IS NOT NULL
          AND l.entity = 'market' AND l.doc_type = 'b3_reference_rate'
        UNION ALL
        -- v45 (29_api_index.sql): B3 index levels log under entity 'b3' next to
        -- COTAHIST and the BDI group, so the row reads its own doc_type.
        SELECT '*b3_index_level*'::text, MAX(l.finished_at),
               (array_agg(l.git_sha ORDER BY l.finished_at DESC, l.id DESC))[1]
        FROM public.cvm_ingest_log l
        WHERE l.status = 'ok' AND l.finished_at IS NOT NULL
          AND l.entity = 'b3' AND l.doc_type = 'index_levels'
        UNION ALL
        -- v65 (32_api_trade_consolidated.sql): the consolidated trade file logs
        -- under entity 'b3' too, one row per session, doc_type trade_consolidated.
        SELECT '*b3_trade_consolidated*'::text, MAX(l.finished_at),
               (array_agg(l.git_sha ORDER BY l.finished_at DESC, l.id DESC))[1]
        FROM public.cvm_ingest_log l
        WHERE l.status = 'ok' AND l.finished_at IS NOT NULL
          AND l.entity = 'b3' AND l.doc_type = 'trade_consolidated'
        UNION ALL
        SELECT '*credit_market*'::text, MAX(l.finished_at),
               (array_agg(l.git_sha ORDER BY l.finished_at DESC, l.id DESC))[1]
        FROM public.cvm_ingest_log l
        WHERE l.status = 'ok' AND l.finished_at IS NOT NULL
          AND l.entity = 'b3' AND l.doc_type = 'credit_consolidated'
    ),
    credit_span AS (
        SELECT MIN(d.day::date) AS first_date, MAX(d.day::date) AS last_date
        FROM public.b3_credit_capture c
        JOIN public.cvm_ingest_log l ON l.run_id = c.capture_id
        CROSS JOIN LATERAL jsonb_array_elements_text(c.expected_dates) d(day)
        WHERE c.source = 'b3_bdi_consolidated_records' AND c.status = 'complete'
          AND l.entity = 'b3' AND l.doc_type = 'credit_consolidated' AND l.status = 'ok'
          AND l.rows_upserted = c.debenture_rows * 9
          AND c.observed_at <= CURRENT_TIMESTAMP
          AND l.finished_at BETWEEN c.observed_at AND CURRENT_TIMESTAMP
          AND c.delivered_dates ? d.day
          AND d.day::date BETWEEN c.requested_from AND c.requested_to
          AND d.day::date <= CURRENT_DATE
    ),
    base AS (
        -- Session data (quotes/derivatives) is complete by construction and a
        -- trade_date is never in the future, so all three dates coincide.
        SELECT 'quotes'::text AS dataset, (SELECT MAX(q.trade_date) FROM public.vw_b3_quote_vista q) AS as_of,
               (SELECT MAX(q.trade_date) FROM public.vw_b3_quote_vista q) AS complete_through, 'b3_cotahist'::text AS source,
               -- The tape start (one index probe), so a caller knows the depth
               -- before asking: quote_history refuses a window that starts
               -- before an instrument's first session instead of returning a
               -- shorter series.
               ('B3 COTAHIST cash tape from '
                || (SELECT MIN(q.trade_date) FROM public.b3_cotahist q WHERE q.tpmerc = '010')
                || '. quote_history refuses a window that starts before an instrument''s first session (its coverage_start field); a session missing inside the coverage is a session with no trade. close_adj needs the issuer''s corporate-event sweep proof.')::text AS notes,
               (SELECT MAX(q.trade_date) FROM public.vw_b3_quote_vista q) AS newest_period,
               'b3'::text AS log_entity
        UNION ALL
        SELECT 'funds'::text,
               (SELECT MAX(d.last_period) FROM public.dim_fund d WHERE d.last_period <= CURRENT_DATE),
               public.latest_complete_period(NULL), 'cvm'::text, NULL::text,
               (SELECT MAX(d.last_period) FROM public.dim_fund d), '*funds*'::text
        UNION ALL
        SELECT 'fund_nav'::text,
               (SELECT MAX(f.period) FROM public.fact_fund_monthly f WHERE f.period <= CURRENT_DATE),
               public.latest_complete_period(NULL), 'cvm'::text,
               'columns are per family: a null outside the family''s list in catalog().applicability is not applicable, not missing. api.metric_coverage() reports the filed span of each (family, metric) pair.'::text,
               (SELECT MAX(f.period) FROM public.fact_fund_monthly f), '*funds*'::text
        UNION ALL
        -- Per-family rows: the families file on different cadences (FI daily,
        -- FIDC/FII with a 1-2 month lag, FIP annually), so one blended date
        -- misreads all of them. FIP is exactly where as_of and newest_period
        -- diverge.
        SELECT 'funds_' || fam.entity_type,
               (SELECT MAX(f.period) FROM public.fact_fund_monthly f
                 WHERE f.entity_type = fam.entity_type AND f.period <= CURRENT_DATE),
               public.latest_complete_period(fam.entity_type), 'cvm'::text,
               CASE fam.entity_type
                   WHEN 'fidc' THEN
                       'regime break at 2020-11-30: delinquency (tab VI''s filed total, from 2013-01) is null through 2020-10-31 for a fund with no tab VI row that month, and filed on every row from 2020-11-30. A null is not zero, not clean books — never read it as zero or compare counts of reporting funds across 2020-10 → 2020-11. See catalog().regime_breaks.'
                   WHEN 'fip' THEN
                       'files annually, keyed to 31-December: newest_period is a year-end key that can sit in the future, as_of is the newest period that has actually elapsed. Never read newest_period as freshness.'
               END::text,
               (SELECT MAX(f.period) FROM public.fact_fund_monthly f
                 WHERE f.entity_type = fam.entity_type),
               fam.entity_type
        -- The families come from dim_fund (one row per fund, ~70k), not from a
        -- DISTINCT over the fact matview, which would walk the whole index;
        -- a family with no fact rows yet produces no row, as before.
        FROM (SELECT DISTINCT d.entity_type FROM public.dim_fund d) fam
        WHERE EXISTS (SELECT 1 FROM public.fact_fund_monthly f
                       WHERE f.entity_type = fam.entity_type)
        UNION ALL
        -- Options + termo land in the same COTAHIST file as cash quotes, but the
        -- segments can lag independently, so freshness is reported per segment.
        -- GREATEST of three equality maxes rather than one IN-list max: coverage()
        -- is the bootstrap call every agent makes first, and only the equality
        -- form gets the MIN/MAX index rewrite (see api.option_chain).
        SELECT 'derivatives'::text,
               GREATEST(
                   (SELECT MAX(b.trade_date) FROM public.b3_cotahist b WHERE b.tpmerc = '070'),
                   (SELECT MAX(b.trade_date) FROM public.b3_cotahist b WHERE b.tpmerc = '080'),
                   (SELECT MAX(b.trade_date) FROM public.b3_cotahist b WHERE b.tpmerc = '030')
               ),
               GREATEST(
                   (SELECT MAX(b.trade_date) FROM public.b3_cotahist b WHERE b.tpmerc = '070'),
                   (SELECT MAX(b.trade_date) FROM public.b3_cotahist b WHERE b.tpmerc = '080'),
                   (SELECT MAX(b.trade_date) FROM public.b3_cotahist b WHERE b.tpmerc = '030')
               ),
               'b3_cotahist'::text,
               NULL::text,
               GREATEST(
                   (SELECT MAX(b.trade_date) FROM public.b3_cotahist b WHERE b.tpmerc = '070'),
                   (SELECT MAX(b.trade_date) FROM public.b3_cotahist b WHERE b.tpmerc = '080'),
                   (SELECT MAX(b.trade_date) FROM public.b3_cotahist b WHERE b.tpmerc = '030')
               ),
               'b3'::text
        UNION ALL
        -- Listed-company filings. Read from cia_filing (one row per submitted
        -- ITR/DFP document) rather than from cia_account: the account table is
        -- ~31M rows across yearly partitions and MAX(dt_refer) over it is a scan
        -- no anonymous caller's 3-second budget can absorb. complete_through is
        -- NULL on purpose — mv_period_completeness models fund filing cadence and
        -- says nothing about companies, and a fabricated completeness date is
        -- exactly the claim this function exists to prevent.
        SELECT 'financials'::text,
               (SELECT MAX(f.dt_refer) FROM public.cia_filing f WHERE f.dt_refer <= CURRENT_DATE),
               NULL::date, 'cvm'::text,
               'api.financials serves latest stored statement versions; api.financial_statement_history exposes every stored version for one company and required statement. Exact document metadata may be unavailable; coverage reads filing headers and does not scan partitioned account rows.'::text,
               (SELECT MAX(f.dt_refer) FROM public.cia_filing f), 'cia_aberta'::text
        UNION ALL
        -- FII property-register snapshots. The source has no stable property
        -- identifier: row_hash identifies source-row content within a filing,
        -- not the physical asset across reports.
        SELECT 'fii_property_history'::text,
               (SELECT MAX(i.data_referencia) FROM public.cvm_fii_imovel i WHERE i.data_referencia <= CURRENT_DATE),
               NULL::date, 'cvm'::text,
               'One exact fund CNPJ; one source row per filing snapshot. CVM publishes no stable property id; row_hash is source-row identity only. NULL measurements remain missing, never zero.'::text,
               (SELECT MAX(i.data_referencia) FROM public.cvm_fii_imovel i), 'fii'::text
        UNION ALL
        SELECT 'focus_expectations'::text,
               (SELECT MAX(e.reference_date) FROM public.bacen_expectativas e WHERE e.reference_date <= CURRENT_DATE),
               NULL::date, 'bacen'::text,
               'Weekly Focus observations by report date and exact horizon. The API pins baseCalculo=0 and unsmoothed 12-month inflation; migration 16 fixed horizon collisions, but older lost horizon rows require re-fetch. Later corrections to survey dates outside the daily 30-day refresh are not a vintage archive.'::text,
               (SELECT MAX(e.reference_date) FROM public.bacen_expectativas e), 'bacen'::text
        UNION ALL
        -- ANBIMA boletim: a published edition is complete by construction (a
        -- monthly publication, not a filing cadence), so both dates coincide.
        -- The log entity is 'anbima_etf' for history's sake (see
        -- src/pipeline/anbima_pipeline.py), though the table is no longer
        -- ETF-only.
        SELECT 'anbima_classes'::text, MAX(a.reference_date), MAX(a.reference_date),
               'anbima'::text, NULL::text, MAX(a.reference_date), 'anbima_etf'::text
        FROM public.anbima_class_monthly a
        UNION ALL
        -- FIDC concentration tabs (migration 38, #233). Members of the same
        -- monthly informe as cvm_fidc_mensal, so the fidc completeness clamp
        -- applies. Each MAX is an index-only probe on (period DESC). notes
        -- carry what the dates cannot: where each series starts and what its
        -- identifiers are. as_of is bounded like every other period arm; these
        -- file monthly in arrears, so it should equal newest_period.
        SELECT 'fidc_cedentes'::text,
               (SELECT MAX(c.period) FROM public.cvm_fidc_cedente c WHERE c.period <= CURRENT_DATE),
               public.latest_complete_period('fidc'), 'cvm'::text,
               'tab I cedente slots exist from 2019-11; cedente_id is checksum-verified at ingest (placeholders dropped, never coerced); share_pct is a percent of the block, not of the fund'::text,
               (SELECT MAX(c.period) FROM public.cvm_fidc_cedente c), 'fidc'::text
        UNION ALL
        SELECT 'fidc_sacados'::text,
               (SELECT MAX(k.period) FROM public.cvm_fidc_sacado k WHERE k.period <= CURRENT_DATE),
               public.latest_complete_period('fidc'), 'cvm'::text,
               'tab VIII from 2013-01: the 25 largest debtors as anonymized (rank, value); seq is CVM''s rank as filed, never recomputed'::text,
               (SELECT MAX(k.period) FROM public.cvm_fidc_sacado k), 'fidc'::text
        UNION ALL
        SELECT 'fidc_sectors'::text,
               (SELECT MAX(s.period) FROM public.cvm_fidc_setor s WHERE s.period <= CURRENT_DATE),
               public.latest_complete_period('fidc'), 'cvm'::text,
               'tab II from 2013-01: receivables by sector, a hierarchy (fidc_portfolio.parent); TOTAL is the panel metric receivables'::text,
               (SELECT MAX(s.period) FROM public.cvm_fidc_setor s), 'fidc'::text
        UNION ALL
        SELECT 'fidc_scr'::text,
               (SELECT MAX(r2.period) FROM public.cvm_fidc_scr r2 WHERE r2.period <= CURRENT_DATE),
               public.latest_complete_period('fidc'), 'cvm'::text,
               'tab X exists from 2023-10 only: SCR grade ladders AA..H by debtor and by operation; a month before that has no rows, not zero-graded ones'::text,
               (SELECT MAX(r2.period) FROM public.cvm_fidc_scr r2), 'fidc'::text
        UNION ALL
        -- FIDC structure tabs (v31): tranches (X_2/X_3/X_6 + X_4) and the
        -- tab VI aging ladder. Same informe, same fidc completeness clamp.
        -- The note says where the span comes from: CVM's yearly HIST archive
        -- through 2024-12 and the monthly informe from 2025-01.
        SELECT 'fidc_tranches'::text,
               (SELECT MAX(t2.period) FROM public.cvm_fidc_tranche t2 WHERE t2.period <= CURRENT_DATE),
               public.latest_complete_period('fidc'), 'cvm'::text,
               'tabs X_2/X_3/X_6 (+ X_4 flows) from 2013-01: CVM''s yearly HIST archive through 2024-12, the monthly informe from 2025-01. Quotas, quota value, return and promised vs realised performance are as filed (percent fields carry CVM''s outliers, 1e14 and more, never rescaled); flows keep CVM''s TP_OPER labels verbatim'::text,
               (SELECT MAX(t2.period) FROM public.cvm_fidc_tranche t2), 'fidc'::text
        UNION ALL
        SELECT 'fidc_aging'::text,
               (SELECT MAX(a2.period) FROM public.cvm_fidc_aging a2 WHERE a2.period <= CURRENT_DATE),
               public.latest_complete_period('fidc'), 'cvm'::text,
               'tab VI from 2013-01: CVM''s yearly HIST archive through 2024-12, the monthly informe from 2025-01. to_maturity and overdue ladders in ten day-bands each, BRL as filed; overdue_total is CVM''s filed total, not a sum of the bands'::text,
               (SELECT MAX(a2.period) FROM public.cvm_fidc_aging a2), 'fidc'::text
        UNION ALL
        -- The B3 securities-lending and investor-flow group (#235, #240-#245),
        -- published since but absent from this function until v27 — so the one
        -- call an agent is told to make before claiming freshness said nothing
        -- about five endpoints that were already answering.
        --
        -- THE RATCHET LIVES IN `notes`, not in the dates. B3 retains ~21
        -- business days of these tables and publishes no archive, so as_of and
        -- the FIRST date are both facts about what SILO captured, not about
        -- what exists. A caller who reads a short window as a data problem
        -- will go looking for a backfill that cannot be run. The note says so
        -- on every row, because the dates cannot.
        --
        -- A session is complete by construction (B3 publishes the day's book
        -- once), so complete_through = as_of, as it does for quotes. Each MAX
        -- is an index probe on a date column over a table the retention window
        -- already bounds.
        SELECT 'short_interest'::text,
               (SELECT MAX(p.trade_date) FROM public.b3_lending_open_position p WHERE p.trade_date <= CURRENT_DATE),
               (SELECT MAX(p.trade_date) FROM public.b3_lending_open_position p WHERE p.trade_date <= CURRENT_DATE),
               'b3'::text,
               'RATCHET: B3 keeps ~21 business days of the lending book and publishes no archive, so this series starts at SILO''s first capture and cannot be backfilled at any price — a short window is the retention limit, not a gap. Read pct_float together with float_basis: index_free_float (index constituents only) and shares_outstanding (a larger denominator, so a smaller percentage) are different metrics, and any ranking must filter to one. pct_float and days_to_cover are NULL, never 0, when the denominator is missing or the name did not trade.'::text,
               (SELECT MAX(p.trade_date) FROM public.b3_lending_open_position p), '*b3_lending_balance*'::text
        UNION ALL
        SELECT 'short_interest_by_sector'::text,
               (SELECT MAX(p.trade_date) FROM public.b3_lending_open_position p WHERE p.trade_date <= CURRENT_DATE),
               (SELECT MAX(p.trade_date) FROM public.b3_lending_open_position p WHERE p.trade_date <= CURRENT_DATE),
               'b3'::text,
               'Same ratchet and same spine as short_interest. Sector is B3''s own top-level sector from the index portfolios; tickers B3 publishes no sector for (ETFs, BDRs, anything outside the index universe) are bucketed as Não classificado rather than dropped, so the bars sum to the whole book. short_value_equities restricts to SHARES and UNIT for the single-name view.'::text,
               (SELECT MAX(p.trade_date) FROM public.b3_lending_open_position p), '*b3_lending_balance*'::text
        UNION ALL
        SELECT 'lending_trades'::text,
               (SELECT MAX(t.trade_date) FROM public.b3_lending_trade t WHERE t.trade_date <= CURRENT_DATE),
               (SELECT MAX(t.trade_date) FROM public.b3_lending_trade t WHERE t.trade_date <= CURRENT_DATE),
               'b3'::text,
               'RATCHET: ~21 business days at the source, no archive, history starts at first capture. rate_pct is quantity-weighted, while B3''s own published average in the lending-rate table weights by NUMBER OF TRADES — the two answer different questions and neither overwrites the other (measured 2026-09-10 across 569 tickers: mean absolute difference 0.037pp). internal_trades counts trades a single broker crossed with itself; about three quarters of the tape is that.'::text,
               (SELECT MAX(t.trade_date) FROM public.b3_lending_trade t), '*b3_lending_trade*'::text
        UNION ALL
        SELECT 'lending_participants'::text,
               (SELECT MAX(t.trade_date) FROM public.b3_lending_trade t WHERE t.trade_date <= CURRENT_DATE),
               (SELECT MAX(t.trade_date) FROM public.b3_lending_trade t WHERE t.trade_date <= CURRENT_DATE),
               'b3'::text,
               'RATCHET: ~21 business days at the source, no archive, history starts at first capture. broker_code is the B3 PARTICIPANT intermediating, NEVER the beneficial owner: ~75% of trades carry the same code on both legs (32,197 of 43,165 on 2026-09-10), so a large borrow through a broker is its client book, not a position it holds. internal_legs / internal_qty are what separate client churn from directional flow — never read a broker''s quantity_borrowed as its own short.'::text,
               (SELECT MAX(t.trade_date) FROM public.b3_lending_trade t), '*b3_lending_trade*'::text
        UNION ALL
        -- as_of is the newest REFERENCE date held, which trails the calendar by
        -- B3's T+2 publication lag even when ingest is perfectly healthy. That
        -- is the source's cadence, not our staleness — exactly the distinction
        -- AGENTS.md draws between complete_through and landed_at.
        SELECT 'investor_flow'::text,
               (SELECT MAX(i.reference_date) FROM public.b3_investor_participation i WHERE i.reference_date <= CURRENT_DATE),
               (SELECT MAX(i.reference_date) FROM public.b3_investor_participation i WHERE i.reference_date <= CURRENT_DATE),
               'b3'::text,
               'RATCHET: ~21 business days at the source, no archive, history starts at first capture. Published T+2, so as_of trails the calendar even when ingest is healthy. The daily figures are a FIRST DIFFERENCE of a month-to-date cumulative snapshot and never difference across a month boundary; flow_basis says which row you have — delta (a real one-session difference), month_open (the month''s first session), or unknown_opening_snapshot (no earlier snapshot held that month), whose flows are NULL BY CONSTRUCTION and must never be read or summed as zeros. Values are R$ thousands.'::text,
               (SELECT MAX(i.reference_date) FROM public.b3_investor_participation i), '*b3_investor_flow*'::text
        UNION ALL
        -- Inflation (BACEN SGS). The headline month is the honest as_of: the
        -- cores, classifications and groups publish on the same day as 433.
        -- A published month is complete by construction (a statistical
        -- release, not a filing cadence), so both dates coincide.
        SELECT 'inflation'::text,
               (SELECT MAX(s.reference_date) FROM public.bacen_sgs s WHERE s.series_code = 433 AND s.reference_date <= CURRENT_DATE),
               (SELECT MAX(s.reference_date) FROM public.bacen_sgs s WHERE s.series_code = 433 AND s.reference_date <= CURRENT_DATE),
               'bacen'::text,
               'Monthly changes in percent AS PUBLISHED; acc_12m is DERIVED (the trailing twelve monthly changes chained, NULL unless all twelve are present and consecutive) and reproduces BACEN''s own IPCA_12M (13522) exactly for the headline. IPCA15 is the mid-month preview, not a revision. Group rows are variations, never contributions — weights are inflation_items. Group codes 1640..1643 are Comunicação, Saúde, Despesas pessoais, Educação (measured, not IBGE''s order). IPCA runs from 1980-01, cores and groups from 1991-01, IPCA-15 from 2000-05.'::text,
               (SELECT MAX(s.reference_date) FROM public.bacen_sgs s WHERE s.series_code = 433), '*bacen_sgs*'::text
        UNION ALL
        SELECT 'inflation_items'::text,
               (SELECT MAX(i.reference_month) FROM public.ibge_ipca_item_monthly i WHERE i.reference_month <= CURRENT_DATE),
               (SELECT MAX(i.reference_month) FROM public.ibge_ipca_item_monthly i WHERE i.reference_month <= CURRENT_DATE),
               'ibge'::text,
               'Weights, monthly / YTD / 12-month changes AS PUBLISHED by IBGE SIDRA (table 1419 for 2012-01..2019-12, 7060 from 2020-01); contribution = weight × change_month / 100 is the one derived column. SIDRA item codes CHANGED with the 2020-01 structure — item_number and names are the continuity, sidra_table says which structure a row came from. Sum contributions within one level only. No item tree exists before 2012-01; the group variations before that are inflation (BACEN).'::text,
               (SELECT MAX(i.reference_month) FROM public.ibge_ipca_item_monthly i), 'ibge'::text
        UNION ALL
        -- The FNET document register (v33; api.fund_documents and
        -- api.fund_restatements in 24_api_fnet.sql). The period is the
        -- DELIVERY day. complete_through is the day before as_of: the crawl
        -- that saw a document delivered on as_of ran on or after that day,
        -- possibly while FNET was still receiving that day's documents, but
        -- the day before had already ended — so it is the newest delivery day
        -- the register can claim in full. Two index probes on
        -- idx_fnet_document_delivered, not a scan.
        SELECT 'fnet_documents'::text,
               x.as_of_ts::date,
               (x.as_of_ts::date - 1),
               'fnet'::text,
               'B3 Fundos.NET document register, metadata only: each version is its own fnet_id (versao, modalidade AP/RE/RC), status (AC/IC/CC) is as of fetched_at, and FNET links no versions (fund_restatements pairs them by a stated group key). The period is the DELIVERY day; complete_through is the day before as_of, the newest day the crawl had seen end. History begins at first capture / backfill (run_backfill --fnet-only), not at FNET''s own start: a delivery day before the first crawled one is not empty, it was not crawled. Fund links come from a fortnightly per-fund sweep, so recent documents may have no cnpj yet — they are in the register and reach fund_documents after the next sweep of their fund (fund_restatements serves them with cnpj NULL).'::text,
               x.newest_ts::date, '*fnet_register*'::text
        FROM (
            SELECT (SELECT MAX(d.delivered_at) FROM public.fnet_document d
                     WHERE d.delivered_at < (CURRENT_DATE + 1)::timestamp) AS as_of_ts,
                   (SELECT MAX(d.delivered_at) FROM public.fnet_document d) AS newest_ts
        ) x
        UNION ALL
        -- v38 (26_api_events_macro.sql). IPE filings, keyed on the DELIVERY
        -- day. complete_through is NULL for the reason it is NULL on the
        -- financials row: no completeness model covers company filings, and a
        -- guessed one is the claim this function exists to prevent. The note
        -- carries the one limit the dates hide: filings without a protocol
        -- number are not held at all.
        SELECT 'company_events'::text,
               MAX((e.data_entrega AT TIME ZONE 'UTC')::date)
                   FILTER (WHERE (e.data_entrega AT TIME ZONE 'UTC')::date <= CURRENT_DATE),
               NULL::date, 'cvm'::text,
               'IPE filings (fatos relevantes, comunicados, assembly material), one row per protocol at its newest version, text as filed, source_url on CVM''s RAD. History starts in 2015 and is NOT complete for any year: CVM assigned no protocol number before 2015 (and still omits it on a minority of filings — 12% of 2015), cia_event is keyed on (protocolo, versao), and a key is never synthesized, so those filings are not held. The period is the delivery date.'::text,
               MAX((e.data_entrega AT TIME ZONE 'UTC')::date), '*cia_ipe*'::text
        FROM public.cia_event e
        UNION ALL
        -- The non-inflation SGS series (macro_series). One row for nine series
        -- with different cadences, so as_of is the newest ELAPSED observation
        -- of any of them (SELIC_META is published ahead to the next Copom
        -- date; newest_period shows that). A published value is final by
        -- construction, so complete_through = as_of, as on the inflation row.
        SELECT 'macro_series'::text,
               (SELECT MAX(s.reference_date) FROM public.bacen_sgs s WHERE s.series_code IN (432, 11, 12, 189, 188, 25, 1, 21619, 4380) AND s.reference_date <= CURRENT_DATE),
               (SELECT MAX(s.reference_date) FROM public.bacen_sgs s WHERE s.series_code IN (432, 11, 12, 189, 188, 25, 1, 21619, 4380) AND s.reference_date <= CURRENT_DATE),
               'bacen'::text,
               'Nine BACEN SGS series as published, units on every row: SELIC_META (432, % a.a., dated per calendar day and published AHEAD to the next Copom date — newest_period can sit in the future), SELIC_DIARIA (11) and CDI (12, % per business day), IGPM (189) and INPC (188, monthly, published in the following month), POUPANCA (25, the old-rule deposit return, one value per anniversary day), USDBRL (1) and EURBRL (21619, BRL per unit), PIB (4380, monthly, R$ millions). The cadences differ, so as_of is the newest elapsed observation of ANY of them — read a monthly series'' own last row before calling it late.'::text,
               (SELECT MAX(s.reference_date) FROM public.bacen_sgs s WHERE s.series_code IN (432, 11, 12, 189, 188, 25, 1, 21619, 4380)), '*bacen_sgs*'::text
        UNION ALL
        SELECT 'ptax'::text,
               (SELECT MAX(p.reference_date) FROM public.bacen_ptax p WHERE p.reference_date <= CURRENT_DATE),
               (SELECT MAX(p.reference_date) FROM public.bacen_ptax p WHERE p.reference_date <= CURRENT_DATE),
               'bacen'::text,
               'PTAX compra / venda per currency and business day, BRL per one unit of the currency, as published. The ingest keeps the last bulletin of the day it received — the Fechamento PTAX for any completed day (the daily run is 03:00 BRT, before the first bulletin); the bulletin type is not stored.'::text,
               (SELECT MAX(p.reference_date) FROM public.bacen_ptax p), '*bacen_ptax*'::text
        UNION ALL
        -- v42 (27_api_rates.sql). B3 session files: a trade_date is never in
        -- the future and a published session is final, so the three dates
        -- coincide, as on the quotes row. One index probe each.
        SELECT 'di_futures'::text,
               (SELECT MAX(f.trade_date) FROM public.b3_futures_settlement f WHERE f.trade_date <= CURRENT_DATE),
               (SELECT MAX(f.trade_date) FROM public.b3_futures_settlement f WHERE f.trade_date <= CURRENT_DATE),
               'b3'::text,
               'B3 Price Report (BVBG.086.01), outright DI1 futures, one row per session and contract (future_curve, future_series), from 2018-01-02: B3''s older reports are empty. DI1 is quoted in RATE, so the quote columns are % a.a. on 252 business days and settlement_price is the PU. History comes from market_backfill.yml, so a span that starts late was not loaded, not missing at B3.'::text,
               (SELECT MAX(f.trade_date) FROM public.b3_futures_settlement f), '*market_price_report*'::text
        UNION ALL
        SELECT 'reference_curves'::text,
               (SELECT MAX(r.trade_date) FROM public.b3_reference_rate r WHERE r.trade_date <= CURRENT_DATE),
               (SELECT MAX(r.trade_date) FROM public.b3_reference_rate r WHERE r.trade_date <= CURRENT_DATE),
               'b3'::text,
               'B3 reference rates (TaxaSwap.txt), every vertex of PRE (DI x pré), DOC (clean onshore dollar coupon, LINEAR on 360 days) and DPL (clean IPCA coupon, a real rate), from 2008-01-02 (curve, curve_history). Past the last maturity of the contract anchoring each curve (DI1, DDI, DAP) B3 extrapolates the last forward rate, so the long vertices are not prices (Manual de Curvas v21). History comes from market_backfill.yml.'::text,
               (SELECT MAX(r.trade_date) FROM public.b3_reference_rate r), '*market_reference_rate*'::text
        UNION ALL
        -- v45 (29_api_index.sql). A session level is final once published, so the
        -- three dates coincide. The depth of each index is in the notes, read
        -- from the table, so a second index shows up here with no edit.
        SELECT 'index_history'::text,
               (SELECT MAX(i.trade_date) FROM public.b3_index_level i WHERE i.trade_date <= CURRENT_DATE),
               (SELECT MAX(i.trade_date) FROM public.b3_index_level i WHERE i.trade_date <= CURRENT_DATE),
               'b3'::text,
               'Daily levels of B3-published indices AS PUBLISHED (index_history), each a total-return index per B3 (distributions reinvested), not adjusted: B3 re-scaled IBOV eleven times, the last on 1997-03-03, and divisor_step marks the first session after each, where a level ratio is not a return. Depth per index: '
                   || COALESCE((SELECT string_agg(d.index_code || ' from ' || d.first_date::text, '; ' ORDER BY d.index_code)
                                FROM (SELECT i.index_code, MIN(i.trade_date) AS first_date
                                      FROM public.b3_index_level i GROUP BY i.index_code) d), 'none loaded yet')
                   || '. The whole series is refetched nightly.'::text,
               (SELECT MAX(i.trade_date) FROM public.b3_index_level i), '*b3_index_level*'::text
        UNION ALL
        -- v65 (32_api_trade_consolidated.sql). Only a file B3 marks Final is
        -- stored, so a session is complete once it lands: the three dates
        -- coincide. The first session is read from the table.
        SELECT 'trade_consolidated_history'::text,
               (SELECT MAX(t.trade_date) FROM public.b3_trade_consolidated t WHERE t.trade_date <= CURRENT_DATE),
               (SELECT MAX(t.trade_date) FROM public.b3_trade_consolidated t WHERE t.trade_date <= CURRENT_DATE),
               'b3'::text,
               'B3 TradeInformationConsolidatedFile, segment FORWARD only (trade_consolidated_history): the fixed-income ETFs COTAHIST does not carry (IMAB11, B5P211, IRFM11, LFTS11, ...) and the other FORWARD tickers, as published. The close is last_price; ref_price is a reference, never a close, and is all a session with no trade carries. No opening price exists in the source. Prices are not adjusted for distributions, so a return from last_price is price-only. The source''s retention edge was 2025-06-10 on 2026-09-30, so history cannot start earlier. First session held: '
                   || COALESCE((SELECT MIN(t.trade_date)::text FROM public.b3_trade_consolidated t), 'none loaded yet')
                   || '.'::text,
               (SELECT MAX(t.trade_date) FROM public.b3_trade_consolidated t), '*b3_trade_consolidated*'::text
        UNION ALL
        SELECT 'credit_market_history'::text, s.last_date, s.last_date,
               'b3_bdi_consolidated_records'::text,
               'Stored debenture observation span from ' || COALESCE(s.first_date::text, 'none')
               || '. Latest complete audited capture is selected per trade date before instrument filters. The span does not certify gap-free history or original publication-time PIT. Separate settlement/classification groups; reference prices are not trades. No yield, outstanding or coupon-adjusted return.'::text,
               s.last_date, '*credit_market*'::text
        FROM credit_span s
    )
    SELECT b.dataset, b.as_of, b.complete_through, b.source, b.notes,
           b.newest_period, l.landed_at, l.landed_git_sha
    FROM base b
    LEFT JOIN landed l ON l.entity = b.log_entity
    ORDER BY 1;
$$;

COMMENT ON FUNCTION api.coverage() IS
    'Freshness AND honesty per dataset. as_of = the newest period that has landed and has actually ELAPSED (bounded by today); complete_through = the newest COMPLETE period, which is what default windows serve; newest_period = the newest period KEY present, which can sit in the future when a family files forward-dated (FIP is keyed 31-December); landed_at = when ingest last SUCCEEDED for that source, from cvm_ingest_log (status ok with a finish time, so a later failed run never advances it); landed_git_sha = the git commit of THAT run — which code produced this data — NULL when the run recorded none (before migration 44, or run outside GitHub Actions), never borrowed from an older run. funds_<family> rows report each filing cadence separately. notes carries a caveat the dates cannot: the quotes row states where the cash tape starts (quote_history refuses a window before an instrument''s first session); the funds_fidc row states the 2020-11 delinquency regime break (null for a fund with no tab VI row before, filed on every row after — never read that null as zero); funds_fip states why its newest_period runs ahead; fund_nav points at catalog().applicability and api.metric_coverage(); the fidc_tranches and fidc_aging rows state that those informe tabs come from CVM''s yearly HIST archive through 2024-12 and the monthly informe from 2025-01; the fnet_documents row (the FNET register behind fund_documents and fund_restatements) is keyed on the DELIVERY day, with complete_through the day before as_of, and states that its history begins at first capture / backfill and that fund links come from a fortnightly sweep, so recent documents may have no cnpj yet; the company_events row (IPE filings, keyed on the delivery date, complete_through NULL as on financials) states that history starts in 2015 and that filings CVM published without a protocol number are not held; the macro_series and ptax rows carry their units and cadences (SELIC_META is published ahead, so its newest_period can sit in the future); the di_futures and reference_curves rows (B3 Price Report DI1 contracts from 2018, B3 reference curves from 2008) state where each history starts and that the long curve vertices are B3''s extrapolation, not prices; and the five B3 lending / flow rows (short_interest, short_interest_by_sector, lending_trades, lending_participants, investor_flow) state the RATCHET — B3 keeps ~21 business days and publishes no archive, so their span starts at first capture and no backfill exists — along with the float_basis, brokerage-not-owner and first-difference traps that make those series easy to read wrongly. Their landed_at is split by ingest doc_type, so a COTAHIST run never reports as the lending group''s freshness.';

REVOKE ALL ON FUNCTION api.coverage() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.coverage() TO anon, authenticated;

-- ---------------------------------------------------------------------------
-- metric_coverage — the filed span of every (family, metric) pair
-- ---------------------------------------------------------------------------
-- coverage() answers "how fresh is this dataset". This answers "does this
-- family file this metric at all, and since when" — the question an agent
-- otherwise answers by pulling a series and inferring from nulls, which is
-- exactly how a format change gets read as a credit event. Only pairs with at
-- least one filed value are listed (see mv_metric_coverage): an absent pair is
-- not-applicable, not late.
CREATE OR REPLACE FUNCTION api.metric_coverage()
RETURNS TABLE (
    entity_type  TEXT,
    metric       TEXT,
    first_period DATE,
    last_period  DATE,
    filed_rows   BIGINT,
    total_rows   BIGINT
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    SELECT m.entity_type, m.metric, m.first_period, m.last_period,
           m.filed_rows, m.total_rows
    FROM public.mv_metric_coverage m
    ORDER BY 1, 2;
$$;

COMMENT ON FUNCTION api.metric_coverage() IS
    'Filed span per (entity_type, metric): first_period / last_period are the oldest and newest periods carrying a NON-NULL value, filed_rows / total_rows say how dense it is. A pair absent from this list is one the family never files (catalog().applicability) — not one whose data is late. Use it to read catalog().metrics.<m>.since against the warehouse instead of trusting a note.';

REVOKE ALL ON FUNCTION api.metric_coverage() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.metric_coverage() TO anon, authenticated;

-- ---------------------------------------------------------------------------
-- Research panel — long observations a researcher can correlate / factor
-- ---------------------------------------------------------------------------
-- One row = (id, date, metric, value). Mix tickers (B3 last session in the
-- month) with fund CNPJs (CVM monthly). Missing months stay absent — no ffill,
-- no interpolated return across a gap. freq=day is quotes only.
-- ---------------------------------------------------------------------------

-- Signature change (p_entity_type, p_min_nav, p_min_months, p_after): drop the
-- old shape first — CREATE OR REPLACE cannot add parameters, and PostgREST
-- resolves an RPC by argument names, so the 5-argument form must not survive
-- as an overload.
DROP FUNCTION IF EXISTS api.panel(TEXT[], TEXT[], DATE, DATE, TEXT);

-- Default change (p_metrics NULL = each family's own default, below):
-- CREATE OR REPLACE keeps a parameter's old default, so drop the shape first.
DROP FUNCTION IF EXISTS api.panel(TEXT[], TEXT[], DATE, DATE, TEXT, TEXT, NUMERIC, INT, TEXT);

CREATE OR REPLACE FUNCTION api.panel(
    p_ids     TEXT[],
    -- NULL = each family's default: close_adj for shares and units (the
    -- research universe's ISIN rule), close for every other ticker, option and
    -- termo, settlement_rate for futures, nav for funds. An explicit list is
    -- served as asked.
    p_metrics TEXT[] DEFAULT NULL,
    p_from    DATE   DEFAULT (CURRENT_DATE - 365),
    -- NULL (the default) = honest window: quote/option/termo/future arms run to
    -- CURRENT_DATE (a session print is complete by construction), while fund
    -- arms clamp per entity family to latest_complete_period() so a
    -- partially-filed trailing month is not served as if it were the
    -- industry. An EXPLICIT p_to is the researcher escape hatch: it serves
    -- whatever exists in the window, partial months included.
    p_to      DATE   DEFAULT NULL,
    p_freq    TEXT   DEFAULT 'month',
    -- Restrict the fund arms to one family. A CNPJ can file under two
    -- families in one month (385 do, fi + fidc), so without it the grain is
    -- (id, asset_class, date, metric), not (id, date, metric).
    p_entity_type TEXT    DEFAULT NULL,
    -- Universe mode (p_ids empty + p_entity_type): keep funds whose latest
    -- non-null NAV in the window is at least p_min_nav (BRL) and which have
    -- at least p_min_months non-null observations of the FIRST requested
    -- metric. Filters on published values; never a rank.
    p_min_nav     NUMERIC DEFAULT NULL,
    p_min_months  INT     DEFAULT NULL,
    -- Cursor. NULL = whole result (refused above 1000 rows); '' = first page;
    -- 'date|id|metric|asset_class' = the page after that key. A page is
    -- exactly 1000 rows until the last, which is shorter.
    p_after       TEXT    DEFAULT NULL
)
RETURNS TABLE (
    id          TEXT,
    id_type     TEXT,
    asset_class TEXT,
    date        DATE,
    metric      TEXT,
    value       NUMERIC,
    source      TEXT
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
WITH
params AS (
    SELECT
        -- assert_panel_ids raises 22023 when the tier's id ceiling is
        -- exceeded (3 anonymous, 50 signed in). Wrapping the array in
        -- argument position is what makes the check unavoidable: this
        -- function is LANGUAGE sql and cannot RAISE on its own, but an
        -- argument is always evaluated.
        api.assert_panel_ids(ARRAY(
            SELECT upper(btrim(x))
            FROM unnest(COALESCE(p_ids, ARRAY[]::TEXT[])) AS x
            WHERE btrim(x) <> ''
        )) AS ids,
        ARRAY(
            SELECT lower(btrim(x))
            FROM unnest(COALESCE(p_metrics, ARRAY['close','close_adj','nav']::TEXT[])) AS x
            WHERE btrim(x) <> ''
        ) AS metrics,
        p_metrics IS NULL AS default_metrics,
        CASE WHEN lower(COALESCE(p_freq, 'month')) IN ('day', 'd', 'daily') THEN 'day' ELSE 'month' END AS freq,
        p_from AS d0,
        COALESCE(p_to, CURRENT_DATE) AS d1,  -- quote/option/termo upper bound
        p_to AS d1_explicit,                 -- NULL = clamp fund arms (below)
        -- Universe gate + family validation, in argument position like
        -- assert_panel_ids above: evaluated on every call, raises 22023.
        api.assert_panel_universe(
            cardinality(ARRAY(SELECT x FROM unnest(COALESCE(p_ids, ARRAY[]::TEXT[])) AS x WHERE btrim(x) <> '')),
            p_entity_type
        ) AS entity_type,
        cardinality(ARRAY(SELECT x FROM unnest(COALESCE(p_ids, ARRAY[]::TEXT[])) AS x WHERE btrim(x) <> '')) = 0 AS universe,
        p_min_nav    AS min_nav,
        p_min_months AS min_months,
        c.paging, c.after_date, c.after_id, c.after_metric, c.after_class
    FROM api.parse_panel_cursor(p_after) c
),
tickers AS (
    SELECT x AS ticker
    FROM params p, unnest(p.ids) AS x
    WHERE length(regexp_replace(x, '[^0-9]', '', 'g')) <> 14
),
-- Universe mode: the family's funds in the window, filtered on published
-- values only. "Latest NAV" is the last non-null vl_patrim_liq by raw period;
-- "observations" counts non-null values of the FIRST requested metric. Both
-- bounds use the same two-regime upper bound as fund_rows below.
universe AS (
    SELECT f.cnpj
    FROM public.fact_fund_monthly f
    JOIN params p ON TRUE
    WHERE p.universe
      AND p.freq = 'month'
      AND f.entity_type = p.entity_type
      AND date_trunc('month', f.period)::date >= date_trunc('month', p.d0)::date
      AND (
            (p.d1_explicit IS NOT NULL
             AND date_trunc('month', f.period)::date
                 <= date_trunc('month', p.d1_explicit)::date)
         OR (p.d1_explicit IS NULL
             AND f.period <= public.latest_complete_period(f.entity_type))
      )
    GROUP BY f.cnpj
    HAVING ((SELECT min_nav FROM params) IS NULL
            OR (ARRAY_AGG(f.vl_patrim_liq ORDER BY f.period DESC) FILTER (WHERE f.vl_patrim_liq IS NOT NULL))[1]
               >= (SELECT min_nav FROM params))
       AND ((SELECT min_months FROM params) IS NULL
            OR COUNT(CASE (SELECT metrics[1] FROM params)
                         WHEN 'nav'          THEN f.vl_patrim_liq
                         WHEN 'quota'        THEN f.vl_quota
                         WHEN 'delinquency'  THEN f.vl_inadimpl
                         WHEN 'yield'        THEN f.pct_yield_mes
                         WHEN 'inflows'      THEN f.captc_mes
                         WHEN 'redemptions'  THEN f.resg_mes
                         WHEN 'quotaholders' THEN f.nr_cotst::numeric
                     END) >= (SELECT min_months FROM params))
),
cnpjs AS (
    SELECT regexp_replace(x, '[^0-9]', '', 'g') AS cnpj
    FROM params p, unnest(p.ids) AS x
    WHERE length(regexp_replace(x, '[^0-9]', '', 'g')) = 14
    UNION ALL
    SELECT u.cnpj FROM universe u
),
-- Last session in each month (real print, not a made-up month-end).
quote_month AS (
    SELECT DISTINCT ON (q.ticker, date_trunc('month', q.trade_date))
        q.ticker,
        date_trunc('month', q.trade_date)::date AS period,
        q.trade_date AS obs_date,
        q.close,
        q.close_unit,
        q.volume,
        q.asset_class,
        q.quotation_factor,
        q.isin
    FROM api.quotes q
    JOIN params p ON TRUE
    WHERE p.freq = 'month'
      AND q.trade_date BETWEEN p.d0 AND p.d1
      AND q.ticker IN (SELECT ticker FROM tickers)
    ORDER BY q.ticker, date_trunc('month', q.trade_date), q.trade_date DESC, q.board
),
quote_day AS (
    SELECT DISTINCT ON (q.ticker, q.trade_date)
        q.ticker, q.trade_date AS period, q.trade_date AS obs_date,
        q.close, q.close_unit, q.volume, q.asset_class, q.quotation_factor, q.isin
    FROM api.quotes q
    JOIN params p ON TRUE
    WHERE p.freq = 'day'
      AND q.trade_date BETWEEN p.d0 AND p.d1
      AND q.ticker IN (SELECT ticker FROM tickers)
    ORDER BY q.ticker, q.trade_date, q.board
),
quote_px AS (
    SELECT u.*,
           -- The research universe's membership rule (28_api_research.sql):
           -- the ISIN's instrument code, ACN, or CDA / UNT with a ticker ending 11.
           COALESCE(substr(u.isin, 7, 3) = 'ACN'
                    OR (substr(u.isin, 7, 3) IN ('CDA', 'UNT') AND u.ticker LIKE '%11'),
                    FALSE) AS in_universe
    FROM (
        SELECT * FROM quote_month
        UNION ALL
        SELECT * FROM quote_day
    ) u
),
-- close_adj: the same adjustment and the same refusals as quote_history
-- (api.close_adj_status / close_adj_ratio / assert_close_adj). Each
-- (ticker, ISIN) asked for close_adj is checked once over the requested
-- window; a stretch it cannot adjust refuses the panel (22023) instead of
-- serving the raw close under the adjusted name.
adj_ids AS (
    -- One status lookup per (ticker, ISIN), not per row.
    SELECT d.ticker, d.isin, s.anchor
    FROM (
        SELECT DISTINCT q.ticker, q.isin
        FROM quote_px q
        JOIN params p ON TRUE
        WHERE 'close_adj' = ANY (p.metrics)
          AND (NOT p.default_metrics OR q.in_universe)
    ) d
    CROSS JOIN LATERAL api.close_adj_status(d.isin, d.ticker) s
),
adj_ok AS (
    SELECT a.ticker, a.isin, a.anchor
    FROM adj_ids a
    JOIN params p ON TRUE
    WHERE api.assert_close_adj('panel', a.ticker, a.isin, p.d0, p.d1)
),
-- close_return honesty guards (SERVING.md step 4):
--   * daily: the previous SESSION must be within 7 calendar days. Carnaval
--     and year-end close the exchange for up to ~5 days; anything longer is
--     a listing gap (halt, delisting window, illiquid re-print) and a
--     "daily" return across it is a multi-week move wearing a daily label.
--     NULL, not a fabricated smooth number.
--   * both grains: the quotation factor must not have changed between the
--     two prints. A fatcot flip (measured live: GOLL2 1000->1, IBOV11
--     1->100, on 2025-03-05) rescales the quote by that factor and reports a ~±99.9%
--     "return" with no market move behind it.
--   * both grains: a share-count event between the two prints adjusts the
--     previous close (#396 step 2, owner decision 2026-10-04). A DESDOBRAMENTO,
--     GRUPAMENTO or BONIFICACAO changes how many shares there are, not what
--     they are worth, so the previous close is divided by the event's share
--     ratio (1 + factor/100 for DESDOBRAMENTO and BONIFICACAO, factor for
--     GRUPAMENTO, events between the prints multiplied: B3's rule, the one
--     api.close_adj_ratio uses) and the return is close / adjusted previous
--     close - 1. The owner's example: 100.00 the day before a 1:4 split
--     (factor 300) is 25.00 adjusted, so a 26.00 close is +4%, not -74%;
--     BBAS3's 2:1 split, 56.46 -> 27.91, is -1.13%, not -50.57%. An event goes
--     ex the session after its last_date_prior, so it lies between
--     prev_obs_date and obs_date when prev_obs_date <= last_date_prior <
--     obs_date. On the monthly grain the event may sit anywhere between the
--     two month-end prints. Still NULL, never a guess: an event with an
--     unreadable factor (NULL or a ratio <= 0), and one label on one date
--     published with two factors (the rows cannot say which applies). Only
--     events b3_corporate_event holds adjust a return; the sweep that fills
--     it is per issuer since the tape start, and an event it has not stored
--     yet still reads as a return (api.close_adj_status reports the proof).
quote_ret AS (
    SELECT
        r.ticker,
        r.period,
        r.asset_class,
        CASE
            WHEN r.prev_quotation_factor IS DISTINCT FROM r.quotation_factor
            THEN NULL
            WHEN ev.n_events > ev.n_readable OR ev.n_events > ev.n_label_dates
            THEN NULL
            WHEN (SELECT freq FROM params) = 'day'
             AND r.prev_obs_date >= r.period - 7
            THEN r.close * ev.share_ratio / NULLIF(r.prev_close, 0) - 1
            WHEN (SELECT freq FROM params) = 'month'
             AND r.prev_period = (r.period - INTERVAL '1 month')::date
            THEN r.close * ev.share_ratio / NULLIF(r.prev_close, 0) - 1
            ELSE NULL
        END AS close_return
    FROM (
        SELECT
            ticker,
            period,
            asset_class,
            isin,
            obs_date,
            quotation_factor,
            close,
            lag(quotation_factor) OVER w AS prev_quotation_factor,
            lag(obs_date)         OVER w AS prev_obs_date,
            lag(period)           OVER w AS prev_period,
            lag(close)            OVER w AS prev_close
        FROM quote_px
        WINDOW w AS (PARTITION BY ticker ORDER BY period)
    ) r
    -- The share-count events between the two prints. DISTINCT: a republished
    -- event can come back as a second row that differs only in approved_on.
    -- asset_issued is in it so one label on one date paid in two assets counts
    -- twice and is refused like two factors are (#353).
    -- No event gives share_ratio 1 and leaves the return as it was.
    CROSS JOIN LATERAL (
        SELECT
            count(*) AS n_events,
            count(*) FILTER (WHERE x.share_ratio > 0) AS n_readable,
            count(DISTINCT (x.label, x.last_date_prior)) AS n_label_dates,
            COALESCE(exp(sum(ln(CASE WHEN x.share_ratio > 0 THEN x.share_ratio END))), 1) AS share_ratio
        FROM (
            SELECT DISTINCT
                e.label,
                e.last_date_prior,
                e.asset_issued,
                CASE e.label WHEN 'GRUPAMENTO' THEN e.factor ELSE 1 + e.factor / 100 END AS share_ratio
            FROM public.b3_corporate_event e
            WHERE e.isin = r.isin
              AND e.label IN ('DESDOBRAMENTO', 'GRUPAMENTO', 'BONIFICACAO')
              AND e.last_date_prior >= r.prev_obs_date
              AND e.last_date_prior < r.obs_date
        ) x
    ) ev
),
-- Derivative segments (options tpmerc 070/080, termo 030). Disjoint from the
-- vista arms by tpmerc, so existing arm output is untouched — before these
-- arms an option codneg simply resolved to nothing. Month = last session in
-- the month, the same real-print convention as quote_month. COTAHIST's grain
-- for these rows includes codbdi (and prazot for termo): the panel is 1-D per
-- (id, date, metric), so a within-session tie is cut deterministically
-- (DISTINCT ON + full ORDER BY — for termo the shortest term wins, ordered
-- length-then-text so digit strings sort numerically without a cast) rather
-- than aggregated into a synthetic number. option_history / termo_history
-- expose the full grain.
option_month AS (
    SELECT DISTINCT ON (b.codneg, date_trunc('month', b.trade_date))
        b.codneg,
        date_trunc('month', b.trade_date)::date AS period,
        b.preco_fechamento AS close,
        b.volume
    FROM public.b3_cotahist b
    JOIN params p ON TRUE
    WHERE p.freq = 'month'
      AND b.tpmerc IN ('070', '080')
      AND b.trade_date BETWEEN p.d0 AND p.d1
      AND b.codneg IN (SELECT ticker FROM tickers)
    ORDER BY b.codneg, date_trunc('month', b.trade_date), b.trade_date DESC, b.codbdi
),
option_day AS (
    SELECT DISTINCT ON (b.codneg, b.trade_date)
        b.codneg,
        b.trade_date AS period,
        b.preco_fechamento AS close,
        b.volume
    FROM public.b3_cotahist b
    JOIN params p ON TRUE
    WHERE p.freq = 'day'
      AND b.tpmerc IN ('070', '080')
      AND b.trade_date BETWEEN p.d0 AND p.d1
      AND b.codneg IN (SELECT ticker FROM tickers)
    ORDER BY b.codneg, b.trade_date, b.codbdi
),
option_px AS (
    SELECT * FROM option_month
    UNION ALL
    SELECT * FROM option_day
),
termo_month AS (
    SELECT DISTINCT ON (b.codneg, date_trunc('month', b.trade_date))
        b.codneg,
        date_trunc('month', b.trade_date)::date AS period,
        b.preco_fechamento AS close,
        b.volume
    FROM public.b3_cotahist b
    JOIN params p ON TRUE
    WHERE p.freq = 'month'
      AND b.tpmerc = '030'
      AND b.trade_date BETWEEN p.d0 AND p.d1
      AND b.codneg IN (SELECT ticker FROM tickers)
    ORDER BY b.codneg, date_trunc('month', b.trade_date), b.trade_date DESC,
             length(b.prazot), b.prazot, b.codbdi
),
termo_day AS (
    SELECT DISTINCT ON (b.codneg, b.trade_date)
        b.codneg,
        b.trade_date AS period,
        b.preco_fechamento AS close,
        b.volume
    FROM public.b3_cotahist b
    JOIN params p ON TRUE
    WHERE p.freq = 'day'
      AND b.tpmerc = '030'
      AND b.trade_date BETWEEN p.d0 AND p.d1
      AND b.codneg IN (SELECT ticker FROM tickers)
    ORDER BY b.codneg, b.trade_date, length(b.prazot), b.prazot, b.codbdi
),
termo_px AS (
    SELECT * FROM termo_month
    UNION ALL
    SELECT * FROM termo_day
),
-- B3 futures (B8 phase B): b3_futures_settlement, the B3 Price Report, DI1
-- from 2018-01-02. Ids are B3's own contract codes (DI1F27), never split into
-- root and maturity here. Futures are not on the COTAHIST tape, so such a code
-- resolved to nothing in the arms above, and these rows are disjoint from
-- them. Month = last session in the month, the real-print convention of
-- quote_month; (trade_date, ticker) is the table's key, so DISTINCT ON has no
-- tie to cut. DI1 publishes its settlement twice, as a rate (% a.a., 252
-- business days) and as a PU, so each is its own metric: one "settlement"
-- would not say which. Only a settlement B3 marks F (AdjstdQtStin) is served:
-- the panel has no status column, and the 23 P sessions (2018-02 to 2018-05)
-- stay in future_series and future_curve, which carry settlement_status.
future_month AS (
    SELECT DISTINCT ON (f.ticker, date_trunc('month', f.trade_date))
        f.ticker,
        date_trunc('month', f.trade_date)::date AS period,
        f.settlement_rate,
        f.settlement_price,
        f.open_interest
    FROM public.b3_futures_settlement f
    JOIN params p ON TRUE
    WHERE p.freq = 'month'
      AND f.settlement_status = 'F'
      AND f.trade_date BETWEEN p.d0 AND p.d1
      AND f.ticker IN (SELECT ticker FROM tickers)
    ORDER BY f.ticker, date_trunc('month', f.trade_date), f.trade_date DESC
),
future_day AS (
    SELECT f.ticker, f.trade_date AS period,
           f.settlement_rate, f.settlement_price, f.open_interest
    FROM public.b3_futures_settlement f
    JOIN params p ON TRUE
    WHERE p.freq = 'day'
      AND f.settlement_status = 'F'
      AND f.trade_date BETWEEN p.d0 AND p.d1
      AND f.ticker IN (SELECT ticker FROM tickers)
),
future_px AS (
    SELECT * FROM future_month
    UNION ALL
    SELECT * FROM future_day
),
-- fact_fund_monthly does NOT use one period convention. Measured 2026-08-27:
--   fi / fii / fiagro  first-of-month   2026-07-01
--   fidc               month-END        2026-07-31   (178,237 rows)
--   fip                year-END, annual 2026-12-31   ( 13,293 rows)
-- The equity arms above stamp date_trunc('month', trade_date), i.e. first of
-- month. Passing f.period through raw therefore put a FIDC on 2026-07-31 and an
-- FI or a ticker on 2026-07-01 — different rows of the same panel, for the same
-- month. Pivoted wide, those columns never co-occur, so the catalog's own
-- headline example ("how does PETR4 relate to delinquency in this FIDC?")
-- returned a matrix with zero overlapping observations. No error, no null — the
-- dates simply never met.
--
-- Normalising to first-of-month is a presentation choice, not a data edit: the
-- landing tables and fact_fund_monthly keep the period CVM published, and
-- api.funds / fund_nav still serve it verbatim. Only the panel, whose whole
-- purpose is aligning ids onto shared dates, snaps them together.
--
-- The window filter reads the normalised value too. On the raw column,
-- p_to = '2026-07-01' excluded FIDC's 2026-07-31 row even though July was
-- squarely inside the requested range — the same bug, cutting the newest month
-- off every FIDC panel.
fund_rows AS (
    SELECT
        f.cnpj,
        f.entity_type,
        date_trunc('month', f.period)::date AS period,
        f.vl_patrim_liq AS nav,
        f.vl_quota AS quota,
        f.vl_inadimpl AS delinquency,
        f.pct_yield_mes AS yield,
        f.captc_mes AS inflows,
        f.resg_mes AS redemptions,
        f.nr_cotst AS quotaholders
    FROM public.fact_fund_monthly f
    JOIN params p ON TRUE
    WHERE p.freq = 'month'
      AND date_trunc('month', f.period)::date >= date_trunc('month', p.d0)::date
      -- Upper bound, two regimes (see p_to's comment): an explicit p_to is
      -- served verbatim; the NULL default clamps each row to its own entity
      -- family's latest COMPLETE period (raw-convention comparison — the
      -- completeness matview keeps FIDC month-end / FIP year-end periods, so
      -- f.period compares against a bound in the same convention).
      AND (
            (p.d1_explicit IS NOT NULL
             AND date_trunc('month', f.period)::date
                 <= date_trunc('month', p.d1_explicit)::date)
         OR (p.d1_explicit IS NULL
             AND f.period <= public.latest_complete_period(f.entity_type))
      )
      AND f.cnpj IN (SELECT cnpj FROM cnpjs)
      AND (p.entity_type IS NULL OR f.entity_type = p.entity_type)
),
-- FIDC concentration arms (migration 38). Same month normalisation and the
-- same two-regime upper bound as fund_rows; the family is fidc by
-- construction, so p_entity_type either is NULL, is 'fidc', or excludes
-- these rows. Read only when asked for: the metric test is in the WHERE so
-- a default (close, nav) panel never touches these tables.
fidc_book AS (
    SELECT s.cnpj,
           date_trunc('month', s.period)::date AS period,
           s.vl_carteira AS receivables
    FROM public.cvm_fidc_setor s
    JOIN params p ON TRUE
    WHERE p.freq = 'month'
      AND 'receivables' = ANY (p.metrics)
      AND (p.entity_type IS NULL OR p.entity_type = 'fidc')
      AND s.cnpj IN (SELECT cnpj FROM cnpjs)
      AND date_trunc('month', s.period)::date >= date_trunc('month', p.d0)::date
      AND (
            (p.d1_explicit IS NOT NULL
             AND date_trunc('month', s.period)::date
                 <= date_trunc('month', p.d1_explicit)::date)
         OR (p.d1_explicit IS NULL
             AND s.period <= public.latest_complete_period('fidc'))
      )
),
-- top1 = the rank-1 row as filed; top25 = the sum of whatever ranks the fund
-- filed (1..n, n <= 25) — nothing imputed for ranks it did not file. The
-- rank is CVM's (seq), never recomputed from valor.
fidc_sacado AS (
    SELECT k.cnpj,
           date_trunc('month', k.period)::date AS period,
           MAX(k.valor) FILTER (WHERE k.seq = 1) AS sacado_top1,
           SUM(k.valor)                          AS sacado_top25
    FROM public.cvm_fidc_sacado k
    JOIN params p ON TRUE
    WHERE p.freq = 'month'
      AND ('sacado_top1' = ANY (p.metrics) OR 'sacado_top25' = ANY (p.metrics))
      AND (p.entity_type IS NULL OR p.entity_type = 'fidc')
      AND k.cnpj IN (SELECT cnpj FROM cnpjs)
      AND date_trunc('month', k.period)::date >= date_trunc('month', p.d0)::date
      AND (
            (p.d1_explicit IS NOT NULL
             AND date_trunc('month', k.period)::date
                 <= date_trunc('month', p.d1_explicit)::date)
         OR (p.d1_explicit IS NULL
             AND k.period <= public.latest_complete_period('fidc'))
      )
    GROUP BY k.cnpj, date_trunc('month', k.period)::date
)
, ranked (id, id_type, asset_class, date, metric, value, source) AS (
SELECT q.ticker, 'ticker'::text, q.asset_class, q.period, 'close'::text, q.close, 'b3_cotahist'::text
FROM quote_px q JOIN params p ON TRUE
WHERE 'close' = ANY (p.metrics)
  AND (NOT p.default_metrics OR NOT q.in_universe)
UNION ALL
SELECT q.ticker, 'ticker', q.asset_class, q.period, 'close_adj',
       round(q.close_unit / api.close_adj_ratio(q.isin, q.obs_date, a.anchor), 6), 'b3_cotahist'
FROM quote_px q
JOIN adj_ok a ON a.ticker = q.ticker AND a.isin IS NOT DISTINCT FROM q.isin
WHERE q.close_unit IS NOT NULL
UNION ALL
SELECT q.ticker, 'ticker', q.asset_class, q.period, 'close_unit', q.close_unit, 'b3_cotahist'
FROM quote_px q JOIN params p ON TRUE
WHERE 'close_unit' = ANY (p.metrics)
  AND q.close_unit IS NOT NULL
UNION ALL
SELECT q.ticker, 'ticker', q.asset_class, q.period, 'volume', q.volume, 'b3_cotahist'
FROM quote_px q JOIN params p ON TRUE
WHERE 'volume' = ANY (p.metrics)
UNION ALL
SELECT r.ticker, 'ticker', r.asset_class, r.period, 'close_return', r.close_return, 'b3_cotahist'
FROM quote_ret r JOIN params p ON TRUE
WHERE 'close_return' = ANY (p.metrics)
  AND r.close_return IS NOT NULL
UNION ALL
SELECT o.codneg, 'option', 'derivative', o.period, 'close', o.close, 'b3_cotahist'
FROM option_px o JOIN params p ON TRUE
WHERE 'close' = ANY (p.metrics)
UNION ALL
SELECT o.codneg, 'option', 'derivative', o.period, 'volume', o.volume, 'b3_cotahist'
FROM option_px o JOIN params p ON TRUE
WHERE 'volume' = ANY (p.metrics)
UNION ALL
SELECT t.codneg, 'termo', 'derivative', t.period, 'close', t.close, 'b3_cotahist'
FROM termo_px t JOIN params p ON TRUE
WHERE 'close' = ANY (p.metrics)
UNION ALL
SELECT t.codneg, 'termo', 'derivative', t.period, 'volume', t.volume, 'b3_cotahist'
FROM termo_px t JOIN params p ON TRUE
WHERE 'volume' = ANY (p.metrics)
UNION ALL
SELECT u.ticker, 'future', 'derivative', u.period, 'settlement_rate', u.settlement_rate, 'b3_price_report'
FROM future_px u JOIN params p ON TRUE
WHERE ('settlement_rate' = ANY (p.metrics) OR p.default_metrics)
  AND u.settlement_rate IS NOT NULL
UNION ALL
SELECT u.ticker, 'future', 'derivative', u.period, 'settlement_price', u.settlement_price, 'b3_price_report'
FROM future_px u JOIN params p ON TRUE
WHERE 'settlement_price' = ANY (p.metrics)
UNION ALL
SELECT u.ticker, 'future', 'derivative', u.period, 'open_interest', u.open_interest::numeric, 'b3_price_report'
FROM future_px u JOIN params p ON TRUE
WHERE 'open_interest' = ANY (p.metrics)
  AND u.open_interest IS NOT NULL
UNION ALL
SELECT f.cnpj, 'cnpj', f.entity_type, f.period, 'nav', f.nav, 'cvm'
FROM fund_rows f JOIN params p ON TRUE
WHERE 'nav' = ANY (p.metrics) AND f.nav IS NOT NULL
UNION ALL
SELECT f.cnpj, 'cnpj', f.entity_type, f.period, 'quota', f.quota, 'cvm'
FROM fund_rows f JOIN params p ON TRUE
WHERE 'quota' = ANY (p.metrics) AND f.quota IS NOT NULL
UNION ALL
SELECT f.cnpj, 'cnpj', f.entity_type, f.period, 'delinquency', f.delinquency, 'cvm'
FROM fund_rows f JOIN params p ON TRUE
WHERE 'delinquency' = ANY (p.metrics) AND f.delinquency IS NOT NULL
UNION ALL
SELECT f.cnpj, 'cnpj', f.entity_type, f.period, 'yield', f.yield, 'cvm'
FROM fund_rows f JOIN params p ON TRUE
WHERE 'yield' = ANY (p.metrics) AND f.yield IS NOT NULL
UNION ALL
SELECT f.cnpj, 'cnpj', f.entity_type, f.period, 'inflows', f.inflows, 'cvm'
FROM fund_rows f JOIN params p ON TRUE
WHERE 'inflows' = ANY (p.metrics) AND f.inflows IS NOT NULL
UNION ALL
SELECT f.cnpj, 'cnpj', f.entity_type, f.period, 'redemptions', f.redemptions, 'cvm'
FROM fund_rows f JOIN params p ON TRUE
WHERE 'redemptions' = ANY (p.metrics) AND f.redemptions IS NOT NULL
UNION ALL
SELECT f.cnpj, 'cnpj', f.entity_type, f.period, 'quotaholders', f.quotaholders::numeric, 'cvm'
FROM fund_rows f JOIN params p ON TRUE
WHERE 'quotaholders' = ANY (p.metrics) AND f.quotaholders IS NOT NULL
UNION ALL
SELECT b.cnpj, 'cnpj', 'fidc', b.period, 'receivables', b.receivables, 'cvm'
FROM fidc_book b
WHERE b.receivables IS NOT NULL
UNION ALL
SELECT k.cnpj, 'cnpj', 'fidc', k.period, 'sacado_top1', k.sacado_top1, 'cvm'
FROM fidc_sacado k JOIN params p ON TRUE
WHERE 'sacado_top1' = ANY (p.metrics) AND k.sacado_top1 IS NOT NULL
UNION ALL
SELECT k.cnpj, 'cnpj', 'fidc', k.period, 'sacado_top25', k.sacado_top25, 'cvm'
FROM fidc_sacado k JOIN params p ON TRUE
WHERE 'sacado_top25' = ANY (p.metrics) AND k.sacado_top25 IS NOT NULL
)
-- One page + one. ORDER BY (date, id, metric, asset_class) — the cursor key
-- — makes both the page and the cut deterministic. Columns by position:
-- 1 id, 3 asset_class, 4 date, 5 metric.
, page AS (
    SELECT r.*
    FROM ranked r
    JOIN params p ON TRUE
    WHERE p.after_date IS NULL
       OR (r.date, r.id, r.metric, COALESCE(r.asset_class, ''))
          > (p.after_date, p.after_id, p.after_metric, COALESCE(p.after_class, ''))
    ORDER BY 4, 1, 5, 3
    LIMIT 1001
)
-- assert_row_cap sees the 1001st row and REFUSES (22023) unless the caller
-- is paging: a panel over the page is never trimmed to look complete. The
-- subquery is uncorrelated, so it is evaluated once, not per row.
SELECT g.id, g.id_type, g.asset_class, g.date, g.metric, g.value, g.source
FROM page g
WHERE api.assert_row_cap((SELECT count(*) FROM page), (SELECT paging FROM params), 'panel')
ORDER BY 4, 1, 5, 3
LIMIT 1000;
$$;

COMMENT ON FUNCTION api.panel(TEXT[], TEXT[], DATE, DATE, TEXT, TEXT, NUMERIC, INT, TEXT) IS
    'Long panel for correlation/factor work. Mix tickers, option/termo codnegs, B3 futures contract codes (DI1F27) + CNPJs. Grain is (id, asset_class, date, metric): a CNPJ filing under two families yields one row per family unless p_entity_type narrows it. No ffill. p_metrics NULL = each family''s default: close_adj for shares and units, close for other tickers, options and termo, settlement_rate for futures, nav for funds. Futures (b3_price_report, DI1 from 2018-01-02) serve settlement_rate (% a.a., 252 business days), settlement_price (the PU) and open_interest, only for a settlement B3 marks final (F); future_series carries the status. close_adj is quote_history''s adjusted close (splits, groupings, bonus shares; anchored to the latest session) and a window it cannot adjust REFUSES 22023 naming ticker, period and cause; close stays raw. Quotes follow the instrument across boards. close_return is p_t/p_{t-1}-1, cash tickers only, with the previous close divided by the share ratio of any split, grouping or bonus (DESDOBRAMENTO, GRUPAMENTO, BONIFICACAO) between the two prints, so a share-count change never reads as a return (a 1:4 split from 100.00 to 26.00 is +4%). It is NULL across calendar gaps, across a quotation-factor change and across an event whose factor is unreadable or published twice with two factors; it is a price return, not a total return (close_adj holds the adjusted level). Row cap: more than 1000 rows RAISES 22023 (never trimmed) unless p_after pages: '''' = first page, ''date|id|metric|asset_class'' = next; a page shorter than 1000 is the last. Universe mode: p_ids empty + p_entity_type walks a whole family (optionally p_min_nav, p_min_months), signed-in callers only.';

REVOKE ALL ON FUNCTION api.panel(TEXT[], TEXT[], DATE, DATE, TEXT, TEXT, NUMERIC, INT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.panel(TEXT[], TEXT[], DATE, DATE, TEXT, TEXT, NUMERIC, INT, TEXT) TO anon, authenticated;


-- Signature change (trailing tickers column): drop the old shape first.
DROP FUNCTION IF EXISTS api.lookup(TEXT);

CREATE OR REPLACE FUNCTION api.lookup(
    p_query TEXT
)
RETURNS TABLE (
    id          TEXT,
    id_type     TEXT,
    asset_class TEXT,
    name        TEXT,
    isin        TEXT,
    cnpj        TEXT,
    -- The company's B3 tickers from vw_company_ticker (CVM's published FCA
    -- valores-mobiliários map, migration 25) — the CNPJ and the ticker come
    -- from the same published row, so nothing is name-matched or inferred.
    -- NULL for non-company rows and for companies with no active listing.
    tickers     TEXT[]
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    -- Hardening (SERVING.md step 5):
    --   * LIKE metacharacters in the query are escaped, so a stray '%'/'_' in
    --     a pasted name narrows nothing and cannot scan-explode the ILIKE;
    --   * results are RANKED (exact id match, then name-prefix, then
    --     name-contains) before the LIMIT — the previous bare LIMIT 20 cut an
    --     arbitrary 20 rows, so an exact ticker hit could lose its seat to
    --     twenty fuzzy name matches;
    --   * name ILIKE is backed by pg_trgm (migration 24: cia_company;
    --     11_indexes.sql: dim_fund).
    WITH q AS (
        SELECT btrim(COALESCE(p_query, '')) AS raw,
               replace(replace(replace(btrim(COALESCE(p_query, '')),
                   '\', '\\'), '%', '\%'), '_', '\_') AS like_safe
    ),
    hits AS (
        SELECT t.ticker AS id, 'ticker'::text AS id_type, t.asset_class,
               t.short_name AS name, t.isin, NULL::text AS cnpj,
               NULL::text[] AS tickers,
               0 AS rank
        FROM (
            SELECT DISTINCT ON (ticker)
                ticker, asset_class, short_name, isin
            FROM api.quotes, q
            WHERE ticker = upper(q.raw) OR isin = upper(q.raw)
            ORDER BY ticker, trade_date DESC
        ) t
        UNION ALL
        SELECT d.cnpj, 'cnpj', d.entity_type, d.fund_name, NULL, d.cnpj,
               NULL::text[],
               CASE
                   WHEN d.cnpj = regexp_replace(q.raw, '[^0-9]', '', 'g') THEN 0
                   WHEN d.fund_name ILIKE q.like_safe || '%' ESCAPE '\' THEN 1
                   ELSE 2
               END
        FROM public.dim_fund d, q
        WHERE d.cnpj = regexp_replace(q.raw, '[^0-9]', '', 'g')
           OR d.fund_name ILIKE '%' || q.like_safe || '%' ESCAPE '\'
        UNION ALL
        SELECT c.cd_cvm, 'cd_cvm', 'cia', c.denom_cia, NULL, c.cnpj_cia,
               -- Published mapping only (FCA): active listings, deterministic
               -- order. NULL (not an empty array) when the company has no
               -- active listed ticker.
               (SELECT NULLIF(array_agg(vt.codneg ORDER BY vt.codneg), '{}')
                FROM public.vw_company_ticker vt
                WHERE vt.cnpj_cia = c.cnpj_cia AND vt.is_active),
               CASE
                   WHEN c.cnpj_cia = regexp_replace(q.raw, '[^0-9]', '', 'g') THEN 0
                   WHEN c.cd_cvm = q.raw THEN 0
                   WHEN c.denom_cia ILIKE q.like_safe || '%' ESCAPE '\' THEN 1
                   ELSE 2
               END
        FROM public.cia_company c, q
        WHERE c.cnpj_cia = regexp_replace(q.raw, '[^0-9]', '', 'g')
           OR c.cd_cvm = q.raw
           OR c.denom_cia ILIKE '%' || q.like_safe || '%' ESCAPE '\'
    )
    SELECT h.id, h.id_type, h.asset_class, h.name, h.isin, h.cnpj, h.tickers
    FROM hits h
    ORDER BY h.rank, h.name, h.id
    LIMIT 20;
$$;

-- Option/termo codnegs are deliberately NOT resolved here: lookup is a
-- name-resolution surface and option series have no names — only the codneg
-- itself, which the caller already holds. Adding a ~100k-id derivative
-- namespace to a name resolver would bloat every query for zero resolution
-- power. Discover derivative ids via api.option_chain(prefix) — api.universe
-- was dropped (migration 31), so option_chain is now the only route, and it
-- requires a codneg prefix of at least 3 characters: there is no cold browse
-- of the derivative namespace.
COMMENT ON FUNCTION api.lookup(TEXT) IS
    'Resolve ticker / ISIN / CNPJ / company name. Company rows carry their B3 tickers from CVM''s published FCA valores-mobiliários map (vw_company_ticker) — never a name match, never inferred. Does not resolve option/termo codnegs (no names to resolve — use option_chain, which needs a 3-character prefix).';

REVOKE ALL ON FUNCTION api.lookup(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.lookup(TEXT) TO anon, authenticated;

-- ---------------------------------------------------------------------------
-- Listed companies (CIA Aberta) — financial statements
-- ---------------------------------------------------------------------------

-- Internal: resolve a caller id to one company. Never granted.
--
-- CREATE OR REPLACE cannot widen a RETURNS TABLE, so the functions in this
-- section are dropped in reverse dependency order first. Without this, adding a
-- column to any of them fails on an already-deployed database with
-- "cannot change return type of existing function" — green on a fresh CI
-- cluster and red on Supabase, which is the worst way to find out.
DROP FUNCTION IF EXISTS api.financial_statement_history(TEXT, TEXT, DATE, DATE, TEXT, TEXT);
DROP FUNCTION IF EXISTS api.company_financials(TEXT, DATE, DATE, TEXT);
DROP FUNCTION IF EXISTS api.financials(TEXT, TEXT, DATE, DATE, TEXT, TEXT);
DROP FUNCTION IF EXISTS api.cia_statement_rows(TEXT, DATE, DATE, TEXT, TEXT, TEXT);
DROP FUNCTION IF EXISTS api.company_ref(TEXT);

CREATE OR REPLACE FUNCTION api.company_ref(p_id TEXT)
RETURNS TABLE (cd_cvm TEXT, cnpj TEXT, company TEXT, ticker TEXT,
               setor TEXT, segmento TEXT)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    WITH q AS (
        SELECT upper(btrim(COALESCE(p_id, ''))) AS raw,
               regexp_replace(COALESCE(p_id, ''), '[^0-9]', '', 'g') AS digits
    ),
    hits AS (
        -- A ticker resolves ONLY through CVM's published FCA map, active
        -- listings only: the CNPJ and the codneg arrive on the same filed row,
        -- so nothing here is name-matched or inferred.
        SELECT c.cd_cvm, c.cnpj_cia, c.denom_cia, vt.codneg AS codneg,
               c.setor, c.segmento, 0 AS rank
        FROM q
        JOIN public.vw_company_ticker vt ON vt.codneg = q.raw AND vt.is_active
        JOIN public.cia_company c ON c.cnpj_cia = vt.cnpj_cia
        UNION ALL
        SELECT c.cd_cvm, c.cnpj_cia, c.denom_cia, NULL::text,
               c.setor, c.segmento, 1
        FROM q JOIN public.cia_company c
          ON length(q.digits) = 14 AND c.cnpj_cia = q.digits
        UNION ALL
        SELECT c.cd_cvm, c.cnpj_cia, c.denom_cia, NULL::text,
               c.setor, c.segmento, 2
        FROM q JOIN public.cia_company c ON c.cd_cvm = q.raw
    )
    SELECT h.cd_cvm, h.cnpj_cia, h.denom_cia, h.codneg, h.setor, h.segmento
    FROM hits h
    ORDER BY h.rank, h.cd_cvm
    LIMIT 1;
$$;

REVOKE ALL ON FUNCTION api.company_ref(TEXT) FROM PUBLIC;

-- Internal: the filtered statement rows both public functions read. Uncapped
-- on purpose — api.financials caps the long result, api.company_financials
-- aggregates first. Keeping one body means the honesty filters below cannot
-- drift between the two surfaces.
CREATE OR REPLACE FUNCTION api.cia_statement_rows(
    p_id        TEXT,
    p_from      DATE,
    p_to        DATE,
    p_scope     TEXT,
    p_doc_type  TEXT,
    p_statement TEXT,
    -- NULL = latest stored version of every document, which is NOT
    -- point-in-time. A date T reads only what CVM had received before T
    -- (cia_filing.dt_receb < T), then keeps the highest remaining version of
    -- each document (#414; the recipe is #375's,
    -- docs/reference/research/pit-fundamentals.md).
    p_as_of     DATE
)
RETURNS TABLE (
    cd_cvm        TEXT,
    cnpj          TEXT,
    company       TEXT,
    ticker        TEXT,
    setor         TEXT,
    segmento      TEXT,
    doc_type      TEXT,
    statement     TEXT,
    scope         TEXT,
    ref_date      DATE,
    period_start  DATE,
    period_end    DATE,
    period_months INT,
    account_code  TEXT,
    account_name  TEXT,
    value         NUMERIC,
    version       INT
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    WITH ref AS MATERIALIZED (
        -- setor/segmento ride along from company_ref because CVM's chart of
        -- accounts is sector-specific: the same cd_conta is a different
        -- quantity for a bank and an industrial filer. A caller computing a
        -- median, rank or percentile needs the partition key on the row, not
        -- a second round trip. It is a partition key, not a display label.
        --
        -- Resolve the company once, before cia_account is touched (#536, the
        -- shape fixed in api.financial_statement_history by #531).
        -- api.company_ref is a set-returning function the planner estimates
        -- at 1,000 rows, so joined directly the company never reached the
        -- index condition and a whole cia_account partition could be scanned.
        -- The scalar subquery below hands the planner one cd_cvm. Zero or one
        -- row either way, same rows out.
        SELECT r.cd_cvm, r.cnpj, r.company, r.ticker, r.setor, r.segmento
        FROM api.company_ref(p_id) r
    ),
    win AS (
        SELECT COALESCE(p_from, CURRENT_DATE - 1825) AS d0,
               COALESCE(p_to,   CURRENT_DATE)        AS d1,
               lower(btrim(COALESCE(p_scope, 'con'))) AS scope
    ),
    rows_ AS (
        SELECT
            r.cd_cvm AS r_cd_cvm, r.cnpj AS r_cnpj,
            r.company AS r_company, r.ticker AS r_ticker,
            r.setor AS r_setor, r.segmento AS r_segmento,
            a.doc_type, a.grupo, a.escopo, a.dt_refer,
            a.dt_ini_exerc, a.dt_fim_exerc,
            a.cd_conta, a.ds_conta, a.vl_conta, a.versao,
            -- A restatement re-files the document under a higher versao and
            -- the old rows stay (they are part of the natural key). Serving
            -- both would report the same quarter twice with different
            -- numbers, so only the newest version of each statement is kept.
            MAX(a.versao) OVER (
                PARTITION BY a.doc_type, a.grupo, a.escopo, a.dt_refer
            ) AS latest_versao
        FROM public.cia_account a
        JOIN ref r ON r.cd_cvm = a.cd_cvm
                  AND a.cd_cvm = (SELECT x.cd_cvm FROM ref x)
        JOIN win w ON TRUE
        WHERE
            -- 'ÚLTIMO' is the period the document is FOR; 'PENÚLTIMO' is the
            -- prior-year comparative printed beside it. Accented, verbatim
            -- from the latin-1 source: an unaccented comparison matches zero
            -- rows.
              a.ordem_exerc = 'ÚLTIMO'
          AND a.escopo = w.scope
          AND a.dt_refer BETWEEN w.d0 AND w.d1
          AND (p_statement IS NULL OR a.grupo    = upper(btrim(p_statement)))
          AND (p_doc_type  IS NULL OR a.doc_type = lower(btrim(p_doc_type)))
          -- As of T: a document counts only if its exact (company, type,
          -- reference date, version) header was received before T. A document
          -- with no header or a NULL receipt date is dropped, never assumed
          -- early. This runs BEFORE the MAX(versao) window above, so the
          -- "highest remaining version" is the highest one known at T.
          AND (p_as_of IS NULL OR EXISTS (
                SELECT 1 FROM public.cia_filing f
                WHERE f.cd_cvm   = a.cd_cvm
                  AND f.doc_type = a.doc_type
                  AND f.dt_refer = a.dt_refer
                  AND f.versao   = a.versao
                  AND f.dt_receb < p_as_of))
    )
    SELECT
        x.r_cd_cvm, x.r_cnpj, x.r_company, x.r_ticker,
        x.r_setor, x.r_segmento,
        x.doc_type, x.grupo, x.escopo,
        x.dt_refer, x.dt_ini_exerc, x.dt_fim_exerc,
        -- An ITR prints the same account twice under one dt_refer: once for
        -- the three months and once year-to-date, separated ONLY by
        -- dt_ini_exerc. Publishing the span is what stops a caller adding a
        -- quarter to a cumulative figure; it is never collapsed here.
        CASE
            WHEN x.dt_ini_exerc IS NOT NULL AND x.dt_fim_exerc IS NOT NULL
            THEN (EXTRACT(YEAR  FROM AGE(x.dt_fim_exerc + 1, x.dt_ini_exerc)) * 12
                + EXTRACT(MONTH FROM AGE(x.dt_fim_exerc + 1, x.dt_ini_exerc)))::int
        END AS period_months,
        x.cd_conta, x.ds_conta, x.vl_conta, x.versao
    FROM rows_ x
    WHERE x.versao = x.latest_versao;
$$;

REVOKE ALL ON FUNCTION api.cia_statement_rows(TEXT, DATE, DATE, TEXT, TEXT, TEXT, DATE) FROM PUBLIC;

DROP FUNCTION IF EXISTS api.financials(TEXT, TEXT, DATE, DATE, TEXT, TEXT);
CREATE OR REPLACE FUNCTION api.financials(
    p_id        TEXT,
    p_statement TEXT DEFAULT NULL,
    p_from      DATE DEFAULT (CURRENT_DATE - 1825),
    p_to        DATE DEFAULT CURRENT_DATE,
    p_scope     TEXT DEFAULT 'con',
    p_doc_type  TEXT DEFAULT NULL,
    p_as_of     DATE DEFAULT NULL
)
RETURNS TABLE (
    id            TEXT,
    id_type       TEXT,
    cnpj          TEXT,
    company       TEXT,
    ticker        TEXT,
    doc_type      TEXT,
    statement     TEXT,
    scope         TEXT,
    ref_date      DATE,
    period_start  DATE,
    period_end    DATE,
    period_months INT,
    account_code  TEXT,
    account_name  TEXT,
    value         NUMERIC,
    version       INT,
    source        TEXT,
    -- Appended, not inserted mid-row, so an existing positional consumer is
    -- unaffected. CVM's chart is sector-specific, so these are the partition
    -- key for any median/rank/percentile a caller computes over several
    -- companies — never a display label. See docs/reference/CIA_DATA_MAP.md.
    setor         TEXT,
    segmento      TEXT
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    -- One page + one. The 1001st row is what makes "over the page"
    -- detectable; assert_row_cap then REFUSES (22023) rather than handing
    -- back a truncated series that looks complete. This function has no
    -- cursor, so a caller over the page narrows the window instead.
    -- The explicit column list lets the outer ORDER BY name columns as
    -- declared, which also dodges OUT-parameter ambiguity.
    WITH page (id, id_type, cnpj, company, ticker, doc_type, statement, scope, ref_date, period_start, period_end, period_months, account_code, account_name, value, version, source, setor, segmento) AS (
        SELECT
            s.cd_cvm, 'cd_cvm'::text, s.cnpj, s.company, s.ticker,
            s.doc_type, s.statement, s.scope,
            s.ref_date, s.period_start, s.period_end, s.period_months,
            s.account_code, s.account_name, s.value, s.version, 'cvm'::text,
            s.setor, s.segmento
        FROM api.cia_statement_rows(p_id, p_from, p_to, p_scope, p_doc_type, p_statement, p_as_of) s
        ORDER BY s.ref_date DESC, s.statement, s.period_months NULLS FIRST, s.account_code
        LIMIT 1001
    )
    SELECT g.* FROM page g
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'financials')
    ORDER BY g.ref_date DESC, g.statement, g.period_months NULLS FIRST, g.account_code
    LIMIT 1000;
$$;

REVOKE ALL ON FUNCTION api.financials(TEXT, TEXT, DATE, DATE, TEXT, TEXT, DATE) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.financials(TEXT, TEXT, DATE, DATE, TEXT, TEXT, DATE) TO anon, authenticated;

COMMENT ON FUNCTION api.financials(TEXT, TEXT, DATE, DATE, TEXT, TEXT, DATE) IS
    'Filed statement lines for one company, one row per account, latest stored version of each document. p_as_of (a date, default NULL) makes the read point-in-time: only documents CVM had received (cia_filing.dt_receb) BEFORE that date are read, the highest remaining version of each is kept, and a document with no filing header is dropped. NULL reads the latest stored version of every document and is NOT point-in-time: a later filing or a restatement appears as if it had been known. Versions superseded before 2026 are not held, so an as-of read is stale for a restating company, never early. version is on every row. Refuses above 1,000 rows with SQLSTATE 22023; narrow the window.';

-- Raw statement lines across every stored filing version. `financials` above
-- remains the latest-version view; this narrower, explicit history endpoint
-- lets a researcher inspect restatements without mixing them into a current
-- series. The statement is required and every response refuses above 1,000.
CREATE OR REPLACE FUNCTION api.financial_statement_history(
    p_id        TEXT,
    p_statement TEXT,
    p_from      DATE DEFAULT (CURRENT_DATE - 1825),
    p_to        DATE DEFAULT CURRENT_DATE,
    p_scope     TEXT DEFAULT 'con',
    p_doc_type  TEXT DEFAULT NULL
)
RETURNS TABLE (
    id                      TEXT,
    id_type                 TEXT,
    cnpj                    TEXT,
    company                 TEXT,
    ticker                  TEXT,
    doc_type                TEXT,
    statement               TEXT,
    scope                   TEXT,
    ref_date                DATE,
    period_start            DATE,
    period_end              DATE,
    period_months           INT,
    account_code            TEXT,
    account_name            TEXT,
    value                   NUMERIC,
    version                 INT,
    source                  TEXT,
    filed_currency          TEXT,
    filed_scale             TEXT,
    filing_metadata_found   BOOLEAN,
    filing_document_id      TEXT,
    filing_received_date    DATE,
    filing_link             TEXT
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    IF p_statement IS NULL OR btrim(p_statement) = '' THEN
        RAISE EXCEPTION 'p_statement is required'
            USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    WITH ref AS MATERIALIZED (
        -- Resolve the company once, before cia_account is touched (#531).
        -- api.company_ref is a set-returning function the planner estimates
        -- at 1,000 rows, so joined directly it never reached the index: a
        -- merge join scanned a whole cia_account partition (504 at 3 s).
        -- The scalar subquery below hands the planner one cd_cvm to put in
        -- the index condition. Zero or one row either way, same rows out.
        SELECT r0.cd_cvm, r0.cnpj, r0.company, r0.ticker
        FROM api.company_ref(p_id) r0
    ),
    page AS (
        SELECT
            r.cd_cvm AS id,
            'cd_cvm'::text AS id_type,
            r.cnpj,
            r.company,
            r.ticker,
            a.doc_type,
            a.grupo AS statement,
            a.escopo AS scope,
            a.dt_refer AS ref_date,
            a.dt_ini_exerc AS period_start,
            a.dt_fim_exerc AS period_end,
            CASE
                WHEN a.dt_ini_exerc IS NOT NULL AND a.dt_fim_exerc IS NOT NULL
                THEN (EXTRACT(YEAR FROM AGE(a.dt_fim_exerc + 1, a.dt_ini_exerc)) * 12
                    + EXTRACT(MONTH FROM AGE(a.dt_fim_exerc + 1, a.dt_ini_exerc)))::int
            END AS period_months,
            a.cd_conta AS account_code,
            a.ds_conta AS account_name,
            a.vl_conta AS value,
            a.versao AS version,
            'cvm'::text AS source,
            NULLIF(a.raw ->> 'MOEDA', '') AS filed_currency,
            a.escala_moeda AS filed_scale,
            f.id IS NOT NULL AS filing_metadata_found,
            f.id_doc AS filing_document_id,
            f.dt_receb AS filing_received_date,
            f.link_doc AS filing_link
        FROM public.cia_account a
        JOIN ref r ON r.cd_cvm = a.cd_cvm
                  AND a.cd_cvm = (SELECT x.cd_cvm FROM ref x)
        LEFT JOIN public.cia_filing f
          ON f.cd_cvm = a.cd_cvm
         AND f.doc_type = a.doc_type
         AND f.dt_refer = a.dt_refer
         AND f.versao = a.versao
        WHERE a.dt_refer BETWEEN COALESCE(p_from, CURRENT_DATE - 1825)
                             AND COALESCE(p_to, CURRENT_DATE)
          AND a.grupo = upper(btrim(p_statement))
          AND a.escopo = lower(btrim(COALESCE(p_scope, 'con')))
          AND (p_doc_type IS NULL OR a.doc_type = lower(btrim(p_doc_type)))
          AND a.ordem_exerc = 'ÚLTIMO'
        ORDER BY a.dt_refer DESC, a.versao DESC NULLS LAST,
                 a.dt_ini_exerc, a.cd_conta
        LIMIT 1001
    )
    SELECT page.*
    FROM page
    WHERE api.assert_row_cap(
        (SELECT count(*) FROM page), FALSE, 'financial_statement_history'
    )
    ORDER BY page.ref_date DESC, page.version DESC NULLS LAST,
             page.period_start, page.account_code
    LIMIT 1000;
END;
$$;

COMMENT ON FUNCTION api.financial_statement_history(TEXT, TEXT, DATE, DATE, TEXT, TEXT) IS
    'Filed account lines for one company and one statement, retaining every stored version. `financials` remains the latest-version surface. period_start/period_end preserve the filed span; `filed_currency` and `filed_scale` are source provenance, while `value` already has the filed scale applied at ingest. Filing-header fields are joined only on (cd_cvm, doc_type, dt_refer, versao); `filing_metadata_found=false` means no exact header match and the metadata fields remain NULL. Refuses above 1,000 rows with SQLSTATE 22023; narrow dates or statement. Values are in the filed currency, not converted.';

REVOKE ALL ON FUNCTION api.financial_statement_history(TEXT, TEXT, DATE, DATE, TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.financial_statement_history(TEXT, TEXT, DATE, DATE, TEXT, TEXT) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION api.financial_statement_history(TEXT, TEXT, DATE, DATE, TEXT, TEXT) TO silo_api;

DROP FUNCTION IF EXISTS api.company_financials(TEXT, DATE, DATE, TEXT);
CREATE OR REPLACE FUNCTION api.company_financials(
    p_id    TEXT,
    p_from  DATE DEFAULT (CURRENT_DATE - 1825),
    p_to    DATE DEFAULT CURRENT_DATE,
    p_scope TEXT DEFAULT 'con',
    p_as_of DATE DEFAULT NULL
)
RETURNS TABLE (
    id             TEXT,
    id_type        TEXT,
    cnpj           TEXT,
    company        TEXT,
    ticker         TEXT,
    doc_type       TEXT,
    scope          TEXT,
    ref_date       DATE,
    period_start   DATE,
    period_end     DATE,
    period_months  INT,
    revenue        NUMERIC,
    gross_profit   NUMERIC,
    net_income     NUMERIC,
    total_assets   NUMERIC,
    equity         NUMERIC,
    net_margin_pct NUMERIC,
    roe_pct        NUMERIC,
    version        INT,
    source         TEXT,
    -- Appended, not inserted mid-row, so an existing positional consumer is
    -- unaffected. revenue and gross_profit below are NOT like-for-like across
    -- sectors (3.01 is sales for an industrial filer and intermediation income
    -- for a bank), which is exactly why the sector ships on the row: it is the
    -- partition key for any median, rank or percentile computed over several
    -- companies. Ranking these columns across sectors ranks two different
    -- quantities. See docs/reference/CIA_DATA_MAP.md.
    setor          TEXT,
    segmento       TEXT
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    -- One page + one. The 1001st row is what makes "over the page"
    -- detectable; assert_row_cap then REFUSES (22023) rather than handing
    -- back a truncated series that looks complete. This function has no
    -- cursor, so a caller over the page narrows the window instead.
    -- The explicit column list lets the outer ORDER BY name columns as
    -- declared, which also dodges OUT-parameter ambiguity.
    WITH page (id, id_type, cnpj, company, ticker, doc_type, scope, ref_date, period_start, period_end, period_months, revenue, gross_profit, net_income, total_assets, equity, net_margin_pct, roe_pct, version, source, setor, segmento) AS (
        WITH s AS (
            SELECT * FROM api.cia_statement_rows(p_id, p_from, p_to, p_scope, NULL, NULL, p_as_of)
        ),
        income AS (
            SELECT
                s.cd_cvm, s.cnpj, s.company, s.ticker, s.setor, s.segmento,
                s.doc_type, s.scope, s.ref_date,
                s.period_start, s.period_end, s.period_months, s.version,
                -- max(...) FILTER, not sum: one (document, account) group can hold
                -- several rows and summing them would double-count.
                MAX(s.value) FILTER (WHERE s.account_code = '3.01') AS revenue,
                MAX(s.value) FILTER (WHERE s.account_code = '3.03') AS gross_profit,
                -- NET INCOME IS KEYED ON THE FILED LABEL (v36), exactly as in
                -- api.income_statements, so the two surfaces agree. Until v35 it
                -- read conta 3.11 alone, which is wrong in two directions:
                --   * bank B files NO 3.11 — its net income is on 3.09 under the
                --     label below — so 282 statements (0.56% of 50,439, Itaú
                --     Unibanco and BTG Pactual among them) read NULL;
                --   * the insurer chart's 3.11 is CONTINUING OPERATIONS; its net
                --     income is 3.13. The code read served the wrong quantity.
                -- The label match fixes both without a code fallback. Never
                -- COALESCE a code in: 3.09 is pre-participations profit on the
                -- industrial and bank-A charts (Banco do Brasil FY2024: 3.09 and
                -- 3.11 both 29.17bn only because 3.10 is zero).
                --
                -- 3.01/3.03 above stay code-keyed and are not like-for-like
                -- between a bank and an industrial filer — which is why setor
                -- ships on the row. Use api.income_statements for label-keyed
                -- revenue. Documented in docs/reference/CIA_DATA_MAP.md.
                MAX(s.value) FILTER (WHERE lower(btrim(s.account_name)) IN (
                    'lucro/prejuízo consolidado do período',
                    'lucro ou prejuízo líquido consolidado do período')) AS net_income
            FROM s
            WHERE s.statement = 'DRE'
            GROUP BY s.cd_cvm, s.cnpj, s.company, s.ticker, s.setor, s.segmento,
                     s.doc_type, s.scope,
                     s.ref_date, s.period_start, s.period_end, s.period_months, s.version
        ),
        balance AS (
            SELECT
                s.doc_type, s.ref_date, s.version,
                MAX(s.value) FILTER (WHERE s.statement = 'BPA' AND s.account_code = '1') AS total_assets,
                -- Equity is matched by its published LABEL, not by code: the code
                -- moves between 2.03 and 2.08 across chart layouts. This is the
                -- one label match in the contract and it stays inside a single
                -- company's own filing — it never joins two entities.
                MAX(s.value) FILTER (
                    WHERE s.statement = 'BPP'
                      AND s.account_name IN ('Patrimônio Líquido Consolidado', 'Patrimônio Líquido')
                ) AS equity
            FROM s
            WHERE s.statement IN ('BPA', 'BPP')
            GROUP BY s.doc_type, s.ref_date, s.version
        )
        SELECT
            i.cd_cvm, 'cd_cvm'::text, i.cnpj, i.company, i.ticker,
            i.doc_type, i.scope, i.ref_date,
            i.period_start, i.period_end, i.period_months,
            i.revenue, i.gross_profit, i.net_income,
            b.total_assets, b.equity,
            CASE WHEN i.revenue > 0 THEN round(100.0 * i.net_income / i.revenue, 2) END,
            -- The period's return on equity, NOT annualised: a three-month row
            -- divides a quarter's profit by equity. period_months says which.
            CASE WHEN b.equity  > 0 THEN round(100.0 * i.net_income / b.equity,  2) END,
            i.version, 'cvm'::text,
            i.setor, i.segmento
        FROM income i
        -- Balance rows are joined on the SAME document version. A restatement that
        -- bumps only the balance sheet leaves assets/equity NULL rather than
        -- pairing this period's profit with a different filing's balance.
        LEFT JOIN balance b
               ON b.doc_type = i.doc_type
              AND b.ref_date = i.ref_date
              AND b.version IS NOT DISTINCT FROM i.version
        ORDER BY i.ref_date DESC, i.doc_type, i.period_months NULLS FIRST
        LIMIT 1001
    )
    SELECT g.* FROM page g
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'company_financials')
    ORDER BY g.ref_date DESC, g.doc_type, g.period_months NULLS FIRST
    LIMIT 1000;
$$;

REVOKE ALL ON FUNCTION api.company_financials(TEXT, DATE, DATE, TEXT, DATE) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.company_financials(TEXT, DATE, DATE, TEXT, DATE) TO anon, authenticated;

COMMENT ON FUNCTION api.company_financials(TEXT, DATE, DATE, TEXT, DATE) IS
    'Headline financials for one company, one row per filed period, latest stored version of each document. p_as_of (a date, default NULL) makes the read point-in-time: only documents CVM had received (cia_filing.dt_receb) BEFORE that date are read, the highest remaining version of each is kept, and a document with no filing header is dropped. NULL reads the latest stored version of every document and is NOT point-in-time: a later filing or a restatement appears as if it had been known. Versions superseded before 2026 are not held, so an as-of read is stale for a restating company, never early.';

-- ---------------------------------------------------------------------------
-- Listed companies — the income statement, one row per filed period
-- ---------------------------------------------------------------------------
--
-- api.financials serves statement LINES (one row per account). This serves the
-- income statement as a PERIOD: one row carrying named fields, which is the
-- shape a caller asking for "the last four income statements" actually wants.
--
-- THE FIELDS ARE KEYED ON THE AS-FILED LABEL, NOT ON cd_conta AND NOT ON setor.
-- That is the whole design, and it is measured rather than assumed. CVM ships
-- four DRE charts of accounts, and the same code carries different concepts
-- across them (FY2024, consolidated, annual; company counts in brackets):
--
--   code | industrial [448]        | bank A [10]          | bank B [7]           | insurer [2]
--   -----+-------------------------+----------------------+----------------------+-------------------
--   3.01 | Receita de Venda        | Receitas DE Interm.  | Receitas DA Interm.  | Receitas Seguradoras
--   3.05 | EBIT                    | pre-tax result       | pre-tax result       | other op. result
--   3.07 | pre-tax result          | continuing ops       | continuing ops       | EBIT
--   3.09 | continuing ops          | pre-participations   | NET INCOME           | pre-tax result
--   3.11 | NET INCOME              | NET INCOME           | (absent)             | continuing ops
--
-- Read the 3.09/3.11 columns: net income sits on 3.11 for the industrial and
-- bank A charts, on 3.09 for bank B (which files no 3.11 at all), and on 3.13
-- for the insurer chart, whose 3.11 is the continuing-operations line. Three
-- different codes, one pair of labels. EVERY statement in the warehouse
-- that lacks 3.11 is bank B (verified: all 31 of FY2024's, and the 3.09 label on
-- every one of them is `Lucro/Prejuízo Consolidado do Período`). So keying on
-- the label is not merely safer than keying on the code — it is strictly more
-- complete, because it resolves net income for the filings a code-keyed read
-- must return NULL for.
--
-- Note also that `de` versus `da` Intermediação is NOT a wording variant to be
-- normalised away: it separates two charts with different layouts. Labels are
-- compared with lower() to absorb capitalisation only (CVM ships both
-- `Antes`/`antes` on 3.07), never with accent- or preposition-folding.
--
-- setor is NOT the key. It under-partitions: `Bancos` contains both bank charts,
-- and `Emp. Adm. Part. - Sem Setor Principal` contains an industrial and a bank
-- filer. It ships on the row because it is the right unit for a peer median,
-- which is a different job. docs/reference/CIA_DATA_MAP.md carries the evidence tables.
--
-- A concept a chart does not report reads NULL. operating_income is an
-- industrial line: banks do not publish an EBIT level and insurers put a
-- different concept on 3.07, so both read NULL rather than borrowing a number
-- that looks like one. Same for the insurer's operating_expenses, whose filed
-- line is `Despesas Administrativas` — narrower than the other charts' operating
-- expenses, so it is deliberately not mapped.
DROP FUNCTION IF EXISTS api.income_statements(TEXT, DATE, DATE, TEXT, TEXT);
CREATE OR REPLACE FUNCTION api.income_statements(
    p_id       TEXT,
    p_from     DATE DEFAULT (CURRENT_DATE - 1825),
    p_to       DATE DEFAULT CURRENT_DATE,
    p_scope    TEXT DEFAULT 'con',
    p_doc_type TEXT DEFAULT NULL,
    p_as_of    DATE DEFAULT NULL
)
RETURNS TABLE (
    id                    TEXT,
    id_type               TEXT,
    cnpj                  TEXT,
    company               TEXT,
    ticker                TEXT,
    setor                 TEXT,
    segmento              TEXT,
    doc_type              TEXT,
    scope                 TEXT,
    ref_date              DATE,
    period_start          DATE,
    period_end            DATE,
    period_months         INT,
    chart                 TEXT,
    revenue               NUMERIC,
    cost_of_revenue       NUMERIC,
    gross_profit          NUMERIC,
    operating_expenses    NUMERIC,
    operating_income      NUMERIC,
    financial_result      NUMERIC,
    pretax_income         NUMERIC,
    income_tax            NUMERIC,
    continuing_operations NUMERIC,
    net_income            NUMERIC,
    net_income_controlling    NUMERIC,
    net_income_noncontrolling NUMERIC,
    version               INT,
    source                TEXT
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    WITH page (id, id_type, cnpj, company, ticker, setor, segmento, doc_type, scope, ref_date, period_start, period_end, period_months, chart, revenue, cost_of_revenue, gross_profit, operating_expenses, operating_income, financial_result, pretax_income, income_tax, continuing_operations, net_income, net_income_controlling, net_income_noncontrolling, version, source) AS (
        WITH s AS (
            SELECT * FROM api.cia_statement_rows(p_id, p_from, p_to, p_scope, p_doc_type, 'DRE', p_as_of)
        ),
        lab AS (
            SELECT s.*, lower(btrim(s.account_name)) AS lbl FROM s
        )
        SELECT
            x.cd_cvm, 'cd_cvm'::text, x.cnpj, x.company, x.ticker,
            x.setor, x.segmento, x.doc_type, x.scope,
            x.ref_date, x.period_start, x.period_end, x.period_months,
            -- Which chart this filing used, from the revenue line's own label.
            -- Informational: the field mapping below never consults it.
            CASE
                WHEN bool_or(x.lbl = 'receita de venda de bens e/ou serviços')        THEN 'industrial'
                WHEN bool_or(x.lbl LIKE 'receitas d_ intermediação financeira')       THEN 'bank'
                WHEN bool_or(x.lbl = 'receitas das atividades seguradoras/resseguradoras') THEN 'insurer'
            END,
            -- max(...) FILTER, not sum: one (document, label) group can hold
            -- several rows and summing them would double-count.
            MAX(x.value) FILTER (WHERE x.lbl IN (
                'receita de venda de bens e/ou serviços',
                'receitas de intermediação financeira',
                'receitas da intermediação financeira',
                'receitas das atividades seguradoras/resseguradoras')),
            MAX(x.value) FILTER (WHERE x.lbl IN (
                'custo dos bens e/ou serviços vendidos',
                'despesas de intermediação financeira',
                'despesas da intermediação financeira',
                'despesas da atividade seguradora/resseguradora')),
            MAX(x.value) FILTER (WHERE x.lbl IN (
                'resultado bruto',
                'resultado bruto de intermediação financeira',
                'resultado bruto intermediação financeira')),
            MAX(x.value) FILTER (WHERE x.lbl IN (
                'despesas/receitas operacionais',
                'outras despesas e receitas operacionais',
                'outras despesas/receitas operacionais')),
            MAX(x.value) FILTER (WHERE x.lbl =
                'resultado antes do resultado financeiro e dos tributos'),
            MAX(x.value) FILTER (WHERE x.lbl = 'resultado financeiro'),
            MAX(x.value) FILTER (WHERE x.lbl =
                'resultado antes dos tributos sobre o lucro'),
            MAX(x.value) FILTER (WHERE x.lbl =
                'imposto de renda e contribuição social sobre o lucro'),
            MAX(x.value) FILTER (WHERE x.lbl IN (
                'resultado líquido das operações continuadas',
                'lucro ou prejuízo das operações continuadas')),
            -- NET INCOME. Both labels mean the consolidated result for the
            -- period; the first is filed on 3.11 by three charts and on 3.09 by
            -- bank B, which is exactly why this reads the label.
            MAX(x.value) FILTER (WHERE x.lbl IN (
                'lucro/prejuízo consolidado do período',
                'lucro ou prejuízo líquido consolidado do período')),
            -- The attribution split, filed one level below net income (3.11.01 /
            -- 3.11.02, or 3.13.01 / 3.13.02 on the insurer chart). Keying on the
            -- label means the parent's code is irrelevant. CVM ships `a Sócios`
            -- and `aos Sócios` for the same concept, so both are listed; per-share
            -- figures are built on the controlling share, not on net_income.
            MAX(x.value) FILTER (WHERE x.lbl IN (
                'atribuído a sócios da empresa controladora',
                'atribuído aos sócios da empresa controladora')),
            MAX(x.value) FILTER (WHERE x.lbl IN (
                'atribuído a sócios não controladores',
                'atribuído aos sócios não controladores')),
            x.version, 'cvm'::text
        FROM lab x
        GROUP BY x.cd_cvm, x.cnpj, x.company, x.ticker, x.setor, x.segmento,
                 x.doc_type, x.scope, x.ref_date, x.period_start, x.period_end,
                 x.period_months, x.version
        ORDER BY x.ref_date DESC, x.doc_type, x.period_months NULLS FIRST
        LIMIT 1001
    )
    SELECT g.* FROM page g
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'income_statements')
    ORDER BY g.ref_date DESC, g.doc_type, g.period_months NULLS FIRST
    LIMIT 1000;
$$;

COMMENT ON FUNCTION api.income_statements(TEXT, DATE, DATE, TEXT, TEXT, DATE) IS
    'Income statement, one row per filed period, with named fields. Fields are keyed on the AS-FILED account label, not on cd_conta and not on setor: CVM ships four DRE charts and the same code means different things across them. net_income therefore resolves for the filings that report it on 3.09 (the one bank chart with no 3.11) as well as those on 3.11. A concept a chart does not file reads NULL — operating_income is industrial-only. `chart` says which layout the filing used. Values are absolute reais. p_as_of (a date, default NULL) makes the read point-in-time: only documents CVM had received (cia_filing.dt_receb) BEFORE that date are read, the highest remaining version of each is kept, and a document with no filing header is dropped. NULL reads the latest stored version of every document and is NOT point-in-time: a later filing or a restatement appears as if it had been known. Versions superseded before 2026 are not held, so an as-of read is stale for a restating company, never early.';

REVOKE ALL ON FUNCTION api.income_statements(TEXT, DATE, DATE, TEXT, TEXT, DATE) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.income_statements(TEXT, DATE, DATE, TEXT, TEXT, DATE) TO anon, authenticated;

-- ---------------------------------------------------------------------------
-- Listed companies — the balance sheet, one row per filed period
-- ---------------------------------------------------------------------------
--
-- Same design as api.income_statements: fields keyed on the AS-FILED label
-- (lower(btrim()) only — never accent- or preposition-folded), never on cd_conta
-- and never on setor. The census (FY2024, consolidated, annual; BPA + BPP) finds
-- three charts, and the codes disagree exactly as they do on the DRE:
--
--   concept          | industrial [450] | bank A [10] | bank B [7]
--   -----------------+------------------+-------------+-----------
--   cash & equiv.    | 1.01.01          | 1.01        | 1.01
--   PP&E             | 1.02.03          | 1.06        | 1.06
--   equity (consol.) | 2.03             | 2.07        | 2.08
--
-- ONE LABEL IS NOT ALWAYS ONE CONCEPT WITHIN A FILING. The industrial chart
-- files `Empréstimos e Financiamentos` twice — 2.01.04 under `Passivo
-- Circulante` and 2.02.01 under `Passivo Não Circulante` — so a line is matched
-- on its own label AND its parent's label (the parent is the row whose code is
-- this code minus its last segment, in the same document). Still label-keyed:
-- the parent's code is never consulted, only its filed name.
--
-- A concept a chart does not file reads NULL. Banks publish no current /
-- non-current split and no `Empréstimos e Financiamentos` line, so current_*,
-- noncurrent_* and both debt fields read NULL for them rather than borrowing a
-- deposits or funding line that looks like debt. `chart` is informational and
-- the field mapping never consults it.
DROP FUNCTION IF EXISTS api.balance_sheets(TEXT, DATE, DATE, TEXT, TEXT);
CREATE OR REPLACE FUNCTION api.balance_sheets(
    p_id       TEXT,
    p_from     DATE DEFAULT (CURRENT_DATE - 1825),
    p_to       DATE DEFAULT CURRENT_DATE,
    p_scope    TEXT DEFAULT 'con',
    p_doc_type TEXT DEFAULT NULL,
    p_as_of    DATE DEFAULT NULL
)
RETURNS TABLE (
    id                        TEXT,
    id_type                   TEXT,
    cnpj                      TEXT,
    company                   TEXT,
    ticker                    TEXT,
    setor                     TEXT,
    segmento                  TEXT,
    doc_type                  TEXT,
    scope                     TEXT,
    ref_date                  DATE,
    chart                     TEXT,
    total_assets              NUMERIC,
    current_assets            NUMERIC,
    cash_and_equivalents      NUMERIC,
    short_term_investments    NUMERIC,
    receivables               NUMERIC,
    inventories               NUMERIC,
    noncurrent_assets         NUMERIC,
    property_plant_equipment  NUMERIC,
    intangible_assets         NUMERIC,
    total_liabilities_and_equity NUMERIC,
    current_liabilities       NUMERIC,
    noncurrent_liabilities    NUMERIC,
    short_term_debt           NUMERIC,
    long_term_debt            NUMERIC,
    equity                    NUMERIC,
    share_capital             NUMERIC,
    noncontrolling_interests  NUMERIC,
    version                   INT,
    source                    TEXT
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    WITH page (id, id_type, cnpj, company, ticker, setor, segmento, doc_type, scope, ref_date, chart, total_assets, current_assets, cash_and_equivalents, short_term_investments, receivables, inventories, noncurrent_assets, property_plant_equipment, intangible_assets, total_liabilities_and_equity, current_liabilities, noncurrent_liabilities, short_term_debt, long_term_debt, equity, share_capital, noncontrolling_interests, version, source) AS (
        WITH s AS (
            SELECT * FROM api.cia_statement_rows(p_id, p_from, p_to, p_scope, p_doc_type, 'BPA', p_as_of)
            UNION ALL
            SELECT * FROM api.cia_statement_rows(p_id, p_from, p_to, p_scope, p_doc_type, 'BPP', p_as_of)
        ),
        lab AS (
            SELECT s.*, lower(btrim(s.account_name)) AS lbl,
                   lower(btrim(p.account_name))       AS parent_lbl
            FROM s
            LEFT JOIN s p
                   ON p.cd_cvm   = s.cd_cvm
                  AND p.doc_type = s.doc_type
                  AND p.ref_date = s.ref_date
                  AND p.version IS NOT DISTINCT FROM s.version
                  AND p.account_code = regexp_replace(s.account_code, '\.[^.]+$', '')
        )
        SELECT
            x.cd_cvm, 'cd_cvm'::text, x.cnpj, x.company, x.ticker,
            x.setor, x.segmento, x.doc_type, x.scope, x.ref_date,
            CASE
                WHEN bool_or(x.lbl = 'ativo circulante')          THEN 'industrial'
                WHEN bool_or(x.lbl LIKE 'ativos financeiros%')    THEN 'bank'
            END,
            -- max(...) FILTER, not sum: see api.income_statements.
            MAX(x.value) FILTER (WHERE x.lbl = 'ativo total'),
            MAX(x.value) FILTER (WHERE x.lbl = 'ativo circulante'),
            MAX(x.value) FILTER (WHERE x.lbl = 'caixa e equivalentes de caixa'
                                   AND x.parent_lbl IN ('ativo circulante', 'ativo total')),
            MAX(x.value) FILTER (WHERE x.lbl = 'aplicações financeiras'
                                   AND x.parent_lbl = 'ativo circulante'),
            MAX(x.value) FILTER (WHERE x.lbl = 'contas a receber'
                                   AND x.parent_lbl = 'ativo circulante'),
            MAX(x.value) FILTER (WHERE x.lbl = 'estoques'
                                   AND x.parent_lbl = 'ativo circulante'),
            MAX(x.value) FILTER (WHERE x.lbl = 'ativo não circulante'),
            MAX(x.value) FILTER (WHERE x.lbl = 'imobilizado'
                                   AND x.parent_lbl IN ('ativo não circulante', 'ativo total')),
            MAX(x.value) FILTER (WHERE x.lbl = 'intangível'
                                   AND x.parent_lbl IN ('ativo não circulante', 'ativo total')),
            MAX(x.value) FILTER (WHERE x.lbl = 'passivo total'),
            MAX(x.value) FILTER (WHERE x.lbl = 'passivo circulante'),
            MAX(x.value) FILTER (WHERE x.lbl = 'passivo não circulante'),
            MAX(x.value) FILTER (WHERE x.lbl = 'empréstimos e financiamentos'
                                   AND x.parent_lbl = 'passivo circulante'),
            MAX(x.value) FILTER (WHERE x.lbl = 'empréstimos e financiamentos'
                                   AND x.parent_lbl = 'passivo não circulante'),
            MAX(x.value) FILTER (WHERE x.lbl = 'patrimônio líquido consolidado'),
            -- Bank A files capital one level lower, under the controlling
            -- shareholders' equity line (2.07.01.xx).
            MAX(x.value) FILTER (WHERE x.lbl = 'capital social realizado'
                                   AND x.parent_lbl IN ('patrimônio líquido consolidado',
                                                        'patrimônio líquido atribuído ao controlador')),
            -- Industrial and bank B file `Participação dos Acionistas Não
            -- Controladores`; bank A files the attribution line instead.
            MAX(x.value) FILTER (WHERE x.lbl IN (
                'participação dos acionistas não controladores',
                'patrimônio líquido atribuído aos não controladores')
                                   AND x.parent_lbl = 'patrimônio líquido consolidado'),
            x.version, 'cvm'::text
        FROM lab x
        GROUP BY x.cd_cvm, x.cnpj, x.company, x.ticker, x.setor, x.segmento,
                 x.doc_type, x.scope, x.ref_date, x.version
        ORDER BY x.ref_date DESC, x.doc_type
        LIMIT 1001
    )
    SELECT g.* FROM page g
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'balance_sheets')
    ORDER BY g.ref_date DESC, g.doc_type
    LIMIT 1000;
$$;

COMMENT ON FUNCTION api.balance_sheets(TEXT, DATE, DATE, TEXT, TEXT, DATE) IS
    'Balance sheet, one row per filed period, with named fields. Fields are keyed on the AS-FILED account label (and, where one label is filed twice, its parent''s label), not on cd_conta and not on setor: CVM ships three balance-sheet charts and equity alone sits on 2.03, 2.07 or 2.08. A concept a chart does not file reads NULL — banks file no current/non-current split and no `Empréstimos e Financiamentos`, so those fields are NULL for them, never zero. `chart` says which layout the filing used. Values are absolute reais. p_as_of (a date, default NULL) makes the read point-in-time: only documents CVM had received (cia_filing.dt_receb) BEFORE that date are read, the highest remaining version of each is kept, and a document with no filing header is dropped. NULL reads the latest stored version of every document and is NOT point-in-time: a later filing or a restatement appears as if it had been known. Versions superseded before 2026 are not held, so an as-of read is stale for a restating company, never early.';

REVOKE ALL ON FUNCTION api.balance_sheets(TEXT, DATE, DATE, TEXT, TEXT, DATE) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.balance_sheets(TEXT, DATE, DATE, TEXT, TEXT, DATE) TO anon, authenticated;

-- ---------------------------------------------------------------------------
-- Listed companies — the cash flow statement, one row per filed period
-- ---------------------------------------------------------------------------
--
-- CVM files the DFC under one of two methods — `DFC_MD` (direct, 16 companies
-- in FY2024) or `DFC_MI` (indirect, ~450) — and `method` says which. Only the
-- TOTALS are mapped: 6.01 – 6.05.02 carry the same labels across every chart
-- (with a `das` variant on seven filers), so they key cleanly. The detail lines
-- beneath them do not: capex alone is filed under 20+ free-text labels
-- (`Aquisição de imobilizado`, `Adições ao imobilizado e intangível`, ...) at
-- whatever code the company chose. Mapping those would be a guess, so there is
-- no capex or dividends field; read them from api.financials, where the filed
-- label is on the row. operating_cash_generated and working_capital_changes are
-- indirect-method lines and read NULL on a direct-method filing.
DROP FUNCTION IF EXISTS api.cash_flow_statements(TEXT, DATE, DATE, TEXT, TEXT);
CREATE OR REPLACE FUNCTION api.cash_flow_statements(
    p_id       TEXT,
    p_from     DATE DEFAULT (CURRENT_DATE - 1825),
    p_to       DATE DEFAULT CURRENT_DATE,
    p_scope    TEXT DEFAULT 'con',
    p_doc_type TEXT DEFAULT NULL,
    p_as_of    DATE DEFAULT NULL
)
RETURNS TABLE (
    id                       TEXT,
    id_type                  TEXT,
    cnpj                     TEXT,
    company                  TEXT,
    ticker                   TEXT,
    setor                    TEXT,
    segmento                 TEXT,
    doc_type                 TEXT,
    scope                    TEXT,
    ref_date                 DATE,
    period_start             DATE,
    period_end               DATE,
    period_months            INT,
    method                   TEXT,
    operating_cash_flow      NUMERIC,
    operating_cash_generated NUMERIC,
    working_capital_changes  NUMERIC,
    investing_cash_flow      NUMERIC,
    financing_cash_flow      NUMERIC,
    fx_effect                NUMERIC,
    net_change_in_cash       NUMERIC,
    cash_start               NUMERIC,
    cash_end                 NUMERIC,
    version                  INT,
    source                   TEXT
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    WITH page (id, id_type, cnpj, company, ticker, setor, segmento, doc_type, scope, ref_date, period_start, period_end, period_months, method, operating_cash_flow, operating_cash_generated, working_capital_changes, investing_cash_flow, financing_cash_flow, fx_effect, net_change_in_cash, cash_start, cash_end, version, source) AS (
        WITH s AS (
            SELECT *, 'direct'::text AS method
            FROM api.cia_statement_rows(p_id, p_from, p_to, p_scope, p_doc_type, 'DFC_MD', p_as_of)
            UNION ALL
            SELECT *, 'indirect'::text
            FROM api.cia_statement_rows(p_id, p_from, p_to, p_scope, p_doc_type, 'DFC_MI', p_as_of)
        ),
        lab AS (
            -- The parent's label anchors the two indirect-method lines: one
            -- filer (cd_cvm 25950, FY2024) repeats `Caixa Gerado nas Operações`
            -- as its own child at 0.00, and MAX over both would return the 0
            -- whenever the real figure is negative.
            SELECT s.*, lower(btrim(s.account_name)) AS lbl,
                   lower(btrim(p.account_name))       AS parent_lbl
            FROM s
            LEFT JOIN s p
                   ON p.cd_cvm   = s.cd_cvm
                  AND p.doc_type = s.doc_type
                  AND p.ref_date = s.ref_date
                  AND p.method   = s.method
                  AND p.period_start IS NOT DISTINCT FROM s.period_start
                  AND p.version IS NOT DISTINCT FROM s.version
                  AND p.account_code = regexp_replace(s.account_code, '\.[^.]+$', '')
        )
        SELECT
            x.cd_cvm, 'cd_cvm'::text, x.cnpj, x.company, x.ticker,
            x.setor, x.segmento, x.doc_type, x.scope,
            x.ref_date, x.period_start, x.period_end, x.period_months,
            x.method,
            -- Insurers (2 filers) label the operating total by their activity.
            MAX(x.value) FILTER (WHERE x.lbl IN (
                'caixa líquido atividades operacionais',
                'caixa líquido das atividades operacionais',
                'caixa líquido atividades seguradora/resseguradora')),
            MAX(x.value) FILTER (WHERE x.lbl IN (
                'caixa gerado nas operações',
                'caixa gerado pelas operações')
                AND x.parent_lbl IN (
                'caixa líquido atividades operacionais',
                'caixa líquido das atividades operacionais',
                'caixa líquido atividades seguradora/resseguradora')),
            MAX(x.value) FILTER (WHERE x.lbl = 'variações nos ativos e passivos'
                AND x.parent_lbl IN (
                'caixa líquido atividades operacionais',
                'caixa líquido das atividades operacionais',
                'caixa líquido atividades seguradora/resseguradora')),
            MAX(x.value) FILTER (WHERE x.lbl IN (
                'caixa líquido atividades de investimento',
                'caixa líquido das atividades de investimento')),
            MAX(x.value) FILTER (WHERE x.lbl IN (
                'caixa líquido atividades de financiamento',
                'caixa líquido das atividades de financiamento')),
            MAX(x.value) FILTER (WHERE x.lbl IN (
                'variação cambial s/ caixa e equivalentes',
                'efeitos de variação cambial s/ caixa e equivalentes')),
            MAX(x.value) FILTER (WHERE x.lbl = 'aumento (redução) de caixa e equivalentes'),
            MAX(x.value) FILTER (WHERE x.lbl = 'saldo inicial de caixa e equivalentes'),
            MAX(x.value) FILTER (WHERE x.lbl = 'saldo final de caixa e equivalentes'),
            x.version, 'cvm'::text
        FROM lab x
        GROUP BY x.cd_cvm, x.cnpj, x.company, x.ticker, x.setor, x.segmento,
                 x.doc_type, x.scope, x.ref_date, x.period_start, x.period_end,
                 x.period_months, x.method, x.version
        ORDER BY x.ref_date DESC, x.doc_type, x.period_months NULLS FIRST
        LIMIT 1001
    )
    SELECT g.* FROM page g
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'cash_flow_statements')
    ORDER BY g.ref_date DESC, g.doc_type, g.period_months NULLS FIRST
    LIMIT 1000;
$$;

COMMENT ON FUNCTION api.cash_flow_statements(TEXT, DATE, DATE, TEXT, TEXT, DATE) IS
    'Cash flow statement, one row per filed period, with named TOTALS keyed on the as-filed label. `method` is direct (DFC_MD) or indirect (DFC_MI). Only the section totals and the cash reconciliation are mapped: detail lines such as capex and dividends are free-text per company and are NOT fields — read them from api.financials. operating_cash_generated and working_capital_changes are indirect-method lines and read NULL on a direct-method filing, never zero. Values are absolute reais. p_as_of (a date, default NULL) makes the read point-in-time: only documents CVM had received (cia_filing.dt_receb) BEFORE that date are read, the highest remaining version of each is kept, and a document with no filing header is dropped. NULL reads the latest stored version of every document and is NOT point-in-time: a later filing or a restatement appears as if it had been known. Versions superseded before 2026 are not held, so an as-of read is stale for a restating company, never early.';

REVOKE ALL ON FUNCTION api.cash_flow_statements(TEXT, DATE, DATE, TEXT, TEXT, DATE) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.cash_flow_statements(TEXT, DATE, DATE, TEXT, TEXT, DATE) TO anon, authenticated;

-- ---------------------------------------------------------------------------
-- Catalog — the metric map, public (INSTRUMENTS.md: discovery is contract)
-- ---------------------------------------------------------------------------
-- The same JSON serve/catalog.py's catalog_payload() serves at /v1/catalog,
-- as one jsonb constant, so an agent on the Data API can self-describe
-- without the local adapter. The statement between the GENERATED markers is
-- written by scripts/gen_catalog_sql.py from catalog_payload(); edit
-- serve/catalog.py and rerun it, never the block. tests/test_api_contract_sql.py
-- fails while the block is stale. Catalog changes bump CATALOG_VERSION in
-- serve/catalog.py (the "version" key below follows it).
--
-- SECURITY INVOKER (the file-wide DEFINER rule does not apply): the body
-- reads no relation at all — it returns a constant — so DEFINER would grant
-- owner rights for nothing. INVOKER is the minimal privilege, and with no
-- object references there is no search_path surface to pin.

-- BEGIN GENERATED api.catalog() (scripts/gen_catalog_sql.py) — do not edit
CREATE OR REPLACE FUNCTION api.catalog()
RETURNS jsonb
LANGUAGE sql
STABLE
AS $fn$
SELECT $json${
  "kind": "catalog",
  "version": 74,
  "primitive": "panel",
  "agent": "You are querying Silo, a Brazilian public-markets warehouse (CVM funds, B3 COTAHIST cash quotes, options and termo, the B3 securities-lending and investor-flow group, B3's DI1 futures and reference-rate curves, and Brazilian inflation — BACEN's IPCA series and IBGE's item tree with weights). Call catalog once and cache it. Resolve names with lookup, then fetch a panel. The primitive is a panel (id, date, metric, value). Correlation, ranking, spreads, regressions and other relations are reductions of that panel — compute them in the notebook. Do not fabricate ids, fills, or ticker-CNPJ matches. TWO SURFACES, AND THEY DIFFER: the DEPLOYED api is Supabase PostgREST — POST /rest/v1/rpc/<function> with a JSON body of p_-prefixed named arguments (arrays stay arrays), views at GET /rest/v1/<view>, header `apikey`. The /v1/* routes in `endpoints` are an optional local Flask adapter (serve/app.py) that is not necessarily deployed; its query-string form and its `format=wide` envelope exist ONLY there. Prefer the postgrest section unless you know the /v1 adapter is running. Read the row-cap constraint: EVERY function REFUSES (SQLSTATE 22023) a window over 1000 rows instead of trimming it — page panel, quote_history and fund_nav with p_after, narrow the rest. fund_nav also needs p_entity_type to page. The GET views still cut at 1000 and keep the OLDEST rows, so READ THE Content-Range RESPONSE HEADER on those: `0-999/*` is the only thing that tells you. BEFORE READING A NULL AS A GAP, call coverage() and metric_coverage(): a null outside a family's column set is not applicable, and a metric absent from metric_coverage() is one that family never files. coverage().as_of is the newest ELAPSED period; newest_period can sit in the future when a family files forward-dated (FIP is keyed 31-December), so never read it as freshness. PRICE IS THE DEFAULT, everything else is opt-in: panel with no p_metrics returns `close_adj` (split-, grouping- and bonus-adjusted) for share and unit tickers, `close` for other tickers and `nav` for CNPJs, and quote_history with no p_fields returns ticker, trade_date and close_adj; that is the call to make unless you actually need another measure — name metrics or fields explicitly only when you will use them (p_fields=['close'] for the raw close). A close_adj window SILO cannot adjust is refused with the cause, never served raw. The wide endpoints are the exception and behave the other way round: quote_latest and the views return their full OHLCV/identity row every time, so trim them with PostgREST `?select=` (e.g. `?select=ticker,trade_date,close`) rather than pulling 22 columns to read one. See `defaults`.",
  "defaults": {
    "principle": "price by default; every other measure is opt-in",
    "panel": {
      "metrics": [
        "close",
        "close_adj",
        "nav"
      ],
      "means": "p_metrics omitted: close_adj for share and unit tickers, close for every other ticker, option and termo, settlement_rate for futures, nav for cnpj ids; an explicit list is served as asked, and a metric absent for an id type simply yields no rows",
      "grain": "(id, asset_class, date, metric) — a CNPJ filing under two families yields one row per family; p_entity_type narrows to one",
      "to_widen": "pass p_metrics explicitly, e.g. p_metrics=['close','volume']"
    },
    "quote_history": {
      "fields": [
        "ticker",
        "trade_date",
        "close_adj"
      ],
      "means": "one JSON object per session with only the selected keys; ticker and trade_date are in every row",
      "to_widen": "pass p_fields, e.g. p_fields=['close','volume'] for the raw close and volume; an unknown name refuses (22023)",
      "precision": "prices are decimals as published (6 decimal places on the tape); close_adj is rounded to 6 decimal places",
      "available": {
        "ticker": "string",
        "trade_date": "date",
        "close_adj": "number",
        "close": "number",
        "open": "number",
        "high": "number",
        "low": "number",
        "average": "number",
        "bid": "number",
        "ask": "number",
        "close_unit": "number",
        "trades": "integer",
        "quantity": "number",
        "volume": "number",
        "quotation_factor": "integer",
        "board": "string",
        "isin": "string",
        "short_name": "string",
        "spec": "string",
        "currency": "string",
        "asset_class": "string",
        "source": "string",
        "coverage_start": "date",
        "coverage_end": "date",
        "prior_no_trade_sessions": "integer",
        "events_proven_at": "string",
        "data_revision": "string",
        "close_total_return": "number",
        "close_total_return_null_reason": "string",
        "market": "string",
        "term_days": "string",
        "contract_price": "number",
        "contract_expiry": "date",
        "contract_correction": "string",
        "contract_points": "number",
        "contract_points_raw": "string",
        "distribution_number": "string",
        "fetched_at": "string"
      }
    },
    "wide_endpoints": {
      "which": [
        "quote_latest",
        "fund_nav",
        "api.quotes and the typed views"
      ],
      "behaviour": "fixed full row (OHLCV + identity); the column list cannot vary by argument",
      "to_narrow": "PostgREST ?select=, e.g. /rest/v1/rpc/quote_latest?select=ticker,trade_date,close"
    }
  },
  "metrics": {
    "close": {
      "id_type": [
        "ticker",
        "option",
        "termo"
      ],
      "asset_class": [
        "equity",
        "unit",
        "bdr",
        "fund_quota",
        "index",
        "right",
        "bonus",
        "cash_security",
        "derivative"
      ],
      "grain": [
        "day",
        "month"
      ],
      "source": "b3_cotahist",
      "meaning": "Unadjusted close, as traded. Cash tickers: every BDI board (the instrument's own series), classified from published TPMERC/ESPECI. Option/termo codnegs: that derivative segment's session close. Month = last session. The default for tickers outside shares and units, and for options and termo."
    },
    "close_adj": {
      "id_type": [
        "ticker"
      ],
      "asset_class": [
        "equity",
        "unit"
      ],
      "grain": [
        "day",
        "month"
      ],
      "source": "b3_cotahist",
      "meaning": "Close per single share, backward-adjusted for splits, groupings and bonus shares by B3's rule and anchored to the instrument's latest session; 6 decimal places. No dividend, JCP or subscription-right adjustment. Shares (ISIN code ACN) and units (CDA/UNT, ticker ending 11) only. A window it cannot adjust REFUSES (22023) naming ticker, period and cause; it is never the raw close under this name. The panel default for shares and units. Month = last session.",
      "derived": true
    },
    "volume": {
      "id_type": [
        "ticker",
        "option",
        "termo"
      ],
      "asset_class": [
        "equity",
        "unit",
        "bdr",
        "fund_quota",
        "index",
        "right",
        "bonus",
        "cash_security",
        "derivative"
      ],
      "grain": [
        "day",
        "month"
      ],
      "source": "b3_cotahist",
      "meaning": "Session traded volume (BRL). Cash: every BDI board (the instrument's own series); option/termo: that derivative segment. Month = last session."
    },
    "close_unit": {
      "id_type": [
        "ticker"
      ],
      "asset_class": [
        "equity",
        "unit",
        "bdr",
        "fund_quota",
        "index",
        "right",
        "bonus",
        "cash_security"
      ],
      "grain": [
        "day",
        "month"
      ],
      "source": "b3_cotahist",
      "meaning": "Close per single quoted unit: close / quotation_factor, both published. Use this to compare price levels across papers; a paper quoted per lot (factor 1000) otherwise reads 1000x its unit price. Still unadjusted for corporate actions.",
      "derived": true
    },
    "close_return": {
      "id_type": [
        "ticker"
      ],
      "asset_class": [
        "equity",
        "unit",
        "bdr",
        "fund_quota",
        "index",
        "right",
        "bonus",
        "cash_security"
      ],
      "grain": [
        "day",
        "month"
      ],
      "source": "b3_cotahist",
      "meaning": "p_t/p'_{t-1}-1, where p' is the previous stored close divided by the share ratio of every split, grouping or bonus (DESDOBRAMENTO, GRUPAMENTO, BONIFICACAO) between the two prints: 1 + factor/100 for DESDOBRAMENTO and BONIFICACAO, factor for GRUPAMENTO. A share-count change never reads as a return: 100.00 before a 1:4 split is 25.00, so a 26.00 close is +4%, not -74%. On the monthly grain the event may sit anywhere between the two month-end prints. NULL (no row) across an event whose factor is unreadable or published twice with two factors. Price only: dividends and JCP still move it, so it is not a total return. Daily: previous session. Monthly: previous calendar month else null.",
      "derived": true
    },
    "settlement_rate": {
      "id_type": [
        "future"
      ],
      "asset_class": [
        "derivative"
      ],
      "grain": [
        "day",
        "month"
      ],
      "source": "b3_price_report",
      "meaning": "Futures settlement as a rate, as B3 publishes it: for DI1, % a.a. on 252 business days. Ids are B3 contract codes (DI1F27: root, B3 month letter, two-digit year; future_curve lists a session's). Only a settlement B3 marks final (F) is served; future_series carries the status. Nothing is rolled or made continuous: a contract stops at maturity. Month = last session. The default for a future."
    },
    "settlement_price": {
      "id_type": [
        "future"
      ],
      "asset_class": [
        "derivative"
      ],
      "grain": [
        "day",
        "month"
      ],
      "source": "b3_price_report",
      "meaning": "Futures settlement price as B3 publishes it: for DI1 the PU (preço unitário). Final (F) settlements only. Month = last session."
    },
    "open_interest": {
      "id_type": [
        "future"
      ],
      "asset_class": [
        "derivative"
      ],
      "grain": [
        "day",
        "month"
      ],
      "source": "b3_price_report",
      "meaning": "Open contracts at the session's close, as B3 publishes them, on sessions with a final (F) settlement. Month = last session, not a sum or an average."
    },
    "nav": {
      "id_type": [
        "cnpj"
      ],
      "asset_class": [
        "fi",
        "fidc",
        "fii",
        "fip",
        "fiagro"
      ],
      "grain": [
        "month"
      ],
      "source": "cvm",
      "meaning": "Fund net assets (vl_patrim_liq).",
      "coverage": "api.metric_coverage()"
    },
    "quota": {
      "id_type": [
        "cnpj"
      ],
      "asset_class": [
        "fi"
      ],
      "grain": [
        "month"
      ],
      "source": "cvm",
      "meaning": "FI unit quota. Comparable subclass only.",
      "coverage": "api.metric_coverage()"
    },
    "delinquency": {
      "id_type": [
        "cnpj"
      ],
      "asset_class": [
        "fidc",
        "fiagro"
      ],
      "grain": [
        "month"
      ],
      "source": "cvm",
      "meaning": "Delinquent portfolio value (not a rate unless you divide by nav).",
      "since": {
        "fidc": "2013-01-31"
      },
      "coverage": "api.metric_coverage()"
    },
    "yield": {
      "id_type": [
        "cnpj"
      ],
      "asset_class": [
        "fii"
      ],
      "grain": [
        "month"
      ],
      "source": "cvm",
      "meaning": "Monthly yield % as published (FII complemento).",
      "coverage": "api.metric_coverage()"
    },
    "inflows": {
      "id_type": [
        "cnpj"
      ],
      "asset_class": [
        "fi"
      ],
      "grain": [
        "month"
      ],
      "source": "cvm",
      "meaning": "Gross monthly subscriptions.",
      "coverage": "api.metric_coverage()"
    },
    "redemptions": {
      "id_type": [
        "cnpj"
      ],
      "asset_class": [
        "fi"
      ],
      "grain": [
        "month"
      ],
      "source": "cvm",
      "meaning": "Gross monthly redemptions.",
      "coverage": "api.metric_coverage()"
    },
    "quotaholders": {
      "id_type": [
        "cnpj"
      ],
      "asset_class": [
        "fi",
        "fii"
      ],
      "grain": [
        "month"
      ],
      "source": "cvm",
      "meaning": "Number of unit-holders (fi, fii). Not served for fidc, fiagro, fip.",
      "coverage": "api.metric_coverage()"
    },
    "receivables": {
      "id_type": [
        "cnpj"
      ],
      "asset_class": [
        "fidc"
      ],
      "grain": [
        "month"
      ],
      "source": "cvm",
      "meaning": "Receivables portfolio total (tab II TAB_II_VL_CARTEIRA), the denominator for any concentration ratio. Sector lines are in fidc_portfolio."
    },
    "sacado_top1": {
      "id_type": [
        "cnpj"
      ],
      "asset_class": [
        "fidc"
      ],
      "grain": [
        "month"
      ],
      "source": "cvm",
      "meaning": "Exposure to the single largest sacado (tab VIII rank 1), as filed. The debtor is anonymized in the source; divide by receivables in the notebook for a concentration ratio."
    },
    "sacado_top25": {
      "id_type": [
        "cnpj"
      ],
      "asset_class": [
        "fidc"
      ],
      "grain": [
        "month"
      ],
      "source": "cvm",
      "meaning": "Sum of the exposures to the largest sacados the fund filed (tab VIII ranks 1..n, n at most 25). A fund that files fewer than 25 ranks sums fewer; nothing is imputed for the missing ranks. Divide by receivables in the notebook.",
      "derived": true
    }
  },
  "cotahist": {
    "source_url": "https://www.b3.com.br/data/files/33/67/B9/50/D84057102C784E47AC094EA8/SeriesHistoricas_Layout.pdf",
    "reference_date": "2020-10-05",
    "reference_version": "2.0",
    "description_language": "en",
    "description_basis": "Paraphrases of the dated layout; not certified current descriptions or historical validity intervals.",
    "unknown_codes": "Preserve source codes. Missing descriptions stay null; do not reject a row or infer a label.",
    "supplemental_interpretations": {
      "codbdi": {
        "13": {
          "description": "FIAGRO",
          "basis": "Observed instruments and ESPECI in the source file; not an official code-table label.",
          "source_urls": [
            "https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_D05102026.ZIP"
          ],
          "review_date": "2026-10-07",
          "valid_from": null,
          "valid_to": null
        },
        "34": {
          "description": "Non-sponsored BDRs (DRN)",
          "basis": "Observed instruments and ESPECI in the source file; not an official code-table label.",
          "source_urls": [
            "https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_D05102026.ZIP"
          ],
          "review_date": "2026-10-07",
          "valid_from": null,
          "valid_to": null
        },
        "35": {
          "description": "Sponsored BDRs and associated instruments (DR1/DR2/DR3; also PPLA11 UNT)",
          "basis": "Observed instruments and ESPECI in the source file; not an official code-table label.",
          "source_urls": [
            "https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_D05102026.ZIP"
          ],
          "review_date": "2026-10-07",
          "valid_from": null,
          "valid_to": null
        },
        "36": {
          "description": "ETF BDRs (DRE)",
          "basis": "Observed instruments and ESPECI in the source file; not an official code-table label.",
          "source_urls": [
            "https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_D05102026.ZIP"
          ],
          "review_date": "2026-10-07",
          "valid_from": null,
          "valid_to": null
        },
        "92": {
          "description": "Midpoint Order Book",
          "basis": "Observed 92/021 BTCI11M; B3 documents M as Midpoint.",
          "source_urls": [
            "https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_D20072026.ZIP",
            "https://clientes.b3.com.br/c/document_library/get_file?groupId=20119&uuid=88b5af46-5e95-a026-9d92-bb5e598086c0"
          ],
          "review_date": "2026-10-07",
          "valid_from": null,
          "valid_to": null
        },
        "93": {
          "description": "Book of Block Trade (BBT)",
          "basis": "Observed 93/021 Q-suffixed instruments; B3 documents Q as BBT.",
          "source_urls": [
            "https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_D05102026.ZIP",
            "https://clientes.b3.com.br/c/document_library/get_file?groupId=20119&uuid=88b5af46-5e95-a026-9d92-bb5e598086c0"
          ],
          "review_date": "2026-10-07",
          "valid_from": null,
          "valid_to": null
        }
      },
      "tpmerc": {
        "021": {
          "description": "Block trading",
          "basis": "Observed on Midpoint and BBT instruments; exact official market label unavailable.",
          "source_urls": [
            "https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_D05102026.ZIP",
            "https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_D20072026.ZIP",
            "https://clientes.b3.com.br/c/document_library/get_file?groupId=20119&uuid=88b5af46-5e95-a026-9d92-bb5e598086c0"
          ],
          "review_date": "2026-10-07",
          "valid_from": null,
          "valid_to": null
        }
      },
      "indopc": {
        "0": {
          "description": "BRL / no correction index indicated",
          "basis": "Cross-layout interpretation: related securities register maps ICOATV=0 to R$; not an explicit INDOPC definition.",
          "source_urls": [
            "https://bvmf.bmfbovespa.com.br/cias-listadas/Titulos-Negociaveis/download/Titulos_Negociaveis.PDF"
          ],
          "review_date": "2026-10-07",
          "valid_from": null,
          "valid_to": null
        }
      }
    },
    "coverage": "Dictionary presence does not mean observations exist. Consult coverage() and the dated storage/serving audit.",
    "codbdi": {
      "02": {
        "code": "02",
        "description": "Standard lot",
        "status": "documented_in_reference"
      },
      "05": {
        "code": "05",
        "description": "Sanction status (2020 label; repo also uses it for fund subtype)",
        "status": "documented_in_reference"
      },
      "06": {
        "code": "06",
        "description": "Legacy insolvency",
        "status": "documented_in_reference"
      },
      "07": {
        "code": "07",
        "description": "Extrajudicial recovery",
        "status": "documented_in_reference"
      },
      "08": {
        "code": "08",
        "description": "Judicial recovery",
        "status": "documented_in_reference"
      },
      "09": {
        "code": "09",
        "description": "Special administration",
        "status": "documented_in_reference"
      },
      "10": {
        "code": "10",
        "description": "Rights / receipts",
        "status": "documented_in_reference"
      },
      "11": {
        "code": "11",
        "description": "Intervention",
        "status": "documented_in_reference"
      },
      "12": {
        "code": "12",
        "description": "Real-estate funds",
        "status": "documented_in_reference"
      },
      "13": {
        "code": "13",
        "description": null,
        "status": "unknown_in_reference"
      },
      "14": {
        "code": "14",
        "description": "Investment certificates / public debt (legacy label)",
        "status": "documented_in_reference"
      },
      "18": {
        "code": "18",
        "description": "Obligations",
        "status": "documented_in_reference"
      },
      "22": {
        "code": "22",
        "description": "Private bonus instruments",
        "status": "documented_in_reference"
      },
      "26": {
        "code": "26",
        "description": "Public debt instruments",
        "status": "documented_in_reference"
      },
      "32": {
        "code": "32",
        "description": "Index call exercises",
        "status": "documented_in_reference"
      },
      "33": {
        "code": "33",
        "description": "Index put exercises",
        "status": "documented_in_reference"
      },
      "34": {
        "code": "34",
        "description": null,
        "status": "unknown_in_reference"
      },
      "35": {
        "code": "35",
        "description": null,
        "status": "unknown_in_reference"
      },
      "36": {
        "code": "36",
        "description": null,
        "status": "unknown_in_reference"
      },
      "38": {
        "code": "38",
        "description": "Call exercises",
        "status": "documented_in_reference"
      },
      "42": {
        "code": "42",
        "description": "Put exercises",
        "status": "documented_in_reference"
      },
      "46": {
        "code": "46",
        "description": "Unquoted-security auctions",
        "status": "documented_in_reference"
      },
      "48": {
        "code": "48",
        "description": "Privatization auctions",
        "status": "documented_in_reference"
      },
      "49": {
        "code": "49",
        "description": "Espírito Santo recovery-fund auctions",
        "status": "documented_in_reference"
      },
      "50": {
        "code": "50",
        "description": "Auctions",
        "status": "documented_in_reference"
      },
      "51": {
        "code": "51",
        "description": "FINOR auctions",
        "status": "documented_in_reference"
      },
      "52": {
        "code": "52",
        "description": "FINAM auctions",
        "status": "documented_in_reference"
      },
      "53": {
        "code": "53",
        "description": "FISET auctions",
        "status": "documented_in_reference"
      },
      "54": {
        "code": "54",
        "description": "Delinquent-share auctions",
        "status": "documented_in_reference"
      },
      "56": {
        "code": "56",
        "description": "Court-authorized sales",
        "status": "documented_in_reference"
      },
      "58": {
        "code": "58",
        "description": "Other",
        "status": "documented_in_reference"
      },
      "60": {
        "code": "60",
        "description": "Share exchanges",
        "status": "documented_in_reference"
      },
      "61": {
        "code": "61",
        "description": "META",
        "status": "documented_in_reference"
      },
      "62": {
        "code": "62",
        "description": "Forwards",
        "status": "documented_in_reference"
      },
      "66": {
        "code": "66",
        "description": "Debentures, maturity ≤3 years",
        "status": "documented_in_reference"
      },
      "68": {
        "code": "68",
        "description": "Debentures, maturity >3 years",
        "status": "documented_in_reference"
      },
      "70": {
        "code": "70",
        "description": "Retained-gain futures",
        "status": "documented_in_reference"
      },
      "71": {
        "code": "71",
        "description": "Futures",
        "status": "documented_in_reference"
      },
      "74": {
        "code": "74",
        "description": "Index calls",
        "status": "documented_in_reference"
      },
      "75": {
        "code": "75",
        "description": "Index puts",
        "status": "documented_in_reference"
      },
      "78": {
        "code": "78",
        "description": "Calls",
        "status": "documented_in_reference"
      },
      "82": {
        "code": "82",
        "description": "Puts",
        "status": "documented_in_reference"
      },
      "83": {
        "code": "83",
        "description": "BovespaFix",
        "status": "documented_in_reference"
      },
      "84": {
        "code": "84",
        "description": "SomaFix",
        "status": "documented_in_reference"
      },
      "90": {
        "code": "90",
        "description": "Registered spot-forward",
        "status": "documented_in_reference"
      },
      "92": {
        "code": "92",
        "description": null,
        "status": "unknown_in_reference"
      },
      "93": {
        "code": "93",
        "description": null,
        "status": "unknown_in_reference"
      },
      "96": {
        "code": "96",
        "description": "Odd lots",
        "status": "documented_in_reference"
      },
      "99": {
        "code": "99",
        "description": "General total",
        "status": "documented_in_reference"
      }
    },
    "tpmerc": {
      "010": {
        "code": "010",
        "description": "Spot",
        "status": "documented_in_reference"
      },
      "012": {
        "code": "012",
        "description": "Call exercise",
        "status": "documented_in_reference"
      },
      "013": {
        "code": "013",
        "description": "Put exercise",
        "status": "documented_in_reference"
      },
      "017": {
        "code": "017",
        "description": "Auction",
        "status": "documented_in_reference"
      },
      "020": {
        "code": "020",
        "description": "Odd lot",
        "status": "documented_in_reference"
      },
      "021": {
        "code": "021",
        "description": null,
        "status": "unknown_in_reference"
      },
      "030": {
        "code": "030",
        "description": "Forward",
        "status": "documented_in_reference"
      },
      "050": {
        "code": "050",
        "description": "Retained-gain futures",
        "status": "documented_in_reference"
      },
      "060": {
        "code": "060",
        "description": "Continuous-settlement futures",
        "status": "documented_in_reference"
      },
      "070": {
        "code": "070",
        "description": "Call options",
        "status": "documented_in_reference"
      },
      "080": {
        "code": "080",
        "description": "Put options",
        "status": "documented_in_reference"
      }
    },
    "indopc": {
      "0": {
        "code": "0",
        "description": null,
        "status": "unknown_in_reference"
      },
      "1": {
        "code": "1",
        "description": "USD correction",
        "status": "documented_in_reference"
      },
      "2": {
        "code": "2",
        "description": "TJLP correction",
        "status": "documented_in_reference"
      },
      "8": {
        "code": "8",
        "description": "IGP-M correction",
        "status": "documented_in_reference"
      },
      "9": {
        "code": "9",
        "description": "URV correction",
        "status": "documented_in_reference"
      }
    },
    "especi": "Original text is spec; asset_class/fund_type are separate derived classifications. The dated CODBDI label is not an asset-class rule.",
    "record_type": "Only valid register-01 quotes are stored. TIPREG 99 trailer differs from CODBDI 99.",
    "natural_key": [
      "codneg",
      "trade_date",
      "tpmerc",
      "codbdi",
      "prazot"
    ],
    "source_fields": {
      "trade_date": "Session date",
      "board": "CODBDI",
      "ticker": "CODNEG (codneg on derivative routes)",
      "market": "TPMERC",
      "short_name": "NOMRES",
      "spec": "ESPECI",
      "term_days": "PRAZOT",
      "currency": "MODREF; legacy routes may replace null with R$",
      "open": "PREABE",
      "high": "PREMAX",
      "low": "PREMIN",
      "average": "PREMED",
      "close": "PREULT (exercise_price on exercise events)",
      "bid": "PREOFC",
      "ask": "PREOFV",
      "trades": "TOTNEG",
      "quantity": "QUATOT",
      "volume": "VOLTOT",
      "contract_price": "PREEXE (strike on option routes); not yield or credit spread",
      "contract_correction": "INDOPC (strike_correction on option routes)",
      "contract_expiry": "DATVEN (expiry on option routes); 99991231 decoded to null",
      "quotation_factor": "FATCOT",
      "contract_points_raw": "PTOEXE original text",
      "isin": "CODISI; options carry underlying identity, not necessarily the option series ISIN",
      "distribution_number": "DISMES sequence, not a cash distribution amount"
    },
    "derived_fields": {
      "contract_points": "PTOEXE / 1e6; zero filler or unreadable points become null; strike_points on option routes",
      "close_unit": "close / NULLIF(quotation_factor, 0), not a corporate-event adjustment"
    },
    "routes": {
      "cash": {
        "market": [
          "010"
        ],
        "view": "quotes",
        "history": "quote_history",
        "latest": "quote_latest"
      },
      "classified_cash": {
        "market": [
          "010",
          "020",
          "021"
        ],
        "views": [
          "equities",
          "bdrs",
          "units",
          "fund_quotas",
          "cash_securities"
        ],
        "limitation": "Only these five classes have typed views; index/right/bonus 010 prints remain in quotes."
      },
      "options": {
        "market": [
          "070",
          "080"
        ],
        "functions": [
          "option_chain",
          "option_history"
        ]
      },
      "exercises": {
        "market": [
          "012",
          "013"
        ],
        "function": "option_exercises",
        "kind": "event"
      },
      "auctions": {
        "market": [
          "017"
        ],
        "view": "auctions",
        "kind": "event"
      },
      "forward": {
        "market": [
          "030"
        ],
        "function": "termo_history"
      }
    },
    "local_http_optional_fields": "Additional raw quote_history fields are selectable with fields; adjusted/total-return fields stay SQL-only.",
    "local_http_default_history_fields": [
      "open",
      "high",
      "low",
      "close",
      "volume",
      "trades"
    ],
    "provenance_limit": "fetched_at is warehouse time; source is the dataset identifier, not file identity. No byte-exact payload, header/trailer reconciliation or source-vintage archive."
  },
  "notebook_reducers": {
    "describe": "Per-column n, null_rate, min, max, last. No model.",
    "corr": "Pairwise Pearson on complete pairs of the wide matrix. One relation among many.",
    "rank": "Latest non-null value per id for the first metric, descending.",
    "spread": "First column minus second column of the wide matrix, dates aligned."
  },
  "constraints": [
    "PORTFOLIO FEE PEERS ARE A CURRENT EXTRATO SNAPSHOT, NOT A HISTORY OR SAVING ESTIMATE. portfolio_fee_peers compares positive administration fees up to 5 percent/year filed within 36 months, within the same ANBIMA class, FUNDO_COTAS S/N and FI versus CLASSES-FIF document scope. Active means a non-null quota in the current or previous two reference months. ETFs enter the group (v66, #609) only through the owner-reviewed ANBIMA class to index map, because CVM files no ANBIMA class for an ETF: an active ETF whose underlying index is mapped to the class is a peer in each of the class's cells, with the third-party etfsbrasil fee (etf_market_snapshot), never a CVM-disclosed one, and is counted apart (n_etf_peers beside n_fund_peers, etf_peer_tickers, etf_peer_fee_source). At least 30 usable FUND fees (including the target when eligible) are required; ETFs never make a group qualify, they only join one that already has 30 funds (owner, #609 Q18); no wider fallback. Percentile uses midrank ties; difference is percentage points from the median. Future/latest-only documents, zero or invalid fees and insufficient groups are explicitly not compared. Performance fees, total expense and replacement recommendations are outside scope.",
    "A CLASS RETURN DISTRIBUTION IS A STATISTIC OF FUNDS, NOT A BENCHMARK OR A RECOMMENDATION. class_return_distribution (v66, #609) gives, for one ANBIMA class exactly as filed in the Extrato and one FUNDO_COTAS flag, the p25, median and p75 of the FI funds' net quota return (fact_fund_monthly's stable quota subclass, the quota fund_nav serves) over 12 and 6 months ending at the close of one month. Active funds as in portfolio_fee_peers; a fund with no positive quota at either end, or with a quota subclass change, is excluded and counted. Fewer than 30 funds with a return, or an incomplete month: nao_avaliado with a reason, never a wider class. ETFs are not in the universe; an equivalent ETF's own return is set against these numbers by the caller.",
    "A CRA OR CRI RETURN IS THE SECURITIZER'S VALUE ON THE CURVE, NOT A MARKET PRICE. portfolio_credit_returns (v71, #766) gives, per CETIP code, the 13 month-ends p_end_month - 12 .. p_end_month from cvm_securit_serie (the series p_series / p_classes name, from portfolio_instruments, else the code's only series in the window; the highest versao of each month): pu = valor_certificados / quantidade_certificados, paid_per_unit = (rendimentos + amortizacoes) / quantidade, and factor = (pu + paid) / previous pu. Compound the 12 factors for the 12-month return. A month_flag makes the month, and every window that contains it, unknown: serie_ambigua, mes_ausente, valor_invalido, quantidade_mudou, pu_repetido (the month before's value carried over), queda_sem_evento_arquivado (the pu falls and no payment is filed: an unfiled coupon, never a loss), pagamento_acima_do_pu, pagamento_incompativel (a payment month whose return is outside 0.5 .. 1.5 times the line's median month with no payment, or with fewer than 3 such months). Measured 2026-10-08: with complete filings MRV's CRI 24I1980390 returns 109.9% to 110.1% of the CDI over 12 months against a contract of 110%; its 2026-04 coupon was never filed. rentabilidade is never read. No credit event the filing does not show is visible here.",
    "A CRA OR CRI RETURN IS THE SECURITIZER'S VALUE ON THE CURVE, NOT A MARKET PRICE. portfolio_credit_returns (v71, #766) gives, per CETIP code, the 13 month-ends p_end_month - 12 .. p_end_month from cvm_securit_serie (the series p_series / p_classes name, from portfolio_instruments, else the code's only series in the window; the highest versao of each month): pu = valor_certificados / quantidade_certificados, paid_per_unit = (rendimentos + amortizacoes) / quantidade, and factor = (pu + paid) / previous pu. Compound the 12 factors for the 12-month return. A month_flag makes the month, and every window that contains it, unknown: serie_ambigua, mes_ausente, valor_invalido, quantidade_mudou, pu_repetido (the month before's value carried over), queda_sem_evento_arquivado (the pu falls and no payment is filed: an unfiled coupon, never a loss), pagamento_acima_do_pu, pagamento_incompativel (a payment month whose return is outside 0.5 .. 1.5 times the line's median month with no payment, or with fewer than 3 such months). Measured 2026-10-08: the MRV 24I1980390 check still has an unfiled April 2026 coupon and is unknown. rentabilidade is never read. No credit event the filing does not show is visible here.",
    "DEBENTURE RETURNS ARE MEDIAN FUND MARKS, NOT TRADE PRICES. portfolio_debenture_returns (v73) uses only exact ticker matches in cvm_fi_cda_acoes block 4 with tp_aplic='Debêntures': each fund's PU is sum(vl_merc_pos_final)/sum(qt_pos_final), then the monthly PU is the median across funds. At least 3 funds are required. This source has no coupon or amortization flow, so it never invents either. Missing months, invalid positions, fewer than 3 funds, or a decline whose event cannot be screened leave the window unknown. The owner deferred the monthly fall limit; NULL therefore marks every PU decrease as limite_pendente until that decision is recorded. The marketed flag cvm_fi_cda_debentures.titulo_cetip is not an instrument code and is not used.",
    "A MARKET EQUIVALENT NAMES AN ETF WITH THE SAME OBJECTIVE, NOT A RECOMMENDATION. portfolio_equivalents (v68, #609) lists, for each ANBIMA class exactly as filed in the Extrato, the active ETFs (cvm_etf_registry.is_active, one row per CNPJ) that track an index the owner-reviewed class-to-index list maps to the class (only approved pairs, read in reverse), with each ETF's third-party PL and fee from etfsbrasil.com.br (etf_market_snapshot, dated, never a CVM filing). is_equivalent marks the largest by PL across all the class's indices (ties by ticker); an ETF with no PL is never ranked. segment says where its prices are: fixed_income_br in trade_consolidated_history (last_price), the others in quote_history (close, without distributions). A class with no approved pair, no active ETF or no PL comes back with status sem_par, sem_etf or sem_pl and a reason. The index is never inferred from a fund's name. Since v68 portfolio_fees also serves the filed benchmark whatever the fee source: benchmark_extrato (the Extrato's PARAM_TAXA_PERFM, its only benchmark column) and benchmark_lamina (the lâmina's INDICE_REFER when every class filed the same one, benchmark_lamina_n distinct values); as filed, never inferred from a name or a class.",
    "A NULL OUTSIDE A FAMILY'S COLUMN SET IS NOT APPLICABLE, NOT MISSING. fund_nav returns the same eleven columns for every family, but each family files only some of them (`applicability` in this catalog, read off fact_fund_monthly's per-family arms): fi files quota, quotaholders, inflows and redemptions; fidc and fiagro file delinquency; fii files quotaholders, monthly_yield and assets; fip files nav alone. A null outside that list is set by construction and carries no information; a null inside it is a blank in that month's filing.",
    "A FIDC CEDENTE SHARE IS A PERCENT OF ITS BLOCK, NOT OF THE FUND. fidc_cedentes serves tab I's nine slots per block: bloco A is the receivables acquired WITH substantial retention of risks and benefits by the originator, B WITHOUT, and share_pct is the cedente's share of that block. The block totals are not served (tab I's asset lines are not ingested), so a share cannot be turned into reais here. cedente_id is the originator's own filed CPF/CNPJ, kept only when its check digits verify — placeholders (all-zero, all-nine) and unrecoverable identifiers were dropped at ingest, never coerced — and cedente_tickers is the FCA map's active listings for it, NULL when not listed. share_pct is AS FILED and dirty in the way CVM's percentage fields are: 9% of slots carry a value above 100 (max 19,771 in 2026-07); validate the range in the notebook, never read it as a fraction. Slots exist from 2019-11; nothing is matched by name.",
    "FIDC SACADOS ARE ANONYMIZED RANKS. fidc_sacados and the sacado_top1 / sacado_top25 metrics come from tab VIII, which publishes the 25 largest debtors as (rank, value) with no identity — CVM's dictionary describes neither column. seq is CVM's rank as filed and is never recomputed from valor (65 of 3,043 funds filed a non-descending series in 2026-07; they are served as filed). sacado_top25 sums the ranks the fund filed, which may be fewer than 25. Concentration = sacado_top1 / receivables (or top25 / receivables) is a notebook division, not a served number — and it can exceed 1: tab VIII and tab II do not share a base for every fund (2026-07: the top-25 sum exceeds the receivables total for 1.9% of funds, rank 1 alone for 0.5%), served as filed and never capped.",
    "FIDC PORTFOLIO ROWS ARE A HIERARCHY. fidc_portfolio kind=sector serves tab II as one row per code: TOTAL is the whole receivables book, a lettered code (A..K) a sector, and a code with a digit (C1, F3) a member of its lettered parent (`parent`). Sum leaves or sum parents, never both. kind=scr_debtor and kind=scr_operation are the BACEN SCR grade ladders AA..H for the same receivables, graded by debtor and by operation respectively — two views of one book, not two books. tab X exists from 2023-10 only; earlier months have no scr rows, not zero-graded ones.",
    "WHICH CODE PRODUCED THIS DATA. coverage().landed_git_sha is the git commit of the very ingest run that set landed_at — the code that parsed and stored the newest data for that dataset — read from GITHUB_SHA on the run. It is NULL when that run recorded none (a run from before lineage existed, 2026-09-24, or one started outside GitHub Actions), and it is never borrowed from an older run, because an older run's code did not produce the newest rows. The audit log behind it also records parser_version, bumped only when a parser or field map changes what a stored value means; neither is a property of the SOURCE, so neither says anything about how much CVM, B3 or BACEN have published (that is complete_through).",
    "FIDC TRANCHES AND AGING BEGIN IN 2013-01, AND ARE SERVED AS FILED. fidc_tranches (informe tabs X_2/X_3/X_6 + X_4) and fidc_aging (tab VI) are loaded from 2013-01: CVM's yearly HIST archive through 2024-12, the monthly informe from 2025-01. The value columns have the same names in both; only the fund identifier column changes (coverage() measures the span). fidc_tranches is one row per (fund, month, classe_serie): quotas, quota_value, return_month, and performance_expected vs performance_realised (what the series promised vs delivered, percent), dirty the way CVM's percentage fields are (CVM files magnitudes of 1e14 and more) — never rescaled, never clipped, range-check in the notebook. Its `flows` array carries tab X_4's operations with CVM's TP_OPER label verbatim (e.g. Captações no Mês, Resgates no Mês, Amortizações); the vocabulary has drifted, so match labels yourself and never read a label you did not find as zero. tranche_filed = FALSE marks a series with flows but no X_2 row. fidc_aging is long: kind=to_maturity (not yet due, by days to maturity) and kind=overdue (by days past due), ten day-bands each, plus kind=overdue_total — CVM's FILED total, not a sum of the bands, and the two can disagree. Nothing is derived by either function: no performance gap, no subordination ratio, no band sums.",
    "THE FNET REGISTER KNOWS A DOCUMENT'S FUND ONLY BY LINK, AND LINKS NO VERSIONS. fund_documents and fund_restatements serve B3 Fundos.NET's document register as published, metadata only: each version is its own fnet_id, versao counts the filings, modalidade is AP (original), RE (voluntary restatement) or RC (a restatement CVM required), and status is AC / IC (superseded) / CC (cancelled) AS OF fetched_at, not live. FNET rows carry NO CNPJ: a document belongs to a fund because FNET returned it when SILO queried cnpjFundo = that CNPJ, in a sweep that reaches every FII/FIDC once a fortnight — so a document delivered since the fund's last sweep is not in fund_documents yet, and fund_restatements serves it with cnpj NULL rather than dropping it. fund_name is FNET's label and is never joined on. Because FNET does not say which document a re-filing replaces, fund_restatements PAIRS each versao > 1 with the document in the same group — (cnpj link, categoria, tipo_documento, especie, reference_raw) — carrying the highest lower versao, the greatest fnet_id winning a tie (a group can legitimately hold several v1 documents, e.g. assemblies); an unlinked document or one with no reference text is never paired, so its previous_fnet_id and lag_days are NULL — not 'no predecessor', just not pairable. lag_days is days between deliveries. source_url is FNET's own download link for the id. History starts at SILO's first crawl or backfill, not at FNET's; coverage() reports the fnet_documents span.",
    "A RESTATEMENT DIFF COMPARES FNET'S TWO VERSIONS OF ONE DOCUMENT, FIELD BY FIELD, AND ONLY WHERE SILO HAS DIFFED THEM. fund_restatement_diff returns one row per field that differs between a re-filed document and the version fund_restatements pairs it with (previous_fnet_id): for now the FIDC informe mensal only, restatements delivered from 2026 on. field_path is the XML path; a repeated block (a tranche, a cedente) is addressed by its declared key, CLASSE_SENIOR[SERIE=Série 1], and one with no usable key by position, [#2] — match_basis says which, and position rows are approximate by construction (a dropped duplicate block reads as removed fields). old_value / new_value are the text exactly as printed, comma decimals included; NULL is nil or absent and change_kind says which (changed, added, removed, nil_to_value, value_to_nil). old_num / new_num / delta exist only on numeric leaves (amounts, quantities, percentages, rates): an identifier such as a CNPJ is compared as text, and nothing is coerced. cvm_column stays NULL until an XML-to-CVM-column crosswalk exists, so do not assume a path maps onto a SILO column. A document with no rows was re-filed with nothing changed OR was not diffed: read fund_restatements' diff_status (compared, or why not — unlinked, no predecessor yet, not XML, a declared key or a stored body hash that disagrees; NULL = not diffed) and n_fields_changed, which counts this function's rows for the pair. The diff is of FNET's documents, not of CVM's CSVs (republished in place), and tab VIII (debtors) is not in the XML, so its restatements are invisible here.",
    "FIDC DELINQUENCY STARTS IN 2013-01 AND IS ON EVERY ROW FROM 2020-11. `delinquency` is tab VI's total of overdue credits (TAB_VI_B_VL_DIRCRED_INAD) as filed: from CVM's yearly HIST archive through 2024-12, from the monthly informe from 2025-01, the same field on both. Through 2020-10-31 a fund with no tab VI row that month, or a blank cell, is null (about 70% to 93% of fidc rows carry a value); from 2020-11-30 it is filed on every row, and a fund with no delinquent receivables files 0. A null is not zero and not clean books: never read it as zero or fill it, and never compare a count of reporting funds across 2020-10 → 2020-11. Machine-readable in `regime_breaks`, and on the funds_fidc coverage row's `notes`.",
    "A FUND'S DEBENTURE HOLDINGS ARE A DIFFERENT SHAPE FROM ITS EQUITY HOLDINGS. api.fund_debentures (CDA block 6) is one row per (fund, month, issuer, maturity, rate structure, application type), as filed and never summed — two series of one issuer maturing the same day at different coupons are different securities. The issuer is its own filed CPF/CNPJ (issuer_id); p_issuer also takes a listed company's ticker or CVM code, resolved only through CVM's published FCA map, and issuer_tickers carries the issuer's active listed codes back (NULL when not listed — most debenture issuers are not). Nothing is matched by name.",
    "ANBIMA CLASS ROWS ARE INDUSTRY AGGREGATES, NOT FUNDS. api.anbima_classes serves the Boletim de Fundos de Investimento as published — R$ milhões (unit brl_mm) and percentage points (unit pct) — per class, ANBIMA type or industry total (`level`; class aggregates by default). No fund in this warehouse is mapped to an ANBIMA class: CVM's `classe` is CVM's taxonomy, so never join a fund to a class by name, and there is no panel arm because these rows carry no id. An unknown category, metric or level raises 22023 listing what exists rather than returning an empty array.",
    "INFLATION IS SERVED AS PUBLISHED, IN PERCENT, WITH ONE DERIVED COLUMN PER FUNCTION. api.inflation is BACEN's SGS, long: value is the change in the month (unit pct_month) except IPCA_12M — BACEN's own 12-month accumulation, code 13522 (pct_12m) — and IPCA_DIFUSAO, the share of items that rose (pct_items). acc_12m is DERIVED: the trailing twelve monthly changes chained, ((Π(1+v/100))−1)×100, NULL unless all twelve months are present and consecutive — never a shorter chain, never filled; it reproduces IPCA_12M exactly for the headline, which is served beside it so you can check. IPCA15 is the mid-month preview, not a revision of IPCA. Group rows (family = group) are VARIATIONS, not contributions: the weights live only in api.inflation_items, whose contribution column is weight × change_month / 100 in percentage points of the headline — sum contributions within ONE level only (a group and its subgroups are the same money twice). BACEN's group codes are NOT in IBGE's order (1640 is Comunicação, 1641 Saúde, 1642 Despesas pessoais, 1643 Educação; measured against IBGE SIDRA, do not reorder by intuition). SIDRA's item codes changed with the 2020-01 structure; item_number is the continuity and sidra_table says which. Neither function has a panel arm — the rows carry no id — and an unknown series, family, level or item raises 22023 rather than returning an empty array.",
    "THE SCREENS ARE SIGNALS, NOT VERDICTS. api.screen_zombie_growth, screen_captive_vehicles, screen_evergreen_aging, screen_overdue_securit, screen_dormant_funds, screen_dormant_trend, screen_delinquency_drivers, screen_restatements, screen_late_filers and screen_silent_filers return the funds or series that crossed a stated threshold in public filings — never a score, a rating, a rank of suspicion or a finding. Every row carries `screen` (which one produced it) and `params` (the exact arguments, keyed by argument name, so the call can be replayed); `screens` in this catalog says what each measures and what else produces the same pattern (an exclusive FII is legal and looks captive; a distressed-credit mandate looks like zombie growth; an extended CRA looks overdue until it is re-filed). Defaults reproduce the dashboard pages (/suspicious, /dormant, /fidc) for the seven that have one; the three filing screens have no page and their defaults are stated in `screens`. A threshold out of its range or NULL raises 22023 — it is never clamped, because a screen evaluated at a threshold you did not ask for is a different screen. Confirm any row against the fund's own filings before repeating it.",
    "A LATE FILING IS A TIMESTAMP COMPARED WITH A CITED RULE, AND A SILENT ONE IS READ FROM CVM, NOT FNET. screen_late_filers measures the FIRST FNET delivery of a fund's monthly informe (Informe Mensal Estruturado, versao 1) against the deadline Resolução CVM 175 states — FIDC: Anexo Normativo II, art. 27, III; FII: Anexo Normativo III, art. 36, I; both 15 days after the end of the reference month, counted as calendar days because the text says dias — and every row carries that citation in deadline_rule. It measures only months after each family's adaptation deadline (from 2024-12 for FIDC, 2025-07 for FII) and refuses a window ending earlier, because the predecessor instructions' deadlines are not cited here. No holiday calendar is applied, so p_min_days_late (default 5) absorbs a deadline that rolled over a weekend or holiday; CVM extensions are invisible to it. A month with no informe in the register is NOT counted late — FNET history is partial. screen_silent_filers answers absence from CVM's own deep tables (dim_fund: the informe diário for FI, the monthly informe for FIDC / FII / FIAGRO) against latest_complete_period, for funds whose registry row is active; a merged or liquidated fund whose status CVM has not updated, reporting moved to a new class CNPJ, or a SILO ingest gap produce the same row. screen_restatements counts re-filings (versao > 1) by modalidade — RE voluntary, RC required by CVM — per cnpjFundo link. None of the three ever identifies a fund by fund_name.",
    "COMPANY EVENTS ARE IPE FILINGS AS FILED, FROM 2015, AND NOT EVERY FILING IS HELD. api.company_events serves cia_event — CVM's IPE feed: fatos relevantes, comunicados ao mercado, assembly material and the rest — one row per protocol at its NEWEST version (version says which), every text field (category, event_type, species, subject) exactly as filed, and source_url, the document's link on CVM's RAD. The company is resolved exactly as financials resolves p_id: a ticker only through CVM's published FCA map (active listings), a 14-digit CNPJ or a CVM code, never a name. CVM assigned no protocol number to IPE filings before 2015 and still omits it on a minority (12% of 2015); cia_event is keyed on (protocolo, versao) and a key is never synthesized, so those filings are NOT held — an empty window before 2015, or a filing you know exists and cannot find, is that limit, not an absence of events. p_category matches CVM's label exactly; an unknown one raises 22023 listing the categories held.",
    "MACRO SERIES AND PTAX ARE SERVED AS BACEN PUBLISHES THEM, UNIT ON EVERY ROW, NOTHING DERIVED. api.macro_series serves nine non-inflation SGS series by label or code: SELIC_META (432, % a.a.; dated per calendar day and published AHEAD to the next Copom date, so a p_to after today can return forward-dated targets), SELIC_DIARIA (11) and CDI (12) in % PER BUSINESS DAY (never annualise one yourself without saying so), IGPM (189) and INPC (188) as % change in the month, POUPANCA (25) — the OLD-RULE deposit return (deposits until 2012-05-03), one value per anniversary day, each the return over the month starting that day, not a calendar-month figure — USDBRL (1) and EURBRL (21619) in BRL per unit, and PIB (4380) monthly in R$ millions at current prices. The IPCA set is api.inflation's; asking macro_series for it raises 22023 with that pointer. api.ptax serves PTAX compra and venda per currency and business day in BRL per ONE unit of the currency (JPY and ARS included): the last bulletin of the day the ingest received, which for a completed day is the Fechamento PTAX (measured against SGS 1 and Olinda on 2026-09-22/23); the bulletin type is not stored. No mid rate, cross rate, fill or holiday row is invented.",
    "THE RESEARCH UNIVERSE IS A TAPE FACT, NOT A LISTING RECORD, AND ITS COMPANY LINK SAYS HOW IT WAS MADE. api.research_universe returns one row per ticker+ISIN pair of listed shares and units traded on the B3 cash market since 2019-01-02 (the start of the tape). Membership is the ISIN's own instrument code, characters 7-9: ACN (shares), CDA and UNT (units, whose ticker must also end in 11); subscription receipts, BDRs, funds and indices are outside it, so instrument_type = equity on api.quotes is NOT the definition (it lets about 100 receipts in). THE ISIN IS THE IDENTITY: a rename is a NEW row and nothing links it to the old one, and two tickers can share an ISIN (NEOE3 and NEOE3B). first_observed, last_observed and n_sessions are facts about SILO's tape, never listing or delisting dates; n_sessions far below the calendar span is a gap (NATU3: one ISIN, no sessions 2019-12 to 2025-07). cnpj comes from CVM's published FCA ticker map and cnpj_basis says how: fca_ticker (that exact ticker), fca_issuer_stem (the ticker's 4-letter stem, when exactly one CNPJ holds an FCA ticker with it: an inference, so it is labelled), or NULL (no link: cnpj and setor_current are NULL, never guessed from a name). setor_current is CVM's cadastro setor as of TODAY, not the setor on a past date. TO READ THE UNIVERSE AT A DATE T, keep the rows with first_observed <= T <= last_observed; a pair inside a gap still matches that filter. The view is rebuilt daily, so last_observed lags the tape by up to a day (built_at says when). Not trimmed: more than 1000 rows raises 22023.",
    "THE BENCHMARK INDEX IS api.index_history, TAKEN BY INDEX CODE, AND EVERY CODE IT HOLDS IS A TOTAL-RETURN INDEX, AS B3 PUBLISHES IT. It serves the daily level of a B3-published index (IBOV from 1968-01-02, then IBXX, IBXL, IFIX, SMLL, IDIV, ICON, IMOB and UTIL, each from its own first session; coverage() lists the depth of each) from B3's own statistics, and accepts an INDEX CODE only: a ticker raises 22023 naming the codes held, so BOVA11 (an ETF) and IBOV11 (the Ibovespa options settlement code: each of its prints is that session's settlement index, never the official close, and since December 2025 it prints on nearly every session, so a dense series is not a sign that it is the index) can never stand in for the index by construction. The levels are NOT adjusted: B3 re-scaled IBOV eleven times (divided by 100 on 1983-10-04 and by 10 on ten other sessions, the last on 1997-03-03) and divisor_step is TRUE on the first session after each, where a level ratio is not a return; from 1997-03-03 on there is none. B3 itself labels IBOV and each of those codes a total-return index (distributions reinvested, Manual de Definicoes e Procedimentos dos Indices da B3, Feb 2023; IDIV's separate Price Return version is not on this endpoint and is not served), so a level already includes dividends: the like-for-like series from quote_history is close_total_return, never close_adj, which is price only. Levels before an index's publication date are B3's own back-calculation and are not marked. There is no return or adjusted column, and no code is labelled anything but what B3 calls it. It pages with p_after like quote_history, because IBOV from 1968 is 14,489 rows.",
    "THE FIXED-INCOME ETFs ARE IN api.trade_consolidated_history, NOT IN quote_history, AND THEIR CLOSE IS last_price. B3 lists the 46 Brazilian fixed-income ETFs (IMAB11, B5P211, IRFM11, LFTS11, ...) in segment FORWARD, which the COTAHIST files do not carry, so quote_history and panel have nothing for them. api.trade_consolidated_history serves B3's TradeInformationConsolidatedFile for that segment only (the 46 ETFs and 21 other FORWARD tickers), one row per ticker and session, as published: ticker, trade_date, isin, segment, min_price, max_price, avg_price, last_price, ref_price, oscillation_pct, trade_count, quantity, notional_brl, file_status, source. A ticker it does not hold raises 22023 saying so and pointing at quote_history; an unknown ticker never comes back as an empty set. The close is last_price. ref_price is B3's reference price, NOT a trade and NEVER a close: a session with no trade carries only ref_price, and last_price (with the other price, count and volume columns) is NULL there. There is NO opening price: the file has none, and none is ever filled from another source. notional_brl is this file's volume and is not comparable with COTAHIST's or B3's BDI (BOVA11 on 2026-09-29: R$587,459,700.14 here against R$588,765,462.41 in COTAHIST). Prices are NOT adjusted for distributions: a return from last_price is a price-only return, which understates the real return of an ETF that distributes income (many fixed-income ETFs pay coupons); for one that reinvests the difference is small. History starts at the source's retention edge, 2025-06-10 when checked on 2026-09-30, and cannot be extended backwards. It pages with p_after like quote_history.",
    "THE PORTFOLIO FUNCTIONS RESOLVE, COST AND LOOK THROUGH A SET OF FUNDS AND COMPARE EACH FUND'S MONTH WITH ITS CLASS, AND EACH SAYS WHAT IT DID NOT DECIDE. api.portfolio_resolve takes statement lines (p_names, with optional parallel p_cnpjs, p_quotas and p_quota_dates) and returns up to 5 candidate funds per line, ranked: a CNPJ the line carries wins (match_kind cnpj); else (v56) a name that is exactly a ticker of SILO's curated ETF registry (cvm_etf_registry) gives that ETF's CNPJ (match_kind etf_ticker, one candidate, never ambiguous: api.lookup returns no CNPJ for a ticker and a fixed income ETF is not in COTAHIST); else an exact match, case and accents ignored, on any name the fund ever filed (exact_current, or exact_history for a former legal name, with matched_period the last CDA month it was filed under); else trigram over the whole name history, similarity 0..1 (an input of up to four words also scores by word_similarity, so an abbreviation like XP Bancos can match; anything below 0.25 is no candidate). A quota the statement prints is compared with the candidate's cvm_fi_diario quota on that exact date and one within 0.5% ranks first, which is how the XP Bancos master and its FIC (same words, different quotas) are told apart. Since v72 a FIAGRO, which files no daily quota, is compared on a month-end date with its cvm_fiagro_mensal quota of that month (filed with two decimals, so the tolerance is half a cent of the quota plus 0.01%; on any other date no quota is read, and FII is not read), and a fund whose name scores below the floor only because the line abbreviates its type (FIRF, CrPr) is added as a name hint: scored 0.5 at most, ranked behind the candidates that scored on their own unless its quota matches and theirs does not, the reason says so, and the line stays ambiguous unless that fund's quota matches. ambiguous is TRUE on every row of a line whose top two candidates are within 0.05 of similarity and the quota does not separate them: the line is UNRESOLVED, the reason says why, and nothing is picked silently. No indexer, sector or economic group is ever inferred from a name. At most 200 lines per call. api.portfolio_fees keeps two kinds of number apart. DISCLOSED (disclosed_*) is the fee the fund published: from the Extrato (cvm_fi_extrato, newest version) first, else the lamina (cvm_fi_lamina, newest reference month), else cad_fi (cvm_fund_registry taxa_adm / taxa_perfm, legacy funds only), ONE source per fund, named in disclosed_origin (extrato, lamina or cad_fi) and disclosed_source with disclosed_as_of (the filing date), disclosed_age_months and disclosed_age_days. The order is the CVM Extrato das Informacoes first (cvm_fi_extrato, one row per fund or class, a fee for 84.3% of active FI funds; for a CVM 175 fund it is the CLASS, there is no subclass column and no subclass fee is assumed), then the lamina, then cad_fi. A filed administration fee of exactly 0 comes back as 0 with filed_zero TRUE (read it as not informed, never as a zero cost); a filed value above 5 is NOT returned as the fee: disclosed_taxa_adm is NULL, implausible_filed is TRUE and the value as filed is in taxa_adm_filed_raw. An Extrato row that exists stays the source even then, unless (v55) it filed exactly 0 or above 5 and the lamina's single fee is in (0, 5] and NEWER: then the newer lamina is the source. fee_resolution names the rule that applied (extrato, extrato_lamina_beside when the Extrato filed 0 or above 5 and a lamina fee is returned beside it, extrato_to_check when there is none, lamina_newer, lamina, cad_fi); lamina_taxa_adm (with _min, _max, lamina_n_classes, lamina_age_months) and extrato_taxa_adm_filed (with extrato_as_of) give the other document's fee as filed for every fund, never rescaled and never a fee to add; extrato_lamina_ratio is the Extrato over the lamina when both are above 0, and extrato_scale_factor is 10 or 100 when an Extrato above 5 equals that factor times the lamina within two-decimal rounding, a flag only. Treat every fund whose fee_resolution is extrato_lamina_beside or extrato_to_check as to be checked and sum neither value. For lamina_newer the newer lamina's fee in disclosed_taxa_adm is a disclosed fee like any other: use it as the cost, sum it and compare it with the estimate (owner's decision of 2026-10-03, v56), keep the fund flagged for review because the two documents disagree, and never sum the Extrato value beside it. The Extrato's performance fee (extrato_taxa_perfm with its benchmark, method and text), entry and exit fees and custody fee are returned as filed, and lamina_pr_pl_despesa is the declared total expense ratio from the lamina with its period, never added to the administration fee. ETFs (v56): CVM's Extrato, lamina and cad_fi carry no fee for an ETF (0 of the 178 active registry ETFs on 2026-10-03), so for a CNPJ in SILO's curated ETF registry etf_ticker names its ticker and etf_site_taxa_adm, etf_site_as_of and etf_site_source give the 'Taxa de administracao total' that etfsbrasil.com.br prints (etf_market_snapshot, the newest snapshot with a fee, joined by ticker): a third-party site, not a CVM filing, never in disclosed_*, returned as published; etf_site_note says so and why a value is NULL. Since v57 etf_site_nr_cotistas and etf_site_pl give the number of quotaholders and the net assets in R$ that the same site prints in the SAME snapshot (etf_site_as_of): third-party descriptive facts, never summed, never a fee base (CVM has no 2026 daily report row for any registry ETF, so they are the only ones SILO holds). A part not filed is NULL, never a zero fee, and lamina classes that disclose different fees give a NULL single value, a min and max and a note. The ESTIMATE (adm_fee_flow, perf_fee_flow, *_pct_annual_est) comes from the balancete accruals: the fee accounts accumulate from each fund's fiscal-year start and are filed negative, so the month's accrual is previous minus current accumulated value, times 12 over NAV (groups 6 + 7 + 8) in percent a year. In the fiscal-year reset month the accumulated fee falls: fiscal_reset_suspect is TRUE and the estimate is NULL, unless cad_fi DT_INI_EXERC confirms the fiscal year starts that month, when the month's accumulated value alone is the accrual. The estimate is labelled an estimate on every row and is never the disclosed fee. At most 200 CNPJs per call. api.portfolio_lookthrough follows the fund quotas of CDA block 2 from each root, recursively (cycle-guarded, p_max_depth 1..6, default 4), for ONE CDA month: p_month, or the last month whose block-2 filing count reaches 90% of the median of the 12 before it (the /holdings rule). Every fund on the way lists its own holdings: block 1 government bonds (repo collateral is NOT a holding of the bond and is served apart as asset_kind repo), block 2 quotas (fund_quota when looked through, else fund_quota_unfiled when the held fund filed no CDA that month, fund_quota_depth_cap, fund_quota_cycle), block 4 stocks and debentures (issuer_code is ISIN characters 3-6, never a CNPJ) and block 6 private credit (issuer_cnpj only when the filing says the issuer is a PJ; indexer as filed). weight_in_root is the value over the holder's NAV (fact_fund_monthly, same month) times the weights down the path; NULL when a NAV on the path is unknown. A fund reached by two paths appears once per path: sum weight_in_root over every row but fund_quota. Blocks 3, 5, 7 and 8 are not ingested, so weights need not sum to 1 and cash is not shown. At most 200 CNPJs per call. api.portfolio_movement says whether a fund's month is unusual for its own class (movimento incomum), for ONE month (p_month, or the last complete FI month): own_value_pct is the fund's monthly QUOTA RETURN, month-end vl_quota over the previous month's (fact_fund_monthly, the one stable quota subclass), in percent; a NAV change is not used, because most of it is flows. The class is the ANBIMA class AS FILED in the CVM Extrato (class_as_filed, its newest filing, not the class on the month's date; class and subclass split that label at its first ' - ' for display, nothing is read from a fund's name); the peers are every FI fund of that class with a return that month (n_peers, the fund included). class_mean_pct and class_sd_pct are the mean and sample standard deviation of the peers' returns winsorized at the class's own 1st and 99th percentile of that month (class_p01_pct, class_p99_pct); the fund's own value is not winsorized. z = (own - mean) / sd. level is forte when |z| > 3 (investigator_trigger TRUE), atencao when |z| > 2, normal otherwise, strictly greater: exactly 2 is normal. A fund is nao_avaliado, with a Portuguese reason, when its class has fewer than min_peers (30) peers with a return or a zero standard deviation, it has no class (outside the Extrato, which covers about 84% of active FI funds, or no classe_anbima), no return (no quota in both months), is an ETF, FIDC, FII, FIP or FIAGRO, or the month is not complete; there is no fallback to a wider class. Measured on production over six months to 2026-09, among the funds evaluated, |z| > 2 flagged 5.2% to 5.7% of fund-months and |z| > 3 2.4% to 2.9%. It states a number, a class, a sample size and a month: it is not a forecast, a verdict or a recommendation. api.portfolio_instruments (v62) takes a statement's instrument codes (p_codes; trimmed, upper-cased, a leading CRA-, CRI- or DEB- stripped, the hyphen required) and, per code: match_kind securit_cetip for a CRA or CRI whose codigo_cetip is the code in cvm_securit_serie, every series at the code's newest data_referencia, one row per (numero_serie, classe) at its highest versao, the series columns as filed (instrument_type cra_mensal or cri_mensal, cnpj_securit, data_vencimento, situacao, taxa_juros as text, classificacao_risco_atual, valor_total_integralizado), and since v67 cd_isin, the series' codigo_isin as filed, not validated (NULL when not filed; issuer_code stays NULL, a CRA or CRI ISIN names the securitizer); else match_kind cda_ticker for a debenture in CDA block 4 (tp_aplic Debêntures) at the newest month the code appears in at all (cda_period; the newest CDA month may still be filling): cd_isin (the most common ISIN), issuer_code (ISIN characters 3-6, never a CNPJ), n_fundos (distinct holding funds) and preco_marcacao_fundos (sum of the funds' market value over the sum of their quantity, 6 places: their own mark, not a trade price); a code held that month as something else is no match and the reason names what it was held as; else one row with match_kind NULL and the reason. Nothing is inferred from a code's letters. At most 200 codes per call. api.portfolio_fund_terms (v62) returns one row per input CNPJ: gestor_id (a CNPJ or a CPF, never padded), gestor_name, admin_cnpj and admin_name as filed in cvm_fund_registry, one registry row per CNPJ picked by is_active, then no dt_cancel, then the newest dt_cancel, then the newest fetched_at, then entity_type (the reason names it); and the redemption terms qt_dia_conversao_cota, qt_dia_pagto_resgate, tp_dia_pagto_resgate and qt_dia_resgate_cotas (lock-up) from the CVM Extrato (terms_source extrato, terms_dt_comptc its filed version's date), or, only when the CNPJ has no Extrato, from the lamina (terms_source lamina; its conversion and lock-up columns mapped by name to the same meanings, the row with no subclass else the newest). Values are as filed, NULL is not filed and never zero; a FII, FIDC, FIP or FIAGRO is in neither document and the reason says so, in Portuguese like every reason of both functions. At most 200 CNPJs per call. All six refuse above one 1000-row page (22023), never trim.",
    "DI FUTURES AND B3'S REFERENCE CURVES ARE SERVED AS B3 PUBLISHES THEM, AND THE LONG END OF EVERY CURVE IS B3'S EXTRAPOLATION. api.future_curve lists every outright DI1 contract on one session (B3 Price Report, from 2018-01-02) and api.future_series follows one contract; DI1 is QUOTED IN RATE, so settlement_rate and the open/low/high/avg/close columns are % a.a. on 252 business days (the low rate is the high price) and settlement_price is the PU. contract_month, read from the ticker with B3's month letters (F = January … Z = December), is the one derived column; nothing is rolled or spliced into a continuous series. api.curve serves one reference curve on one session, every vertex (TaxaSwap, from 2008-01-02): PRE is DI x pré, DPL the clean IPCA coupon (a real rate; B3's implied inflation is (1 + PRE) / (1 + DPL) − 1 at the same tenor), both compounded on 252 business days, and DOC the clean onshore dollar coupon, LINEAR on 360 calendar days — read rate_basis before comparing two curves. Past the last maturity of the contract anchoring a curve (DI1, DDI, DAP) B3 EXTENDS the last forward rate (Manual de Curvas v21), so the long vertices are extrapolation, not prices. api.curve_history serves one of B3's FIXED vertices through time by its nominal tenor (p_tenor_days: 30, 90, 360, 720 …); any other tenor raises 22023 with the list, because interpolating is analysis for the notebook.",
    "THE B3 LENDING AND FLOW GROUP IS A RATCHET, AND IT IS THE ONLY PART OF THIS WAREHOUSE THAT IS. short_interest, short_interest_by_sector, lending_trades, lending_participants and investor_flow read B3 tables that B3 keeps for about 21 BUSINESS DAYS and publishes no archive for. History therefore starts at SILO's first capture and cannot be extended backwards at any price — a missed session is gone, not late, and no backfill exists to ask for. coverage() reports the real span per endpoint; read it before describing any of these series as short, broken or anomalous, and never infer a level change from a window that simply begins where capture began. An over-wide request to the source returns HTTP 200 with a silently clamped window, which is why the ingest reconciles what it asked for against what it received.",
    "pct_float IS TWO DIFFERENT METRICS AND float_basis SAYS WHICH ONE YOU HAVE. api.short_interest divides the balance on loan by whichever denominator exists for that ticker. float_basis = 'index_free_float' means B3's published free float (theoretical_qty from the broadest index portfolio carrying the ticker) and exists for index constituents only, ~149 tickers; float_basis = 'shares_outstanding' means capital social from the cash instrument registry, a LARGER denominator that yields a SMALLER percentage for the same position. They are not the same measure and are never comparable: ANY ranking, screen or cross-section on pct_float must filter to ONE basis first, or it sorts index members against non-members on an axis they do not share. float_denominator carries the number actually used. pct_float and days_to_cover are NULL — never 0 — when their denominator is missing or the name did not trade; 0 would sort an unknown to exactly the wrong end.",
    "IN THE LENDING TAPE, doador AND tomador ARE BROKERAGES, NOT BENEFICIAL OWNERS. lending_participants' broker_code / broker_name and lending_trades' lender_brokers / borrower_brokers identify the B3 PARTICIPANT intermediating a trade, never who ends up long or short. B3 names ~33 participants in a whole session, and about three quarters of trades carry the SAME code on both legs (measured 2026-09-10: 32,197 of 43,165, 74.6%) — a broker crossing its own client book. So a large borrow through a broker is its clients' position, not the broker's view, and 'the biggest short' read off this tape is a statement about order flow routing. internal_legs / internal_qty (lending_participants) and internal_trades (lending_trades) are what tell the two apart: high internal share is client churn, low internal share is flow that actually crossed the market. They are published beside the totals rather than netted away, because dropping them makes the remainder look like conviction and keeping them silently makes churn look like demand.",
    "investor_flow IS A FIRST DIFFERENCE, NOT A PUBLISHED DAILY SERIES. B3 publishes investor participation as a MONTH-TO-DATE CUMULATIVE snapshot with a T+2 lag; the daily figures are consecutive snapshots subtracted WITHIN one month, and the difference never reaches across a month boundary (that would report a whole month as one day's flow). flow_basis says which kind of row you have: 'delta' is a real one-session difference, 'month_open' is the month's first session where MTD equals the day, and 'unknown_opening_snapshot' is a row whose predecessor SILO does not hold — those carry NULL flows ON PURPOSE and must never be read, filled or summed as zeros. mtd_buy_value_thousands / mtd_sell_value_thousands carry the cumulative figures as published, so the difference can be checked against the source rather than trusted. Values are R$ thousands. Sum a month only over rows whose flow_basis you have inspected.",
    "LISTED-COMPANY FINANCIALS ARE FILED, NOT DERIVED. api.financials returns one row per account line exactly as the company filed it; nothing is summed, annualised or restated. Read period_months before comparing two rows: an ITR publishes the SAME account twice under one reference date, once for the three months and once year-to-date, and they are distinguished only by the period span. Adding a 3-month row to a 6-month row double-counts the quarter.",
    "THE LATEST-VERSION FUNDAMENTALS ARE NOT POINT-IN-TIME UNLESS p_as_of IS GIVEN. financials, company_financials, income_statements, balance_sheets and cash_flow_statements take a trailing p_as_of DATE (default NULL). NULL reads the latest stored version of every document, so a later filing or a restatement appears as if it had been known on an earlier date: fine for a current screen, look-ahead in a backtest. A date T reads only the documents CVM had received before T (cia_filing.dt_receb < T; a document received ON T is excluded), keeps the highest remaining version of each and all its lines, and drops a document with no filing header. ref_date still says which period a row is FOR; the window p_from/p_to is on that, not on the receipt date. CVM's files carry only the newest version of each document and most versions superseded before 2026 are not held, so an as-of read is stale for a company that restated, never early. financial_statement_history already exposes every stored version with its filing_received_date.",
    "FINANCIALS DEFAULT TO CONSOLIDATED (scope=con) AND TO THE PERIOD THE DOCUMENT IS FOR (ordem_exerc ULTIMO). The prior-year comparative printed beside it is never returned. When a company re-files, only the newest version of each statement is served and `version` carries it; in company_financials a balance sheet from a different version than the income statement reads NULL rather than being paired across filings.",
    "CVM'S CHART OF ACCOUNTS IS SECTOR-SPECIFIC, SO `setor` IS A PARTITION KEY, NOT A LABEL. financials and company_financials carry setor and segmento on every row for exactly one reason: the same account code is a different quantity in a different chart. Measured live, 3.01 is `Receita de Venda de Bens e/ou Serviços` for PETR4 and `Receitas de Intermediação Financeira` for Banco do Brasil (cd_cvm 1023), and 3.05 is EBIT for the first and pre-tax profit for the second. So company_financials.revenue and gross_profit are NOT like-for-like across sectors: PARTITION every median, rank, percentile and peer comparison BY setor, and read the as-filed Portuguese account_name rather than assuming a code carries one concept. There is deliberately no canonical English line-item mapping, because keying one on account_code would mislabel at least one sector.",
    "company_financials.net_income IS KEYED ON THE FILED LABEL (since v36), exactly as in api.income_statements, so the two surfaces agree. It matches `Lucro/Prejuízo Consolidado do Período` / `Lucro ou Prejuízo Líquido Consolidado do Período`, which sits on 3.11 for the industrial and bank-A charts, on 3.09 for bank B (which files no 3.11) and on 3.13 for insurers (whose 3.11 is continuing operations). Until v35 it read 3.11 alone, so 282 bank-B statements (Itaú and BTG among them) read NULL and insurers got their continuing-operations line. No code is ever substituted: 3.09 is pre-participations profit on the other charts. revenue and gross_profit remain code-keyed (3.01 / 3.03) and are not like-for-like across sectors — use api.income_statements for label-keyed revenue. Every value in both functions is in absolute reais: the filed ESCALA_MOEDA is applied at ingest, so never scale by thousands again.",
    "api.income_statements IS KEYED ON THE FILED LABEL, NOT THE ACCOUNT CODE. It returns the income statement as one row per filed period with named fields, and it resolves each field by matching the as-filed Portuguese account_name (case-folded, nothing else folded) rather than by cd_conta. This is measured: CVM ships FOUR DRE charts of accounts and net income sits on 3.11 for the industrial and bank-A charts, on 3.09 for the bank-B chart which files no 3.11, and on 3.13 for the insurer chart whose 3.11 is the continuing-operations line. `chart` tells you which layout a filing used. A concept a chart does not file reads NULL rather than borrowing a neighbouring line: operating_income (EBIT) is an industrial line only, and insurers get NULL operating_expenses because their filed line is the narrower `Despesas Administrativas`. Never read a NULL here as zero. net_income_controlling is the figure per-share numbers are built on, not net_income.",
    "api.balance_sheets AND api.cash_flow_statements FOLLOW THE SAME LABEL-KEYED DESIGN. balance_sheets returns one row per filed period with named fields matched on the as-filed account_name (case-folded only); where a filing files one label twice (industrial `Empréstimos e Financiamentos` under both current and non-current liabilities) the PARENT's label disambiguates, and no code is ever consulted. Equity sits on 2.03, 2.07 or 2.08 depending on the chart; `chart` says which. Banks file no current/non-current split and no debt line, so current_assets, current_liabilities, noncurrent_*, short_term_debt and long_term_debt read NULL for them — never zero, and never a deposits line standing in for debt. cash_flow_statements maps ONLY the section totals and the cash reconciliation (operating / investing / financing, fx_effect, net_change_in_cash, cash_start, cash_end), which are uniform across charts; `method` is direct or indirect. There is no capex or dividends field on purpose: those lines are free text per filer (capex alone has 20+ spellings), so read those lines with api.financials, where the filed label is on the row. operating_cash_generated and working_capital_changes are indirect-method lines and read NULL on a direct-method filing.",
    "A TICKER RESOLVES TO A COMPANY ONLY THROUGH CVM'S PUBLISHED FCA MAP, active listings only — the CNPJ and the trading code arrive on the same filed row. financials('PETR4'), financials('33000167000101') and financials('9512') are the same company. A delisted code resolves to nothing rather than to a guess, and no company↔ticker edge is ever inferred from a name.",
    "PANEL GRAIN IS (id, asset_class, date, metric), NOT (id, date, metric). A CNPJ can file under two fund families in one month (385 do, fi + fidc), and the panel returns one row per family for it — pivoting on (id, date, metric) then either raises on the duplicate or silently averages two vehicles. Pass p_entity_type (fi|fidc|fii|fip|fiagro) to keep one family, or keep asset_class in your pivot key.",
    "Never invent a price, NAV, or identifier match.",
    "Missing observations stay null; do not ffill or interpolate.",
    "freq=day is quotes only. Mix equity with fund fundamentals on freq=month.",
    "close_return across a missing month is null, not a multi-month return.",
    "close_return is adjusted for splits, groupings and bonus shares: across one (DESDOBRAMENTO, GRUPAMENTO, BONIFICACAO in B3's corporate-event history; monthly: anywhere between the two month-end prints) the previous close is divided by the event's share ratio, B3's rule (1 + factor/100 for DESDOBRAMENTO and BONIFICACAO, factor for GRUPAMENTO, events multiplied), before the return is taken, so a 1:4 split from 100.00 to a 26.00 close is +4% and BBAS3's 2:1 split (56.46 to 27.91) is -1.13%, not -50.57%. An event with an unreadable factor, or one label on one date published with two factors, makes that return NULL (no row), never a guess. It is a price return, not a total return: dividends and JCP still move it. The adjustment reads the share-count events stored for the ISIN from B3's published history; an event the nightly corporate-event sweep has not stored yet (an issuer without a sweep proof) is not seen and still reads as a return.",
    "close is the price as published, which for a paper quoted per lot refers to 1000 shares; close_unit divides it by the published quotation_factor so levels are comparable. Neither is corporate-action adjusted, and `adjusted` is FALSE on every view row because it describes close. The adjusted price is close_adj (quote_history's default field, the panel's default metric for shares and units; see the next constraint).",
    "close_adj IS CONTINUOUS ACROSS SPLITS, GROUPINGS AND BONUS SHARES ONLY, AND IT IS ANCHORED TO THE INSTRUMENT'S LATEST SESSION. It is the close per single share divided by the share ratio of every later event, by B3's rule: 1 + factor/100 for DESDOBRAMENTO and BONIFICACAO, factor for GRUPAMENTO, distinct events on one date multiplied. Past levels change when a new event lands and returns do not, so never read a past level as the price seen that day, and never combine pages with different data_revision values. Dividends, JCP and subscription rights are not adjusted in this version (they move value to holders and change no share count; total return is separate). A window close_adj cannot cover is REFUSED (22023, DETAIL reason=adjustment_unavailable; cause=...) naming ticker, period and cause, never served as the raw close: outside shares (ISIN code ACN) and units (CDA/UNT, ticker ending 11); issuer events not proven swept, or the proof older than the last session; a stretch on or before a stock event this version does not adjust (spin-off CIS RED CAP, INCORPORACAO, REST CAP ACOES, RESG TOTAL RV, any new stock label), an unreadable factor, or one label on one date published with two factors. The absence of events is never taken as proof: the sweep proof is. Select close explicitly for the raw close.",
    "quote_history IS KEYED ON THE ISIN AND REFUSES WHAT IT CANNOT SERVE WHOLE. The series follows the instrument across BDI boards (p_board restricts it). 22023 with DETAIL reason=: unknown_ticker (never printed on the cash tape); outside_coverage (no session in the window, or the window starts before the instrument's first session; the tape starts 2019-01-02, see coverage()); isin_change (the ticker printed under two ISINs in the window that its lineage does not splice; a reused receipt code is a new instrument and is never joined); ambiguous_session (two rows on one session; pass p_board); invalid_field; adjustment_unavailable. Inside the coverage a missing session is a session with no trade (COTAHIST lists only papers that traded; prior_no_trade_sessions counts them), holidays are not sessions, and a field with no value is a JSON null. A ticker whose company changed its trading code or ISIN runs through its older instrument (ticker lineage, #381): an older (ticker, ISIN) is spliced in front only when it is the same company (the same ticker, or one CNPJ in CVM's FCA map), the same share class (ISIN characters 7-11), its last cash session is the one right before the newer first session with no overlap, no stock event goes ex at the seam, and exactly one candidate qualifies; every row keeps its own ticker and ISIN, close_adj divides older rows by the later instruments' share ratios too, and close_total_return is NULL before a seam (VIIA3 BRVIIAACNOR7 to BHIA3 BRBHIAACNOR1 on 2023-09-20).",
    "close_total_return (SELECT IT IN p_fields) IS close_adj with cash distributions reinvested at the ex-date close, also anchored to the latest session: the level is divided by the product of (1 + cash / ex-session close) over every distribution that went ex after the session, so the latest session equals close_adj and earlier levels are lower by the cash paid since. Cash is B3's full history (DIVIDENDO, JRS CAP PROPRIO gross of withholding tax, RENDIMENTO, REST CAP DIN), counted only where its ISIN is proven against the tape. It is NULL, with close_total_return_null_reason saying why, where close_adj cannot be served for that session; where the ISIN has no resolved distribution in B3's history (a non-payer, or one B3's history does not match: the two look the same, so neither gets a price return labelled as a total return); where a later distribution of the issuer's share class has no proven ISIN; where a distribution B3's supplement lists is missing from the history; and where a later distribution has no ex-date close within 7 days. A NULL is never the price return in disguise.",
    "Daily close_return is null when the previous session is more than 7 calendar days back (halts, listing gaps), and null across a quotation-factor change — a fatcot flip rescales the quote with no market move behind it. Across a split, grouping or bonus between the two prints both grains adjust the previous close by the event's share ratio (#396).",
    "Default windows are honest: with no explicit `to`, fund metrics end at each family's latest COMPLETE period (coverage() reports it as complete_through) — a partially-filed trailing month is not served. An explicit `to` serves the window verbatim, partial months included.",
    "Company↔ticker IS joined — via CVM's published FCA valores-mobiliários map only (lookup returns a tickers array on company rows). Nothing is matched by name; a company with no active published listing has tickers null.",
    "Analysis (corr, OLS, copulas, event studies) is a reduction of a panel. Fetch the panel first.",
    "CIA, FII AND FOCUS HELD DATA. api.financial_statement_history returns raw CIA account lines across all stored filing versions for one required statement and company id; `financials` remains latest-version only. Filing header metadata is present only on an exact key match. Values are already scaled at ingest and remain in filed currency. api.fii_property_history filters one exact fund CNPJ and reference-date window; CVM publishes no stable property id, so row_hash identifies a source row, not a durable asset. Nullable measurements remain NULL. api.focus_expectations returns the weekly path across BCB survey dates for one exact endpoint and required forecast horizon, with an optional indicator. The stored key retains each date/horizon; `baseCalculo=0` is the trailing 30-day respondent sample and 12-month inflation is unsmoothed. It is not a vintage archive of corrected old reports, and migration 16-era missing horizons may await re-fetch. All three endpoints refuse above 1,000 rows.",
    "DEBENTURE MARKET OBSERVATIONS: api.credit_market_history preserves instrument code, trade date, settlement date and trade classification, with nine nullable metrics, units, capture/raw/row hashes and actual observation/audit timestamps. Select complete successfully audited captures per trade date BEFORE filtering a code; a removed row stays removed. p_as_of filters both observation and audit completion, not original publication-time PIT. Group min/avg/max prices, quantity/count/volume differ from repeated instrument-wide last/reference prices; reference may be modeled and never substitutes for a trade. No summed repeated prices, inferred issuer CNPJ/stock ticker, yield, spread, outstanding or coupon-adjusted return. Known empty windows stay empty; unknown code at cutoff raises 22023. Narrow the dates above 1000 groups; no date-only paging. Coverage reports a held span, not gap-free trading history.",
    "Row caps — getting this wrong means silently analysing a TRUNCATED series, the exact fabrication this API exists to prevent. THE PAGE IS 1000 ROWS, imposed by PostgREST (db-max-rows) on every response. EVERY set-returning function now REFUSES rather than trims: a window that would produce more than 1000 rows raises SQLSTATE 22023 naming the function, so a short result can no longer look complete. The error says WHY (the response is one 1000-row page and SILO never returns a silently truncated result) and HOW to fix it for that function, in the message and again as PostgREST's `details` / `hint`. That is all fifty-eight — panel, quote_history, fund_nav, option_history, termo_history, financials, financial_statement_history, company_financials, income_statements, balance_sheets, cash_flow_statements, anbima_classes, inflation, inflation_items, fii_property_history, focus_expectations, fidc_cedentes, fidc_sacados, fidc_portfolio, fidc_tranches, fidc_aging, fund_holdings, fund_debentures, fund_documents, fund_restatements, fund_restatement_diff, company_events, macro_series, ptax, future_curve, future_series, curve, curve_history, research_universe, index_history, trade_consolidated_history, portfolio_resolve, portfolio_fees, portfolio_lookthrough, portfolio_movement, portfolio_instruments, portfolio_fund_terms, portfolio_fee_peers, class_return_distribution, portfolio_equivalents, portfolio_credit_returns, portfolio_debenture_returns, credit_market_history and the ten screen_* functions (`limits.page.all`). FIVE OF THEM PAGE with p_after: panel, quote_history, fund_nav, index_history and trade_consolidated_history. Send p_after='' for the first page, then the key from the last row — for the panel 'date|id|metric|asset_class', for quote_history, fund_nav, index_history and trade_consolidated_history just that row's date as 'YYYY-MM-DD'; every page is exactly 1000 rows until the last, which is shorter. fund_nav ALSO REQUIRES p_entity_type when paging, because its cursor is a bare period and one CNPJ can file under two families in the same month. The rest do not page: narrow p_from/p_to instead (inflation and inflation_items default to the last 36 months for that reason), for fidc_cedentes / fidc_sacados / fidc_portfolio narrow the months (a p_cedente lookup spans many funds), for fund_holdings / fund_debentures narrow the months (a p_ticker or p_issuer lookup spans many funds), pin one p_kind on fidc_portfolio, or ask for the newest N rows with an explicit p_limit (1..1000 — until v34 the FIDC three, and until v41 fund_holdings and fund_debentures, trimmed SILENTLY at 500 anonymous / 5,000 signed in; they no longer do), or for a screen raise its thresholds or pin its output filter (p_dormancy / p_min_nav, p_driver, p_family, p_modalidade). The old sentinels (5001 on the series functions, 100001 on the panel) are GONE and were never observable anyway — PostgREST cut the response at 1000 first (measured 2026-08-28: quote_history from 2019 returned exactly 1000 rows, 200, OLDEST rows kept). On GET views the Content-Range RESPONSE HEADER is still the signal: `0-999/*` means cut; send `Prefer: count=exact` to read the true total. The RPC functions no longer need it — they raise instead. RANGE PAGING DOES NOT WORK ON RPC (a Range header on /rest/v1/rpc/panel returns the same first page again); p_after is the RPC cursor, Range/limit/offset are the view cursor. The local /v1 Flask adapter pages the SQL itself and answers 400 above its own total; do not carry its rules over.",
    "An unrecognised metric name is IGNORED, not rejected: the panel comes back smaller and perfectly plausible. Take metric names from this catalog's `metrics` map, never from memory.",
    "Option chains require a codneg prefix of at least 3 characters (api.option_chain); an unfiltered whole-market chain is refused.",
    "CALLER TIERS. Anonymous access is free but deliberately small: panel accepts at most 3 ids per call, search_funds returns at most 25 rows, and option_chain pages at most 200. Signing in (GitHub) raises those to 50 ids, 200 rows and 2000 respectively, and the query timeout from 3s to 8s, and unlocks panel universe mode (p_ids empty + p_entity_type: a whole family, paged with p_after). Exceeding the id ceiling raises SQLSTATE 22023 naming the limit — the panel is never silently truncated to fit.",
    "Signing in does NOT raise rows-per-response: the 1000-row cap is a server-wide PostgREST setting applied identically to every caller. Page views, and narrow the window on functions, whatever tier you are.",
    "Option rows carry underlying_ticker resolved from the PUBLISHED ISIN mapping (an option row's ISIN is its underlying's ISIN), never from the codneg root; it is null when the underlying had no cash print that session. Termo rows still carry no underlying column.",
    "tpmerc 012/013 are option exercise EVENTS served by option_exercises, and 017 auction prints by auctions — neither is a quote series; do not compute returns over them.",
    "fund_quotas rows carry fund_type (etf | fii | fidc | fiagro) from B3's published CODBDI board code, null when the board has no family signal (odd lot). equities rows carry share_class (ON/PN/PNA/PNB/PNC/PND) and governance_segment (NM/N1/N2/MA/M2/MB) parsed from published ESPECI, never from the ticker suffix.",
    "Each cash instrument type has its own endpoint (equities, bdrs, units, fund_quotas, cash_securities) — the same rows as quotes, split by the type derived from published TPMERC/ESPECI. Their grain adds `lot` (standard = tpmerc 010, odd = 020, block = 021); filter lot=eq.standard for round lots. quotes itself stays standard-lot only.",
    "Price series stay unified: a codneg has exactly one instrument type, so quote_history works for any cash ticker without knowing its type first."
  ],
  "limits": {
    "rows_per_response": {
      "value": 1000,
      "scope": "every response, every tier — PostgREST db-max-rows, a server-wide setting; signing in does not change it",
      "kept": "the OLDEST rows; a cut-short series looks like one that simply ends",
      "detect": "the Content-Range response header: `0-999/*` is a truncated page; send `Prefer: count=exact` and it reads `0-999/<total>`",
      "paging": {
        "views": "limit/offset (and Range) page normally on GET /rest/v1/<view>",
        "rpc": "does not page: a Range on /rest/v1/rpc/<function> returns the first page again — narrow p_from/p_to, ids or metrics instead"
      }
    },
    "page": {
      "size": 1000,
      "all": [
        "panel",
        "quote_history",
        "fund_nav",
        "option_history",
        "termo_history",
        "financials",
        "company_financials",
        "income_statements",
        "balance_sheets",
        "cash_flow_statements",
        "anbima_classes",
        "inflation",
        "inflation_items",
        "financial_statement_history",
        "fii_property_history",
        "focus_expectations",
        "fidc_cedentes",
        "fidc_sacados",
        "fidc_portfolio",
        "fidc_tranches",
        "fidc_aging",
        "fund_holdings",
        "fund_debentures",
        "fund_documents",
        "fund_restatements",
        "fund_restatement_diff",
        "screen_zombie_growth",
        "screen_captive_vehicles",
        "screen_evergreen_aging",
        "screen_overdue_securit",
        "screen_dormant_funds",
        "screen_dormant_trend",
        "screen_delinquency_drivers",
        "screen_restatements",
        "screen_late_filers",
        "screen_silent_filers",
        "company_events",
        "macro_series",
        "ptax",
        "future_curve",
        "future_series",
        "curve",
        "curve_history",
        "research_universe",
        "index_history",
        "trade_consolidated_history",
        "portfolio_resolve",
        "portfolio_fees",
        "portfolio_lookthrough",
        "portfolio_movement",
        "portfolio_instruments",
        "portfolio_fund_terms",
        "portfolio_fee_peers",
        "class_return_distribution",
        "portfolio_equivalents",
        "portfolio_credit_returns",
        "portfolio_debenture_returns",
        "credit_market_history"
      ],
      "cursor_protocol": "p_after: null = whole result (refused above 1000 rows); '' = first page; the function's key copied from the last row = the next page; a page shorter than 1000 is the last",
      "functions": {
        "paged": {
          "panel": "'<date>|<id>|<metric>|<asset_class>' copied from the last row; order is date, id, metric, asset_class",
          "quote_history": "the last row's trade_date as 'YYYY-MM-DD'; order is trade_date. Keep the same p_fields on every page, and restart when data_revision changes between pages",
          "index_history": "the last row's trade_date as 'YYYY-MM-DD'; order is trade_date",
          "trade_consolidated_history": "the last row's trade_date as 'YYYY-MM-DD'; order is trade_date",
          "fund_nav": "the last row's period as 'YYYY-MM-DD'; order is period, entity_type. PAGING REQUIRES p_entity_type — the cursor is a bare period, which is unique only within one family, and 385 CNPJs file under two (fi + fidc) in the same month. Without it you get 22023, not a wrong answer. Whole-result mode needs no p_entity_type and labels every row with its family"
        },
        "raise_only": [
          "option_history",
          "termo_history",
          "financials",
          "company_financials",
          "income_statements",
          "balance_sheets",
          "cash_flow_statements",
          "anbima_classes",
          "inflation",
          "inflation_items",
          "financial_statement_history",
          "fii_property_history",
          "focus_expectations",
          "fidc_cedentes",
          "fidc_sacados",
          "fidc_portfolio",
          "fidc_tranches",
          "fidc_aging",
          "fund_holdings",
          "fund_debentures",
          "fund_documents",
          "fund_restatements",
          "fund_restatement_diff",
          "screen_zombie_growth",
          "screen_captive_vehicles",
          "screen_evergreen_aging",
          "screen_overdue_securit",
          "screen_dormant_funds",
          "screen_dormant_trend",
          "screen_delinquency_drivers",
          "screen_restatements",
          "screen_late_filers",
          "screen_silent_filers",
          "company_events",
          "macro_series",
          "ptax",
          "future_curve",
          "future_series",
          "curve",
          "curve_history",
          "research_universe",
          "portfolio_resolve",
          "portfolio_fees",
          "portfolio_lookthrough",
          "portfolio_movement",
          "portfolio_instruments",
          "portfolio_fund_terms",
          "portfolio_fee_peers",
          "class_return_distribution",
          "portfolio_equivalents",
          "portfolio_credit_returns",
          "portfolio_debenture_returns",
          "credit_market_history"
        ]
      },
      "over_cap": "SQLSTATE 22023 naming the function — nothing is trimmed to fit. The message says WHY (one 1000-row page; SILO never returns a silently truncated result) and HOW for that function (page with p_after, narrow p_from/p_to, take an explicit p_limit head, raise a screen's thresholds); PostgREST also returns the two halves as `details` and `hint`",
      "no_sentinel": "there is no cap+1 row to count any more. The old 5001 (series) and 100001 (panel) sentinels were unobservable on the hosted API, because PostgREST cuts every response at 1000 rows long before either is reached; they are gone, and the 22023 replaces them"
    },
    "tiers": {
      "anon": {
        "panel_ids": 3,
        "panel_universe": false,
        "search_funds_rows": 25,
        "option_chain_rows": 200,
        "option_exercises_rows": 500,
        "statement_timeout_seconds": 3
      },
      "authenticated": {
        "panel_ids": 50,
        "panel_universe": true,
        "search_funds_rows": 200,
        "option_chain_rows": 2000,
        "option_exercises_rows": 5000,
        "statement_timeout_seconds": 8
      },
      "exceeding_an_id_ceiling": "SQLSTATE 22023 naming the limit — a panel is never silently trimmed to fit",
      "how_to_sign_in": "GitHub at https://silo-bz-deloslabs.vercel.app/signin.html; send the JWT as `Authorization: Bearer <jwt>` beside `apikey` (the SDK takes it as token= or SILO_TOKEN)"
    }
  },
  "applicability": {
    "fund_nav": {
      "rule": "every family returns the same eleven columns; a null OUTSIDE the family's list below is set by construction (not applicable), a null INSIDE it is a blank in that month's filing",
      "columns_by_family": {
        "fi": [
          "nav",
          "quota",
          "quotaholders",
          "inflows",
          "redemptions"
        ],
        "fidc": [
          "nav",
          "delinquency"
        ],
        "fiagro": [
          "nav",
          "delinquency"
        ],
        "fii": [
          "nav",
          "quotaholders",
          "monthly_yield",
          "assets"
        ],
        "fip": [
          "nav"
        ]
      },
      "period_convention": {
        "fi": "first day of the month",
        "fidc": "last day of the month",
        "fiagro": "first day of the month",
        "fii": "first day of the month",
        "fip": "31-Dec of the filing year (annual)"
      },
      "panel_metric_names": {
        "monthly_yield": "yield"
      }
    },
    "fidc_concentration": {
      "rule": "receivables, sacado_top1 and sacado_top25 exist for fidc only; a fund of any other family simply has no rows for them",
      "columns_by_family": {
        "fidc": [
          "receivables",
          "sacado_top1",
          "sacado_top25"
        ]
      },
      "starts": {
        "receivables": "2013-01 (tab II)",
        "sacado_top1": "2013-01 (tab VIII)",
        "sacado_top25": "2013-01 (tab VIII)"
      }
    }
  },
  "regime_breaks": [
    {
      "dataset": "funds_fidc",
      "column": "delinquency",
      "boundary": "2020-11-30",
      "before": "through 2020-10-31 delinquency comes from CVM's HIST tab VI, which has no row for some funds in some months: such a fund, or a blank cell, is null (about 70% to 93% of fidc rows carry a value) — not zero, not clean books, not a missing month",
      "after": "from 2020-11-30 tab VI is filed for every fund and delinquency is on every row (a fund with no delinquent receivables files 0). It is the same filed field from 2013-01 to date: TAB_VI_B_VL_DIRCRED_INAD, from the HIST archive through 2024-12 and the monthly informe from 2025-01",
      "never": "read a pre-2020-11 null as zero or fill it, or compare a count of reporting funds across 2020-10 → 2020-11; the filed values on both sides are the same measure"
    }
  ],
  "screens": {
    "zombie_growth": {
      "function": "screen_zombie_growth",
      "family": "fidc",
      "source": "cvm_fidc_aging (tab VI total) and cvm_fidc_mensal, one aging month",
      "grain": "one row per FIDC in the chosen aging month",
      "params": {
        "p_period": null,
        "p_min_delinq_pct": 5,
        "p_min_aum": 1000000
      },
      "bounds": {
        "p_period": "an aging month-end; null = the latest aging period",
        "p_min_delinq_pct": "0..100, percent of NAV",
        "p_min_aum": ">= 0, BRL"
      },
      "dashboard": "/suspicious",
      "meaning": "Delinquent receivables above p_min_delinq_pct of NAV while NAV stays above p_min_aum: credit going bad inside a fund that still carries meaningful money. The same pattern comes from a distressed-credit mandate, a fund in orderly wind-down, or one late payer in a small book. delinquency_pct is delinquency / NAV, and can exceed 100."
    },
    "captive_vehicles": {
      "function": "screen_captive_vehicles",
      "family": "fii",
      "source": "cvm_fii_mensal (complemento), trailing window from today",
      "grain": "one row per FII",
      "params": {
        "p_lookback_months": 3,
        "p_max_investors": 10,
        "p_min_aum": 50000000
      },
      "bounds": {
        "p_lookback_months": "1..36",
        "p_max_investors": "1..1000; flagged when the window minimum is below it",
        "p_min_aum": ">= 0, BRL, against the window maximum NAV"
      },
      "dashboard": "/suspicious",
      "meaning": "An FII whose NAV peaked above p_min_aum while its quotaholder count never reached p_max_investors in the window: a large vehicle held by a handful of investors. Exclusive and family-office FIIs are legal and look exactly like this."
    },
    "evergreen_aging": {
      "function": "screen_evergreen_aging",
      "family": "fidc",
      "source": "cvm_fidc_aging, trailing window from today, funds with > R$100k delinquent",
      "grain": "one row per FIDC",
      "params": {
        "p_lookback_months": 12,
        "p_min_longtail_pct": 70,
        "p_max_variation_pp": 10
      },
      "bounds": {
        "p_lookback_months": "3..36",
        "p_min_longtail_pct": "0..100, share of delinquency overdue > 1080 days",
        "p_max_variation_pp": "0..100 percentage points across the window"
      },
      "dashboard": "/suspicious",
      "meaning": "Receivables overdue more than 1080 days stay a large and nearly constant share of delinquency: old credit neither written off nor recovered, the pattern of rolled rather than resolved receivables. A slow judicial recovery, or a policy of not writing off, looks the same. months_observed counts the aging months actually filed."
    },
    "overdue_securit": {
      "function": "screen_overdue_securit",
      "family": "securit",
      "source": "cvm_securit_serie, each series' newest monthly filing",
      "grain": "one row per series (instrument_type, securitizer, code, series number)",
      "params": {
        "p_min_volume": 100000
      },
      "bounds": {
        "p_min_volume": ">= 0, BRL paid in"
      },
      "dashboard": "/suspicious",
      "meaning": "A CRI/CRA/other series past its filed maturity whose newest filing still reports a non-terminal status (not Cancelado, Vencido, Liquidado or Encerrado). The FILING is stale; the screen cannot say whether the series was extended, renegotiated, not yet re-filed or is in silent default. status is served as filed. The series number is not a column, so two series under one instrument_code read as two rows with the same identity."
    },
    "dormant_funds": {
      "function": "screen_dormant_funds",
      "family": "fi",
      "source": "fact_fund_monthly (fi), anchored on latest_complete_period('fi')",
      "grain": "one row per FI class",
      "params": {
        "p_lookback_months": 3,
        "p_dormancy": null,
        "p_min_nav": null
      },
      "bounds": {
        "p_lookback_months": "2..12"
      },
      "filters": {
        "p_dormancy": "empty_shell | parked_capital; null = both (output filter)",
        "p_min_nav": "keep last_nav >= this, BRL; null = no floor (output filter)"
      },
      "dashboard": "/dormant",
      "meaning": "An FI class that filed every month of the window with zero subscriptions and zero redemptions. empty_shell: no quotaholder at all — a registered, filing vehicle holding nobody's money. parked_capital: quotaholders present, no money in or out — exclusive and closed structures look exactly like this. A month with unreported flows or quotaholders disqualifies the fund rather than counting as zero. FI only: the other families file no monthly flows. parked_capital alone exceeds one page; pin p_dormancy and walk p_min_nav bands."
    },
    "dormant_trend": {
      "function": "screen_dormant_trend",
      "family": "fi",
      "source": "fact_fund_monthly (fi), the dormant_funds screen at every month-end",
      "grain": "one row per month",
      "params": {
        "p_lookback_months": 3,
        "p_history_months": 36
      },
      "bounds": {
        "p_lookback_months": "2..12",
        "p_history_months": "1..60"
      },
      "dashboard": "/dormant",
      "meaning": "dormant_funds evaluated at every month-end: funds_filing, empty_shells and parked_capital counts, and parked_nav (NAV sitting in parked_capital classes). Counts of a screen, not of misconduct."
    },
    "delinquency_drivers": {
      "function": "screen_delinquency_drivers",
      "family": "fidc",
      "source": "fact_fund_monthly (fidc) — the series fund_nav and panel serve",
      "grain": "one row per FIDC with >= p_min_months observations in the window",
      "params": {
        "p_end": null,
        "p_months": 12,
        "p_min_months": 6,
        "p_min_delta_brl": 1000000,
        "p_min_delta_pp": 1.0,
        "p_driver": null
      },
      "bounds": {
        "p_end": "window end; null = latest_complete_period('fidc'); the window may not start before 2025-01",
        "p_months": "2..24",
        "p_min_months": "2..p_months",
        "p_min_delta_brl": ">= 0, BRL",
        "p_min_delta_pp": ">= 0, percentage points"
      },
      "filters": {
        "p_driver": "consistent_worsening | value_up_rate_masked | denominator_only | improvement | stable; null = all (output filter)"
      },
      "dashboard": "/fidc",
      "meaning": "First vs last observation of FIDC delinquency in BRL and in percentage points of NAV, the move classified by the two thresholds: consistent_worsening (value up and rate up), value_up_rate_masked (value up, rate flat or down — NAV grew with it), denominator_only (rate up, value flat or down — NAV shrank, not new delinquency), improvement (both down), stable. No sector, no debtor, no guarantee: a classification of two numbers, not a finding about the fund. stopped_reporting flags a last filing two or more months behind the window end. Every FIDC gets a row, so the unfiltered set exceeds one page; pin p_driver."
    },
    "restatements": {
      "function": "screen_restatements",
      "family": "fii, fidc, etf (FNET)",
      "source": "fnet_document + fnet_document_filter (cnpjFundo links), trailing delivery window",
      "grain": "one row per fund CNPJ (cnpjFundo link)",
      "params": {
        "p_months": 12,
        "p_end": null,
        "p_min_restatements": 3,
        "p_min_rate_pct": 20,
        "p_modalidade": null
      },
      "bounds": {
        "p_months": "1..36, trailing months of delivery days",
        "p_end": "last delivery day of the window; null = today",
        "p_min_restatements": "1..1000 re-filings (versao > 1) in the window",
        "p_min_rate_pct": "0..100, re-filings as percent of the fund's documents in the window"
      },
      "filters": {
        "p_modalidade": "RE | RC: count only voluntary or only CVM-required re-filings; null = every versao > 1"
      },
      "dashboard": null,
      "meaning": "A fund whose FNET re-filings (versao > 1) in the window number at least p_min_restatements AND are at least p_min_rate_pct of its documents. restatements_re (voluntary) and restatements_rc (required by CVM) split them as FNET publishes modalidade. The same pattern comes from routine typo corrections, an administrator or custodian migration re-submitting a whole book, the resolution-175 adaptation, a FNET template change forcing re-submission, one error cascading through consecutive informes, or a CVM supervision sweep across an administrator's funds; an RC says CVM asked, not what was wrong. Fund identity is the cnpjFundo link only; unlinked documents and history before SILO's first crawl are not counted."
    },
    "late_filers": {
      "function": "screen_late_filers",
      "family": "fii, fidc (FNET)",
      "source": "fnet_document 'Informe Mensal Estruturado', versao 1, first delivery per (cnpjFundo link, reference month)",
      "grain": "one row per fund CNPJ with at least p_min_late late months",
      "params": {
        "p_months": 12,
        "p_end": null,
        "p_min_days_late": 5,
        "p_min_late": 2,
        "p_family": null
      },
      "bounds": {
        "p_months": "1..36 reference months ending at p_end",
        "p_end": "any day in the last reference month; null = the newest month whose deadline has passed; a window ending before 2024-12 raises 22023",
        "p_min_days_late": "1..90 days past the cited deadline",
        "p_min_late": "1..p_months late months"
      },
      "filters": {
        "p_family": "fii | fidc; null = both (output filter)"
      },
      "deadline_rule": {
        "fidc": "Resolução CVM 175, Anexo Normativo II, art. 27, III — informe mensal within 15 days after the end of the reference month; measured from reference month 2024-12 (FIDC adaptation deadline 2024-11-29)",
        "fii": "Resolução CVM 175, Anexo Normativo III, art. 36, I — monthly form (Suplemento I) within 15 days after the end of the reference month; measured from reference month 2025-07 (adaptation deadline 2025-06-30)",
        "counting": "calendar days (the text says dias); no holiday calendar is applied — p_min_days_late absorbs a weekend or holiday rollover",
        "text_read": "conteudo.cvm.gov.br consolidated annexes, 2026-09-25"
      },
      "dashboard": null,
      "meaning": "A FII or FIDC whose monthly informe first reached FNET at least p_min_days_late days after the cited deadline, in at least p_min_late measured months. informes counts the months measured, informes_late the late ones, max_days_late the worst, median_lag_days the fund's median delivery lag after month end. A timestamp compared with a rule, not a finding: CVM can grant extensions, delivered_at is FNET's upload time, an administrator transfer can delay one month for a whole book, and a fund with several classes is measured on its earliest filing. A month with no informe in the register is not counted (the register is partial) — absence is silent_filers."
    },
    "silent_filers": {
      "function": "screen_silent_filers",
      "family": "fi, fidc, fii, fiagro (CVM)",
      "source": "dim_fund (last period filed in CVM's datasets) against latest_complete_period(family), cvm_fund_registry.is_active",
      "grain": "one row per (fund CNPJ, family)",
      "params": {
        "p_min_silent_months": 3,
        "p_max_silent_months": 24,
        "p_family": null
      },
      "bounds": {
        "p_min_silent_months": "1..120 complete months with no filing",
        "p_max_silent_months": "p_min_silent_months..240"
      },
      "filters": {
        "p_family": "fi | fidc | fii | fiagro; null = all four (output filter)"
      },
      "dashboard": null,
      "meaning": "A fund CVM's registry still lists as active whose last periodic informe in CVM's own dataset (informe diário for FI, the monthly informe for FIDC / FII / FIAGRO) is N complete months behind the family's latest complete period — never today, so an unpublished month is not silence. fnet_last_delivered_at (FII / FIDC) shows a fund still delivering to FNET. The same row comes from a fund merged, incorporated or liquidated whose status CVM has not updated, reporting moved to a class CNPJ other than the fund's by the resolution-175 adaptation, CVM's dataset lagging the filing, or a SILO ingest gap (check coverage() first). FIP files annually and is not screened."
    }
  },
  "examples": [
    {
      "ask": "How does PETR4 relate to delinquency in this FIDC?",
      "call": "POST /rest/v1/rpc/panel {\"p_ids\": [\"PETR4\", \"<cnpj>\"], \"p_metrics\": [\"close_return\", \"delinquency\"], \"p_freq\": \"month\"}",
      "then": "Pivot the long rows on (date, id, metric), then a pairwise-complete correlation in the notebook. Do not ffill."
    },
    {
      "ask": "Rank these funds by latest NAV",
      "call": "POST /rest/v1/rpc/panel {\"p_ids\": [\"<cnpj>\", \"<cnpj>\"], \"p_metrics\": [\"nav\"], \"p_freq\": \"month\"}",
      "then": "Take the last non-null NAV per id. Keep asset_class in the key: a CNPJ filing under two families returns one row per family."
    },
    {
      "ask": "Did inflows and quota move together for this FI?",
      "call": "POST /rest/v1/rpc/panel {\"p_ids\": [\"<cnpj>\"], \"p_metrics\": [\"inflows\", \"quota\"], \"p_freq\": \"month\"}",
      "then": "Correlate the two metrics' series; nulls stay null."
    },
    {
      "ask": "Spread of two equity closes at month end",
      "call": "POST /rest/v1/rpc/panel {\"p_ids\": [\"PETR4\", \"VALE3\"], \"p_metrics\": [\"close\"], \"p_freq\": \"month\"}",
      "then": "Subtract the aligned series; a missing month is null, not interpolated."
    },
    {
      "ask": "Which of these FIDCs is most exposed to one debtor?",
      "call": "POST /rest/v1/rpc/panel {\"p_ids\": [\"<cnpj>\", \"<cnpj>\", \"<cnpj>\"], \"p_metrics\": [\"sacado_top1\", \"receivables\"], \"p_freq\": \"month\"}",
      "then": "Divide sacado_top1 by receivables per row; the debtor is anonymized, so this is a ratio, not a name."
    },
    {
      "ask": "Did this FIDC's senior tranche deliver what it promised?",
      "call": "POST /rest/v1/rpc/fidc_tranches {\"p_cnpj\": \"<cnpj>\", \"p_from\": \"2025-01-01\"}",
      "then": "Compare performance_realised with performance_expected per classe_serie in the notebook; both are as filed and can carry CVM's outliers. History starts 2013-01 (CVM's HIST archive through 2024-12). Read the aging ladder under it with fidc_aging; overdue_total is CVM's filed total, not a sum."
    },
    {
      "ask": "Which FIDCs restated a filing this month, and how late?",
      "call": "POST /rest/v1/rpc/fund_restatements {\"p_tipo_fundo\": \"FIDC\", \"p_from\": \"<month start>\"}",
      "then": "Each row is a re-filed document (versao > 1; modalidade RE is voluntary, RC was required by CVM) with lag_days since the version it replaced. The pairing is by a stated group key because FNET links no versions; cnpj NULL means the fortnightly fund sweep has not linked it yet — never match it to a fund by fund_name. Open the versions with fund_documents' source_url."
    },
    {
      "ask": "What did this FIDC change when it restated its December informe?",
      "call": "POST /rest/v1/rpc/fund_restatement_diff {\"p_fnet_id\": <fund_restatements.fnet_id>}",
      "then": "One row per field that differs from previous_fnet_id, text as printed, delta on numeric leaves (delinquency, PL, quota values). Check fund_restatements' diff_status first: no rows with diff_status 'compared' means re-filed with nothing changed; any other status (or NULL) means not diffed. match_basis 'position' rows are approximate. Open both versions with source_url and previous_source_url."
    },
    {
      "ask": "Which FIDCs keep filing their monthly informe late?",
      "call": "POST /rest/v1/rpc/screen_late_filers {\"p_family\": \"fidc\"}",
      "then": "Each row is a SIGNAL: a fund whose first FNET delivery of the informe mensal came at least p_min_days_late days after the deadline in deadline_rule (Resolução CVM 175, cited on the row) in at least p_min_late of the last 12 measured months. It says nothing about extensions CVM may have granted, and a month missing from the register is not counted. Open the filings with fund_documents(cnpj) and check screen_silent_filers for funds that stopped filing altogether."
    },
    {
      "ask": "What material facts has PETR4 published this year?",
      "call": "POST /rest/v1/rpc/company_events {\"p_id\": \"PETR4\", \"p_category\": \"Fato Relevante\", \"p_from\": \"<year start>\"}",
      "then": "One row per protocol at its newest version, text as filed; open source_url for the document on CVM's RAD. Filings CVM published without a protocol number (all before 2015) are not held, so an empty early window is that limit, not a quiet company."
    },
    {
      "ask": "How did CDI and the Selic target move over the last year?",
      "call": "POST /rest/v1/rpc/macro_series {\"p_series\": \"CDI\"}  then  {\"p_series\": \"SELIC_META\"}",
      "then": "Read `unit` first: CDI is % per business day, SELIC_META % a.a. Compound or annualise in the notebook and say so. For PTAX buy and sell per currency call ptax; for IPCA call inflation."
    },
    {
      "ask": "What is the DI curve pricing, and how has the one-year point moved?",
      "call": "POST /rest/v1/rpc/future_curve {}  then  POST /rest/v1/rpc/curve_history {\"p_curve\": \"PRE\", \"p_tenor_days\": 360}",
      "then": "future_curve lists every DI1 contract of the newest session: settlement_rate is % a.a. on 252 business days and the quote columns are rates too. curve_history is B3's own fixed 360-day vertex of PRE, never an interpolation; any other tenor means reading curve and interpolating in the notebook. The long end of every curve is B3's extrapolation, not a price."
    },
    {
      "ask": "Just give me the panel; I will run a factor model",
      "call": "POST /rest/v1/rpc/panel {\"p_ids\": [\"PETR4\", \"VALE3\", \"<cnpj>\"], \"p_metrics\": [\"close_return\", \"nav\"], \"p_freq\": \"month\"}",
      "then": "Model in the notebook from the long rows. Anonymous callers are capped at 3 ids — a 4th raises 22023, it is not trimmed."
    },
    {
      "ask": "Is core inflation running above the headline?",
      "call": "POST /rest/v1/rpc/inflation {\"p_family\": \"core\"}",
      "then": "Rows are monthly changes in percent as published, one per (month, series); acc_12m is the trailing twelve chained and NULL until a series has twelve consecutive months. Put IPCA (p_series='IPCA', or family headline) beside them; never annualise a single month."
    },
    {
      "ask": "What moved the IPCA last month?",
      "call": "POST /rest/v1/rpc/inflation_items {\"p_level\": 1, \"p_from\": \"<month start>\"}",
      "then": "contribution is weight × change_month / 100 in percentage points; the nine level-1 rows sum to the headline to rounding. Drill with p_level=2..4 and p_item=<structure number> — but sum ONE level at a time, a group and its subgroups are the same money twice."
    },
    {
      "ask": "Which FIDCs match the evergreen-aging screen?",
      "call": "POST /rest/v1/rpc/screen_evergreen_aging {}",
      "then": "Each row is a SIGNAL, not a finding: it carries `screen` and `params` (the thresholds it crossed). Read `screens.evergreen_aging.meaning` for what else looks the same, then take the cnpjs to fund_nav or panel and the fund's own filings before saying anything about it."
    },
    {
      "ask": "Which names are most heavily shorted right now?",
      "call": "GET /rest/v1/short_interest?trade_date=eq.<the trade_date coverage() reports>&float_basis=eq.index_free_float&order=pct_float.desc&limit=25",
      "then": "A view, not an RPC: filter and page it with PostgREST syntax. The float_basis filter is REQUIRED for a ranking — index_free_float and shares_outstanding are different denominators and sorting them together is meaningless. Read the ratchet constraint before calling the window short."
    },
    {
      "ask": "Who was borrowing PETR4 last session, and was it real demand?",
      "call": "GET /rest/v1/lending_participants?ticker=eq.PETR4&trade_date=eq.<session>&order=quantity_borrowed.desc",
      "then": "broker_code is the INTERMEDIARY, never the owner. Compare internal_qty against quantity_lent + quantity_borrowed per broker: a high internal share is that broker crossing its own clients, not a position it took."
    },
    {
      "ask": "What did foreign investors do this month?",
      "call": "GET /rest/v1/investor_flow?investor_type=eq.<type>&reference_date=gte.<month start>&order=reference_date.asc",
      "then": "Check flow_basis on every row first. 'unknown_opening_snapshot' rows carry NULL flows by construction — drop them, never read them as zero. Values are R$ thousands, differenced from a month-to-date snapshot published T+2."
    }
  ],
  "id_types": [
    "ticker",
    "cnpj",
    "cd_cvm",
    "option",
    "termo",
    "future"
  ],
  "asset_classes": [
    "equity",
    "unit",
    "bdr",
    "fund_quota",
    "index",
    "right",
    "bonus",
    "cash_security",
    "fi",
    "fidc",
    "fii",
    "fip",
    "fiagro",
    "cia",
    "derivative"
  ],
  "freq": [
    "day",
    "month"
  ],
  "endpoints": {
    "catalog": "GET /v1/catalog",
    "tools": "GET /v1/tools",
    "panel": "GET /v1/panel",
    "lookup": "GET /v1/lookup?q=",
    "quotes": "GET /v1/quotes/{ticker}",
    "credit_market_history": "GET /v1/credit/{code}/history",
    "funds": "GET /v1/funds/{cnpj}/nav",
    "coverage": "GET /v1/coverage",
    "metric_coverage": "GET /v1/metric-coverage"
  },
  "postgrest": {
    "panel": "POST /rest/v1/rpc/panel",
    "lookup": "POST /rest/v1/rpc/lookup",
    "coverage": "POST /rest/v1/rpc/coverage",
    "metric_coverage": "POST /rest/v1/rpc/metric_coverage",
    "search_funds": "POST /rest/v1/rpc/search_funds",
    "fund_profile": "POST /rest/v1/rpc/fund_profile",
    "fund_holdings": "POST /rest/v1/rpc/fund_holdings",
    "fund_nav": "POST /rest/v1/rpc/fund_nav",
    "quote_history": "POST /rest/v1/rpc/quote_history",
    "quote_latest": "POST /rest/v1/rpc/quote_latest",
    "quotes_view": "GET /rest/v1/quotes",
    "funds_view": "GET /rest/v1/funds",
    "equities": "GET /rest/v1/equities",
    "bdrs": "GET /rest/v1/bdrs",
    "units": "GET /rest/v1/units",
    "fund_quotas": "GET /rest/v1/fund_quotas",
    "cash_securities": "GET /rest/v1/cash_securities",
    "auctions": "GET /rest/v1/auctions",
    "option_chain": "POST /rest/v1/rpc/option_chain",
    "option_history": "POST /rest/v1/rpc/option_history",
    "option_exercises": "POST /rest/v1/rpc/option_exercises",
    "termo_history": "POST /rest/v1/rpc/termo_history",
    "financials": "POST /rest/v1/rpc/financials",
    "financial_statement_history": "POST /rest/v1/rpc/financial_statement_history",
    "company_financials": "POST /rest/v1/rpc/company_financials",
    "income_statements": "POST /rest/v1/rpc/income_statements",
    "balance_sheets": "POST /rest/v1/rpc/balance_sheets",
    "cash_flow_statements": "POST /rest/v1/rpc/cash_flow_statements",
    "anbima_classes": "POST /rest/v1/rpc/anbima_classes",
    "inflation": "POST /rest/v1/rpc/inflation",
    "inflation_items": "POST /rest/v1/rpc/inflation_items",
    "fii_property_history": "POST /rest/v1/rpc/fii_property_history",
    "focus_expectations": "POST /rest/v1/rpc/focus_expectations",
    "fund_debentures": "POST /rest/v1/rpc/fund_debentures",
    "fidc_cedentes": "POST /rest/v1/rpc/fidc_cedentes",
    "fidc_sacados": "POST /rest/v1/rpc/fidc_sacados",
    "fidc_portfolio": "POST /rest/v1/rpc/fidc_portfolio",
    "screen_zombie_growth": "POST /rest/v1/rpc/screen_zombie_growth",
    "screen_captive_vehicles": "POST /rest/v1/rpc/screen_captive_vehicles",
    "screen_evergreen_aging": "POST /rest/v1/rpc/screen_evergreen_aging",
    "screen_overdue_securit": "POST /rest/v1/rpc/screen_overdue_securit",
    "screen_dormant_funds": "POST /rest/v1/rpc/screen_dormant_funds",
    "screen_dormant_trend": "POST /rest/v1/rpc/screen_dormant_trend",
    "screen_delinquency_drivers": "POST /rest/v1/rpc/screen_delinquency_drivers",
    "screen_restatements": "POST /rest/v1/rpc/screen_restatements",
    "screen_late_filers": "POST /rest/v1/rpc/screen_late_filers",
    "screen_silent_filers": "POST /rest/v1/rpc/screen_silent_filers",
    "fidc_tranches": "POST /rest/v1/rpc/fidc_tranches",
    "fidc_aging": "POST /rest/v1/rpc/fidc_aging",
    "fund_documents": "POST /rest/v1/rpc/fund_documents",
    "fund_restatements": "POST /rest/v1/rpc/fund_restatements",
    "fund_restatement_diff": "POST /rest/v1/rpc/fund_restatement_diff",
    "company_events": "POST /rest/v1/rpc/company_events",
    "macro_series": "POST /rest/v1/rpc/macro_series",
    "ptax": "POST /rest/v1/rpc/ptax",
    "future_curve": "POST /rest/v1/rpc/future_curve",
    "future_series": "POST /rest/v1/rpc/future_series",
    "curve": "POST /rest/v1/rpc/curve",
    "curve_history": "POST /rest/v1/rpc/curve_history",
    "research_universe": "POST /rest/v1/rpc/research_universe",
    "index_history": "POST /rest/v1/rpc/index_history",
    "trade_consolidated_history": "POST /rest/v1/rpc/trade_consolidated_history",
    "credit_market_history": "POST /rest/v1/rpc/credit_market_history",
    "portfolio_resolve": "POST /rest/v1/rpc/portfolio_resolve",
    "portfolio_fees": "POST /rest/v1/rpc/portfolio_fees",
    "portfolio_lookthrough": "POST /rest/v1/rpc/portfolio_lookthrough",
    "portfolio_movement": "POST /rest/v1/rpc/portfolio_movement",
    "portfolio_instruments": "POST /rest/v1/rpc/portfolio_instruments",
    "portfolio_fund_terms": "POST /rest/v1/rpc/portfolio_fund_terms",
    "portfolio_fee_peers": "POST /rest/v1/rpc/portfolio_fee_peers",
    "class_return_distribution": "POST /rest/v1/rpc/class_return_distribution",
    "portfolio_equivalents": "POST /rest/v1/rpc/portfolio_equivalents",
    "portfolio_credit_returns": "POST /rest/v1/rpc/portfolio_credit_returns",
    "portfolio_debenture_returns": "POST /rest/v1/rpc/portfolio_debenture_returns",
    "short_interest": "GET /rest/v1/short_interest",
    "short_interest_by_sector": "GET /rest/v1/short_interest_by_sector",
    "lending_trades": "GET /rest/v1/lending_trades",
    "lending_participants": "GET /rest/v1/lending_participants",
    "investor_flow": "GET /rest/v1/investor_flow"
  }
}
$json$::jsonb;
$fn$;
-- END GENERATED api.catalog()

COMMENT ON FUNCTION api.catalog() IS
    'Machine-readable metric/constraint catalog, identical to serve/ /v1/catalog (pinned by an offline test). Constant jsonb; SECURITY INVOKER because it reads nothing.';

REVOKE ALL ON FUNCTION api.catalog() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.catalog() TO anon, authenticated;


-- ---------------------------------------------------------------------------
-- silo_api — the read-only privilege bundle serve/ connects through
-- ---------------------------------------------------------------------------
-- The role is created (NOLOGIN, statement_timeout='15s',
-- default_transaction_read_only=on) in 12_grants_and_rls.sql, which applies
-- before this file. If the role is missing, these grants fail loudly under
-- ON_ERROR_STOP=1 — intentional; never wrap them in a silent conditional.
--
-- The bundle is schema api and nothing else: USAGE on the schema, SELECT on
-- the eight views, EXECUTE on the twenty-one functions. (It said "seven" and
-- "thirteen" until v27, having stopped being counted somewhere around
-- api.auctions and the FIDC concentration work; the grants below are the
-- authority, and tests/test_api_contract_sql.py pins them to
-- EXPECTED_FUNCTIONS.) The five B3 lending / flow views added to the contract
-- in v27 are deliberately NOT here: serve/app.py serves no /v1 route for
-- them, so the adapter role has no reason to hold the grant. They reach
-- callers through PostgREST's anon / authenticated grants, which
-- 20_short_interest.sql and 21_lending_participants.sql own.
-- It deliberately receives no
-- grant in schema public — the DEFINER functions and owner-privileged views
-- above are the only path from silo_api to the data. serve/-only works with
-- exactly this; exposing schema api on the Supabase Data API would be a
-- separate, owner-made decision (documented in docs/reference/API.md when taken).

GRANT USAGE ON SCHEMA api TO silo_api;

GRANT SELECT ON api.quotes, api.funds TO silo_api;
GRANT SELECT ON api.equities, api.bdrs, api.units,
                api.fund_quotas, api.cash_securities TO silo_api;
GRANT SELECT ON api.auctions TO silo_api;

GRANT EXECUTE ON FUNCTION api.quote_history(TEXT, DATE, DATE, TEXT, TEXT, TEXT[]) TO silo_api;
GRANT EXECUTE ON FUNCTION api.quote_latest(TEXT, TEXT)                TO silo_api;
GRANT EXECUTE ON FUNCTION api.option_chain(TEXT, DATE, DATE, INT)     TO silo_api;
GRANT EXECUTE ON FUNCTION api.option_history(TEXT, DATE, DATE)        TO silo_api;
GRANT EXECUTE ON FUNCTION api.termo_history(TEXT, DATE, DATE)         TO silo_api;
GRANT EXECUTE ON FUNCTION api.fund_profile(TEXT)                      TO silo_api;
GRANT EXECUTE ON FUNCTION api.fund_nav(TEXT, DATE, DATE, TEXT, TEXT)  TO silo_api;
GRANT EXECUTE ON FUNCTION api.search_funds(TEXT, TEXT, INT)           TO silo_api;
GRANT EXECUTE ON FUNCTION api.coverage()                              TO silo_api;
GRANT EXECUTE ON FUNCTION api.metric_coverage()                       TO silo_api;
GRANT EXECUTE ON FUNCTION api.panel(TEXT[], TEXT[], DATE, DATE, TEXT, TEXT, NUMERIC, INT, TEXT) TO silo_api;
GRANT EXECUTE ON FUNCTION api.lookup(TEXT)                            TO silo_api;
GRANT EXECUTE ON FUNCTION api.fund_holdings(TEXT, TEXT, DATE, DATE, TEXT, INT) TO silo_api;
GRANT EXECUTE ON FUNCTION api.financials(TEXT, TEXT, DATE, DATE, TEXT, TEXT, DATE) TO silo_api;
GRANT EXECUTE ON FUNCTION api.company_financials(TEXT, DATE, DATE, TEXT, DATE) TO silo_api;
GRANT EXECUTE ON FUNCTION api.income_statements(TEXT, DATE, DATE, TEXT, TEXT, DATE) TO silo_api;
GRANT EXECUTE ON FUNCTION api.balance_sheets(TEXT, DATE, DATE, TEXT, TEXT, DATE) TO silo_api;
GRANT EXECUTE ON FUNCTION api.cash_flow_statements(TEXT, DATE, DATE, TEXT, TEXT, DATE) TO silo_api;
GRANT EXECUTE ON FUNCTION api.anbima_classes(TEXT, TEXT, TEXT, DATE, DATE) TO silo_api;
GRANT EXECUTE ON FUNCTION api.fund_debentures(TEXT, TEXT, DATE, DATE, INT) TO silo_api;
GRANT EXECUTE ON FUNCTION api.fidc_cedentes(TEXT, TEXT, DATE, DATE, INT)   TO silo_api;
GRANT EXECUTE ON FUNCTION api.fidc_sacados(TEXT, DATE, DATE, INT)          TO silo_api;
GRANT EXECUTE ON FUNCTION api.fidc_portfolio(TEXT, TEXT, DATE, DATE, INT)  TO silo_api;
GRANT EXECUTE ON FUNCTION api.fidc_tranches(TEXT, DATE, DATE, TEXT)        TO silo_api;
GRANT EXECUTE ON FUNCTION api.fidc_aging(TEXT, DATE, DATE)                 TO silo_api;
GRANT EXECUTE ON FUNCTION api.inflation(TEXT, TEXT, DATE, DATE)            TO silo_api;
GRANT EXECUTE ON FUNCTION api.inflation_items(INT, TEXT, DATE, DATE)       TO silo_api;
GRANT EXECUTE ON FUNCTION api.catalog()                               TO silo_api;

-- Defensive, idempotent no-ops today (silo_api is never directly granted
-- anything in public): strip any direct grant a future change might add by
-- accident, so an apply restores the boundary on every run.
REVOKE ALL ON ALL TABLES    IN SCHEMA public FROM silo_api;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM silo_api;
REVOKE CREATE ON SCHEMA public FROM silo_api;

COMMIT;
