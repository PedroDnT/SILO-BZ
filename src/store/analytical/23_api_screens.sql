-- =============================================================================
-- 23_api_screens.sql
-- The forensic screens, served through schema `api` (COMPETITIVE_GAPS.md §7 B3).
--
-- Until this file the screens in 15_fraud_screens.sql were dashboard-only:
-- /suspicious, /dormant and /fidc read them at build time, and a caller of the
-- API could not reach them at all. They are signals, not verdicts, and this
-- file serves them as exactly that:
--
--   api.screen_zombie_growth         ← fraud_screen_zombie_growth      (FIDC)
--   api.screen_captive_vehicles      ← fraud_screen_captive_vehicles   (FII)
--   api.screen_evergreen_aging       ← fraud_screen_evergreen_aging    (FIDC)
--   api.screen_overdue_securit       ← fraud_screen_overdue_securit    (CRI/CRA)
--   api.screen_dormant_funds         ← fraud_screen_dormant_funds      (FI)
--   api.screen_dormant_trend         ← fraud_screen_dormant_trend      (FI)
--   api.screen_delinquency_drivers   ← fidc_delinquency_drivers        (FIDC)
--
-- ONE DEFINITION. Every wrapper calls the public function the dashboard calls;
-- nothing here restates a screen's logic. A threshold changed in 15 changes
-- the dashboard and the API together, which is the whole reason 15 exists.
--
-- SHAPE: one function per screen, not one api.screens(p_name, ...). Checked
-- against 19_api_contract.sql's conventions:
--   * every api function returns a TYPED table the OpenAPI spec renders column
--     by column (scripts/gen_openapi.py reads pg_get_function_result). The
--     seven screens have seven different row shapes — a fund list, a series
--     list, a month-by-month count — so a single dispatcher would have to
--     return jsonb or a lowest-common-denominator long form, and the spec
--     would stop describing what a caller gets back;
--   * each screen's thresholds are DIFFERENT arguments with different units
--     (a percent, a BRL floor, a month count); per-function signatures keep
--     them named and defaulted in the spec instead of an untyped bag;
--   * the house precedent for "several related shapes" is fidc_cedentes /
--     fidc_sacados / fidc_portfolio — separate functions, one per shape — and
--     fidc_portfolio's long form is used only where the shapes really are one.
--   The neutral `screen_` prefix replaces `fraud_screen_`: the API publishes a
--   signal, and a function name is not the place to allege fraud.
--
-- SIGNALS, NOT VERDICTS. Every row carries `screen` (which screen produced it)
-- and `params` (the arguments it was evaluated with, as jsonb keyed by the
-- argument names, so the call can be replayed exactly). A row is a fund or a
-- series that crossed the stated thresholds — never a score, a rating, a rank
-- of suspicion, or a finding. What each screen measures, and what else can
-- produce the same pattern, is `screens.<name>.meaning` in api.catalog()
-- (serve/catalog.py SCREENS); the COMMENT on each function says it too.
--
-- COLUMNS are English, per SERVING.md ("do not expose Portuguese landing
-- columns"). The mapping from the public function's column names is written
-- beside each wrapper. Values are passed through untouched — a filed status
-- such as `situacao` is served AS FILED in Portuguese, because translating a
-- source's own label would be inventing one.
--
-- ARGUMENTS default to exactly what the dashboard passes (dashboard/pages/
-- suspicious.md, dormant.md, fidc.md; dashboard/sources/supabase/*.sql), so a
-- call with no arguments reproduces the page. Each argument is bounded; an
-- out-of-range or NULL threshold RAISES 22023 naming the range — it is never
-- clamped, because a screen evaluated at a threshold you did not ask for is a
-- different screen with your label on it.
--
-- ROW CAP. The api.assert_row_cap pattern from 19: fetch one page plus one row
-- (LIMIT 1001) and REFUSE with 22023 above 1000, never trim. No cursor — a
-- screen is a short list or it is the wrong screen. The two screens that can
-- exceed a page with their dashboard defaults take OUTPUT filters to narrow
-- with, and those filters are echoed in `params` like the thresholds:
--   screen_dormant_funds        p_dormancy (empty_shell | parked_capital),
--                               p_min_nav  — parked_capital alone was 8,257
--                               classes in the 2026-09-02 health diagnostic;
--   screen_delinquency_drivers  p_driver (one of the five classes) — every
--                               FIDC with ≥ p_min_months observations gets a
--                               row, 'stable' included.
-- Not tiered: no screen has a per-caller row ceiling to clamp (the page is the
-- ceiling, identically for every tier). The binding runtime limit is the
-- role's statement_timeout — 3s anonymous, 8s signed in (19's header).
--
-- PRIVILEGES. Same model as 19: SECURITY DEFINER with an empty pinned
-- search_path, every reference schema-qualified. The public screens are
-- SECURITY INVOKER; called from here they run as the owner, so the caller
-- needs no grant on public — and since this file, holds none (see
-- 15_fraud_screens.sql: the old GRANT EXECUTE ... TO anon, authenticated on
-- the public screens became REVOKE, closing DATA_INVENTORY.md §3's
-- defence-in-depth gap). The public screens pin search_path = public, pg_temp
-- themselves (15), because the empty search_path of a DEFINER caller
-- propagates down the call stack — the same reason latest_complete_period()
-- pins its own (04).
-- silo_api gets no grant: serve/app.py has no /v1 route for the screens, the
-- same decision 20/21 took for the lending views. PostgREST's anon /
-- authenticated grants below are the published surface.
--
-- Ordering: after 15 (the screens) and 19 (api.assert_row_cap). The guard
-- below fails the apply loudly if either is missing.
-- =============================================================================

BEGIN;
-- Apply-time guard for this DDL transaction only (the runtime timeout is the
-- calling role's, as in 19).
SET statement_timeout = '30s';

DO $guard$
BEGIN
    IF to_regprocedure('api.assert_row_cap(bigint, boolean, text)') IS NULL THEN
        RAISE EXCEPTION '23_api_screens.sql needs api.assert_row_cap from 19_api_contract.sql; apply 19 first';
    END IF;
    IF to_regprocedure('public.fraud_screen_zombie_growth(date, numeric, numeric)') IS NULL
       OR to_regprocedure('public.fidc_delinquency_drivers(date, integer, integer, numeric, numeric)') IS NULL THEN
        RAISE EXCEPTION '23_api_screens.sql wraps the screens in 15_fraud_screens.sql; apply 15 first';
    END IF;
END
$guard$;

-- ---------------------------------------------------------------------------
-- Zombie growth (FIDC) — delinquency above p_min_delinq_pct of NAV while NAV
-- stays above p_min_aum. Dashboard: fraud_screen_zombie_growth(null, 5, 1e6).
-- pl_mm → nav_mm, inad_pct → delinquency_pct.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION api.screen_zombie_growth(
    p_period         DATE    DEFAULT NULL,   -- aging month; NULL = the latest aging period
    p_min_delinq_pct NUMERIC DEFAULT 5,      -- delinquency floor, percent of NAV, 0..100
    p_min_aum        NUMERIC DEFAULT 1000000 -- NAV floor, BRL, >= 0
)
RETURNS TABLE (
    cnpj            TEXT,
    fund_name       TEXT,
    period          DATE,
    nav_mm          NUMERIC,
    delinquency_pct NUMERIC,
    screen          TEXT,
    params          JSONB
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $fn$
#variable_conflict use_column
BEGIN
    IF p_min_delinq_pct IS NULL OR p_min_delinq_pct < 0 OR p_min_delinq_pct > 100 THEN
        RAISE EXCEPTION 'screen_zombie_growth: p_min_delinq_pct must be between 0 and 100 (percent of NAV), got %', p_min_delinq_pct
            USING ERRCODE = '22023';
    END IF;
    IF p_min_aum IS NULL OR p_min_aum < 0 THEN
        RAISE EXCEPTION 'screen_zombie_growth: p_min_aum must be a BRL amount >= 0, got %', p_min_aum
            USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    WITH page AS (
        SELECT z.cnpj, z.fund_name, z.period, z.pl_mm, z.inad_pct
        FROM public.fraud_screen_zombie_growth(p_period, p_min_delinq_pct, p_min_aum) z
        ORDER BY z.pl_mm DESC NULLS LAST, z.cnpj
        LIMIT 1001
    )
    SELECT g.cnpj, g.fund_name, g.period, g.pl_mm, g.inad_pct,
           'zombie_growth'::text,
           jsonb_build_object('p_period', p_period,
                              'p_min_delinq_pct', p_min_delinq_pct,
                              'p_min_aum', p_min_aum)
    FROM page g
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'screen_zombie_growth')
    ORDER BY g.pl_mm DESC NULLS LAST, g.cnpj
    LIMIT 1000;
END;
$fn$;

COMMENT ON FUNCTION api.screen_zombie_growth(DATE, NUMERIC, NUMERIC) IS
    'SIGNAL, NOT A VERDICT. FIDCs whose delinquent receivables (tab VI total, cvm_fidc_aging) exceed p_min_delinq_pct of NAV in one aging month while NAV stays above p_min_aum — credit going bad inside a fund that is still carrying meaningful money. A high ratio is also what a distressed-credit mandate, a fund in wind-down or a single late payment in a small book looks like; confirm against the fund''s filings. Defaults are the /suspicious page''s (latest period, 5%, R$1mm). Every row carries screen and params. More than 1000 rows RAISES 22023 (never trimmed): raise p_min_delinq_pct or p_min_aum.';

REVOKE ALL ON FUNCTION api.screen_zombie_growth(DATE, NUMERIC, NUMERIC) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.screen_zombie_growth(DATE, NUMERIC, NUMERIC) TO anon, authenticated;

-- ---------------------------------------------------------------------------
-- Captive vehicles (FII) — large NAV, very few quotaholders over a trailing
-- window. Dashboard: fraud_screen_captive_vehicles(3, 10, 5e7).
-- pl_mm (MAX over the window) → max_nav_mm, min_investors → min_quotaholders.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION api.screen_captive_vehicles(
    p_lookback_months INT     DEFAULT 3,     -- trailing window, months, 1..36
    p_max_investors   INT     DEFAULT 10,    -- flagged when the window minimum is BELOW this, 1..1000
    p_min_aum         NUMERIC DEFAULT 50000000 -- NAV floor (window maximum), BRL, >= 0
)
RETURNS TABLE (
    cnpj             TEXT,
    fund_name        TEXT,
    latest_period    DATE,
    max_nav_mm       NUMERIC,
    min_quotaholders INT,
    screen           TEXT,
    params           JSONB
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $fn$
#variable_conflict use_column
BEGIN
    IF p_lookback_months IS NULL OR p_lookback_months < 1 OR p_lookback_months > 36 THEN
        RAISE EXCEPTION 'screen_captive_vehicles: p_lookback_months must be between 1 and 36, got %', p_lookback_months
            USING ERRCODE = '22023';
    END IF;
    IF p_max_investors IS NULL OR p_max_investors < 1 OR p_max_investors > 1000 THEN
        RAISE EXCEPTION 'screen_captive_vehicles: p_max_investors must be between 1 and 1000, got %', p_max_investors
            USING ERRCODE = '22023';
    END IF;
    IF p_min_aum IS NULL OR p_min_aum < 0 THEN
        RAISE EXCEPTION 'screen_captive_vehicles: p_min_aum must be a BRL amount >= 0, got %', p_min_aum
            USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    WITH page AS (
        SELECT c.cnpj, c.fund_name, c.latest_period, c.pl_mm, c.min_investors
        FROM public.fraud_screen_captive_vehicles(p_lookback_months, p_max_investors, p_min_aum) c
        ORDER BY c.pl_mm DESC NULLS LAST, c.cnpj
        LIMIT 1001
    )
    SELECT g.cnpj, g.fund_name, g.latest_period, g.pl_mm, g.min_investors,
           'captive_vehicles'::text,
           jsonb_build_object('p_lookback_months', p_lookback_months,
                              'p_max_investors', p_max_investors,
                              'p_min_aum', p_min_aum)
    FROM page g
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'screen_captive_vehicles')
    ORDER BY g.pl_mm DESC NULLS LAST, g.cnpj
    LIMIT 1000;
END;
$fn$;

COMMENT ON FUNCTION api.screen_captive_vehicles(INT, INT, NUMERIC) IS
    'SIGNAL, NOT A VERDICT. FIIs whose NAV peaked above p_min_aum in the trailing p_lookback_months while their quotaholder count never reached p_max_investors (cvm_fii_mensal complemento) — a large listed-style vehicle held by a handful of investors. Exclusive and family-office FIIs are legal and look exactly like this; the screen says where to look, not what was found. Defaults are the /suspicious page''s (3 months, fewer than 10, R$50mm). Every row carries screen and params. More than 1000 rows RAISES 22023 (never trimmed).';

REVOKE ALL ON FUNCTION api.screen_captive_vehicles(INT, INT, NUMERIC) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.screen_captive_vehicles(INT, INT, NUMERIC) TO anon, authenticated;

-- ---------------------------------------------------------------------------
-- Evergreen aging (FIDC) — the >1080-day bucket stays a large, flat share of
-- delinquency. Dashboard: fraud_screen_evergreen_aging(12, 70, 10).
-- Column names are already English.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION api.screen_evergreen_aging(
    p_lookback_months  INT     DEFAULT 12,   -- trailing window, months, 3..36
    p_min_longtail_pct NUMERIC DEFAULT 70,   -- >1080d share of delinquency must peak above this, 0..100
    p_max_variation_pp NUMERIC DEFAULT 10    -- and move less than this across the window, 0..100 p.p.
)
RETURNS TABLE (
    cnpj             TEXT,
    fund_name        TEXT,
    months_observed  BIGINT,
    min_longtail_pct NUMERIC,
    max_longtail_pct NUMERIC,
    screen           TEXT,
    params           JSONB
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $fn$
#variable_conflict use_column
BEGIN
    IF p_lookback_months IS NULL OR p_lookback_months < 3 OR p_lookback_months > 36 THEN
        RAISE EXCEPTION 'screen_evergreen_aging: p_lookback_months must be between 3 and 36 (a flat long tail needs more than a month or two to be flat), got %', p_lookback_months
            USING ERRCODE = '22023';
    END IF;
    IF p_min_longtail_pct IS NULL OR p_min_longtail_pct < 0 OR p_min_longtail_pct > 100 THEN
        RAISE EXCEPTION 'screen_evergreen_aging: p_min_longtail_pct must be between 0 and 100, got %', p_min_longtail_pct
            USING ERRCODE = '22023';
    END IF;
    IF p_max_variation_pp IS NULL OR p_max_variation_pp < 0 OR p_max_variation_pp > 100 THEN
        RAISE EXCEPTION 'screen_evergreen_aging: p_max_variation_pp must be between 0 and 100 percentage points, got %', p_max_variation_pp
            USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    WITH page AS (
        SELECT e.cnpj, e.fund_name, e.months_observed, e.min_longtail_pct, e.max_longtail_pct
        FROM public.fraud_screen_evergreen_aging(p_lookback_months, p_min_longtail_pct, p_max_variation_pp) e
        ORDER BY e.max_longtail_pct DESC NULLS LAST, e.cnpj
        LIMIT 1001
    )
    SELECT g.cnpj, g.fund_name, g.months_observed, g.min_longtail_pct, g.max_longtail_pct,
           'evergreen_aging'::text,
           jsonb_build_object('p_lookback_months', p_lookback_months,
                              'p_min_longtail_pct', p_min_longtail_pct,
                              'p_max_variation_pp', p_max_variation_pp)
    FROM page g
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'screen_evergreen_aging')
    ORDER BY g.max_longtail_pct DESC NULLS LAST, g.cnpj
    LIMIT 1000;
END;
$fn$;

COMMENT ON FUNCTION api.screen_evergreen_aging(INT, NUMERIC, NUMERIC) IS
    'SIGNAL, NOT A VERDICT. FIDCs whose receivables overdue more than 1080 days peak above p_min_longtail_pct of total delinquency over the trailing p_lookback_months and move less than p_max_variation_pp across it (cvm_fidc_aging; funds with more than R$100k delinquent only) — old credit that is neither written off nor recovered, the pattern of rolled rather than resolved receivables. A fund in slow judicial recovery, or one whose policy is not to write off, looks the same. Defaults are the /suspicious page''s (12 months, 70%, 10 p.p.). months_observed counts the aging months actually filed. Every row carries screen and params. More than 1000 rows RAISES 22023 (never trimmed).';

REVOKE ALL ON FUNCTION api.screen_evergreen_aging(INT, NUMERIC, NUMERIC) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.screen_evergreen_aging(INT, NUMERIC, NUMERIC) TO anon, authenticated;

-- ---------------------------------------------------------------------------
-- Overdue securitisation (CRI/CRA/other) — series past maturity whose NEWEST
-- filing is not terminal. Dashboard: fraud_screen_overdue_securit(1e5).
-- cnpj_securit → securitizer_cnpj, codigo_identificacao → instrument_code,
-- data_vencimento → maturity, situacao → status (value as filed),
-- valor_total_integralizado/1e6 → volume_mm, classificacao_risco_atual → rating.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION api.screen_overdue_securit(
    p_min_volume NUMERIC DEFAULT 100000      -- paid-in volume floor, BRL, >= 0
)
RETURNS TABLE (
    instrument_type  TEXT,
    securitizer_cnpj TEXT,
    instrument_code  TEXT,
    maturity         DATE,
    status           TEXT,
    volume_mm        NUMERIC,
    rating           TEXT,
    screen           TEXT,
    params           JSONB
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $fn$
#variable_conflict use_column
BEGIN
    IF p_min_volume IS NULL OR p_min_volume < 0 THEN
        RAISE EXCEPTION 'screen_overdue_securit: p_min_volume must be a BRL amount >= 0, got %', p_min_volume
            USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    WITH page AS (
        SELECT o.instrument_type, o.cnpj_securit, o.codigo_identificacao, o.data_vencimento,
               o.situacao, o.volume_mm, o.rating
        FROM public.fraud_screen_overdue_securit(p_min_volume) o
        ORDER BY o.data_vencimento ASC, o.cnpj_securit, o.codigo_identificacao
        LIMIT 1001
    )
    SELECT g.instrument_type, g.cnpj_securit, g.codigo_identificacao, g.data_vencimento,
           g.situacao, g.volume_mm, g.rating,
           'overdue_securit'::text,
           jsonb_build_object('p_min_volume', p_min_volume)
    FROM page g
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'screen_overdue_securit')
    ORDER BY g.data_vencimento ASC, g.cnpj_securit, g.codigo_identificacao
    LIMIT 1000;
END;
$fn$;

COMMENT ON FUNCTION api.screen_overdue_securit(NUMERIC) IS
    'SIGNAL, NOT A VERDICT. Securitisation series (CRI, CRA and other, cvm_securit_serie) past their filed maturity whose NEWEST monthly filing still reports a non-terminal status (not Cancelado, Vencido, Liquidado or Encerrado) with paid-in volume above p_min_volume. One row per series; status is served as filed. A series that was extended, renegotiated or simply not yet re-filed looks the same as one in silent default — the filing is what is stale, and the screen cannot say which. Default is the /suspicious page''s (R$100k). Every row carries screen and params. More than 1000 rows RAISES 22023 (never trimmed): raise p_min_volume.';

REVOKE ALL ON FUNCTION api.screen_overdue_securit(NUMERIC) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.screen_overdue_securit(NUMERIC) TO anon, authenticated;

-- ---------------------------------------------------------------------------
-- Dormant funds (FI) — every month of the window filed, zero subscriptions and
-- zero redemptions. Dashboard: fraud_screen_dormant_funds(3).
-- admin_name → administrator, max_investors → max_quotaholders,
-- last_pl → last_nav.
-- p_dormancy and p_min_nav are OUTPUT filters, not screen thresholds: the
-- screen is evaluated identically and then narrowed, so a caller can walk the
-- ~8k parked-capital classes under the page by NAV band.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION api.screen_dormant_funds(
    p_lookback_months INT     DEFAULT 3,     -- consecutive complete months with no flow, 2..12
    p_dormancy        TEXT    DEFAULT NULL,  -- empty_shell | parked_capital; NULL = both
    p_min_nav         NUMERIC DEFAULT NULL   -- keep rows whose last_nav >= this, BRL; NULL = no floor
)
RETURNS TABLE (
    cnpj             TEXT,
    fund_name        TEXT,
    administrator    TEXT,
    window_from      DATE,
    window_to        DATE,
    months_observed  BIGINT,
    max_quotaholders INT,
    last_nav         NUMERIC,
    dormancy         TEXT,
    screen           TEXT,
    params           JSONB
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $fn$
#variable_conflict use_column
BEGIN
    IF p_lookback_months IS NULL OR p_lookback_months < 2 OR p_lookback_months > 12 THEN
        RAISE EXCEPTION 'screen_dormant_funds: p_lookback_months must be between 2 and 12, got %', p_lookback_months
            USING ERRCODE = '22023';
    END IF;
    IF p_dormancy IS NOT NULL AND p_dormancy NOT IN ('empty_shell', 'parked_capital') THEN
        RAISE EXCEPTION 'screen_dormant_funds: p_dormancy must be empty_shell (no quotaholder) or parked_capital (quotaholders, no flow), got %', p_dormancy
            USING ERRCODE = '22023';
    END IF;
    IF p_min_nav IS NOT NULL AND p_min_nav < 0 THEN
        RAISE EXCEPTION 'screen_dormant_funds: p_min_nav must be a BRL amount >= 0 or null, got %', p_min_nav
            USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    WITH page AS (
        SELECT d.cnpj, d.fund_name, d.admin_name, d.window_from, d.window_to,
               d.months_observed, d.max_investors, d.last_pl, d.dormancy
        FROM public.fraud_screen_dormant_funds(p_lookback_months) d
        WHERE (p_dormancy IS NULL OR d.dormancy = p_dormancy)
          AND (p_min_nav  IS NULL OR d.last_pl >= p_min_nav)
        ORDER BY d.last_pl DESC NULLS LAST, d.cnpj
        LIMIT 1001
    )
    SELECT g.cnpj, g.fund_name, g.admin_name, g.window_from, g.window_to,
           g.months_observed, g.max_investors, g.last_pl, g.dormancy,
           'dormant_funds'::text,
           jsonb_build_object('p_lookback_months', p_lookback_months,
                              'p_dormancy', p_dormancy,
                              'p_min_nav', p_min_nav)
    FROM page g
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'screen_dormant_funds')
    ORDER BY g.last_pl DESC NULLS LAST, g.cnpj
    LIMIT 1000;
END;
$fn$;

COMMENT ON FUNCTION api.screen_dormant_funds(INT, TEXT, NUMERIC) IS
    'SIGNAL, NOT A VERDICT. FI classes that filed EVERY month of the last p_lookback_months complete months (anchored on latest_complete_period(''fi''), never today) with zero subscriptions and zero redemptions. dormancy: empty_shell = no quotaholder at all in the window (a registered, filing vehicle holding nobody''s money); parked_capital = quotaholders present but no money in or out — exclusive and closed structures look exactly like this. A month with unreported flows or quotaholders disqualifies the fund rather than counting as zero. FI only: the other families file no monthly flows. Default is the /dormant page''s (3 months). p_dormancy and p_min_nav narrow the output only and are echoed in params. More than 1000 rows RAISES 22023 (never trimmed) — parked_capital alone exceeds a page: pin p_dormancy and walk p_min_nav bands.';

REVOKE ALL ON FUNCTION api.screen_dormant_funds(INT, TEXT, NUMERIC) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.screen_dormant_funds(INT, TEXT, NUMERIC) TO anon, authenticated;

-- ---------------------------------------------------------------------------
-- Dormant trend (FI) — the dormant screen evaluated at every month-end.
-- Dashboard: fraud_screen_dormant_trend(3, 36). parked_pl → parked_nav.
-- One row per month, so the page is never reached (p_history_months <= 60).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION api.screen_dormant_trend(
    p_lookback_months INT DEFAULT 3,         -- as screen_dormant_funds, 2..12
    p_history_months  INT DEFAULT 36         -- months emitted, 1..60
)
RETURNS TABLE (
    period         DATE,
    funds_filing   BIGINT,
    empty_shells   BIGINT,
    parked_capital BIGINT,
    parked_nav     NUMERIC,
    screen         TEXT,
    params         JSONB
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $fn$
#variable_conflict use_column
BEGIN
    IF p_lookback_months IS NULL OR p_lookback_months < 2 OR p_lookback_months > 12 THEN
        RAISE EXCEPTION 'screen_dormant_trend: p_lookback_months must be between 2 and 12, got %', p_lookback_months
            USING ERRCODE = '22023';
    END IF;
    IF p_history_months IS NULL OR p_history_months < 1 OR p_history_months > 60 THEN
        RAISE EXCEPTION 'screen_dormant_trend: p_history_months must be between 1 and 60, got %', p_history_months
            USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    WITH page AS (
        SELECT t.period, t.funds_filing, t.empty_shells, t.parked_capital, t.parked_pl
        FROM public.fraud_screen_dormant_trend(p_lookback_months, p_history_months) t
        ORDER BY t.period
        LIMIT 1001
    )
    SELECT g.period, g.funds_filing, g.empty_shells, g.parked_capital, g.parked_pl,
           'dormant_trend'::text,
           jsonb_build_object('p_lookback_months', p_lookback_months,
                              'p_history_months', p_history_months)
    FROM page g
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'screen_dormant_trend')
    ORDER BY g.period
    LIMIT 1000;
END;
$fn$;

COMMENT ON FUNCTION api.screen_dormant_trend(INT, INT) IS
    'SIGNAL, NOT A VERDICT. screen_dormant_funds evaluated at every month-end over the last p_history_months complete months, each looking back p_lookback_months: funds_filing (FI classes filing that month), empty_shells and parked_capital (counts), and parked_nav (NAV sitting in parked_capital classes). Counts of a screen, not of misconduct. A fund missing a month in its frame drops out rather than passing. Defaults are the /dormant page''s (3, 36). Every row carries screen and params.';

REVOKE ALL ON FUNCTION api.screen_dormant_trend(INT, INT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.screen_dormant_trend(INT, INT) TO anon, authenticated;

-- ---------------------------------------------------------------------------
-- Delinquency drivers (FIDC) — first vs last observation of delinquency in BRL
-- and in p.p. of NAV, the move classified. Dashboard: fidc_delinquency_drivers().
-- del_start / del_end → delinquency_start / delinquency_end; the rest keep
-- their (English) names. status is the CVM registry status, as filed.
-- p_driver is an OUTPUT filter (every FIDC with >= p_min_months observations
-- gets a row, 'stable' included, so the unfiltered set exceeds a page).
-- The public function refuses a window that starts before 2025-01 (the FIDC
-- delinquency regime break) and p_months / p_min_months below 2 — its 22023
-- reaches the caller unchanged.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION api.screen_delinquency_drivers(
    p_end           DATE    DEFAULT NULL,    -- window end; NULL = latest_complete_period('fidc')
    p_months        INT     DEFAULT 12,      -- window length, months, 2..24; may not start before 2025-01
    p_min_months    INT     DEFAULT 6,       -- observations a fund needs, 2..p_months
    p_min_delta_brl NUMERIC DEFAULT 1000000, -- "up"/"down" threshold on delinquency, BRL, >= 0
    p_min_delta_pp  NUMERIC DEFAULT 1.0,     -- "up"/"down" threshold on the rate, p.p., >= 0
    p_driver        TEXT    DEFAULT NULL     -- keep one class; NULL = all five
)
RETURNS TABLE (
    cnpj              TEXT,
    fund_name         TEXT,
    status            TEXT,
    window_from       DATE,
    window_to         DATE,
    n_months          BIGINT,
    months_missing    INT,
    first_month       DATE,
    last_month        DATE,
    delinquency_start NUMERIC,
    delinquency_end   NUMERIC,
    delta_brl         NUMERIC,
    nav_start         NUMERIC,
    nav_end           NUMERIC,
    delta_nav         NUMERIC,
    rate_start        NUMERIC,
    rate_end          NUMERIC,
    delta_pp          NUMERIC,
    stopped_reporting BOOLEAN,
    driver            TEXT,
    screen            TEXT,
    params            JSONB
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $fn$
#variable_conflict use_column
BEGIN
    IF p_months IS NULL OR p_months < 2 OR p_months > 24 THEN
        RAISE EXCEPTION 'screen_delinquency_drivers: p_months must be between 2 and 24, got %', p_months
            USING ERRCODE = '22023';
    END IF;
    IF p_min_months IS NULL OR p_min_months < 2 OR p_min_months > p_months THEN
        RAISE EXCEPTION 'screen_delinquency_drivers: p_min_months must be between 2 and p_months (%), got %', p_months, p_min_months
            USING ERRCODE = '22023';
    END IF;
    IF p_min_delta_brl IS NULL OR p_min_delta_brl < 0 THEN
        RAISE EXCEPTION 'screen_delinquency_drivers: p_min_delta_brl must be a BRL amount >= 0, got %', p_min_delta_brl
            USING ERRCODE = '22023';
    END IF;
    IF p_min_delta_pp IS NULL OR p_min_delta_pp < 0 THEN
        RAISE EXCEPTION 'screen_delinquency_drivers: p_min_delta_pp must be >= 0 percentage points, got %', p_min_delta_pp
            USING ERRCODE = '22023';
    END IF;
    IF p_driver IS NOT NULL AND p_driver NOT IN ('consistent_worsening', 'value_up_rate_masked', 'denominator_only', 'improvement', 'stable') THEN
        RAISE EXCEPTION 'screen_delinquency_drivers: p_driver must be consistent_worsening, value_up_rate_masked, denominator_only, improvement or stable, got %', p_driver
            USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    WITH page AS (
        SELECT d.*
        FROM public.fidc_delinquency_drivers(p_end, p_months, p_min_months, p_min_delta_brl, p_min_delta_pp) d
        WHERE (p_driver IS NULL OR d.driver = p_driver)
        ORDER BY d.delta_brl DESC NULLS LAST, d.cnpj
        LIMIT 1001
    )
    SELECT g.cnpj, g.fund_name, g.status, g.window_from, g.window_to,
           g.n_months, g.months_missing, g.first_month, g.last_month,
           g.del_start, g.del_end, g.delta_brl,
           g.nav_start, g.nav_end, g.delta_nav,
           g.rate_start, g.rate_end, g.delta_pp,
           g.stopped_reporting, g.driver,
           'delinquency_drivers'::text,
           jsonb_build_object('p_end', p_end,
                              'p_months', p_months,
                              'p_min_months', p_min_months,
                              'p_min_delta_brl', p_min_delta_brl,
                              'p_min_delta_pp', p_min_delta_pp,
                              'p_driver', p_driver)
    FROM page g
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'screen_delinquency_drivers')
    ORDER BY g.delta_brl DESC NULLS LAST, g.cnpj
    LIMIT 1000;
END;
$fn$;

COMMENT ON FUNCTION api.screen_delinquency_drivers(DATE, INT, INT, NUMERIC, NUMERIC, TEXT) IS
    'SIGNAL, NOT A VERDICT. FIDC delinquency over a window, both metrics side by side: first vs last observation of delinquency in BRL (vl_inadimpl) and in percentage points of NAV, with the move classified by the two thresholds — consistent_worsening (value up AND rate up), value_up_rate_masked (value up, rate flat or down: NAV grew with it), denominator_only (rate up, value flat or down: NAV shrank, not new delinquency), improvement (both down), stable. Reads fact_fund_monthly, the series fund_nav and panel serve, so it can be reproduced from them. No sector, no debtor, no guarantee: a classification of two numbers, not a finding about the fund. Refuses a window starting before 2025-01 (FIDC delinquency regime break). stopped_reporting flags a last filing two or more months behind the window end; a fund that quit reporting does not read as clean. Defaults are the /fidc page''s (12 months, 6 observations, R$1mm, 1 p.p.). Every row carries screen and params. More than 1000 rows RAISES 22023 (never trimmed): pin p_driver.';

REVOKE ALL ON FUNCTION api.screen_delinquency_drivers(DATE, INT, INT, NUMERIC, NUMERIC, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.screen_delinquency_drivers(DATE, INT, INT, NUMERIC, NUMERIC, TEXT) TO anon, authenticated;

-- ---------------------------------------------------------------------------
-- The boundary, asserted. 15_fraud_screens.sql revokes the public screens from
-- PUBLIC, anon and authenticated; this proves the revoke held on THIS database
-- (a grant restored by hand in the SQL editor, or a default-privilege rule we
-- cannot see, would otherwise re-open them silently). Fails the apply loudly.
-- ---------------------------------------------------------------------------
DO $boundary$
DECLARE
    f    TEXT;
    r    TEXT;
    leak TEXT[] := '{}';
BEGIN
    FOREACH f IN ARRAY ARRAY[
        'public.fraud_screen_zombie_growth(date, numeric, numeric)',
        'public.fraud_screen_captive_vehicles(integer, integer, numeric)',
        'public.fraud_screen_evergreen_aging(integer, numeric, numeric)',
        'public.fraud_screen_overdue_securit(numeric)',
        'public.fraud_screen_dormant_funds(integer)',
        'public.fraud_screen_dormant_trend(integer, integer)',
        'public.fidc_delinquency_drivers(date, integer, integer, numeric, numeric)'
    ] LOOP
        FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r)
               AND has_function_privilege(r, f::regprocedure, 'EXECUTE') THEN
                leak := leak || (r || ' -> ' || f);
            END IF;
        END LOOP;
    END LOOP;
    IF array_length(leak, 1) > 0 THEN
        RAISE EXCEPTION 'client roles can still EXECUTE the public screens directly (the api.screen_* wrappers are the only door): %',
            array_to_string(leak, '; ');
    END IF;
END
$boundary$;

COMMIT;
