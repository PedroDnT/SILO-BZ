-- =============================================================================
-- 41_api_treasury.sql
-- Tesouro Direto posted rates and prices, served through schema `api`
-- (catalog v86, #1163):
--
--   api.treasury_direct  every title on one base date, or a window of base
--                        dates, optionally one title type and one maturity
--
-- Source: public.tesouro_direto_daily (migration 86), the Treasury's open-data
-- CSV "Taxas dos Títulos Ofertados pelo Tesouro Direto". LICENCE: ODbL 1.0.
-- The owner decided on 2026-11-16 to serve it with the credit the licence asks
-- for, so every row carries source = 'Tesouro Nacional' and licence =
-- 'ODbL-1.0' (this is the one resource that names its source).
--
-- NOTHING IS DERIVED. The rates are the Treasury's posted MORNING quotes on its
-- retail platform, % a year as published (they can be negative: a Tesouro
-- Selic spread, an IPCA+ real rate in 2020); the PU columns are R$ per title
-- as published. They are quotes, not trades. A NULL price is a side the title
-- was not on sale on (the source prints 0,00). base_pu is the same-day mark
-- the platform uses for holdings; buy_pu and sell_pu settle the next business
-- day. The file covers only the titles Tesouro Direto offered, not every
-- federal bond.
-- =============================================================================

CREATE OR REPLACE FUNCTION api.treasury_direct(
    p_title    TEXT DEFAULT NULL,  -- a title type as published (Tesouro IPCA+, ...); NULL = every type
    p_maturity DATE DEFAULT NULL,  -- one maturity; NULL = every maturity
    p_from     DATE DEFAULT NULL,  -- NULL = p_to's base date (one session)
    p_to       DATE DEFAULT NULL   -- NULL = the newest base date held
)
RETURNS TABLE (
    base_date     DATE,
    title         TEXT,
    maturity      DATE,
    buy_rate_pct  NUMERIC,
    sell_rate_pct NUMERIC,
    buy_pu        NUMERIC,
    sell_pu       NUMERIC,
    base_pu       NUMERIC,
    source        TEXT,
    licence       TEXT
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $fn$
#variable_conflict use_column
DECLARE
    v_title TEXT;
    v_to    DATE;
    v_from  DATE;
BEGIN
    IF p_title IS NOT NULL THEN
        SELECT t.tipo_titulo INTO v_title
        FROM public.tesouro_direto_daily t
        WHERE lower(t.tipo_titulo) = lower(btrim(p_title))
        LIMIT 1;
        IF v_title IS NULL THEN
            RAISE EXCEPTION 'treasury_direct: title % is not held; the titles are: %',
                p_title,
                (SELECT string_agg(DISTINCT t.tipo_titulo, ', ' ORDER BY t.tipo_titulo)
                   FROM public.tesouro_direto_daily t)
                USING ERRCODE = '22023';
        END IF;
    END IF;

    -- The newest base date on or before p_to (or held at all).
    SELECT max(t.data_base) INTO v_to
    FROM public.tesouro_direto_daily t
    WHERE t.data_base <= COALESCE(p_to, CURRENT_DATE);
    IF p_to IS NOT NULL AND p_from IS NOT NULL THEN
        v_to := p_to;
    END IF;
    v_from := COALESCE(p_from, v_to);
    IF v_from > v_to THEN
        RAISE EXCEPTION 'treasury_direct: p_from (%) is after p_to (%)', v_from, v_to
            USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    -- One page + one, then assert_row_cap REFUSES (22023). No cursor: narrow
    -- the window, or name a title and a maturity.
    WITH page AS (
        SELECT t.data_base, t.tipo_titulo, t.data_vencimento,
               t.taxa_compra, t.taxa_venda, t.pu_compra, t.pu_venda, t.pu_base
        FROM public.tesouro_direto_daily t
        WHERE t.data_base BETWEEN v_from AND v_to
          AND (v_title IS NULL OR t.tipo_titulo = v_title)
          AND (p_maturity IS NULL OR t.data_vencimento = p_maturity)
        ORDER BY t.data_base DESC, t.tipo_titulo, t.data_vencimento
        LIMIT 1001
    )
    SELECT g.data_base, g.tipo_titulo, g.data_vencimento,
           g.taxa_compra, g.taxa_venda, g.pu_compra, g.pu_venda, g.pu_base,
           'Tesouro Nacional'::text, 'ODbL-1.0'::text
    FROM page g
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'treasury_direct')
    ORDER BY g.data_base DESC, g.tipo_titulo, g.data_vencimento
    LIMIT 1000;
END;
$fn$;

REVOKE ALL ON FUNCTION api.treasury_direct(TEXT, DATE, DATE, DATE) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.treasury_direct(TEXT, DATE, DATE, DATE) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION api.treasury_direct(TEXT, DATE, DATE, DATE) TO silo_api;

COMMENT ON FUNCTION api.treasury_direct(TEXT, DATE, DATE, DATE) IS
    'Tesouro Direto posted rates and prices per title (Tesouro Nacional open data, ODbL 1.0: credit Tesouro Nacional; every row carries source and licence). Newest base date first, then title and maturity. With no argument: every title on the newest base date held, which is the sovereign curve the retail platform posts. p_title is a title type as published (Tesouro Selic, Tesouro Prefixado, Tesouro IPCA+, Tesouro IPCA+ com Juros Semestrais, ...; case is ignored; an unknown type raises 22023 with the list); p_maturity one maturity; p_from..p_to a window of base dates (p_from alone: from p_from to the newest). NOTHING IS DERIVED: buy_rate_pct and sell_rate_pct are the morning quotes in % a year as published, and can be negative; buy_pu and sell_pu settle the next business day, base_pu is the same-day mark. These are QUOTES, NOT TRADES. A NULL price is a side the title was not on sale on. Refuses above 1000 rows (22023): about 60 titles a day, so narrow the window or name a title.';
