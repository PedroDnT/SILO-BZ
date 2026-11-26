-- =============================================================================
-- 44_api_risk_decompose.sql
-- api.risk_decompose(p_ticker, p_from, p_to, p_sector): where the daily return
-- variance of one B3 share or unit lives (catalog v90). Three parts:
--
--   market    Ibovespa (IBOV)
--   sector    one B3 sector index, made orthogonal to IBOV
--   residual  what is left: the part specific to the stock
--
-- REALIZED AND HISTORICAL ONLY. The hedge ratios are neutralization math for
-- the window, not trade advice.
--
-- AN EXCEPTION TO "NO REDUCERS OVER HTTP" (docs/planning/SERVING.md). The
-- owner asked for this endpoint on 2026-11-26; docs/architecture/DECISIONS.md
-- records it. It is one fixed method, written down here, with every input
-- choice in the answer. It is not a general regression service: there is no
-- free choice of regressors.
--
-- DATA. The stock leg is api.quote_history's close_total_return (dividends
-- reinvested), so it matches the index levels, which are total return
-- (29_api_index.sql). A session with a NULL close_total_return is dropped and
-- counted with its reason, never filled. When more than 10% of the stock's
-- sessions in the window have no total return, the whole stock series uses
-- close_adj instead (split-adjusted, no dividends) and stock_series says
-- 'price_only'. Mixing the two bases inside one series is never done.
--
-- JOIN LEVELS, THEN RETURNS. The tape has no row for a session with no trade.
-- The levels of the stock, IBOV and the sector index are inner-joined on
-- trade_date first, and simple returns come from consecutive joined rows, so
-- every series spans the same horizon on every row.
--
-- METHOD. OLS cascade:
--   b_m = cov(r, m) / var(m)
--   g   = cov(s, m) / var(m)          s_perp = s - g m
--   b_s = cov(r - b_m m, s_perp) / var(s_perp)
--   eps = r - b_m m - b_s s_perp
-- m and s_perp are orthogonal, so b_m^2 var(m) + b_s^2 var(s_perp) + var(eps)
-- = var(r) exactly, and the three shares add to 1. Hedge per R$ 1 long:
-- IBOV leg -(b_m - b_s g), sector leg -b_s.
--
-- SECTOR LEG. By default, a fixed map from the company's CVM setor (today's,
-- api.research_universe's setor_current) to a B3 sector index:
--   IFNC banks, insurers, financial holdings      IMAT steel, mining, pulp,
--   IEEX electric power                                petrochemicals, packaging
--   UTIL water, sanitation, gas                   IMOB construction
--   ICON retail, food, beverages, textiles, education, travel, leisure
-- A setor with no index (oil and gas, telecom, IT, transport, machinery,
-- health, agriculture) gets no sector leg: two parts, market and residual,
-- with flag no_sector_index. The map is SILO's rule, not B3 index membership:
-- SILO holds no sector-index portfolio. p_sector overrides it with any index
-- code held except IBOV, or 'none' for two parts. A stock that is a large
-- member of its sector index puts its own risk in the sector leg, so the
-- residual is understated; the endpoint cannot detect that.
--
-- WINDOW. p_to defaults to today and moves back to the last IBOV session on
-- or before it. p_from NULL = 252 returns back (253 IBOV sessions). A window
-- that starts before the ticker's first session on the tape starts there
-- (flag window_clamped). At most 1000 IBOV sessions (about 4 years): a longer
-- window raises 22023.
--
-- MINIMUM SAMPLE. Fewer than 120 joined returns: status
-- 'insufficient_sample', the split columns NULL, the counts still reported.
--
-- SHOCK CHECK. A shock session is one where |IBOV return - median| > 4 x
-- robust sigma, robust sigma = 1.4826 x median(|IBOV return - median|). The
-- split is run again without those sessions (ex_shock_*). No shock session:
-- ex_shock_* NULL. Flag shock_sensitive when a share differs by more than 0.10.
--
-- LIQUIDITY. no_trade_sessions sums prior_no_trade_sessions inside the
-- window; zero_returns counts joined returns exactly 0. Flag illiquid when
-- either is above 5% of the window. Stale prices bias the betas toward 0;
-- beta_dimson (slope on m_t plus slope on m_t-1) is the check, given always.
-- Volatility is annualized with sqrt(252 x n_returns / IBOV returns in the
-- window), which is sqrt(252) for a stock that trades every session.
--
-- PRIVILEGES. SECURITY DEFINER, empty pinned search_path, every relation
-- schema-qualified. api.risk_sector_leg and api.risk_split are internal:
-- revoked from PUBLIC, never granted. One row per call, so no row cap.
--
-- Ordering: after 19 (api.quote_history, api.quote_data_revision), 28
-- (mv_research_universe) and 29 (b3_index_level is read directly).
-- =============================================================================

BEGIN;
-- The dashboard view below runs the function once per IBOV member (~0.2 s each).
SET statement_timeout = '5min';

DO $guard$
BEGIN
    IF to_regprocedure('api.quote_history(text, date, date, text, text, text[])') IS NULL
       OR to_regprocedure('api.quote_data_revision()') IS NULL THEN
        RAISE EXCEPTION '44_api_risk_decompose.sql needs api.quote_history and api.quote_data_revision from 19_api_contract.sql; apply 19 first';
    END IF;
    IF to_regclass('public.mv_research_universe') IS NULL THEN
        RAISE EXCEPTION '44_api_risk_decompose.sql reads public.mv_research_universe; apply 28_api_research.sql first';
    END IF;
END
$guard$;

-- Internal. The B3 sector index SILO maps a CVM setor to; NULL = no index.
-- A holding company (Emp. Adm. Part. - <setor>) takes its setor's index.
CREATE OR REPLACE FUNCTION api.risk_sector_leg(p_setor TEXT)
RETURNS TEXT
LANGUAGE sql
IMMUTABLE
SET search_path = ''
AS $$
    SELECT CASE regexp_replace(COALESCE(p_setor, ''), '^Emp\. Adm\. Part\. - ', '')
        WHEN 'Bancos'                                     THEN 'IFNC'
        WHEN 'Seguradoras e Corretoras'                   THEN 'IFNC'
        WHEN 'Intermediação Financeira'                   THEN 'IFNC'
        WHEN 'Crédito Imobiliário'                        THEN 'IFNC'
        WHEN 'Metalurgia e Siderurgia'                    THEN 'IMAT'
        WHEN 'Extração Mineral'                           THEN 'IMAT'
        WHEN 'Papel e Celulose'                           THEN 'IMAT'
        WHEN 'Petroquímicos e Borracha'                   THEN 'IMAT'
        WHEN 'Embalagens'                                 THEN 'IMAT'
        WHEN 'Energia Elétrica'                           THEN 'IEEX'
        WHEN 'Saneamento, Serv. Água e Gás'               THEN 'UTIL'
        WHEN 'Construção Civil, Mat. Constr. e Decoração' THEN 'IMOB'
        WHEN 'Const. Civil, Mat. Const. e Decoração'      THEN 'IMOB'
        WHEN 'Comércio (Atacado e Varejo)'                THEN 'ICON'
        WHEN 'Alimentos'                                  THEN 'ICON'
        WHEN 'Bebidas e Fumo'                             THEN 'ICON'
        WHEN 'Têxtil e Vestuário'                         THEN 'ICON'
        WHEN 'Educação'                                   THEN 'ICON'
        WHEN 'Hospedagem e Turismo'                       THEN 'ICON'
        WHEN 'Brinquedos e Lazer'                         THEN 'ICON'
    END;
$$;

COMMENT ON FUNCTION api.risk_sector_leg(TEXT) IS
    'Internal. The B3 sector index api.risk_decompose uses for a CVM setor (holding companies take their setor''s index); NULL = no index, two-part split.';

REVOKE ALL ON FUNCTION api.risk_sector_leg(TEXT) FROM PUBLIC;

-- Internal. The OLS cascade on aligned return arrays. p_s NULL = no sector
-- leg (two parts). p_ann annualizes the volatilities. NULL when the sample
-- has no variance.
CREATE OR REPLACE FUNCTION api.risk_split(
    p_r   DOUBLE PRECISION[],
    p_m   DOUBLE PRECISION[],
    p_s   DOUBLE PRECISION[],
    p_ann DOUBLE PRECISION
)
RETURNS jsonb
LANGUAGE plpgsql
IMMUTABLE
SET search_path = ''
AS $$
DECLARE
    v_n   INT := COALESCE(cardinality(p_r), 0);
    v_s   DOUBLE PRECISION[] := COALESCE(p_s, array_fill(0::DOUBLE PRECISION, ARRAY[GREATEST(v_n, 1)]));
    v_vr  DOUBLE PRECISION;
    v_vm  DOUBLE PRECISION;
    v_bm  DOUBLE PRECISION;
    v_g   DOUBLE PRECISION := 0;
    v_bs  DOUBLE PRECISION := 0;
    v_vsp DOUBLE PRECISION := 0;
    v_ve  DOUBLE PRECISION;
BEGIN
    IF v_n < 3 THEN
        RETURN NULL;
    END IF;

    SELECT var_samp(u.r), var_samp(u.m), covar_samp(u.r, u.m), covar_samp(u.s, u.m)
    INTO v_vr, v_vm, v_bm, v_g
    FROM unnest(p_r, p_m, v_s) AS u(r, m, s);

    IF v_vr IS NULL OR v_vr = 0 OR v_vm IS NULL OR v_vm = 0 THEN
        RETURN NULL;
    END IF;
    v_bm := v_bm / v_vm;
    v_g  := CASE WHEN p_s IS NULL THEN 0 ELSE v_g / v_vm END;

    IF p_s IS NOT NULL THEN
        SELECT covar_samp(u.r - v_bm * u.m, u.s - v_g * u.m), var_samp(u.s - v_g * u.m)
        INTO v_bs, v_vsp
        FROM unnest(p_r, p_m, v_s) AS u(r, m, s);
        v_bs := CASE WHEN v_vsp > 0 THEN v_bs / v_vsp ELSE 0 END;
        v_vsp := COALESCE(v_vsp, 0);
    END IF;

    SELECT var_samp(u.r - v_bm * u.m - v_bs * (u.s - v_g * u.m))
    INTO v_ve
    FROM unnest(p_r, p_m, v_s) AS u(r, m, s);

    RETURN jsonb_build_object(
        'n_returns',      v_n,
        'market_share',   round((v_bm * v_bm * v_vm / v_vr)::numeric, 6),
        'sector_share',   CASE WHEN p_s IS NULL THEN NULL
                               ELSE round((v_bs * v_bs * v_vsp / v_vr)::numeric, 6) END,
        'residual_share', round((v_ve / v_vr)::numeric, 6),
        'vol_total',      round((sqrt(v_vr) * p_ann)::numeric, 6),
        'vol_market',     round((abs(v_bm) * sqrt(v_vm) * p_ann)::numeric, 6),
        'vol_sector',     CASE WHEN p_s IS NULL THEN NULL
                               ELSE round((abs(v_bs) * sqrt(v_vsp) * p_ann)::numeric, 6) END,
        'vol_residual',   round((sqrt(GREATEST(v_ve, 0)) * p_ann)::numeric, 6),
        'beta_market',    round(v_bm::numeric, 6),
        'beta_sector',    CASE WHEN p_s IS NULL THEN NULL ELSE round(v_bs::numeric, 6) END,
        'gamma',          CASE WHEN p_s IS NULL THEN NULL ELSE round(v_g::numeric, 6) END,
        'hedge_ibov',     round((-(v_bm - v_bs * v_g))::numeric, 6),
        'hedge_sector',   CASE WHEN p_s IS NULL THEN NULL ELSE round((-v_bs)::numeric, 6) END
    );
END;
$$;

COMMENT ON FUNCTION api.risk_split(DOUBLE PRECISION[], DOUBLE PRECISION[], DOUBLE PRECISION[], DOUBLE PRECISION) IS
    'Internal. api.risk_decompose''s OLS cascade on aligned daily return arrays (stock, IBOV, sector leg or NULL).';

REVOKE ALL ON FUNCTION api.risk_split(DOUBLE PRECISION[], DOUBLE PRECISION[], DOUBLE PRECISION[], DOUBLE PRECISION) FROM PUBLIC;

CREATE OR REPLACE FUNCTION api.risk_decompose(
    p_ticker TEXT,
    -- NULL = 252 returns back from p_to.
    p_from   DATE DEFAULT NULL,
    -- NULL = today; moved back to the last IBOV session on or before it.
    p_to     DATE DEFAULT NULL,
    -- NULL = the CVM setor map; an index code held (not IBOV); 'none' = no sector leg.
    p_sector TEXT DEFAULT NULL
)
RETURNS TABLE (
    ticker                  TEXT,
    isin                    TEXT,
    setor_current           TEXT,
    status                  TEXT,
    window_from             DATE,
    window_to               DATE,
    window_sessions         INT,
    n_returns               INT,
    stock_series            TEXT,
    sector_leg              TEXT,
    sector_leg_basis        TEXT,
    market_share            NUMERIC,
    sector_share            NUMERIC,
    residual_share          NUMERIC,
    vol_total               NUMERIC,
    vol_market              NUMERIC,
    vol_sector              NUMERIC,
    vol_residual            NUMERIC,
    beta_market             NUMERIC,
    beta_sector             NUMERIC,
    gamma                   NUMERIC,
    hedge_ibov              NUMERIC,
    hedge_sector            NUMERIC,
    ex_shock_n_returns      INT,
    ex_shock_market_share   NUMERIC,
    ex_shock_sector_share   NUMERIC,
    ex_shock_residual_share NUMERIC,
    ex_shock_vol_total      NUMERIC,
    ex_shock_beta_market    NUMERIC,
    ex_shock_beta_sector    NUMERIC,
    ex_shock_hedge_ibov     NUMERIC,
    ex_shock_hedge_sector   NUMERIC,
    shock_dates             DATE[],
    shock_sensitive         BOOLEAN,
    null_sessions           INT,
    null_reasons            JSONB,
    no_trade_sessions       INT,
    zero_returns            INT,
    illiquid                BOOLEAN,
    beta_dimson             NUMERIC,
    flags                   TEXT[],
    method                  TEXT,
    data_revision           TEXT
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $fn$
#variable_conflict use_column
DECLARE
    v_ticker     TEXT := upper(btrim(COALESCE(p_ticker, '')));
    v_sector_arg TEXT := upper(NULLIF(btrim(COALESCE(p_sector, '')), ''));
    v_to         DATE;
    v_from       DATE;
    v_first      DATE;
    v_setor      TEXT;
    v_isin       TEXT;
    v_leg        TEXT;
    v_leg_basis  TEXT;
    v_held       TEXT;
    v_sessions   INT;
    v_rows       jsonb[];
    v_n_rows     INT;
    v_n_null     INT;
    v_reasons    jsonb;
    v_basis      TEXT;
    v_no_trade   INT;
    v_base_date  DATE;
    v_dates      DATE[];
    v_r          DOUBLE PRECISION[];
    v_m          DOUBLE PRECISION[];
    v_s          DOUBLE PRECISION[];
    v_n          INT;
    v_zero       INT;
    v_ann        DOUBLE PRECISION;
    v_illiquid   BOOLEAN;
    v_dimson     DOUBLE PRECISION;
    v_med        DOUBLE PRECISION;
    v_mad        DOUBLE PRECISION;
    v_shock      DATE[] := '{}';
    v_xr         DOUBLE PRECISION[];
    v_xm         DOUBLE PRECISION[];
    v_xs         DOUBLE PRECISION[];
    v_full       jsonb;
    v_ex         jsonb;
    v_sensitive  BOOLEAN := FALSE;
    v_status     TEXT := 'ok';
    v_flags      TEXT[] := '{}';
BEGIN
    IF v_ticker = '' THEN
        RAISE EXCEPTION 'risk_decompose: p_ticker is required, a B3 share or unit ticker such as PETR4'
            USING ERRCODE = '22023';
    END IF;

    -- The window, on IBOV sessions.
    SELECT max(l.trade_date) INTO v_to
    FROM public.b3_index_level l
    WHERE l.index_code = 'IBOV' AND l.trade_date <= COALESCE(p_to, CURRENT_DATE);
    IF v_to IS NULL THEN
        RAISE EXCEPTION 'risk_decompose: no IBOV session on or before %', COALESCE(p_to, CURRENT_DATE)
            USING ERRCODE = '22023';
    END IF;
    IF p_from IS NULL THEN
        SELECT min(x.trade_date) INTO v_from
        FROM (SELECT l.trade_date FROM public.b3_index_level l
              WHERE l.index_code = 'IBOV' AND l.trade_date <= v_to
              ORDER BY l.trade_date DESC LIMIT 253) x;
    ELSE
        v_from := p_from;
    END IF;
    IF v_from >= v_to THEN
        RAISE EXCEPTION 'risk_decompose: p_from (%) must be before the window end (%)', v_from, v_to
            USING ERRCODE = '22023';
    END IF;

    -- The company: today's CVM setor and the ticker's first session.
    SELECT u.setor_current, u.isin, u.first_observed
    INTO v_setor, v_isin, v_first
    FROM public.mv_research_universe u
    WHERE u.ticker = v_ticker
    ORDER BY u.last_observed DESC NULLS LAST, u.isin
    LIMIT 1;
    IF v_first IS NOT NULL AND v_from < v_first THEN
        v_from := v_first;
        v_flags := v_flags || 'window_clamped'::text;
    END IF;

    SELECT count(*) INTO v_sessions
    FROM public.b3_index_level l
    WHERE l.index_code = 'IBOV' AND l.trade_date BETWEEN v_from AND v_to;
    IF v_sessions > 1000 THEN
        RAISE EXCEPTION 'risk_decompose: the window % to % holds % IBOV sessions; at most 1000 (about 4 years). Narrow p_from / p_to.',
            v_from, v_to, v_sessions
            USING ERRCODE = '22023';
    END IF;

    -- The sector leg.
    IF v_sector_arg IS NULL THEN
        v_leg := api.risk_sector_leg(v_setor);
        v_leg_basis := CASE WHEN v_leg IS NULL THEN 'none' ELSE 'cvm_setor_map' END;
    ELSIF v_sector_arg = 'NONE' THEN
        v_leg := NULL;
        v_leg_basis := 'caller';
    ELSE
        IF v_sector_arg = 'IBOV' OR NOT EXISTS (
            SELECT 1 FROM public.b3_index_level l WHERE l.index_code = v_sector_arg
        ) THEN
            SELECT string_agg(h.code, ', ' ORDER BY h.code) INTO v_held
            FROM (SELECT DISTINCT l.index_code AS code FROM public.b3_index_level l
                  WHERE l.index_code <> 'IBOV') h;
            RAISE EXCEPTION 'risk_decompose: p_sector must be none or a B3 index code SILO holds other than IBOV (%), got %',
                COALESCE(v_held, 'none loaded yet'), p_sector
                USING ERRCODE = '22023';
        END IF;
        v_leg := v_sector_arg;
        v_leg_basis := 'caller';
    END IF;
    IF v_leg IS NULL AND v_leg_basis = 'none' THEN
        v_flags := v_flags || 'no_sector_index'::text;
    END IF;

    -- The stock. quote_history raises unknown_ticker and its other refusals.
    SELECT array_agg(j ORDER BY (j->>'trade_date')::date) INTO v_rows
    FROM api.quote_history(v_ticker, v_from, v_to, NULL, NULL,
         ARRAY['close_total_return', 'close_total_return_null_reason',
               'close_adj', 'prior_no_trade_sessions']) j;

    SELECT count(*), count(*) FILTER (WHERE j->>'close_total_return' IS NULL)
    INTO v_n_rows, v_n_null
    FROM unnest(v_rows) j;
    v_basis := CASE WHEN v_n_rows > 0 AND v_n_null > 0.10 * v_n_rows
                    THEN 'price_only' ELSE 'total_return' END;
    IF v_basis = 'price_only' THEN
        v_flags := v_flags || 'price_only'::text;
    ELSIF v_n_null > 0 THEN
        v_flags := v_flags || 'null_sessions_dropped'::text;
    END IF;

    SELECT COALESCE(jsonb_object_agg(x.reason, x.n), '{}'::jsonb) INTO v_reasons
    FROM (SELECT COALESCE(j->>'close_total_return_null_reason', 'unstated') AS reason, count(*) AS n
          FROM unnest(v_rows) j
          WHERE j->>'close_total_return' IS NULL
          GROUP BY 1) x;

    -- No-trade sessions inside the window: the first row's count looks back
    -- before the window, so it is left out.
    SELECT COALESCE(sum((j->>'prior_no_trade_sessions')::int), 0) INTO v_no_trade
    FROM unnest(v_rows) WITH ORDINALITY AS t(j, k)
    WHERE t.k > 1;

    -- Join levels, then returns.
    WITH q AS (
        SELECT (j->>'trade_date')::date AS d,
               CASE WHEN v_basis = 'total_return'
                    THEN (j->>'close_total_return')::double precision
                    ELSE (j->>'close_adj')::double precision END AS lvl
        FROM unnest(v_rows) j
    ),
    lv AS (
        SELECT q.d, q.lvl, ib.level::double precision AS im, sl.level::double precision AS sm,
               (ib.divisor_step OR COALESCE(sl.divisor_step, FALSE)) AS step
        FROM q
        JOIN public.b3_index_level ib
          ON ib.index_code = 'IBOV' AND ib.trade_date = q.d
        LEFT JOIN public.b3_index_level sl
          ON sl.index_code = v_leg AND sl.trade_date = q.d
        WHERE q.lvl IS NOT NULL AND q.lvl > 0
          AND (v_leg IS NULL OR sl.level IS NOT NULL)
    ),
    ret AS (
        SELECT lv.d,
               lv.lvl / lag(lv.lvl) OVER w - 1 AS r,
               lv.im / lag(lv.im) OVER w - 1 AS m,
               lv.sm / lag(lv.sm) OVER w - 1 AS s,
               lv.step,
               min(lv.d) OVER () AS base
        FROM lv
        WINDOW w AS (ORDER BY lv.d)
    )
    SELECT array_agg(ret.d ORDER BY ret.d), array_agg(ret.r ORDER BY ret.d),
           array_agg(ret.m ORDER BY ret.d), array_agg(ret.s ORDER BY ret.d),
           min(ret.base)
    INTO v_dates, v_r, v_m, v_s, v_base_date
    FROM ret
    WHERE ret.r IS NOT NULL AND ret.m IS NOT NULL AND NOT ret.step;

    IF v_leg IS NULL THEN
        v_s := NULL;
    END IF;
    v_n := COALESCE(cardinality(v_r), 0);

    SELECT count(*) INTO v_zero FROM unnest(v_r) x WHERE x = 0;
    v_illiquid := v_no_trade > 0.05 * GREATEST(v_sessions - 1, 1)
               OR v_zero > 0.05 * GREATEST(v_n, 1);
    IF v_illiquid THEN
        v_flags := v_flags || 'illiquid'::text;
    END IF;

    IF v_n < 120 THEN
        v_status := 'insufficient_sample';
    ELSE
        v_ann := sqrt(252.0 * v_n / GREATEST(v_sessions - 1, 1));
        v_full := api.risk_split(v_r, v_m, v_s, v_ann);

        -- Dimson: OLS of r_t on m_t and m_t-1, beta = sum of the two slopes.
        SELECT (c_rm * v_ml - c_rl * c_ml) / NULLIF(v_mm * v_ml - c_ml * c_ml, 0)
             + (c_rl * v_mm - c_rm * c_ml) / NULLIF(v_mm * v_ml - c_ml * c_ml, 0)
        INTO v_dimson
        FROM (
            SELECT var_samp(x.m) AS v_mm, var_samp(x.ml) AS v_ml, covar_samp(x.m, x.ml) AS c_ml,
                   covar_samp(x.r, x.m) AS c_rm, covar_samp(x.r, x.ml) AS c_rl
            FROM (SELECT u.r, u.m, lag(u.m) OVER (ORDER BY u.k) AS ml
                  FROM unnest(v_r, v_m) WITH ORDINALITY AS u(r, m, k)) x
            WHERE x.ml IS NOT NULL
        ) a;

        -- Shock sessions: robust z of the IBOV return above 4.
        SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY x) INTO v_med FROM unnest(v_m) x;
        SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY abs(x - v_med)) INTO v_mad FROM unnest(v_m) x;

        IF v_mad > 0 THEN
            SELECT COALESCE(array_agg(u.d ORDER BY u.d) FILTER (WHERE abs(u.m - v_med) > 4 * 1.4826 * v_mad), '{}'),
                   array_agg(u.r ORDER BY u.k) FILTER (WHERE abs(u.m - v_med) <= 4 * 1.4826 * v_mad),
                   array_agg(u.m ORDER BY u.k) FILTER (WHERE abs(u.m - v_med) <= 4 * 1.4826 * v_mad),
                   array_agg(u.s ORDER BY u.k) FILTER (WHERE abs(u.m - v_med) <= 4 * 1.4826 * v_mad)
            INTO v_shock, v_xr, v_xm, v_xs
            FROM unnest(v_dates, v_r, v_m, COALESCE(v_s, array_fill(NULL::double precision, ARRAY[v_n])))
                 WITH ORDINALITY AS u(d, r, m, s, k);
        END IF;

        IF cardinality(v_shock) > 0 AND COALESCE(cardinality(v_xr), 0) >= 120 THEN
            v_ex := api.risk_split(v_xr, v_xm, CASE WHEN v_leg IS NULL THEN NULL ELSE v_xs END, v_ann);
            v_sensitive := v_full IS NOT NULL AND v_ex IS NOT NULL AND (
                abs((v_full->>'market_share')::numeric - (v_ex->>'market_share')::numeric) > 0.10
                OR abs(COALESCE((v_full->>'sector_share')::numeric, 0) - COALESCE((v_ex->>'sector_share')::numeric, 0)) > 0.10
                OR abs((v_full->>'residual_share')::numeric - (v_ex->>'residual_share')::numeric) > 0.10);
            IF v_sensitive THEN
                v_flags := v_flags || 'shock_sensitive'::text;
            END IF;
        END IF;
    END IF;

    RETURN QUERY SELECT
        v_ticker, v_isin, v_setor, v_status,
        v_base_date, v_dates[v_n], v_sessions, v_n,
        v_basis, v_leg, v_leg_basis,
        (v_full->>'market_share')::numeric, (v_full->>'sector_share')::numeric,
        (v_full->>'residual_share')::numeric, (v_full->>'vol_total')::numeric,
        (v_full->>'vol_market')::numeric, (v_full->>'vol_sector')::numeric,
        (v_full->>'vol_residual')::numeric, (v_full->>'beta_market')::numeric,
        (v_full->>'beta_sector')::numeric, (v_full->>'gamma')::numeric,
        (v_full->>'hedge_ibov')::numeric, (v_full->>'hedge_sector')::numeric,
        (v_ex->>'n_returns')::int, (v_ex->>'market_share')::numeric,
        (v_ex->>'sector_share')::numeric, (v_ex->>'residual_share')::numeric,
        (v_ex->>'vol_total')::numeric, (v_ex->>'beta_market')::numeric,
        (v_ex->>'beta_sector')::numeric, (v_ex->>'hedge_ibov')::numeric,
        (v_ex->>'hedge_sector')::numeric,
        v_shock, v_sensitive, v_n_null, v_reasons, v_no_trade, v_zero, v_illiquid,
        round(v_dimson::numeric, 6), v_flags,
        'OLS cascade on daily simple returns from joined levels: IBOV, then the sector index orthogonal to IBOV; total-return stock and index levels; realized, not advice'::text,
        api.quote_data_revision();
END;
$fn$;

COMMENT ON FUNCTION api.risk_decompose(TEXT, DATE, DATE, TEXT) IS
    'Where the daily return variance of one B3 share or unit lives, over a window: market (IBOV), sector (a B3 sector index, made orthogonal to IBOV) and residual (the part specific to the stock). One row. market_share, sector_share and residual_share add to 1; vol_* are annualized volatilities; beta_market, beta_sector, gamma (the sector index''s beta to IBOV) and hedge ratios per R$ 1 long (hedge_ibov = -(beta_market - beta_sector x gamma), hedge_sector = -beta_sector). The ex_shock_* columns are the same split without the shock sessions (shock_dates: |IBOV return - median| > 4 x 1.4826 x MAD), NULL when there is none; shock_sensitive when a share moves more than 0.10. Method: OLS cascade on daily simple returns computed from the inner join of the stock''s close_total_return (dividends reinvested) and the total-return index levels on trade_date, so every series spans the same sessions. Sessions with no total return are dropped and counted (null_reasons); above 10% of the window the stock leg is close_adj for the whole window (stock_series price_only, no dividends). Sector leg (p_sector NULL): SILO''s map from today''s CVM setor: IFNC banks and insurers, IMAT steel, mining, pulp, petrochemicals and packaging, IEEX electric power, UTIL sanitation and gas, IMOB construction, ICON retail, food, beverages, textiles, education, travel and leisure; any other setor has no sector leg (two parts, flag no_sector_index). The map is not index membership. p_sector = an index code held other than IBOV, or none. Window: p_to defaults to today (moved to the last IBOV session), p_from to 252 returns back, clamped to the ticker''s first session (flag window_clamped); more than 1000 sessions RAISES 22023. Fewer than 120 returns: status insufficient_sample, the split columns NULL. illiquid when no-trade sessions or zero returns exceed 5% of the window (stale prices bias betas to 0; beta_dimson is the check). Realized and historical only, not investment advice. Refusals from quote_history (unknown_ticker, ...) pass through.';

REVOKE ALL ON FUNCTION api.risk_decompose(TEXT, DATE, DATE, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.risk_decompose(TEXT, DATE, DATE, TEXT) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION api.risk_decompose(TEXT, DATE, DATE, TEXT) TO silo_api;

-- -----------------------------------------------------------------------------
-- The dashboard's /risk page: api.risk_decompose with its defaults for every
-- member of B3's IBOV theoretical portfolio on the newest reference date held
-- (b3_index_portfolio). Rebuilt on every analytical apply, so it moves with
-- the tape once a day. Not served by the API.
--
-- A REFUSAL IS A ROW, NOT A GAP. One member api.risk_decompose refuses
-- (22023: adjustment_unavailable, outside_coverage, ...) would otherwise fail
-- the whole build. Only 22023, the contract's refusal code, is caught; its
-- message is kept in `refusal` and the page lists it. Every other error
-- propagates and fails the apply.
-- -----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.risk_decompose_ibov_members()
RETURNS TABLE (
    ticker         TEXT,
    asset_name     TEXT,
    ibov_weight    NUMERIC,
    portfolio_date DATE,
    refusal        TEXT,
    result         JSONB
)
LANGUAGE plpgsql
STABLE
SET search_path = ''
AS $$
#variable_conflict use_column
DECLARE
    m RECORD;
BEGIN
    FOR m IN
        SELECT DISTINCT ON (p.codneg) p.codneg, p.asset_name, p.participacao_pct, p.reference_date
        FROM public.b3_index_portfolio p
        WHERE p.index_code = 'IBOV'
          AND p.reference_date = (SELECT max(q.reference_date)
                                  FROM public.b3_index_portfolio q
                                  WHERE q.index_code = 'IBOV')
        ORDER BY p.codneg, p.participacao_pct DESC
    LOOP
        ticker := m.codneg;
        asset_name := m.asset_name;
        ibov_weight := m.participacao_pct;
        portfolio_date := m.reference_date;
        refusal := NULL;
        result := NULL;
        BEGIN
            SELECT to_jsonb(r) INTO result FROM api.risk_decompose(m.codneg) r;
        EXCEPTION WHEN SQLSTATE '22023' THEN
            refusal := SQLERRM;
        END;
        RETURN NEXT;
    END LOOP;
END;
$$;

COMMENT ON FUNCTION public.risk_decompose_ibov_members() IS
    'Dashboard only. api.risk_decompose with its defaults for each IBOV member on the newest portfolio date; a 22023 refusal is kept as the row''s refusal text, any other error propagates.';

REVOKE ALL ON FUNCTION public.risk_decompose_ibov_members() FROM PUBLIC;

DROP MATERIALIZED VIEW IF EXISTS public.mv_risk_decompose_ibov;

CREATE MATERIALIZED VIEW public.mv_risk_decompose_ibov AS
SELECT
    x.ticker,
    x.asset_name,
    x.ibov_weight,
    x.portfolio_date,
    x.refusal,
    x.result->>'status'                                AS status,
    x.result->>'setor_current'                         AS setor_current,
    x.result->>'sector_leg'                            AS sector_leg,
    (x.result->>'window_from')::date                   AS window_from,
    (x.result->>'window_to')::date                     AS window_to,
    (x.result->>'n_returns')::int                      AS n_returns,
    x.result->>'stock_series'                          AS stock_series,
    (x.result->>'market_share')::numeric               AS market_share,
    (x.result->>'sector_share')::numeric               AS sector_share,
    (x.result->>'residual_share')::numeric             AS residual_share,
    (x.result->>'vol_total')::numeric                  AS vol_total,
    (x.result->>'beta_market')::numeric                AS beta_market,
    (x.result->>'beta_sector')::numeric                AS beta_sector,
    (x.result->>'hedge_ibov')::numeric                 AS hedge_ibov,
    (x.result->>'hedge_sector')::numeric               AS hedge_sector,
    (x.result->>'ex_shock_market_share')::numeric      AS ex_shock_market_share,
    (x.result->>'ex_shock_residual_share')::numeric    AS ex_shock_residual_share,
    (x.result->>'shock_sensitive')::boolean            AS shock_sensitive,
    (x.result->>'illiquid')::boolean                   AS illiquid,
    (SELECT string_agg(f, ', ') FROM jsonb_array_elements_text(x.result->'flags') f) AS flags,
    now()                                              AS built_at
FROM public.risk_decompose_ibov_members() x;

CREATE UNIQUE INDEX uq_mv_risk_decompose_ibov ON public.mv_risk_decompose_ibov (ticker);

REVOKE ALL ON public.mv_risk_decompose_ibov FROM PUBLIC, anon, authenticated;

COMMENT ON MATERIALIZED VIEW public.mv_risk_decompose_ibov IS
    'Dashboard /risk: api.risk_decompose (defaults: 252 returns, setor map) for every IBOV member on the newest b3_index_portfolio date, rebuilt on each analytical apply. A member the function refuses keeps its refusal text and NULL split columns. Not served by the API.';

COMMIT;
