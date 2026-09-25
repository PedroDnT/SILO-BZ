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
-- Never fabricate: a ticker with no rows returns zero rows (HTTP 404 at serve/).
-- Prices are unadjusted. Default cash quote is board (codbdi) '02' (standard lot).
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
    v.preco_fechamento / NULLIF(v.fator_cotacao, 0) AS close_unit
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
    CASE v.tpmerc WHEN '010' THEN 'standard' ELSE 'odd' END AS lot,
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
    v.preco_fechamento / NULLIF(v.fator_cotacao, 0) AS close_unit
FROM public.vw_b3_instrument_typed v
WHERE v.instrument_type = 'equity'
  AND v.tpmerc IN ('010', '020', '021');

COMMENT ON VIEW api.equities IS
    'Unadjusted B3 cash quotes for equity: ordinary and preferred shares (ESPECI ON*/PN*). Grain (ticker, trade_date, board, term_days, lot) — lot is standard (tpmerc 010) or odd (020/021), so filter lot=eq.standard for round lots only. share_class (ON|PN|PNA|PNB|PNC|PND) and governance_segment (NM|N1|N2|MA|M2|MB) are parsed from published ESPECI, never from the ticker suffix. Classified from published TPMERC/ESPECI; never inferred.';

ALTER VIEW api.equities SET (security_invoker = false);
GRANT SELECT ON api.equities TO anon, authenticated;

CREATE OR REPLACE VIEW api.bdrs AS
SELECT
    v.codneg            AS ticker,
    v.trade_date,
    v.codbdi            AS board,
    CASE v.tpmerc WHEN '010' THEN 'standard' ELSE 'odd' END AS lot,
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
    v.preco_fechamento / NULLIF(v.fator_cotacao, 0) AS close_unit
FROM public.vw_b3_instrument_typed v
WHERE v.instrument_type = 'bdr'
  AND v.tpmerc IN ('010', '020', '021');

COMMENT ON VIEW api.bdrs IS
    'Unadjusted B3 cash quotes for bdr: Brazilian Depositary Receipts (ESPECI DR*). Grain (ticker, trade_date, board, term_days, lot) — lot is standard (tpmerc 010) or odd (020/021), so filter lot=eq.standard for round lots only. Classified from published TPMERC/ESPECI; never inferred.';

ALTER VIEW api.bdrs SET (security_invoker = false);
GRANT SELECT ON api.bdrs TO anon, authenticated;

CREATE OR REPLACE VIEW api.units AS
SELECT
    v.codneg            AS ticker,
    v.trade_date,
    v.codbdi            AS board,
    CASE v.tpmerc WHEN '010' THEN 'standard' ELSE 'odd' END AS lot,
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
    v.preco_fechamento / NULLIF(v.fator_cotacao, 0) AS close_unit
FROM public.vw_b3_instrument_typed v
WHERE v.instrument_type = 'unit'
  AND v.tpmerc IN ('010', '020', '021');

COMMENT ON VIEW api.units IS
    'Unadjusted B3 cash quotes for unit: units — bundled share packages (ESPECI UNT*). Grain (ticker, trade_date, board, term_days, lot) — lot is standard (tpmerc 010) or odd (020/021), so filter lot=eq.standard for round lots only. Classified from published TPMERC/ESPECI; never inferred.';

ALTER VIEW api.units SET (security_invoker = false);
GRANT SELECT ON api.units TO anon, authenticated;

CREATE OR REPLACE VIEW api.fund_quotas AS
SELECT
    v.codneg            AS ticker,
    v.trade_date,
    v.codbdi            AS board,
    CASE v.tpmerc WHEN '010' THEN 'standard' ELSE 'odd' END AS lot,
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
    v.preco_fechamento / NULLIF(v.fator_cotacao, 0) AS close_unit
FROM public.vw_b3_instrument_typed v
WHERE v.instrument_type = 'fund_quota'
  AND v.tpmerc IN ('010', '020', '021');

COMMENT ON VIEW api.fund_quotas IS
    'Unadjusted B3 cash quotes for fund_quota: listed fund quotas (CI*/FIDC* paper). fund_type splits the family from B3''s published CODBDI board code: etf | fii | fidc | fiagro, NULL when the board carries no signal (odd lot) — filter fund_type=eq.etf for ETFs only. Grain (ticker, trade_date, board, term_days, lot) — lot is standard (tpmerc 010) or odd (020/021), so filter lot=eq.standard for round lots only. Classified from published TPMERC/CODBDI/ESPECI; never inferred.';

ALTER VIEW api.fund_quotas SET (security_invoker = false);
GRANT SELECT ON api.fund_quotas TO anon, authenticated;

CREATE OR REPLACE VIEW api.cash_securities AS
SELECT
    v.codneg            AS ticker,
    v.trade_date,
    v.codbdi            AS board,
    CASE v.tpmerc WHEN '010' THEN 'standard' ELSE 'odd' END AS lot,
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
    v.preco_fechamento / NULLIF(v.fator_cotacao, 0) AS close_unit
FROM public.vw_b3_instrument_typed v
WHERE v.instrument_type = 'cash_security'
  AND v.tpmerc IN ('010', '020', '021');

COMMENT ON VIEW api.cash_securities IS
    'Unadjusted B3 cash quotes for cash_security: everything else on the cash board — subscription rights, receipts, and other non-share paper. Grain (ticker, trade_date, board, term_days, lot) — lot is standard (tpmerc 010) or odd (020/021), so filter lot=eq.standard for round lots only. Classified from published TPMERC/ESPECI; never inferred.';

ALTER VIEW api.cash_securities SET (security_invoker = false);
GRANT SELECT ON api.cash_securities TO anon, authenticated;


-- Signature change (trailing p_after cursor): drop the old shape first.
-- CREATE OR REPLACE cannot add a parameter, and PostgREST resolves an RPC by
-- argument names, so the 4-argument form must not survive as an overload.
DROP FUNCTION IF EXISTS api.quote_history(TEXT, DATE, DATE, TEXT);

CREATE OR REPLACE FUNCTION api.quote_history(
    p_ticker TEXT,
    p_from   DATE DEFAULT (CURRENT_DATE - 365),
    p_to     DATE DEFAULT CURRENT_DATE,
    p_board  TEXT DEFAULT NULL,
    -- NULL = whole result (refuses over 1000 rows); '' = first page;
    -- 'YYYY-MM-DD' = the page after that trade_date.
    p_after  TEXT DEFAULT NULL
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
    asset_class       TEXT
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    WITH params AS (
        SELECT c.paging, c.after_date
        FROM api.parse_date_cursor(p_after, 'quote_history') c
    ),
    selected_board AS (
        SELECT COALESCE(
            p_board,
            (
                SELECT latest.board
                FROM api.quotes latest
                WHERE latest.ticker = upper(btrim(p_ticker))
                ORDER BY latest.trade_date DESC, latest.board
                LIMIT 1
            )
        ) AS board
    ),
    -- One page + one. The 1001st row is what makes "over the page" detectable;
    -- assert_row_cap then REFUSES (22023) instead of handing back a truncated
    -- series that looks complete. Measured 2026-08-28: this window from 2019
    -- returned exactly 1000 rows with a 200 under the old LIMIT 5001, because
    -- PostgREST cuts at db-max-rows long before 5001 is reached.
    page AS (
        SELECT
            q.ticker, q.trade_date, q.board, q.short_name, q.spec, q.currency,
            q.open, q.high, q.low, q.average, q.close, q.bid, q.ask,
            q.trades, q.quantity, q.volume, q.isin, q.quotation_factor,
            q.adjusted, q.source, q.asset_class
        FROM api.quotes q
        JOIN params pp ON TRUE
        WHERE q.ticker = upper(btrim(p_ticker))
          AND q.trade_date BETWEEN p_from AND p_to
          AND q.board = (SELECT sb.board FROM selected_board sb)
          AND (pp.after_date IS NULL OR q.trade_date > pp.after_date)
        ORDER BY q.trade_date
        LIMIT 1001
    )
    -- Positional ORDER BY dodges OUT-parameter name ambiguity (trade_date is
    -- column 2). The subquery is uncorrelated, so it runs once, not per row.
    SELECT
        g.ticker, g.trade_date, g.board, g.short_name, g.spec, g.currency,
        g.open, g.high, g.low, g.average, g.close, g.bid, g.ask,
        g.trades, g.quantity, g.volume, g.isin, g.quotation_factor,
        g.adjusted, g.source, g.asset_class
    FROM page g
    WHERE api.assert_row_cap((SELECT count(*) FROM page),
                             (SELECT pp.paging FROM params pp), 'quote_history')
    ORDER BY 2
    LIMIT 1000;
$$;

COMMENT ON FUNCTION api.quote_history(TEXT, DATE, DATE, TEXT, TEXT) IS
    'Daily unadjusted quote series for one ticker, oldest first. Row cap: more than 1000 rows RAISES 22023 (never trimmed) unless p_after pages: '''' = first page, then the last row''s trade_date as ''YYYY-MM-DD''; a page shorter than 1000 is the last. Or narrow p_from/p_to.';

REVOKE ALL ON FUNCTION api.quote_history(TEXT, DATE, DATE, TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.quote_history(TEXT, DATE, DATE, TEXT, TEXT) TO anon, authenticated;

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
    asset_class       TEXT
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
        q.asset_class
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
    distribution_number TEXT
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
        NULLIF((b.raw ->> 'ptoexe')::NUMERIC, 0) / 1e6,
        b.raw ->> 'indopc',
        b.raw ->> 'dismes'
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
    'One session''s option chain for a REQUIRED codneg prefix (>= 3 chars; else it raises). side = call/put from tpmerc 070/080. p_trade_date NULL = latest option-segment session. underlying_ticker resolves the option row''s ISIN (published: CODISI carries the underlying''s ISIN) to the same session''s cash codneg; NULL when the underlying had no cash print that day. Rows clamped to 1..2000.';

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
    distribution_number TEXT
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
    WITH page (codneg, trade_date, side, strike, expiry, spec, currency, open, high, low, average, close, bid, ask, trades, quantity, volume, isin, quotation_factor, adjusted, source, underlying_ticker, strike_points, strike_correction, distribution_number) AS (
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
            NULLIF((b.raw ->> 'ptoexe')::NUMERIC, 0) / 1e6,
            b.raw ->> 'indopc',
            b.raw ->> 'dismes'
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
    'Daily unadjusted series for one option codneg (tpmerc 070/080), quote_history''s shape plus side/strike/expiry and underlying_ticker (resolved per session from the published ISIN mapping; NULL when the underlying had no cash print that day). Row cap: more than 1000 rows RAISES 22023 (never trimmed); narrow p_from/p_to. No cursor — an option series is short-lived, so a window over a page is a mistake, not a walk.';

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
    source              TEXT
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
        b.source
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
    'Option exercise EVENTS (tpmerc 012 call / 013 put) for a REQUIRED codneg prefix (>= 3 chars). One row per exercise print — these are not quotes and carry no return semantics. underlying_ticker per the published ISIN mapping. Rows clamped to 1..500 anonymous, 1..5000 signed in.';

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
    v.fetched_at
FROM public.vw_b3_instrument_typed v
WHERE v.instrument_type = 'auction';

COMMENT ON VIEW api.auctions IS
    'Auction prints (tpmerc 017, leilão) — one-off event rows, not a quote series. ~210 rows on the whole 2019-2026 tape. Unadjusted, straight from COTAHIST.';

ALTER VIEW api.auctions SET (security_invoker = false);
GRANT SELECT ON api.auctions TO anon, authenticated;

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
    source            TEXT
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
    WITH page (codneg, trade_date, term_days, spec, currency, open, high, low, average, close, bid, ask, trades, quantity, volume, isin, quotation_factor, adjusted, source) AS (
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
            b.source
        FROM public.b3_cotahist b
        WHERE b.tpmerc = '030'
          AND b.codneg = upper(btrim(p_codneg))
          AND b.trade_date BETWEEN p_from AND p_to
        -- Termo grain includes prazot (several terms of one codneg can print on
        -- one session), so order by it too for a deterministic cut. length-then-
        -- text sorts digit strings numerically without a cast that could blow up
        -- on source garbage.
        ORDER BY b.trade_date, length(b.prazot), b.prazot
        LIMIT 1001
    )
    SELECT g.* FROM page g
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'termo_history')
    ORDER BY g.trade_date, length(g.term_days), g.term_days
    LIMIT 1000;
$$;

COMMENT ON FUNCTION api.termo_history(TEXT, DATE, DATE) IS
    'Daily unadjusted series for one termo codneg (tpmerc 030), including term_days (prazot). Grain is (codneg, trade_date, term_days). Row cap: more than 1000 rows RAISES 22023 (never trimmed); narrow p_from/p_to.';

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
    -- period is CVM's filed month-END date, period_month is the panel's key.
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
    'Monthly NAV/flows series for one CNPJ, oldest first. Default window (p_to NULL) ends at the family''s latest COMPLETE period per mv_period_completeness; an explicit p_to serves the window verbatim, partial months included. Row cap: more than 1000 rows RAISES 22023 (never trimmed) unless p_after pages: '''' = first page, then the last row''s period as ''YYYY-MM-DD''. PAGING REQUIRES p_entity_type — one CNPJ can file under two families in the same month (385 do), so a bare period is unique only within one family; whole-result mode serves both and labels each row. period is CVM''s filed month-END date; the trailing period_month is the same month as api.panel keys it (first of month). Columns are per family (fact_fund_monthly arms): fi files quota, quotaholders, inflows, redemptions; fidc and fiagro file delinquency; fii files quotaholders, monthly_yield, assets; fip files nav only — a null outside that list is not applicable, not missing (catalog().applicability). fidc delinquency is null through 2024-12 and filed from 2025-01 (regime break; catalog().regime_breaks).';

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
    v_cap    INT  := CASE api.caller_tier()
                          WHEN 'authenticated' THEN 5000 ELSE 500 END;
    v_limit  INT;
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

    v_limit := LEAST(GREATEST(COALESCE(p_limit, v_cap), 1), v_cap);

    IF COALESCE(p_kind, 'equity') = 'equity' THEN
        RETURN QUERY
        SELECT h.cnpj, h.period, 'equity'::TEXT, h.cd_ativo, h.ds_ativo,
               h.tp_aplic, h.tp_negoc, h.emissor_ligado,
               h.qt_pos_final, h.vl_merc_pos_final
        FROM public.cvm_fi_cda_acoes h
        WHERE (v_cnpj   IS NULL OR h.cnpj     = v_cnpj)
          AND (v_ticker IS NULL OR h.cd_ativo = v_ticker)
          AND (p_from IS NULL OR h.period >= p_from)
          AND (p_to   IS NULL OR h.period <= p_to)
        ORDER BY h.period DESC, h.vl_merc_pos_final DESC NULLS LAST
        LIMIT v_limit;
    ELSE
        RETURN QUERY
        SELECT h.cnpj, h.period, 'fund'::TEXT, h.cnpj_cota, h.nm_fundo_cota,
               h.tp_aplic, h.tp_negoc, h.emissor_ligado,
               h.qt_pos_final, h.vl_merc_pos_final
        FROM public.cvm_fi_cda_cotas h
        WHERE h.cnpj = v_cnpj
          AND (p_from IS NULL OR h.period >= p_from)
          AND (p_to   IS NULL OR h.period <= p_to)
        ORDER BY h.period DESC, h.vl_merc_pos_final DESC NULLS LAST
        LIMIT v_limit;
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
    v_cap     INT  := CASE api.caller_tier()
                          WHEN 'authenticated' THEN 5000 ELSE 500 END;
    v_limit   INT;
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

    v_limit := LEAST(GREATEST(COALESCE(p_limit, v_cap), 1), v_cap);

    RETURN QUERY
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
    LIMIT v_limit;
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
-- HISTORY BEGINS IN 2025. These tabs are ingested from the current-format
-- informe only; CVM's pre-2025 HIST archive publishes no equivalent member for
-- X_2 / X_4 / VI, so an earlier month has no rows — an upstream limit, not a
-- gap to backfill. coverage()'s fidc_tranches / fidc_aging rows say so.
--
-- Neither function derives anything: no performance gap, no subordination
-- ratio, no bucket sums. vw_fidc_tranche_detail / fidc_tranche_performance
-- (the dashboard's read) compute those on the same rows; a caller does the
-- arithmetic in the notebook, where it can see it. Percent fields are dirty
-- the way CVM's percentage fields are (schema.sql: raw values up to 1.6e8) —
-- served as filed, never clipped, never nulled.
--
-- Row cap: one page + one, then api.assert_row_cap REFUSES (22023). No
-- cursor: a fund's whole post-2025 history is tens of rows, so a window over
-- 1000 is a mistake to narrow, not a series to walk. Default window verbatim,
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
    'One FIDC''s tranches, month by month, oldest first: one row per (fund, month, classe_serie) from informe tabs X_2 / X_3 / X_6 — quotas, quota_value, return_month, and performance_expected vs performance_realised (what the series promised vs delivered, percent) — all AS FILED, with the dirty outliers CVM''s percentage fields carry (never clipped; range-check in the notebook). flows is the tranche''s tab X_4 operations as a JSON array [{tp_oper, value, quotas}], labels verbatim (e.g. Captações no Mês, Resgates no Mês, Amortizações) and never bucketed; NULL when none were filed. tranche_filed = FALSE marks a series with flows but no X_2 row. Nothing is derived: no performance gap, no subordination ratio. HISTORY BEGINS IN 2025 — CVM''s HIST archive has no equivalent member, so an earlier month has no rows (an upstream limit, not a gap). p_series pins one tranche label exactly. More than 1000 rows RAISES 22023 (never trimmed): narrow the window.';

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
    'One FIDC''s receivables aging ladder from informe tab VI, long, oldest first: 21 rows per month — kind=to_maturity (credits not yet due, by days to maturity, ten bands 1-30 .. >1080), kind=overdue (by days past due, the same ten bands), and kind=overdue_total, CVM''s FILED total of overdue credits, which is not a sum of the buckets and can disagree with one. Values in BRL as filed; a blank in the filing is NULL, never 0. item names the source column. Tab VI covers the credits acquired WITHOUT substantial retention of risk by the originator (tab V, the with-risk twin, is not ingested). HISTORY BEGINS IN 2025 — CVM''s HIST archive has no equivalent member, so an earlier month has no rows (an upstream limit, not a gap). The panel''s delinquency metric is the fund-level total; this is the ladder under it. More than 1000 rows RAISES 22023 (never trimmed): narrow the window.';

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
    ),
    base AS (
        -- Session data (quotes/derivatives) is complete by construction and a
        -- trade_date is never in the future, so all three dates coincide.
        SELECT 'quotes'::text AS dataset, MAX(q.trade_date) AS as_of,
               MAX(q.trade_date) AS complete_through, 'b3_cotahist'::text AS source,
               NULL::text AS notes, MAX(q.trade_date) AS newest_period,
               'b3'::text AS log_entity
        FROM public.vw_b3_quote_vista q
        UNION ALL
        SELECT 'funds'::text,
               MAX(d.last_period) FILTER (WHERE d.last_period <= CURRENT_DATE),
               public.latest_complete_period(NULL), 'cvm'::text, NULL::text,
               MAX(d.last_period), '*funds*'::text
        FROM public.dim_fund d
        UNION ALL
        SELECT 'fund_nav'::text,
               MAX(f.period) FILTER (WHERE f.period <= CURRENT_DATE),
               public.latest_complete_period(NULL), 'cvm'::text,
               'columns are per family: a null outside the family''s list in catalog().applicability is not applicable, not missing. api.metric_coverage() reports the filed span of each (family, metric) pair.'::text,
               MAX(f.period), '*funds*'::text
        FROM public.fact_fund_monthly f
        UNION ALL
        -- Per-family rows: the families file on different cadences (FI daily,
        -- FIDC/FII with a 1-2 month lag, FIP annually), so one blended date
        -- misreads all of them. FIP is exactly where as_of and newest_period
        -- diverge.
        SELECT 'funds_' || f.entity_type,
               MAX(f.period) FILTER (WHERE f.period <= CURRENT_DATE),
               public.latest_complete_period(f.entity_type), 'cvm'::text,
               CASE f.entity_type
                   WHEN 'fidc' THEN
                       'regime break at 2025-01-31: delinquency is null on every row through 2024-12-31 (CVM''s pre-2025 tab II/III monthly file carries no delinquency field) and filed on every row from 2025-01-31 (tab IV/VI). Not zero, not clean books — never chain-link across 2024-12 → 2025-01. See catalog().regime_breaks.'
                   WHEN 'fip' THEN
                       'files annually, keyed to 31-December: newest_period is a year-end key that can sit in the future, as_of is the newest period that has actually elapsed. Never read newest_period as freshness.'
               END::text,
               MAX(f.period), f.entity_type
        FROM public.fact_fund_monthly f
        GROUP BY f.entity_type
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
               MAX(f.dt_refer) FILTER (WHERE f.dt_refer <= CURRENT_DATE),
               NULL::date, 'cvm'::text,
               'api.financials serves latest stored statement versions; api.financial_statement_history exposes every stored version for one company and required statement. Exact document metadata may be unavailable; coverage reads filing headers and does not scan partitioned account rows.'::text,
               MAX(f.dt_refer), 'cia_aberta'::text
        FROM public.cia_filing f
        UNION ALL
        -- FII property-register snapshots. The source has no stable property
        -- identifier: row_hash identifies source-row content within a filing,
        -- not the physical asset across reports.
        SELECT 'fii_property_history'::text,
               MAX(i.data_referencia) FILTER (WHERE i.data_referencia <= CURRENT_DATE),
               NULL::date, 'cvm'::text,
               'One exact fund CNPJ; one source row per filing snapshot. CVM publishes no stable property id; row_hash is source-row identity only. NULL measurements remain missing, never zero.'::text,
               MAX(i.data_referencia), 'fii'::text
        FROM public.cvm_fii_imovel i
        UNION ALL
        SELECT 'focus_expectations'::text,
               MAX(e.reference_date) FILTER (WHERE e.reference_date <= CURRENT_DATE),
               NULL::date, 'bacen'::text,
               'Weekly Focus observations by report date and exact horizon. The API pins baseCalculo=0 and unsmoothed 12-month inflation; migration 16 fixed horizon collisions, but older lost horizon rows require re-fetch. Later corrections to survey dates outside the daily 30-day refresh are not a vintage archive.'::text,
               MAX(e.reference_date), 'bacen'::text
        FROM public.bacen_expectativas e
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
               MAX(c.period) FILTER (WHERE c.period <= CURRENT_DATE),
               public.latest_complete_period('fidc'), 'cvm'::text,
               'tab I cedente slots exist from 2019-11; cedente_id is checksum-verified at ingest (placeholders dropped, never coerced); share_pct is a percent of the block, not of the fund'::text,
               MAX(c.period), 'fidc'::text
        FROM public.cvm_fidc_cedente c
        UNION ALL
        SELECT 'fidc_sacados'::text,
               MAX(k.period) FILTER (WHERE k.period <= CURRENT_DATE),
               public.latest_complete_period('fidc'), 'cvm'::text,
               'tab VIII from 2013-01: the 25 largest debtors as anonymized (rank, value); seq is CVM''s rank as filed, never recomputed'::text,
               MAX(k.period), 'fidc'::text
        FROM public.cvm_fidc_sacado k
        UNION ALL
        SELECT 'fidc_sectors'::text,
               MAX(s.period) FILTER (WHERE s.period <= CURRENT_DATE),
               public.latest_complete_period('fidc'), 'cvm'::text,
               'tab II from 2013-01: receivables by sector, a hierarchy (fidc_portfolio.parent); TOTAL is the panel metric receivables'::text,
               MAX(s.period), 'fidc'::text
        FROM public.cvm_fidc_setor s
        UNION ALL
        SELECT 'fidc_scr'::text,
               MAX(r2.period) FILTER (WHERE r2.period <= CURRENT_DATE),
               public.latest_complete_period('fidc'), 'cvm'::text,
               'tab X exists from 2023-10 only: SCR grade ladders AA..H by debtor and by operation; a month before that has no rows, not zero-graded ones'::text,
               MAX(r2.period), 'fidc'::text
        FROM public.cvm_fidc_scr r2
        UNION ALL
        -- FIDC structure tabs (v31): tranches (X_2/X_3/X_6 + X_4) and the
        -- tab VI aging ladder. Same informe, same fidc completeness clamp.
        -- The note carries the one thing a short span invites a caller to
        -- misread: it starts in 2025 because CVM publishes no archive of
        -- these members, not because ingest missed anything.
        SELECT 'fidc_tranches'::text,
               MAX(t2.period) FILTER (WHERE t2.period <= CURRENT_DATE),
               public.latest_complete_period('fidc'), 'cvm'::text,
               'tabs X_2/X_3/X_6 (+ X_4 flows) exist from 2025-01 only: CVM''s pre-2025 HIST archive publishes no equivalent member, so an earlier month has no rows — an upstream limit, not a gap to backfill. Quotas, quota value, return and promised vs realised performance are as filed (percent fields carry CVM''s outliers); flows keep CVM''s TP_OPER labels verbatim'::text,
               MAX(t2.period), 'fidc'::text
        FROM public.cvm_fidc_tranche t2
        UNION ALL
        SELECT 'fidc_aging'::text,
               MAX(a2.period) FILTER (WHERE a2.period <= CURRENT_DATE),
               public.latest_complete_period('fidc'), 'cvm'::text,
               'tab VI exists from 2025-01 only: CVM''s pre-2025 HIST archive publishes no equivalent member, so an earlier month has no rows — an upstream limit, not a gap to backfill. to_maturity and overdue ladders in ten day-bands each, BRL as filed; overdue_total is CVM''s filed total, not a sum of the bands'::text,
               MAX(a2.period), 'fidc'::text
        FROM public.cvm_fidc_aging a2
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
               MAX(p.trade_date) FILTER (WHERE p.trade_date <= CURRENT_DATE),
               MAX(p.trade_date) FILTER (WHERE p.trade_date <= CURRENT_DATE),
               'b3'::text,
               'RATCHET: B3 keeps ~21 business days of the lending book and publishes no archive, so this series starts at SILO''s first capture and cannot be backfilled at any price — a short window is the retention limit, not a gap. Read pct_float together with float_basis: index_free_float (index constituents only) and shares_outstanding (a larger denominator, so a smaller percentage) are different metrics, and any ranking must filter to one. pct_float and days_to_cover are NULL, never 0, when the denominator is missing or the name did not trade.'::text,
               MAX(p.trade_date), '*b3_lending_balance*'::text
        FROM public.b3_lending_open_position p
        UNION ALL
        SELECT 'short_interest_by_sector'::text,
               MAX(p.trade_date) FILTER (WHERE p.trade_date <= CURRENT_DATE),
               MAX(p.trade_date) FILTER (WHERE p.trade_date <= CURRENT_DATE),
               'b3'::text,
               'Same ratchet and same spine as short_interest. Sector is B3''s own top-level sector from the index portfolios; tickers B3 publishes no sector for (ETFs, BDRs, anything outside the index universe) are bucketed as Não classificado rather than dropped, so the bars sum to the whole book. short_value_equities restricts to SHARES and UNIT for the single-name view.'::text,
               MAX(p.trade_date), '*b3_lending_balance*'::text
        FROM public.b3_lending_open_position p
        UNION ALL
        SELECT 'lending_trades'::text,
               MAX(t.trade_date) FILTER (WHERE t.trade_date <= CURRENT_DATE),
               MAX(t.trade_date) FILTER (WHERE t.trade_date <= CURRENT_DATE),
               'b3'::text,
               'RATCHET: ~21 business days at the source, no archive, history starts at first capture. rate_pct is quantity-weighted, while B3''s own published average in the lending-rate table weights by NUMBER OF TRADES — the two answer different questions and neither overwrites the other (measured 2026-09-10 across 569 tickers: mean absolute difference 0.037pp). internal_trades counts trades a single broker crossed with itself; about three quarters of the tape is that.'::text,
               MAX(t.trade_date), '*b3_lending_trade*'::text
        FROM public.b3_lending_trade t
        UNION ALL
        SELECT 'lending_participants'::text,
               MAX(t.trade_date) FILTER (WHERE t.trade_date <= CURRENT_DATE),
               MAX(t.trade_date) FILTER (WHERE t.trade_date <= CURRENT_DATE),
               'b3'::text,
               'RATCHET: ~21 business days at the source, no archive, history starts at first capture. broker_code is the B3 PARTICIPANT intermediating, NEVER the beneficial owner: ~75% of trades carry the same code on both legs (32,197 of 43,165 on 2026-09-10), so a large borrow through a broker is its client book, not a position it holds. internal_legs / internal_qty are what separate client churn from directional flow — never read a broker''s quantity_borrowed as its own short.'::text,
               MAX(t.trade_date), '*b3_lending_trade*'::text
        FROM public.b3_lending_trade t
        UNION ALL
        -- as_of is the newest REFERENCE date held, which trails the calendar by
        -- B3's T+2 publication lag even when ingest is perfectly healthy. That
        -- is the source's cadence, not our staleness — exactly the distinction
        -- CLAUDE.md draws between complete_through and landed_at.
        SELECT 'investor_flow'::text,
               MAX(i.reference_date) FILTER (WHERE i.reference_date <= CURRENT_DATE),
               MAX(i.reference_date) FILTER (WHERE i.reference_date <= CURRENT_DATE),
               'b3'::text,
               'RATCHET: ~21 business days at the source, no archive, history starts at first capture. Published T+2, so as_of trails the calendar even when ingest is healthy. The daily figures are a FIRST DIFFERENCE of a month-to-date cumulative snapshot and never difference across a month boundary; flow_basis says which row you have — delta (a real one-session difference), month_open (the month''s first session), or unknown_opening_snapshot (no earlier snapshot held that month), whose flows are NULL BY CONSTRUCTION and must never be read or summed as zeros. Values are R$ thousands.'::text,
               MAX(i.reference_date), '*b3_investor_flow*'::text
        FROM public.b3_investor_participation i
        UNION ALL
        -- Inflation (BACEN SGS). The headline month is the honest as_of: the
        -- cores, classifications and groups publish on the same day as 433.
        -- A published month is complete by construction (a statistical
        -- release, not a filing cadence), so both dates coincide.
        SELECT 'inflation'::text,
               MAX(s.reference_date) FILTER (WHERE s.reference_date <= CURRENT_DATE),
               MAX(s.reference_date) FILTER (WHERE s.reference_date <= CURRENT_DATE),
               'bacen'::text,
               'Monthly changes in percent AS PUBLISHED; acc_12m is DERIVED (the trailing twelve monthly changes chained, NULL unless all twelve are present and consecutive) and reproduces BACEN''s own IPCA_12M (13522) exactly for the headline. IPCA15 is the mid-month preview, not a revision. Group rows are variations, never contributions — weights are inflation_items. Group codes 1640..1643 are Comunicação, Saúde, Despesas pessoais, Educação (measured, not IBGE''s order). IPCA runs from 1980-01, cores and groups from 1991-01, IPCA-15 from 2000-05.'::text,
               MAX(s.reference_date), '*bacen_sgs*'::text
        FROM public.bacen_sgs s
        WHERE s.series_code = 433
        UNION ALL
        SELECT 'inflation_items'::text,
               MAX(i.reference_month) FILTER (WHERE i.reference_month <= CURRENT_DATE),
               MAX(i.reference_month) FILTER (WHERE i.reference_month <= CURRENT_DATE),
               'ibge'::text,
               'Weights, monthly / YTD / 12-month changes AS PUBLISHED by IBGE SIDRA (table 1419 for 2012-01..2019-12, 7060 from 2020-01); contribution = weight × change_month / 100 is the one derived column. SIDRA item codes CHANGED with the 2020-01 structure — item_number and names are the continuity, sidra_table says which structure a row came from. Sum contributions within one level only. No item tree exists before 2012-01; the group variations before that are inflation (BACEN).'::text,
               MAX(i.reference_month), 'ibge'::text
        FROM public.ibge_ipca_item_monthly i
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
    )
    SELECT b.dataset, b.as_of, b.complete_through, b.source, b.notes,
           b.newest_period, l.landed_at, l.landed_git_sha
    FROM base b
    LEFT JOIN landed l ON l.entity = b.log_entity
    ORDER BY 1;
$$;

COMMENT ON FUNCTION api.coverage() IS
    'Freshness AND honesty per dataset. as_of = the newest period that has landed and has actually ELAPSED (bounded by today); complete_through = the newest COMPLETE period, which is what default windows serve; newest_period = the newest period KEY present, which can sit in the future when a family files forward-dated (FIP is keyed 31-December); landed_at = when ingest last SUCCEEDED for that source, from cvm_ingest_log (status ok with a finish time, so a later failed run never advances it); landed_git_sha = the git commit of THAT run — which code produced this data — NULL when the run recorded none (before migration 44, or run outside GitHub Actions), never borrowed from an older run. funds_<family> rows report each filing cadence separately. notes carries a caveat the dates cannot: the funds_fidc row states the 2025-01 delinquency regime break (null on every row before, filed on every row after — never chain-link through it); funds_fip states why its newest_period runs ahead; fund_nav points at catalog().applicability and api.metric_coverage(); the fidc_tranches and fidc_aging rows state that those informe tabs begin in 2025-01 because CVM publishes no archive of them (an upstream limit, not a gap); the fnet_documents row (the FNET register behind fund_documents and fund_restatements) is keyed on the DELIVERY day, with complete_through the day before as_of, and states that its history begins at first capture / backfill and that fund links come from a fortnightly sweep, so recent documents may have no cnpj yet; and the five B3 lending / flow rows (short_interest, short_interest_by_sector, lending_trades, lending_participants, investor_flow) state the RATCHET — B3 keeps ~21 business days and publishes no archive, so their span starts at first capture and no backfill exists — along with the float_basis, brokerage-not-owner and first-difference traps that make those series easy to read wrongly. Their landed_at is split by ingest doc_type, so a COTAHIST run never reports as the lending group''s freshness.';

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

CREATE OR REPLACE FUNCTION api.panel(
    p_ids     TEXT[],
    p_metrics TEXT[] DEFAULT ARRAY['close', 'nav']::TEXT[],
    p_from    DATE   DEFAULT (CURRENT_DATE - 365),
    -- NULL (the default) = honest window: quote/option/termo arms run to
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
            FROM unnest(COALESCE(p_metrics, ARRAY['close','nav']::TEXT[])) AS x
            WHERE btrim(x) <> ''
        ) AS metrics,
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
        q.quotation_factor
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
        q.close, q.close_unit, q.volume, q.asset_class, q.quotation_factor
    FROM api.quotes q
    JOIN params p ON TRUE
    WHERE p.freq = 'day'
      AND q.trade_date BETWEEN p.d0 AND p.d1
      AND q.ticker IN (SELECT ticker FROM tickers)
    ORDER BY q.ticker, q.trade_date, q.board
),
quote_px AS (
    SELECT * FROM quote_month
    UNION ALL
    SELECT * FROM quote_day
),
-- close_return honesty guards (SERVING.md step 4):
--   * daily: the previous SESSION must be within 7 calendar days. Carnaval
--     and year-end close the exchange for up to ~5 days; anything longer is
--     a listing gap (halt, delisting window, illiquid re-print) and a
--     "daily" return across it is a multi-week move wearing a daily label.
--     NULL, not a fabricated smooth number.
--   * both grains: the quotation factor must not have changed between the
--     two prints. A fatcot flip (measured live: GOLL2 1000->1, IBOV11
--     100->1) rescales the quote by that factor and reports a ~±99.9%
--     "return" with no market move behind it.
quote_ret AS (
    SELECT
        ticker,
        period,
        asset_class,
        CASE
            WHEN lag(quotation_factor) OVER w IS DISTINCT FROM quotation_factor
            THEN NULL
            WHEN (SELECT freq FROM params) = 'day'
             AND lag(obs_date) OVER w >= period - 7
            THEN close / NULLIF(lag(close) OVER w, 0) - 1
            WHEN (SELECT freq FROM params) = 'month'
             AND lag(period) OVER w = (period - INTERVAL '1 month')::date
            THEN close / NULLIF(lag(close) OVER w, 0) - 1
            ELSE NULL
        END AS close_return
    FROM quote_px
    WINDOW w AS (PARTITION BY ticker ORDER BY period)
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
    'Long panel for correlation/factor work. Mix tickers, option/termo codnegs, + CNPJs. Grain is (id, asset_class, date, metric): a CNPJ filing under two families yields one row per family unless p_entity_type narrows it. No ffill. close_return is p_t/p_{t-1}-1 from unadjusted closes (a split appears as a jump), cash tickers only, and is null across calendar gaps. Row cap: more than 1000 rows RAISES 22023 (never trimmed) unless p_after pages: '''' = first page, ''date|id|metric|asset_class'' = next; a page shorter than 1000 is the last. Universe mode: p_ids empty + p_entity_type walks a whole family (optionally p_min_nav, p_min_months), signed-in callers only.';

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
    p_statement TEXT
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
    WITH ref AS (
        -- setor/segmento ride along from company_ref because CVM's chart of
        -- accounts is sector-specific: the same cd_conta is a different
        -- quantity for a bank and an industrial filer. A caller computing a
        -- median, rank or percentile needs the partition key on the row, not
        -- a second round trip. It is a partition key, not a display label.
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

REVOKE ALL ON FUNCTION api.cia_statement_rows(TEXT, DATE, DATE, TEXT, TEXT, TEXT) FROM PUBLIC;

DROP FUNCTION IF EXISTS api.financials(TEXT, TEXT, DATE, DATE, TEXT, TEXT);
CREATE OR REPLACE FUNCTION api.financials(
    p_id        TEXT,
    p_statement TEXT DEFAULT NULL,
    p_from      DATE DEFAULT (CURRENT_DATE - 1825),
    p_to        DATE DEFAULT CURRENT_DATE,
    p_scope     TEXT DEFAULT 'con',
    p_doc_type  TEXT DEFAULT NULL
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
    -- companies — never a display label. See docs/CIA_DATA_MAP.md.
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
        FROM api.cia_statement_rows(p_id, p_from, p_to, p_scope, p_doc_type, p_statement) s
        ORDER BY s.ref_date DESC, s.statement, s.period_months NULLS FIRST, s.account_code
        LIMIT 1001
    )
    SELECT g.* FROM page g
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'financials')
    ORDER BY g.ref_date DESC, g.statement, g.period_months NULLS FIRST, g.account_code
    LIMIT 1000;
$$;

REVOKE ALL ON FUNCTION api.financials(TEXT, TEXT, DATE, DATE, TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.financials(TEXT, TEXT, DATE, DATE, TEXT, TEXT) TO anon, authenticated;

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
    WITH page AS (
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
        JOIN api.company_ref(p_id) r ON r.cd_cvm = a.cd_cvm
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
    p_scope TEXT DEFAULT 'con'
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
    -- quantities. See docs/CIA_DATA_MAP.md.
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
            SELECT * FROM api.cia_statement_rows(p_id, p_from, p_to, p_scope, NULL, NULL)
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
                -- NET INCOME IS 3.11 ONLY. There used to be a COALESCE to 3.09
                -- behind it, on the belief that banks file a chart without 3.11.
                -- That belief was wrong twice over. Verified against Banco do
                -- Brasil (cd_cvm 1023, FY2024, con, 12m): 3.09 = 29.17bn "Lucro ou
                -- Prejuizo antes das Participacoes e Contribuicoes Estatutarias",
                -- 3.10 = 0.00 "Participacoes nos Lucros e Contribuicoes
                -- Estatutarias", 3.11 = 29.17bn "Lucro ou Prejuizo Liquido
                -- Consolidado do Periodo". So 3.11 is present and IS net income;
                -- 3.09 is profit BEFORE statutory profit-sharing and coincides
                -- with it only because 3.10 happens to be zero.
                --
                -- The fallback was then measured across the whole table rather
                -- than argued about: of 50,439 DRE statements, 282 (0.56%) have no
                -- 3.11, and for every one of those 282 the 3.09 substitution was
                -- numerically identical to nothing (3.10 was zero or absent) — so
                -- it has never actually overstated net income. It was load-bearing
                -- for those 282 and silently wrong for the first filer to report a
                -- non-zero 3.10 without a 3.11. Those 282 now return NULL, which
                -- is the honest answer: a caller who wants the pre-participations
                -- figure can read 3.09, 3.10 and 3.11 itself from api.financials.
                -- Rule 1 of the integrity rules, applied to a derived column.
                --
                -- Also note the same code means different things across charts, so
                -- 3.01/3.03 above are not like-for-like between a bank and an
                -- industrial filer — which is why setor ships on the row.
                -- Documented in docs/CIA_DATA_MAP.md.
                MAX(s.value) FILTER (WHERE s.account_code = '3.11') AS net_income
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

REVOKE ALL ON FUNCTION api.company_financials(TEXT, DATE, DATE, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.company_financials(TEXT, DATE, DATE, TEXT) TO anon, authenticated;

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
-- which is a different job. docs/CIA_DATA_MAP.md carries the evidence tables.
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
    p_doc_type TEXT DEFAULT NULL
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
            SELECT * FROM api.cia_statement_rows(p_id, p_from, p_to, p_scope, p_doc_type, 'DRE')
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

COMMENT ON FUNCTION api.income_statements(TEXT, DATE, DATE, TEXT, TEXT) IS
    'Income statement, one row per filed period, with named fields. Fields are keyed on the AS-FILED account label, not on cd_conta and not on setor: CVM ships four DRE charts and the same code means different things across them. net_income therefore resolves for the filings that report it on 3.09 (the one bank chart with no 3.11) as well as those on 3.11. A concept a chart does not file reads NULL — operating_income is industrial-only. `chart` says which layout the filing used. Values are absolute reais.';

REVOKE ALL ON FUNCTION api.income_statements(TEXT, DATE, DATE, TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.income_statements(TEXT, DATE, DATE, TEXT, TEXT) TO anon, authenticated;

-- ---------------------------------------------------------------------------
-- Catalog — the metric map, public (INSTRUMENTS.md: discovery is contract)
-- ---------------------------------------------------------------------------
-- The same JSON serve/catalog.py's catalog_payload() serves at /v1/catalog,
-- as one jsonb constant, so an agent on the Data API can self-describe
-- without the local adapter. An offline test
-- (tests/test_api_contract_sql.py) pins this literal to catalog_payload()
-- by deep equality — editing serve/catalog.py without regenerating this
-- block fails CI, and vice versa. Regenerate with:
--   .venv/bin/python -c "import json; from serve.catalog import catalog_payload; print(json.dumps(catalog_payload(), indent=2, ensure_ascii=False))"
-- Catalog changes bump CATALOG_VERSION in serve/catalog.py (mirrored in the
-- "version" key below).
--
-- SECURITY INVOKER (the file-wide DEFINER rule does not apply): the body
-- reads no relation at all — it returns a constant — so DEFINER would grant
-- owner rights for nothing. INVOKER is the minimal privilege, and with no
-- object references there is no search_path surface to pin.

CREATE OR REPLACE FUNCTION api.catalog()
RETURNS jsonb
LANGUAGE sql
STABLE
AS $fn$
SELECT $json${
  "kind": "catalog",
  "version": 35,
  "primitive": "panel",
  "agent": "You are querying Silo, a Brazilian public-markets warehouse (CVM funds, B3 COTAHIST cash quotes, options and termo, the B3 securities-lending and investor-flow group, and Brazilian inflation — BACEN's IPCA series and IBGE's item tree with weights). Call catalog once and cache it. Resolve names with lookup, then fetch a panel. The primitive is a panel (id, date, metric, value). Correlation, ranking, spreads, regressions and other relations are reductions of that panel — compute them in the notebook. Do not fabricate ids, fills, or ticker-CNPJ matches. TWO SURFACES, AND THEY DIFFER: the DEPLOYED api is Supabase PostgREST — POST /rest/v1/rpc/<function> with a JSON body of p_-prefixed named arguments (arrays stay arrays), views at GET /rest/v1/<view>, header `apikey`. The /v1/* routes in `endpoints` are an optional local Flask adapter (serve/app.py) that is not necessarily deployed; its query-string form and its `format=wide` envelope exist ONLY there. Prefer the postgrest section unless you know the /v1 adapter is running. Read the row-cap constraint: EVERY function REFUSES (SQLSTATE 22023) a window over 1000 rows instead of trimming it — page panel, quote_history and fund_nav with p_after, narrow the rest. fund_nav also needs p_entity_type to page. The GET views still cut at 1000 and keep the OLDEST rows, so READ THE Content-Range RESPONSE HEADER on those: `0-999/*` is the only thing that tells you. BEFORE READING A NULL AS A GAP, call coverage() and metric_coverage(): a null outside a family's column set is not applicable, and a metric absent from metric_coverage() is one that family never files. coverage().as_of is the newest ELAPSED period; newest_period can sit in the future when a family files forward-dated (FIP is keyed 31-December), so never read it as freshness. PRICE IS THE DEFAULT, everything else is opt-in: panel with no p_metrics returns `close` for tickers and `nav` for CNPJs, and that is the call to make unless you actually need another measure — name metrics explicitly only when you will use them. The wide endpoints are the exception and behave the other way round: quote_latest, quote_history and the views return their full OHLCV/identity row every time, so trim them with PostgREST `?select=` (e.g. `?select=ticker,trade_date,close`) rather than pulling 22 columns to read one. See `defaults`.",
  "defaults": {
    "principle": "price by default; every other measure is opt-in",
    "panel": {
      "metrics": [
        "close",
        "nav"
      ],
      "means": "close for ticker ids, nav for cnpj ids; a metric absent for an id type simply yields no rows",
      "grain": "(id, asset_class, date, metric) — a CNPJ filing under two families yields one row per family; p_entity_type narrows to one",
      "to_widen": "pass p_metrics explicitly, e.g. p_metrics=['close','volume']"
    },
    "wide_endpoints": {
      "which": [
        "quote_latest",
        "quote_history",
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
      "meaning": "Unadjusted close. Cash tickers: the ticker's latest BDI board by default, classified from published TPMERC/ESPECI. Option/termo codnegs: that derivative segment's session close. Month = last session."
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
      "meaning": "Session traded volume (BRL). Cash: the ticker's latest BDI board by default; option/termo: that derivative segment. Month = last session."
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
      "meaning": "p_t/p_{t-1}-1 from stored unadjusted closes. Corporate actions appear as spurious jumps (a 2:1 split reports roughly -50%). Daily: previous session. Monthly: previous calendar month else null.",
      "derived": true
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
        "fidc": "2025-01-31"
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
  "notebook_reducers": {
    "describe": "Per-column n, null_rate, min, max, last. No model.",
    "corr": "Pairwise Pearson on complete pairs of the wide matrix. One relation among many.",
    "rank": "Latest non-null value per id for the first metric, descending.",
    "spread": "First column minus second column of the wide matrix, dates aligned."
  },
  "constraints": [
    "A NULL OUTSIDE A FAMILY'S COLUMN SET IS NOT APPLICABLE, NOT MISSING. fund_nav returns the same eleven columns for every family, but each family files only some of them (`applicability` in this catalog, read off fact_fund_monthly's per-family arms): fi files quota, quotaholders, inflows and redemptions; fidc and fiagro file delinquency; fii files quotaholders, monthly_yield and assets; fip files nav alone. A null outside that list is set by construction and carries no information; a null inside it is a blank in that month's filing.",
    "A FIDC CEDENTE SHARE IS A PERCENT OF ITS BLOCK, NOT OF THE FUND. fidc_cedentes serves tab I's nine slots per block: bloco A is the receivables acquired WITH substantial retention of risks and benefits by the originator, B WITHOUT, and share_pct is the cedente's share of that block. The block totals are not served (tab I's asset lines are not ingested), so a share cannot be turned into reais here. cedente_id is the originator's own filed CPF/CNPJ, kept only when its check digits verify — placeholders (all-zero, all-nine) and unrecoverable identifiers were dropped at ingest, never coerced — and cedente_tickers is the FCA map's active listings for it, NULL when not listed. share_pct is AS FILED and dirty in the way CVM's percentage fields are: 9% of slots carry a value above 100 (max 19,771 in 2026-07); validate the range in the notebook, never read it as a fraction. Slots exist from 2019-11; nothing is matched by name.",
    "FIDC SACADOS ARE ANONYMIZED RANKS. fidc_sacados and the sacado_top1 / sacado_top25 metrics come from tab VIII, which publishes the 25 largest debtors as (rank, value) with no identity — CVM's dictionary describes neither column. seq is CVM's rank as filed and is never recomputed from valor (65 of 3,043 funds filed a non-descending series in 2026-07; they are served as filed). sacado_top25 sums the ranks the fund filed, which may be fewer than 25. Concentration = sacado_top1 / receivables (or top25 / receivables) is a notebook division, not a served number — and it can exceed 1: tab VIII and tab II do not share a base for every fund (2026-07: the top-25 sum exceeds the receivables total for 1.9% of funds, rank 1 alone for 0.5%), served as filed and never capped.",
    "FIDC PORTFOLIO ROWS ARE A HIERARCHY. fidc_portfolio kind=sector serves tab II as one row per code: TOTAL is the whole receivables book, a lettered code (A..K) a sector, and a code with a digit (C1, F3) a member of its lettered parent (`parent`). Sum leaves or sum parents, never both. kind=scr_debtor and kind=scr_operation are the BACEN SCR grade ladders AA..H for the same receivables, graded by debtor and by operation respectively — two views of one book, not two books. tab X exists from 2023-10 only; earlier months have no scr rows, not zero-graded ones.",
    "WHICH CODE PRODUCED THIS DATA. coverage().landed_git_sha is the git commit of the very ingest run that set landed_at — the code that parsed and stored the newest data for that dataset — read from GITHUB_SHA on the run. It is NULL when that run recorded none (a run from before lineage existed, 2026-09-24, or one started outside GitHub Actions), and it is never borrowed from an older run, because an older run's code did not produce the newest rows. The audit log behind it also records parser_version, bumped only when a parser or field map changes what a stored value means; neither is a property of the SOURCE, so neither says anything about how much CVM, B3 or BACEN have published (that is complete_through).",
    "FIDC TRANCHES AND AGING BEGIN IN 2025, AND ARE SERVED AS FILED. fidc_tranches (informe tabs X_2/X_3/X_6 + X_4) and fidc_aging (tab VI) exist from 2025-01 only: CVM's pre-2025 HIST archive publishes no equivalent member, so an earlier month has no rows — an upstream limit, not a gap and not a backfill to ask for. fidc_tranches is one row per (fund, month, classe_serie): quotas, quota_value, return_month, and performance_expected vs performance_realised (what the series promised vs delivered, percent), dirty the way CVM's percentage fields are — never clipped, range-check in the notebook. Its `flows` array carries tab X_4's operations with CVM's TP_OPER label verbatim (e.g. Captações no Mês, Resgates no Mês, Amortizações); the vocabulary has drifted, so match labels yourself and never read a label you did not find as zero. tranche_filed = FALSE marks a series with flows but no X_2 row. fidc_aging is long: kind=to_maturity (not yet due, by days to maturity) and kind=overdue (by days past due), ten day-bands each, plus kind=overdue_total — CVM's FILED total, not a sum of the bands, and the two can disagree. Nothing is derived by either function: no performance gap, no subordination ratio, no band sums.",
    "THE FNET REGISTER KNOWS A DOCUMENT'S FUND ONLY BY LINK, AND LINKS NO VERSIONS. fund_documents and fund_restatements serve B3 Fundos.NET's document register as published, metadata only: each version is its own fnet_id, versao counts the filings, modalidade is AP (original), RE (voluntary restatement) or RC (a restatement CVM required), and status is AC / IC (superseded) / CC (cancelled) AS OF fetched_at, not live. FNET rows carry NO CNPJ: a document belongs to a fund because FNET returned it when SILO queried cnpjFundo = that CNPJ, in a sweep that reaches every FII/FIDC once a fortnight — so a document delivered since the fund's last sweep is not in fund_documents yet, and fund_restatements serves it with cnpj NULL rather than dropping it. fund_name is FNET's label and is never joined on. Because FNET does not say which document a re-filing replaces, fund_restatements PAIRS each versao > 1 with the document in the same group — (cnpj link, categoria, tipo_documento, especie, reference_raw) — carrying the highest lower versao, the greatest fnet_id winning a tie (a group can legitimately hold several v1 documents, e.g. assemblies); an unlinked document or one with no reference text is never paired, so its previous_fnet_id and lag_days are NULL — not 'no predecessor', just not pairable. lag_days is days between deliveries. source_url is FNET's own download link for the id. History starts at SILO's first crawl or backfill, not at FNET's; coverage() reports the fnet_documents span.",
    "FIDC DELINQUENCY STARTS IN 2025-01. CVM's pre-2025 monthly FIDC file (tab II/III) carried no delinquency field, so `delinquency` is null on every fidc row through 2024-12-31 — not zero, not clean books, not a missing month. From 2025-01-31 the tab IV/VI format is ingested and delinquency is filed on every row. Never chain-link, difference or average a FIDC delinquency series across 2024-12 → 2025-01; the series begins there. Machine-readable in `regime_breaks`, and on the funds_fidc coverage row's `notes`.",
    "A FUND'S DEBENTURE HOLDINGS ARE A DIFFERENT SHAPE FROM ITS EQUITY HOLDINGS. api.fund_debentures (CDA block 6) is one row per (fund, month, issuer, maturity, rate structure, application type), as filed and never summed — two series of one issuer maturing the same day at different coupons are different securities. The issuer is its own filed CPF/CNPJ (issuer_id); p_issuer also takes a listed company's ticker or CVM code, resolved only through CVM's published FCA map, and issuer_tickers carries the issuer's active listed codes back (NULL when not listed — most debenture issuers are not). Nothing is matched by name.",
    "ANBIMA CLASS ROWS ARE INDUSTRY AGGREGATES, NOT FUNDS. api.anbima_classes serves the Boletim de Fundos de Investimento as published — R$ milhões (unit brl_mm) and percentage points (unit pct) — per class, ANBIMA type or industry total (`level`; class aggregates by default). No fund in this warehouse is mapped to an ANBIMA class: CVM's `classe` is CVM's taxonomy, so never join a fund to a class by name, and there is no panel arm because these rows carry no id. An unknown category, metric or level raises 22023 listing what exists rather than returning an empty array.",
    "INFLATION IS SERVED AS PUBLISHED, IN PERCENT, WITH ONE DERIVED COLUMN PER FUNCTION. api.inflation is BACEN's SGS, long: value is the change in the month (unit pct_month) except IPCA_12M — BACEN's own 12-month accumulation, code 13522 (pct_12m) — and IPCA_DIFUSAO, the share of items that rose (pct_items). acc_12m is DERIVED: the trailing twelve monthly changes chained, ((Π(1+v/100))−1)×100, NULL unless all twelve months are present and consecutive — never a shorter chain, never filled; it reproduces IPCA_12M exactly for the headline, which is served beside it so you can check. IPCA15 is the mid-month preview, not a revision of IPCA. Group rows (family = group) are VARIATIONS, not contributions: the weights live only in api.inflation_items, whose contribution column is weight × change_month / 100 in percentage points of the headline — sum contributions within ONE level only (a group and its subgroups are the same money twice). BACEN's group codes are NOT in IBGE's order (1640 is Comunicação, 1641 Saúde, 1642 Despesas pessoais, 1643 Educação; measured against IBGE SIDRA, do not reorder by intuition). SIDRA's item codes changed with the 2020-01 structure; item_number is the continuity and sidra_table says which. Neither function has a panel arm — the rows carry no id — and an unknown series, family, level or item raises 22023 rather than returning an empty array.",
    "THE SCREENS ARE SIGNALS, NOT VERDICTS. api.screen_zombie_growth, screen_captive_vehicles, screen_evergreen_aging, screen_overdue_securit, screen_dormant_funds, screen_dormant_trend and screen_delinquency_drivers return the funds or series that crossed a stated threshold in public filings — never a score, a rating, a rank of suspicion or a finding. Every row carries `screen` (which one produced it) and `params` (the exact arguments, keyed by argument name, so the call can be replayed); `screens` in this catalog says what each measures and what else produces the same pattern (an exclusive FII is legal and looks captive; a distressed-credit mandate looks like zombie growth; an extended CRA looks overdue until it is re-filed). Defaults reproduce the dashboard pages (/suspicious, /dormant, /fidc). A threshold out of its range or NULL raises 22023 — it is never clamped, because a screen evaluated at a threshold you did not ask for is a different screen. Confirm any row against the fund's own filings before repeating it.",
    "THE B3 LENDING AND FLOW GROUP IS A RATCHET, AND IT IS THE ONLY PART OF THIS WAREHOUSE THAT IS. short_interest, short_interest_by_sector, lending_trades, lending_participants and investor_flow read B3 tables that B3 keeps for about 21 BUSINESS DAYS and publishes no archive for. History therefore starts at SILO's first capture and cannot be extended backwards at any price — a missed session is gone, not late, and no backfill exists to ask for. coverage() reports the real span per endpoint; read it before describing any of these series as short, broken or anomalous, and never infer a level change from a window that simply begins where capture began. An over-wide request to the source returns HTTP 200 with a silently clamped window, which is why the ingest reconciles what it asked for against what it received.",
    "pct_float IS TWO DIFFERENT METRICS AND float_basis SAYS WHICH ONE YOU HAVE. api.short_interest divides the balance on loan by whichever denominator exists for that ticker. float_basis = 'index_free_float' means B3's published free float (theoretical_qty from the broadest index portfolio carrying the ticker) and exists for index constituents only, ~149 tickers; float_basis = 'shares_outstanding' means capital social from the cash instrument registry, a LARGER denominator that yields a SMALLER percentage for the same position. They are not the same measure and are never comparable: ANY ranking, screen or cross-section on pct_float must filter to ONE basis first, or it sorts index members against non-members on an axis they do not share. float_denominator carries the number actually used. pct_float and days_to_cover are NULL — never 0 — when their denominator is missing or the name did not trade; 0 would sort an unknown to exactly the wrong end.",
    "IN THE LENDING TAPE, doador AND tomador ARE BROKERAGES, NOT BENEFICIAL OWNERS. lending_participants' broker_code / broker_name and lending_trades' lender_brokers / borrower_brokers identify the B3 PARTICIPANT intermediating a trade, never who ends up long or short. B3 names ~33 participants in a whole session, and about three quarters of trades carry the SAME code on both legs (measured 2026-09-10: 32,197 of 43,165, 74.6%) — a broker crossing its own client book. So a large borrow through a broker is its clients' position, not the broker's view, and 'the biggest short' read off this tape is a statement about order flow routing. internal_legs / internal_qty (lending_participants) and internal_trades (lending_trades) are what tell the two apart: high internal share is client churn, low internal share is flow that actually crossed the market. They are published beside the totals rather than netted away, because dropping them makes the remainder look like conviction and keeping them silently makes churn look like demand.",
    "investor_flow IS A FIRST DIFFERENCE, NOT A PUBLISHED DAILY SERIES. B3 publishes investor participation as a MONTH-TO-DATE CUMULATIVE snapshot with a T+2 lag; the daily figures are consecutive snapshots subtracted WITHIN one month, and the difference never reaches across a month boundary (that would report a whole month as one day's flow). flow_basis says which kind of row you have: 'delta' is a real one-session difference, 'month_open' is the month's first session where MTD equals the day, and 'unknown_opening_snapshot' is a row whose predecessor SILO does not hold — those carry NULL flows ON PURPOSE and must never be read, filled or summed as zeros. mtd_buy_value_thousands / mtd_sell_value_thousands carry the cumulative figures as published, so the difference can be checked against the source rather than trusted. Values are R$ thousands. Sum a month only over rows whose flow_basis you have inspected.",
    "LISTED-COMPANY FINANCIALS ARE FILED, NOT DERIVED. api.financials returns one row per account line exactly as the company filed it; nothing is summed, annualised or restated. Read period_months before comparing two rows: an ITR publishes the SAME account twice under one reference date, once for the three months and once year-to-date, and they are distinguished only by the period span. Adding a 3-month row to a 6-month row double-counts the quarter.",
    "FINANCIALS DEFAULT TO CONSOLIDATED (scope=con) AND TO THE PERIOD THE DOCUMENT IS FOR (ordem_exerc ULTIMO). The prior-year comparative printed beside it is never returned. When a company re-files, only the newest version of each statement is served and `version` carries it; in company_financials a balance sheet from a different version than the income statement reads NULL rather than being paired across filings.",
    "CVM'S CHART OF ACCOUNTS IS SECTOR-SPECIFIC, SO `setor` IS A PARTITION KEY, NOT A LABEL. financials and company_financials carry setor and segmento on every row for exactly one reason: the same account code is a different quantity in a different chart. Measured live, 3.01 is `Receita de Venda de Bens e/ou Serviços` for PETR4 and `Receitas de Intermediação Financeira` for Banco do Brasil (cd_cvm 1023), and 3.05 is EBIT for the first and pre-tax profit for the second. So company_financials.revenue and gross_profit are NOT like-for-like across sectors: PARTITION every median, rank, percentile and peer comparison BY setor, and read the as-filed Portuguese account_name rather than assuming a code carries one concept. There is deliberately no canonical English line-item mapping, because keying one on account_code would mislabel at least one sector.",
    "company_financials.net_income IS CONTA 3.11 ONLY, WITH NO FALLBACK. A filing that does not report 3.11 reads NULL. Do not substitute 3.09: it is `Lucro ou Prejuízo antes das Participações e Contribuições Estatutárias`, i.e. profit BEFORE the statutory profit-sharing on 3.10, and it equals net income only where 3.10 is zero. This is measured, not assumed — 282 of 50,439 DRE statements (0.56%) have no 3.11. If you want the pre-participations figure, call api.financials and read 3.09, 3.10 and 3.11 yourself, then do the arithmetic where you can see it. Every value in both functions is in absolute reais: the filed ESCALA_MOEDA is applied at ingest, so never scale by thousands again. api.income_statements DOES resolve those 282, because it keys on the filed LABEL rather than the code and bank B's 3.09 carries the net-income label — prefer it when you want net income to be as complete as the filings allow.",
    "api.income_statements IS KEYED ON THE FILED LABEL, NOT THE ACCOUNT CODE. It returns the income statement as one row per filed period with named fields, and it resolves each field by matching the as-filed Portuguese account_name (case-folded, nothing else folded) rather than by cd_conta. This is measured: CVM ships FOUR DRE charts of accounts and net income sits on 3.11 for the industrial and bank-A charts, on 3.09 for the bank-B chart which files no 3.11, and on 3.13 for the insurer chart whose 3.11 is the continuing-operations line. `chart` tells you which layout a filing used. A concept a chart does not file reads NULL rather than borrowing a neighbouring line: operating_income (EBIT) is an industrial line only, and insurers get NULL operating_expenses because their filed line is the narrower `Despesas Administrativas`. Never read a NULL here as zero. net_income_controlling is the figure per-share numbers are built on, not net_income.",
    "A TICKER RESOLVES TO A COMPANY ONLY THROUGH CVM'S PUBLISHED FCA MAP, active listings only — the CNPJ and the trading code arrive on the same filed row. financials('PETR4'), financials('33000167000101') and financials('9512') are the same company. A delisted code resolves to nothing rather than to a guess, and no company↔ticker edge is ever inferred from a name.",
    "PANEL GRAIN IS (id, asset_class, date, metric), NOT (id, date, metric). A CNPJ can file under two fund families in one month (385 do, fi + fidc), and the panel returns one row per family for it — pivoting on (id, date, metric) then either raises on the duplicate or silently averages two vehicles. Pass p_entity_type (fi|fidc|fii|fip|fiagro) to keep one family, or keep asset_class in your pivot key.",
    "Never invent a price, NAV, or identifier match.",
    "Missing observations stay null; do not ffill or interpolate.",
    "freq=day is quotes only. Mix equity with fund fundamentals on freq=month.",
    "close_return across a missing month is null, not a multi-month return.",
    "close_return is unadjusted: a 2:1 split reports roughly -50%. It is not a total return.",
    "close is the price as published, which for a paper quoted per lot refers to 1000 shares; close_unit divides it by the published quotation_factor so levels are comparable. Neither is corporate-action adjusted — no split, grouping or bonus adjustment exists yet, and `adjusted` is FALSE on every row.",
    "Daily close_return is null when the previous session is more than 7 calendar days back (halts, listing gaps), and null across a quotation-factor change — a fatcot flip rescales the quote with no market move behind it.",
    "Default windows are honest: with no explicit `to`, fund metrics end at each family's latest COMPLETE period (coverage() reports it as complete_through) — a partially-filed trailing month is not served. An explicit `to` serves the window verbatim, partial months included.",
    "Company↔ticker IS joined — via CVM's published FCA valores-mobiliários map only (lookup returns a tickers array on company rows). Nothing is matched by name; a company with no active published listing has tickers null.",
    "Analysis (corr, OLS, copulas, event studies) is a reduction of a panel. Fetch the panel first.",
    "CIA, FII AND FOCUS HELD DATA. api.financial_statement_history returns raw CIA account lines across all stored filing versions for one required statement and company id; `financials` remains latest-version only. Filing header metadata is present only on an exact key match. Values are already scaled at ingest and remain in filed currency. api.fii_property_history filters one exact fund CNPJ and reference-date window; CVM publishes no stable property id, so row_hash identifies a source row, not a durable asset. Nullable measurements remain NULL. api.focus_expectations returns the weekly path across BCB survey dates for one exact endpoint and required forecast horizon, with an optional indicator. The stored key retains each date/horizon; `baseCalculo=0` is the trailing 30-day respondent sample and 12-month inflation is unsmoothed. It is not a vintage archive of corrected old reports, and migration 16-era missing horizons may await re-fetch. All three endpoints refuse above 1,000 rows.",
    "Row caps — all twenty-eight set-returning endpoints in limits.page.all refuse with SQLSTATE 22023 when a query would exceed 1000 rows; the error explains why and how to narrow it. They are panel, quote_history, fund_nav, option_history, termo_history, financials, company_financials, financial_statement_history, income_statements, anbima_classes, inflation, inflation_items, fii_property_history, focus_expectations, fidc_cedentes, fidc_sacados, fidc_portfolio, fidc_tranches, fidc_aging, fund_documents, fund_restatements, and the seven screen_* functions. Three page with p_after: panel, quote_history and fund_nav. For fund_nav, paging also requires p_entity_type because the cursor is only a period. The other twenty-five require narrower windows or filters. For fidc_cedentes, fidc_sacados and fidc_portfolio, use p_limit as an explicit newest-first head when useful; they do not provide a cursor. Screens need higher thresholds or pinned output filters. The former 5001/100001 sentinels are GONE. PostgREST still cuts GET views at 1000 rows and keeps the OLDEST rows; read Content-Range to detect that. RANGE PAGING DOES NOT WORK ON RPC — use p_after only where listed.",
    "An unrecognised metric name is IGNORED, not rejected: the panel comes back smaller and perfectly plausible. Take metric names from this catalog's `metrics` map, never from memory.",
    "Option chains require a codneg prefix of at least 3 characters (api.option_chain); an unfiltered whole-market chain is refused.",
    "CALLER TIERS. Anonymous access is free but deliberately small: panel accepts at most 3 ids per call, search_funds returns at most 25 rows, and option_chain pages at most 200. Signing in (GitHub) raises those to 50 ids, 200 rows and 2000 respectively, and the query timeout from 3s to 8s, and unlocks panel universe mode (p_ids empty + p_entity_type: a whole family, paged with p_after). Exceeding the id ceiling raises SQLSTATE 22023 naming the limit — the panel is never silently truncated to fit.",
    "Signing in does NOT raise rows-per-response: the 1000-row cap is a server-wide PostgREST setting applied identically to every caller. Page views, and narrow the window on functions, whatever tier you are.",
    "Option rows carry underlying_ticker resolved from the PUBLISHED ISIN mapping (an option row's ISIN is its underlying's ISIN), never from the codneg root; it is null when the underlying had no cash print that session. Termo rows still carry no underlying column.",
    "tpmerc 012/013 are option exercise EVENTS served by option_exercises, and 017 auction prints by auctions — neither is a quote series; do not compute returns over them.",
    "fund_quotas rows carry fund_type (etf | fii | fidc | fiagro) from B3's published CODBDI board code, null when the board has no family signal (odd lot). equities rows carry share_class (ON/PN/PNA/PNB/PNC/PND) and governance_segment (NM/N1/N2/MA/M2/MB) parsed from published ESPECI, never from the ticker suffix.",
    "Each cash instrument type has its own endpoint (equities, bdrs, units, fund_quotas, cash_securities) — the same rows as quotes, split by the type derived from published TPMERC/ESPECI. Their grain adds `lot` (standard = tpmerc 010, odd = 020/021); filter lot=eq.standard for round lots. quotes itself stays standard-lot only.",
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
        "fund_documents",
        "fund_restatements",
        "screen_zombie_growth",
        "screen_captive_vehicles",
        "screen_evergreen_aging",
        "screen_overdue_securit",
        "screen_dormant_funds",
        "screen_dormant_trend",
        "screen_delinquency_drivers"
      ],
      "cursor_protocol": "p_after: null = whole result (refused above 1000 rows); '' = first page; the function's key copied from the last row = the next page; a page shorter than 1000 is the last",
      "functions": {
        "paged": {
          "panel": "'<date>|<id>|<metric>|<asset_class>' copied from the last row; order is date, id, metric, asset_class",
          "quote_history": "the last row's trade_date as 'YYYY-MM-DD'; order is trade_date",
          "fund_nav": "the last row's period as 'YYYY-MM-DD'; order is period, entity_type. PAGING REQUIRES p_entity_type — the cursor is a bare period, which is unique only within one family, and 385 CNPJs file under two (fi + fidc) in the same month. Without it you get 22023, not a wrong answer. Whole-result mode needs no p_entity_type and labels every row with its family"
        },
        "raise_only": [
          "option_history",
          "termo_history",
          "financials",
          "company_financials",
          "income_statements",
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
          "fund_documents",
          "fund_restatements",
          "screen_zombie_growth",
          "screen_captive_vehicles",
          "screen_evergreen_aging",
          "screen_overdue_securit",
          "screen_dormant_funds",
          "screen_dormant_trend",
          "screen_delinquency_drivers"
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
        "fund_holdings_rows": 500,
        "fund_debentures_rows": 500,
        "statement_timeout_seconds": 3
      },
      "authenticated": {
        "panel_ids": 50,
        "panel_universe": true,
        "search_funds_rows": 200,
        "option_chain_rows": 2000,
        "option_exercises_rows": 5000,
        "fund_holdings_rows": 5000,
        "fund_debentures_rows": 5000,
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
      "boundary": "2025-01-31",
      "before": "CVM's monthly FIDC file (tab II/III, ingested for 2019-01..2024-12) carries no delinquency field: delinquency is null on every fidc row through 2024-12-31 — not zero, not clean books, not a missing month",
      "after": "from 2025-01-31 the inf_mensal tab IV/VI format is ingested; delinquency is tab VI's total, filed on every row (a fund with no delinquent receivables files 0)",
      "never": "chain-link, difference or average delinquency across 2024-12 → 2025-01, or read a pre-2025 null as zero; a FIDC delinquency series starts at 2025-01"
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
      "then": "Compare performance_realised with performance_expected per classe_serie in the notebook; both are as filed and can carry CVM's outliers. History starts 2025-01 — there is no earlier tranche data anywhere. Read the aging ladder under it with fidc_aging; overdue_total is CVM's filed total, not a sum."
    },
    {
      "ask": "Which FIDCs restated a filing this month, and how late?",
      "call": "POST /rest/v1/rpc/fund_restatements {\"p_tipo_fundo\": \"FIDC\", \"p_from\": \"<month start>\"}",
      "then": "Each row is a re-filed document (versao > 1; modalidade RE is voluntary, RC was required by CVM) with lag_days since the version it replaced. The pairing is by a stated group key because FNET links no versions; cnpj NULL means the fortnightly fund sweep has not linked it yet — never match it to a fund by fund_name. Open the versions with fund_documents' source_url."
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
    "termo"
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
    "fidc_tranches": "POST /rest/v1/rpc/fidc_tranches",
    "fidc_aging": "POST /rest/v1/rpc/fidc_aging",
    "fund_documents": "POST /rest/v1/rpc/fund_documents",
    "fund_restatements": "POST /rest/v1/rpc/fund_restatements",
    "short_interest": "GET /rest/v1/short_interest",
    "short_interest_by_sector": "GET /rest/v1/short_interest_by_sector",
    "lending_trades": "GET /rest/v1/lending_trades",
    "lending_participants": "GET /rest/v1/lending_participants",
    "investor_flow": "GET /rest/v1/investor_flow"
  }
}$json$::jsonb;
$fn$;

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
-- separate, owner-made decision (documented in docs/API.md when taken).

GRANT USAGE ON SCHEMA api TO silo_api;

GRANT SELECT ON api.quotes, api.funds TO silo_api;
GRANT SELECT ON api.equities, api.bdrs, api.units,
                api.fund_quotas, api.cash_securities TO silo_api;
GRANT SELECT ON api.auctions TO silo_api;

GRANT EXECUTE ON FUNCTION api.quote_history(TEXT, DATE, DATE, TEXT, TEXT) TO silo_api;
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
GRANT EXECUTE ON FUNCTION api.financials(TEXT, TEXT, DATE, DATE, TEXT, TEXT) TO silo_api;
GRANT EXECUTE ON FUNCTION api.company_financials(TEXT, DATE, DATE, TEXT) TO silo_api;
GRANT EXECUTE ON FUNCTION api.income_statements(TEXT, DATE, DATE, TEXT, TEXT) TO silo_api;
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
