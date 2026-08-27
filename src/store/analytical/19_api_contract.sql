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
-- Row caps (SERVING.md Step 3, SQL half). serve/app.py rejects oversized
-- results with HTTP 400 when a series exceeds _MAX_POINTS (5000) or a panel
-- exceeds _MAX_PANEL (100000). Each set-returning series/panel function below
-- therefore LIMITs at cap + 1 (5001 / 100001):
--   * Postgres stops materializing just past the boundary instead of building
--     and shipping an unbounded body for Python to fetchall() and discard;
--   * the adapter can still tell "too large" (cap+1 rows -> 400) apart from
--     "complete" (<= cap rows). A LIMIT at exactly the cap would make the
--     oversized case indistinguishable and silently hand back a truncated —
--     i.e. fabricated — panel, which integrity rule 1 forbids.
-- Keep 5001/100001 in lockstep with serve/app.py _MAX_POINTS/_MAX_PANEL.
-- option_chain is page-shaped, not series-shaped: its own clamp (1..2000) is
-- documented at the function. Discovery functions are already bounded:
-- universe <= 500, lookup <= 20, search_funds <= 200, quote_latest = 1,
-- coverage = 4 rows.
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
    v.instrument_type   AS asset_class
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

DROP FUNCTION IF EXISTS api.quote_history(TEXT, DATE, DATE, TEXT);
CREATE OR REPLACE FUNCTION api.quote_history(
    p_ticker TEXT,
    p_from   DATE DEFAULT (CURRENT_DATE - 365),
    p_to     DATE DEFAULT CURRENT_DATE,
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
    WITH selected_board AS (
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
    )
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
      AND q.trade_date BETWEEN p_from AND p_to
      AND q.board = (SELECT board FROM selected_board)
    ORDER BY q.trade_date
    -- Cap = serve _MAX_POINTS (5000) + 1. 5000 daily prints ~ 20 years of one
    -- ticker's sessions; the +1 row lets serve/ return 400 instead of a
    -- silently truncated series (see header). Deterministic: oldest kept.
    LIMIT 5001;
$$;

COMMENT ON FUNCTION api.quote_history(TEXT, DATE, DATE, TEXT) IS
    'Daily unadjusted quote series for one ticker. Hard-capped at 5001 rows (= serve _MAX_POINTS + 1): above 5000 the adapter answers 400, never a truncated series.';

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

REVOKE ALL ON FUNCTION api.quote_history(TEXT, DATE, DATE, TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION api.quote_latest(TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.quote_history(TEXT, DATE, DATE, TEXT) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION api.quote_latest(TEXT, TEXT) TO anon, authenticated;

-- ---------------------------------------------------------------------------
-- Options & termo (B3 COTAHIST derivative segments; INSTRUMENTS.md Phase A)
-- ---------------------------------------------------------------------------
-- Same landing rows as the cash tape, different tpmerc: calls '070', puts
-- '080', termo '030'. side is derived ONLY from tpmerc — a published B3 code,
-- not a guess. Deliberately absent: an `underlying` column. The codneg root
-- usually names the underlying, but that is a naming convention, not a
-- published mapping; deriving it would synthesize an identity join (integrity
-- rule 3, same reason ticker↔CNPJ stays unjoined). Callers filter by prefix
-- and own that inference.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION api.option_chain(
    p_prefix      TEXT,
    p_expiry_from DATE DEFAULT CURRENT_DATE,
    p_trade_date  DATE DEFAULT NULL,
    p_limit       INT  DEFAULT 500
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
    spec       TEXT
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
        b.especi
    FROM public.b3_cotahist b
    WHERE b.tpmerc IN ('070', '080')
      AND b.trade_date = v_trade_date
      AND b.codneg LIKE v_prefix || '%'
      AND (p_expiry_from IS NULL OR b.data_vencimento >= p_expiry_from)
    ORDER BY b.data_vencimento, b.preco_exercicio, b.tpmerc, b.codneg
    -- Clamp 1..2000. This is a chain-page cap, not the 5001 series cap: one
    -- underlying's chain on one session is hundreds of series (strike ×
    -- expiry × side), so 2000 comfortably holds any honest single-prefix
    -- chain while an over-broad prefix is cut deterministically (ORDER BY
    -- expiry, strike, side, codneg) at a bounded page.
    LIMIT LEAST(GREATEST(COALESCE(p_limit, 500), 1), 2000);
END;
$$;

COMMENT ON FUNCTION api.option_chain(TEXT, DATE, DATE, INT) IS
    'One session''s option chain for a REQUIRED codneg prefix (>= 3 chars; else it raises). side = call/put from tpmerc 070/080. p_trade_date NULL = latest option-segment session. No underlying column: the codneg root is a naming convention, not a published mapping. Rows clamped to 1..2000.';

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
    source            TEXT
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
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
        b.source
    FROM public.b3_cotahist b
    WHERE b.tpmerc IN ('070', '080')
      AND b.codneg = upper(btrim(p_codneg))
      AND b.trade_date BETWEEN p_from AND p_to
    ORDER BY b.trade_date
    -- Cap = serve _MAX_POINTS (5000) + 1, in lockstep with quote_history: the
    -- +1 row lets an adapter tell "too large" from "complete" instead of
    -- silently truncating. An option series is short-lived (months), so 5000
    -- is a pure backstop. Deterministic: oldest kept.
    LIMIT 5001;
$$;

COMMENT ON FUNCTION api.option_history(TEXT, DATE, DATE) IS
    'Daily unadjusted series for one option codneg (tpmerc 070/080), quote_history''s shape plus side/strike/expiry. Hard-capped at 5001 rows (= serve _MAX_POINTS + 1).';

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
    -- Cap = serve _MAX_POINTS (5000) + 1, same lockstep as quote_history.
    LIMIT 5001;
$$;

COMMENT ON FUNCTION api.termo_history(TEXT, DATE, DATE) IS
    'Daily unadjusted series for one termo codneg (tpmerc 030), including term_days (prazot). Grain is (codneg, trade_date, term_days). Hard-capped at 5001 rows (= serve _MAX_POINTS + 1).';

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

CREATE OR REPLACE FUNCTION api.fund_nav(
    p_cnpj        TEXT,
    p_from        DATE DEFAULT '2019-01-01',
    p_to          DATE DEFAULT CURRENT_DATE,
    p_entity_type TEXT DEFAULT NULL
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
    assets        NUMERIC
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
    SELECT
        cnpj,
        period,
        entity_type,
        vl_patrim_liq,
        vl_quota,
        nr_cotst,
        vl_inadimpl,
        pct_yield_mes,
        captc_mes,
        resg_mes,
        vl_ativo
    FROM public.fund_nav_series(
        regexp_replace(p_cnpj, '[^0-9]', '', 'g'),
        p_from,
        p_to,
        p_entity_type
    )
    -- Cap = serve _MAX_POINTS (5000) + 1. Monthly grain: one CNPJ has ~12
    -- rows/year/entity_type, so 5000 is far beyond any honest series — this is
    -- a backstop, and the +1 row lets serve/ 400 instead of truncating.
    -- ORDER BY (period, entity_type) positionally so truncation is
    -- deterministic and dodges OUT-parameter name ambiguity.
    ORDER BY 2, 3
    LIMIT 5001;
$$;

COMMENT ON FUNCTION api.fund_nav(TEXT, DATE, DATE, TEXT) IS
    'Monthly NAV/flows series for one CNPJ. Hard-capped at 5001 rows (= serve _MAX_POINTS + 1): above 5000 the adapter answers 400, never a truncated series.';

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
        LEAST(GREATEST(COALESCE(p_limit, 50), 1), 200)
    );
$$;

REVOKE ALL ON FUNCTION api.fund_profile(TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION api.fund_nav(TEXT, DATE, DATE, TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION api.search_funds(TEXT, TEXT, INT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.fund_profile(TEXT) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION api.fund_nav(TEXT, DATE, DATE, TEXT) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION api.search_funds(TEXT, TEXT, INT) TO anon, authenticated;

-- ---------------------------------------------------------------------------
-- Coverage — freshness without exposing cvm_ingest_log
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION api.coverage()
RETURNS TABLE (
    dataset     TEXT,
    as_of       DATE,
    source      TEXT
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    SELECT 'quotes'::text, MAX(trade_date), 'b3_cotahist'::text
    FROM public.vw_b3_quote_vista
    UNION ALL
    SELECT 'funds'::text, MAX(last_period), 'cvm'::text
    FROM public.dim_fund
    UNION ALL
    SELECT 'fund_nav'::text, MAX(period), 'cvm'::text
    FROM public.fact_fund_monthly
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
           'b3_cotahist'::text;
$$;

REVOKE ALL ON FUNCTION api.coverage() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.coverage() TO anon, authenticated;

-- ---------------------------------------------------------------------------
-- Research panel — long observations a researcher can correlate / factor
-- ---------------------------------------------------------------------------
-- One row = (id, date, metric, value). Mix tickers (B3 last session in the
-- month) with fund CNPJs (CVM monthly). Missing months stay absent — no ffill,
-- no interpolated return across a gap. freq=day is quotes only.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION api.panel(
    p_ids     TEXT[],
    p_metrics TEXT[] DEFAULT ARRAY['close', 'nav']::TEXT[],
    p_from    DATE   DEFAULT (CURRENT_DATE - 365),
    p_to      DATE   DEFAULT CURRENT_DATE,
    p_freq    TEXT   DEFAULT 'month'
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
        ARRAY(
            SELECT upper(btrim(x))
            FROM unnest(COALESCE(p_ids, ARRAY[]::TEXT[])) AS x
            WHERE btrim(x) <> ''
        ) AS ids,
        ARRAY(
            SELECT lower(btrim(x))
            FROM unnest(COALESCE(p_metrics, ARRAY['close','nav']::TEXT[])) AS x
            WHERE btrim(x) <> ''
        ) AS metrics,
        CASE WHEN lower(COALESCE(p_freq, 'month')) IN ('day', 'd', 'daily') THEN 'day' ELSE 'month' END AS freq,
        p_from AS d0,
        p_to   AS d1
),
tickers AS (
    SELECT x AS ticker
    FROM params p, unnest(p.ids) AS x
    WHERE length(regexp_replace(x, '[^0-9]', '', 'g')) <> 14
),
cnpjs AS (
    SELECT regexp_replace(x, '[^0-9]', '', 'g') AS cnpj
    FROM params p, unnest(p.ids) AS x
    WHERE length(regexp_replace(x, '[^0-9]', '', 'g')) = 14
),
-- Last session in each month (real print, not a made-up month-end).
quote_month AS (
    SELECT DISTINCT ON (q.ticker, date_trunc('month', q.trade_date))
        q.ticker,
        date_trunc('month', q.trade_date)::date AS period,
        q.close,
        q.volume,
        q.asset_class
    FROM api.quotes q
    JOIN params p ON TRUE
    WHERE p.freq = 'month'
      AND q.trade_date BETWEEN p.d0 AND p.d1
      AND q.ticker IN (SELECT ticker FROM tickers)
    ORDER BY q.ticker, date_trunc('month', q.trade_date), q.trade_date DESC, q.board
),
quote_day AS (
    SELECT DISTINCT ON (q.ticker, q.trade_date)
        q.ticker, q.trade_date AS period, q.close, q.volume, q.asset_class
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
quote_ret AS (
    SELECT
        ticker,
        period,
        asset_class,
        CASE
            WHEN (SELECT freq FROM params) = 'day'
            THEN close / NULLIF(lag(close) OVER w, 0) - 1
            WHEN lag(period) OVER w = (period - INTERVAL '1 month')::date
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
fund_rows AS (
    SELECT
        f.cnpj,
        f.entity_type,
        f.period,
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
      AND f.period BETWEEN date_trunc('month', p.d0)::date AND p.d1
      AND f.cnpj IN (SELECT cnpj FROM cnpjs)
)
SELECT q.ticker, 'ticker'::text, q.asset_class, q.period, 'close'::text, q.close, 'b3_cotahist'::text
FROM quote_px q JOIN params p ON TRUE
WHERE 'close' = ANY (p.metrics)
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
ORDER BY 4, 1, 5
-- Cap = serve _MAX_PANEL (100000) + 1. Generosity: the Step 3 envelope
-- (50 ids x ~7 applicable metrics x 20 years monthly ~ 84k rows) fits; an
-- unbounded ask (e.g. freq=day over decades) stops materializing here instead
-- of being built, shipped, fetchall()'d and then rejected. The +1 row lets
-- serve/ answer 400 "panel too large" — never a silently truncated (i.e.
-- fabricated) panel. ORDER BY (date, id, metric) makes the cut deterministic.
LIMIT 100001;
$$;

COMMENT ON FUNCTION api.panel(TEXT[], TEXT[], DATE, DATE, TEXT) IS
    'Long panel for correlation/factor work. Mix tickers, option/termo codnegs, + CNPJs. No ffill. close_return is p_t/p_{t-1}-1 from unadjusted closes (a split appears as a jump), cash tickers only, and is null across calendar gaps. Hard-capped at 100001 rows (= serve _MAX_PANEL + 1): above 100000 the adapter answers 400, never a truncated panel.';

REVOKE ALL ON FUNCTION api.panel(TEXT[], TEXT[], DATE, DATE, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.panel(TEXT[], TEXT[], DATE, DATE, TEXT) TO anon, authenticated;

CREATE OR REPLACE FUNCTION api.universe(
    p_asset_class TEXT DEFAULT NULL,
    p_limit       INT  DEFAULT 50
)
RETURNS TABLE (
    id          TEXT,
    id_type     TEXT,
    asset_class TEXT,
    name        TEXT,
    isin        TEXT
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    WITH latest_quote_session AS (
        -- Universe is discovery, not historical coverage. Restrict B3 to one
        -- real session so a sparse type such as BDR does not classify and sort
        -- the entire multi-year COTAHIST tape under the 15s API timeout.
        SELECT max(q.trade_date) AS trade_date
        FROM api.quotes q
    ),
    quote_rows AS (
        SELECT DISTINCT ON (q.ticker)
            q.ticker, q.asset_class, q.short_name, q.isin
        FROM api.quotes q
        JOIN latest_quote_session s ON s.trade_date = q.trade_date
        WHERE p_asset_class IS NULL OR q.asset_class = lower(p_asset_class)
        ORDER BY q.ticker
    )
    SELECT * FROM (
        SELECT q.ticker, 'ticker'::text, q.asset_class, q.short_name, q.isin
        FROM quote_rows q
        UNION ALL
        SELECT d.cnpj, 'cnpj', d.entity_type, d.fund_name, NULL
        FROM public.dim_fund d
        WHERE p_asset_class IS NULL OR d.entity_type = p_asset_class
        UNION ALL
        -- Derivatives list ONLY on explicit request (p_asset_class 'option' /
        -- 'termo'), never in the NULL default: the option namespace is ~10x
        -- the cash tape per session and would drown the default universe.
        --
        -- Scoped to the segment's LATEST session, which is both the honest
        -- answer ("which series are listed now" — option series expire, so a
        -- whole-history list is mostly dead contracts) and the only affordable
        -- one: aggregating every option row ever landed is a seq scan over
        -- ~89% of b3_cotahist, and a full-table GROUP BY on this table already
        -- times out in production. Measured on a 2M-row stand-in: 34k buffers
        -- -> 5k, and it stays flat as history grows. GREATEST-of-equality-maxes
        -- rather than an IN-list max for the same reason as api.option_chain.
        SELECT b.codneg, 'option', 'derivative', max(b.nome_resumido), max(b.isin)
        FROM public.b3_cotahist b
        WHERE p_asset_class = 'option'
          AND b.tpmerc IN ('070', '080')
          AND b.trade_date = GREATEST(
              (SELECT max(x.trade_date) FROM public.b3_cotahist x WHERE x.tpmerc = '070'),
              (SELECT max(x.trade_date) FROM public.b3_cotahist x WHERE x.tpmerc = '080')
          )
        GROUP BY b.codneg
        UNION ALL
        SELECT b.codneg, 'termo', 'derivative', max(b.nome_resumido), max(b.isin)
        FROM public.b3_cotahist b
        WHERE p_asset_class = 'termo'
          AND b.tpmerc = '030'
          AND b.trade_date = (SELECT max(x.trade_date)
                              FROM public.b3_cotahist x WHERE x.tpmerc = '030')
        GROUP BY b.codneg
    ) u
    -- id (col 1) tiebreak: option/termo names repeat across a whole root, so
    -- without it the 500-row cut would be nondeterministic.
    ORDER BY 3, 4 NULLS LAST, 1
    LIMIT LEAST(GREATEST(COALESCE(p_limit, 50), 1), 500);
$$;

COMMENT ON FUNCTION api.universe(TEXT, INT) IS
    'List identifiers by asset_class (NULL = equities + funds). asset_class option/termo lists the derivative codnegs that printed on that segment''s most recent session — currently-listed series, not every series ever listed. Rows clamped to 1..500.';

REVOKE ALL ON FUNCTION api.universe(TEXT, INT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.universe(TEXT, INT) TO anon, authenticated;

CREATE OR REPLACE FUNCTION api.lookup(
    p_query TEXT
)
RETURNS TABLE (
    id          TEXT,
    id_type     TEXT,
    asset_class TEXT,
    name        TEXT,
    isin        TEXT,
    cnpj        TEXT
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    SELECT q.ticker, 'ticker'::text, q.asset_class, q.short_name, q.isin, NULL::text
    FROM (
        SELECT DISTINCT ON (ticker)
            ticker, asset_class, short_name, isin
        FROM api.quotes
        WHERE (
            ticker = upper(btrim(p_query))
            OR isin = upper(btrim(p_query))
          )
        ORDER BY ticker, trade_date DESC
    ) q
    UNION ALL
    SELECT d.cnpj, 'cnpj', d.entity_type, d.fund_name, NULL, d.cnpj
    FROM public.dim_fund d
    WHERE d.cnpj = regexp_replace(p_query, '[^0-9]', '', 'g')
       OR d.fund_name ILIKE '%' || p_query || '%'
    UNION ALL
    SELECT c.cd_cvm, 'cd_cvm', 'cia', c.denom_cia, NULL, c.cnpj_cia
    FROM public.cia_company c
    WHERE c.cnpj_cia = regexp_replace(p_query, '[^0-9]', '', 'g')
       OR c.cd_cvm = btrim(p_query)
       OR c.denom_cia ILIKE '%' || p_query || '%'
    LIMIT 20;
$$;

-- Option/termo codnegs are deliberately NOT resolved here: lookup is a
-- name-resolution surface and option series have no names — only the codneg
-- itself, which the caller already holds. Adding a ~100k-id derivative
-- namespace to a name resolver would bloat every query for zero resolution
-- power. Discover derivative ids via api.universe('option'|'termo') or
-- api.option_chain(prefix).
COMMENT ON FUNCTION api.lookup(TEXT) IS
    'Resolve ticker / ISIN / CNPJ / company name. Does not invent ticker↔CNPJ matches. Does not resolve option/termo codnegs (no names to resolve — use universe or option_chain).';

REVOKE ALL ON FUNCTION api.lookup(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.lookup(TEXT) TO anon, authenticated;

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
SELECT $json$
{
  "kind": "catalog",
  "version": 5,
  "primitive": "panel",
  "agent": "You are querying Silo, a Brazilian public-markets warehouse (CVM funds, B3 COTAHIST cash quotes, options and termo). Call catalog once and cache it. Resolve names with lookup/universe, then GET /v1/panel. The primitive is a panel (id, date, metric, value). Correlation, ranking, spreads, regressions, and other relations are reductions of that panel — compute them in the notebook. Do not fabricate ids, fills, or ticker-CNPJ matches.",
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
    "close_return": {
      "id_type": [
        "ticker"
      ],
      "asset_class": [
        "equity",
        "unit",
        "bdr",
        "fund_quota",
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
      "meaning": "Fund net assets (vl_patrim_liq)."
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
      "meaning": "FI unit quota. Comparable subclass only."
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
      "meaning": "Delinquent portfolio value (not a rate unless you divide by nav)."
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
      "meaning": "Monthly yield % as published (FII complemento)."
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
      "meaning": "Gross monthly subscriptions."
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
      "meaning": "Gross monthly redemptions."
    },
    "quotaholders": {
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
      "meaning": "Number of unit-holders."
    }
  },
  "notebook_reducers": {
    "describe": "Per-column n, null_rate, min, max, last. No model.",
    "corr": "Pairwise Pearson on complete pairs of the wide matrix. One relation among many.",
    "rank": "Latest non-null value per id for the first metric, descending.",
    "spread": "First column minus second column of the wide matrix, dates aligned."
  },
  "constraints": [
    "Never invent a price, NAV, or identifier match.",
    "Missing observations stay null; do not ffill or interpolate.",
    "freq=day is quotes only. Mix equity with fund fundamentals on freq=month.",
    "close_return across a missing month is null, not a multi-month return.",
    "close_return is unadjusted: a 2:1 split reports roughly -50%. It is not a total return.",
    "Ticker↔cia_company is not joined here; lookup returns them separately.",
    "Analysis (corr, OLS, copulas, event studies) is a reduction of a panel. Fetch the panel first.",
    "Panel responses are hard-capped at 100000 rows (series endpoints at 5000); above that the API answers 400 — narrow ids, metrics, or the date window.",
    "Option chains require a codneg prefix of at least 3 characters (api.option_chain); an unfiltered whole-market chain is refused.",
    "Options and termo carry no underlying column: the codneg root is a naming convention, not a published B3 mapping. Prefix filtering is the caller's own inference.",
    "Option/termo codnegs resolve via universe(asset_class=option|termo) or option_chain, not lookup — option series have no names to resolve.",
    "universe(asset_class=option|termo) lists the codnegs that printed on that segment's most recent session — currently-listed series, not every series ever listed. Expired series stay queryable by codneg in option_history."
  ],
  "examples": [
    {
      "ask": "How does PETR4 relate to delinquency in this FIDC?",
      "call": "GET /v1/panel?ids=PETR4,<cnpj>&metrics=close_return,delinquency&freq=month&format=wide",
      "then": "Pairwise-complete correlation in the notebook. Do not ffill."
    },
    {
      "ask": "Rank these funds by latest NAV",
      "call": "GET /v1/panel?ids=<cnpj>,<cnpj>&metrics=nav&freq=month&format=wide",
      "then": "Take the last non-null NAV per id from the wide matrix."
    },
    {
      "ask": "Did inflows and quota move together for this FI?",
      "call": "GET /v1/panel?ids=<cnpj>&metrics=inflows,quota&freq=month&format=wide",
      "then": "Correlate the two columns; nulls stay null."
    },
    {
      "ask": "Spread of two equity closes at month end",
      "call": "GET /v1/panel?ids=PETR4,VALE3&metrics=close&freq=month&format=wide",
      "then": "Subtract aligned columns; a missing month is null, not interpolated."
    },
    {
      "ask": "Just give me the panel; I will run a factor model",
      "call": "GET /v1/panel?ids=PETR4,VALE3,<cnpj>&metrics=close_return,nav&freq=month&format=wide",
      "then": "Model in the notebook from the matrix."
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
    "universe": "GET /v1/universe?asset_class=",
    "quotes": "GET /v1/quotes/{ticker}",
    "funds": "GET /v1/funds/{cnpj}/nav",
    "coverage": "GET /v1/coverage"
  }
}
$json$::jsonb;
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
-- the two views, EXECUTE on the thirteen functions. It deliberately receives no
-- grant in schema public — the DEFINER functions and owner-privileged views
-- above are the only path from silo_api to the data. serve/-only works with
-- exactly this; exposing schema api on the Supabase Data API would be a
-- separate, owner-made decision (documented in docs/API.md when taken).

GRANT USAGE ON SCHEMA api TO silo_api;

GRANT SELECT ON api.quotes, api.funds TO silo_api;

GRANT EXECUTE ON FUNCTION api.quote_history(TEXT, DATE, DATE, TEXT)   TO silo_api;
GRANT EXECUTE ON FUNCTION api.quote_latest(TEXT, TEXT)                TO silo_api;
GRANT EXECUTE ON FUNCTION api.option_chain(TEXT, DATE, DATE, INT)     TO silo_api;
GRANT EXECUTE ON FUNCTION api.option_history(TEXT, DATE, DATE)        TO silo_api;
GRANT EXECUTE ON FUNCTION api.termo_history(TEXT, DATE, DATE)         TO silo_api;
GRANT EXECUTE ON FUNCTION api.fund_profile(TEXT)                      TO silo_api;
GRANT EXECUTE ON FUNCTION api.fund_nav(TEXT, DATE, DATE, TEXT)        TO silo_api;
GRANT EXECUTE ON FUNCTION api.search_funds(TEXT, TEXT, INT)           TO silo_api;
GRANT EXECUTE ON FUNCTION api.coverage()                              TO silo_api;
GRANT EXECUTE ON FUNCTION api.panel(TEXT[], TEXT[], DATE, DATE, TEXT) TO silo_api;
GRANT EXECUTE ON FUNCTION api.universe(TEXT, INT)                     TO silo_api;
GRANT EXECUTE ON FUNCTION api.lookup(TEXT)                            TO silo_api;
GRANT EXECUTE ON FUNCTION api.catalog()                               TO silo_api;

-- Defensive, idempotent no-ops today (silo_api is never directly granted
-- anything in public): strip any direct grant a future change might add by
-- accident, so an apply restores the boundary on every run.
REVOKE ALL ON ALL TABLES    IN SCHEMA public FROM silo_api;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM silo_api;
REVOKE CREATE ON SCHEMA public FROM silo_api;

COMMIT;

