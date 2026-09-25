-- =============================================================================
-- 26_api_events_macro.sql
-- Three datasets SILO already holds, served through schema `api` (catalog v38,
-- DATA_INVENTORY.md §3 "Held and not served"):
--
--   api.company_events  a listed company's IPE filings (fatos relevantes,
--                       comunicados, assembly material …) from cia_event,
--                       the company resolved exactly as api.financials
--                       resolves p_id, with the RAD link as source_url.
--   api.macro_series    the non-inflation BACEN SGS series (SELIC target and
--                       daily rate, CDI, IGP-M, INPC, poupança, the BRL/USD
--                       and BRL/EUR SGS rates, monthly GDP) from bacen_sgs.
--   api.ptax            BACEN's PTAX buy / sell rate per currency per day
--                       from bacen_ptax, as published.
--
-- NOTHING IS DERIVED. Every value is the source's, in the source's unit, and
-- the unit rides on the row. No 12-month chain (api.inflation has the one
-- derived inflation number), no annualisation, no rebasing, no fill.
--
-- company_events. cia_event keeps every (protocolo, versao) CVM publishes; one
-- row per PROTOCOL is served — its newest version, like api.financials serves
-- the newest version of a statement — with `version` saying which. The window
-- is the DELIVERY date (Data_Entrega; the CSV prints a date, no time), falling
-- back to the reference date for a row CVM published without one. Two
-- honest limits, both on the coverage() row: CVM assigned no protocol number
-- before 2015 (and still omits it on a minority of filings), and cia_event's
-- key is (protocolo, versao), so those filings are not held at all
-- (DATA_INVENTORY.md §2 — a key is never synthesized); history therefore
-- starts in 2015 and is not complete for any year. The company is resolved by
-- api.company_ref: a ticker only through CVM's published FCA map (active
-- listings), a 14-digit CNPJ, or a CVM code — never by name. An id that
-- resolves to nothing is an empty result, as for api.financials.
--
-- macro_series. The registry is api.macro_registry(), mirrored from
-- SGS_SERIES minus INFLATION_SERIES in src/pipeline/bacen_pipeline.py
-- (tests/test_wave3_contract.py pins the two). Only registry codes are
-- served — bacen_sgs.series_name is an ingest label, never trusted for naming
-- — and the IPCA set is refused with a pointer to api.inflation, which serves
-- it with its own caveats. Measured against api.bcb.gov.br on 2026-09-25:
-- SELIC_META (432) is dated per CALENDAR day and published AHEAD to the next
-- Copom date (the last observation read 2026-11-04), so the default window
-- ends today; POUPANCA (25) is the old-rule deposit return ("Depósitos de
-- poupança até 03.05.2012 - Rentabilidade no período" in BACEN's catalogue),
-- one value per anniversary day, each the return over the month that starts
-- on that date — not a calendar-month figure; SELIC_DIARIA (11) and CDI (12)
-- are percent per business day.
--
-- ptax. bacen_ptax holds one row per (currency, day): BRL per ONE unit of the
-- currency (JPY included), compra and venda. BACEN publishes up to five
-- bulletins a day (Abertura, three Intermediários, Fechamento) and the ingest
-- keeps the last one it received, which for any day that had ended when the
-- ingest ran is the Fechamento PTAX — measured 2026-09-22/23: the stored USD
-- venda equals SGS 1 and Olinda's Fechamento bulletin to four decimals. The
-- bulletin type itself is not stored, so a day ingested while bulletins were
-- still printing (only a manual mid-day dispatch; the cron runs 03:00 BRT)
-- carries an intermediate rate until the next run's 30-day refresh.
--
-- PRIVILEGES, ROW CAP: 19's and 24's. SECURITY DEFINER with an empty pinned
-- search_path, every relation schema-qualified; EXECUTE revoked from PUBLIC,
-- granted to anon / authenticated and to silo_api (the read bundle serve/
-- connects through), as api.fund_documents is. The landing tables carry no
-- client grant. One page plus one row, then api.assert_row_cap REFUSES with
-- 22023 above 1000 — never trimmed, no cursor: narrow the window.
--
-- Ordering: after 19 (api.assert_row_cap, api.company_ref). The guard below
-- fails the apply loudly if either is missing.
-- =============================================================================

BEGIN;
SET statement_timeout = '30s';

DO $guard$
BEGIN
    IF to_regprocedure('api.assert_row_cap(bigint, boolean, text)') IS NULL
       OR to_regprocedure('api.company_ref(text)') IS NULL THEN
        RAISE EXCEPTION '26_api_events_macro.sql needs api.assert_row_cap and api.company_ref from 19_api_contract.sql; apply 19 first';
    END IF;
    IF to_regclass('public.cia_event') IS NULL
       OR to_regclass('public.bacen_sgs') IS NULL
       OR to_regclass('public.bacen_ptax') IS NULL THEN
        RAISE EXCEPTION '26_api_events_macro.sql serves cia_event, bacen_sgs and bacen_ptax; apply the schema and migrations first';
    END IF;
END
$guard$;

-- ---------------------------------------------------------------------------
-- company_events — one company's IPE filings, newest delivery first
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION api.company_events(
    p_id       TEXT,                 -- ticker (FCA map, active listings), 14-digit CNPJ or CVM code
    p_from     DATE DEFAULT NULL,    -- first delivery day; NULL = 12 months before p_to (or today)
    p_to       DATE DEFAULT NULL,    -- last delivery day, inclusive; NULL = today
    p_category TEXT DEFAULT NULL     -- one categoria exactly as CVM labels it (e.g. Fato Relevante); NULL = every category
)
RETURNS TABLE (
    cd_cvm         TEXT,    -- CVM code of the company
    cnpj           TEXT,    -- the filing's own CNPJ_Companhia, as filed
    company        TEXT,    -- cia_company's registered name
    ticker         TEXT,    -- the code p_id resolved through, when it was a ticker; NULL otherwise
    delivery_date  DATE,    -- Data_Entrega (CVM prints a date, no time)
    reference_date DATE,    -- Data_Referencia
    category       TEXT,    -- Categoria, as filed
    event_type     TEXT,    -- Tipo, as filed
    species        TEXT,    -- Especie, as filed
    subject        TEXT,    -- Assunto, as filed
    protocol       TEXT,    -- Protocolo_Entrega
    version        INT,     -- the newest Versao held for the protocol (the one served)
    source_url     TEXT,    -- Link_Download: the document on CVM's RAD
    source         TEXT
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $fn$
#variable_conflict use_column
DECLARE
    v_cat   TEXT := NULLIF(btrim(COALESCE(p_category, '')), '');
    v_to    DATE := COALESCE(p_to, CURRENT_DATE);
    v_from  DATE;
    v_known TEXT;
BEGIN
    IF p_id IS NULL OR btrim(p_id) = '' THEN
        RAISE EXCEPTION
            'company_events needs p_id: a ticker, a 14-digit CNPJ or a CVM code (find one with lookup)'
            USING ERRCODE = '22023';
    END IF;

    v_from := COALESCE(p_from, (v_to - INTERVAL '12 months')::date);
    IF v_from > v_to THEN
        RAISE EXCEPTION 'company_events: p_from (%) is after p_to (%)', v_from, v_to
            USING ERRCODE = '22023';
    END IF;

    IF v_cat IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM public.cia_event e WHERE e.categoria = v_cat
    ) THEN
        SELECT string_agg(c.categoria, ', ' ORDER BY c.categoria)
          INTO v_known
          FROM (SELECT DISTINCT e.categoria FROM public.cia_event e
                WHERE e.categoria IS NOT NULL) c;
        RAISE EXCEPTION
            'unknown IPE category %; cia_event holds: %', p_category, COALESCE(v_known, '(none)')
            USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    WITH ref AS (
        SELECT r.cd_cvm, r.company, r.ticker FROM api.company_ref(p_id) r
    ),
    latest AS (
        -- One row per protocol: its newest version.
        SELECT DISTINCT ON (e.protocolo)
               e.cd_cvm, e.cnpj_cia, e.data_entrega, e.data_refer, e.categoria,
               e.tipo, e.especie, e.assunto, e.protocolo, e.versao, e.link_download
        FROM public.cia_event e
        JOIN ref r ON r.cd_cvm = e.cd_cvm
        WHERE (v_cat IS NULL OR e.categoria = v_cat)
        ORDER BY e.protocolo, e.versao DESC NULLS LAST
    ),
    -- One page + one, then assert_row_cap REFUSES (22023). No cursor.
    page AS (
        SELECT l.cd_cvm, l.cnpj_cia, r.company, r.ticker,
               (l.data_entrega AT TIME ZONE 'UTC')::date AS d_deliv,
               l.data_refer, l.categoria, l.tipo, l.especie, l.assunto,
               l.protocolo, l.versao, l.link_download
        FROM latest l
        CROSS JOIN ref r
        WHERE COALESCE((l.data_entrega AT TIME ZONE 'UTC')::date, l.data_refer) BETWEEN v_from AND v_to
        ORDER BY COALESCE((l.data_entrega AT TIME ZONE 'UTC')::date, l.data_refer) DESC, l.protocolo DESC
        LIMIT 1001
    )
    SELECT g.cd_cvm, g.cnpj_cia, g.company, g.ticker, g.d_deliv, g.data_refer,
           g.categoria, g.tipo, g.especie, g.assunto, g.protocolo, g.versao,
           g.link_download, 'cvm_ipe'::text
    FROM page g
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'company_events')
    ORDER BY COALESCE(g.d_deliv, g.data_refer) DESC, g.protocolo DESC
    LIMIT 1000;
END;
$fn$;

REVOKE ALL ON FUNCTION api.company_events(TEXT, DATE, DATE, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.company_events(TEXT, DATE, DATE, TEXT) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION api.company_events(TEXT, DATE, DATE, TEXT) TO silo_api;

COMMENT ON FUNCTION api.company_events(TEXT, DATE, DATE, TEXT) IS
    'A listed company''s IPE filings to CVM (cia_event) — fatos relevantes, comunicados ao mercado, assembly material and the rest — newest delivery first, one row per protocol (its newest version; version says which), every text field as filed: category, event_type, species, subject, plus delivery_date, reference_date, protocol and source_url, the document''s link on CVM''s RAD. p_id is resolved exactly as api.financials resolves it: a ticker only through CVM''s published FCA map (active listings), a 14-digit CNPJ or a CVM code — never a name; an id that resolves to nothing returns no rows. Window = delivery date (the reference date for a row published without one), default the 12 months before p_to or today. p_category matches CVM''s label exactly and an unknown one raises 22023 listing the categories held. History starts in 2015: CVM assigned no protocol number before then (and omits it on a minority of later filings), and a filing without one is not held, because cia_event''s key is (protocolo, versao) and a key is never synthesized — coverage() company_events says so. More than 1000 rows RAISES 22023 (never trimmed): narrow the window or pin p_category.';

-- ---------------------------------------------------------------------------
-- macro_registry — the non-inflation SGS series macro_series serves.
-- Internal (no client grant): labels, codes and units only.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION api.macro_registry()
RETURNS TABLE (series TEXT, sgs_code INT, unit TEXT, frequency TEXT)
LANGUAGE sql
IMMUTABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    SELECT * FROM (VALUES
        ('SELIC_META',   432,   'pct_year',     'daily'),
        ('SELIC_DIARIA', 11,    'pct_day',      'daily'),
        ('CDI',          12,    'pct_day',      'daily'),
        ('IGPM',         189,   'pct_month',    'monthly'),
        ('INPC',         188,   'pct_month',    'monthly'),
        ('POUPANCA',     25,    'pct_period',   'daily'),
        ('USDBRL',       1,     'brl_per_usd',  'daily'),
        ('EURBRL',       21619, 'brl_per_eur',  'daily'),
        ('PIB',          4380,  'brl_million',  'monthly')
    ) AS r(series, sgs_code, unit, frequency);
$$;

REVOKE ALL ON FUNCTION api.macro_registry() FROM PUBLIC;

COMMENT ON FUNCTION api.macro_registry() IS
    'Internal. The series api.macro_series serves — label, SGS code, unit, frequency — mirrored from SGS_SERIES minus INFLATION_SERIES in src/pipeline/bacen_pipeline.py. Units: pct_year = % a.a. (the Copom target), pct_day = % per business day, pct_month = % change in the month, pct_period = % over the month starting on that anniversary day (old-rule poupança), brl_per_usd / brl_per_eur = BRL per unit, brl_million = R$ millions at current prices.';

-- ---------------------------------------------------------------------------
-- macro_series — one non-inflation SGS series, as published
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION api.macro_series(
    p_series TEXT,                -- a label (SELIC_META, CDI, IGPM, …) or its SGS code ('432')
    p_from   DATE DEFAULT NULL,   -- NULL = 12 months (daily series) / 120 months (monthly) before p_to
    p_to     DATE DEFAULT NULL    -- NULL = today
)
RETURNS TABLE (
    reference_date DATE,
    series         TEXT,
    sgs_code       INT,
    value          NUMERIC,
    unit           TEXT,
    frequency      TEXT,
    source         TEXT
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $fn$
#variable_conflict use_column
DECLARE
    v_key   TEXT := upper(btrim(COALESCE(p_series, '')));
    v_code  INT;
    v_label TEXT;
    v_unit  TEXT;
    v_freq  TEXT;
    v_to    DATE := COALESCE(p_to, CURRENT_DATE);
    v_from  DATE;
    v_known TEXT;
BEGIN
    SELECT reg.sgs_code, reg.series, reg.unit, reg.frequency
      INTO v_code, v_label, v_unit, v_freq
      FROM api.macro_registry() reg
     WHERE reg.series = v_key OR reg.sgs_code::text = v_key;

    IF v_code IS NULL THEN
        IF EXISTS (SELECT 1 FROM api.inflation_registry() i
                   WHERE i.series = v_key OR i.sgs_code::text = v_key) THEN
            RAISE EXCEPTION
                'macro_series: % is an IPCA series; api.inflation serves the IPCA set with its own units and caveats',
                p_series
                USING ERRCODE = '22023';
        END IF;
        SELECT string_agg(reg.series || ' (' || reg.sgs_code || ')', ', ' ORDER BY reg.series)
          INTO v_known FROM api.macro_registry() reg;
        RAISE EXCEPTION
            'unknown macro series %; macro_series serves: %', COALESCE(p_series, 'NULL'), v_known
            USING ERRCODE = '22023';
    END IF;

    v_from := COALESCE(p_from,
                       (v_to - CASE v_freq WHEN 'daily' THEN INTERVAL '12 months'
                                           ELSE INTERVAL '120 months' END)::date);
    IF v_from > v_to THEN
        RAISE EXCEPTION 'macro_series: p_from (%) is after p_to (%)', v_from, v_to
            USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    -- One page + one, then assert_row_cap REFUSES (22023). No cursor.
    WITH page AS (
        SELECT b.reference_date AS d, b.value AS v
        FROM public.bacen_sgs b
        WHERE b.series_code = v_code
          AND b.reference_date BETWEEN v_from AND v_to
        ORDER BY b.reference_date
        LIMIT 1001
    )
    SELECT g.d, v_label, v_code, g.v, v_unit, v_freq, 'bacen_sgs'::text
    FROM page g
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'macro_series')
    ORDER BY g.d
    LIMIT 1000;
END;
$fn$;

REVOKE ALL ON FUNCTION api.macro_series(TEXT, DATE, DATE) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.macro_series(TEXT, DATE, DATE) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION api.macro_series(TEXT, DATE, DATE) TO silo_api;

COMMENT ON FUNCTION api.macro_series(TEXT, DATE, DATE) IS
    'One non-inflation BACEN SGS series as published, oldest first, the unit on every row: SELIC_META (432, % a.a., the Copom target — dated per calendar day and published AHEAD to the next meeting, so an explicit p_to after today can return forward-dated rows), SELIC_DIARIA (11) and CDI (12, % per business day), IGPM (189) and INPC (188, % change in the month), POUPANCA (25, the OLD-RULE deposit return for deposits until 2012-05-03: one value per anniversary day, each the return over the month starting that day — not a calendar-month figure), USDBRL (1) and EURBRL (21619, BRL per unit, SGS''s selling rates; PTAX buy and sell per currency are api.ptax), PIB (4380, monthly GDP, R$ millions, current prices). p_series takes the label or the SGS code; an IPCA code is refused with a pointer to api.inflation, and an unknown series raises 22023 listing what exists. Nothing is derived, annualised or filled; a missing day stays missing. Default window 12 months for the daily series, 120 for the monthly ones. More than 1000 rows RAISES 22023 (never trimmed): narrow p_from/p_to.';

-- ---------------------------------------------------------------------------
-- ptax — PTAX buy / sell per currency, as published
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION api.ptax(
    p_currency TEXT,               -- ISO code held in bacen_ptax (USD, EUR, GBP, JPY, ARS)
    p_from     DATE DEFAULT NULL,  -- NULL = 12 months before p_to
    p_to       DATE DEFAULT NULL   -- NULL = today
)
RETURNS TABLE (
    reference_date DATE,
    currency       TEXT,
    buy_rate       NUMERIC,
    sell_rate      NUMERIC,
    unit           TEXT,
    source         TEXT
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $fn$
#variable_conflict use_column
DECLARE
    v_cur   TEXT := upper(btrim(COALESCE(p_currency, '')));
    v_to    DATE := COALESCE(p_to, CURRENT_DATE);
    v_from  DATE;
    v_known TEXT;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM public.bacen_ptax x WHERE x.currency = v_cur) THEN
        SELECT string_agg(c.currency, ', ' ORDER BY c.currency)
          INTO v_known
          FROM (SELECT DISTINCT x.currency FROM public.bacen_ptax x) c;
        RAISE EXCEPTION
            'unknown PTAX currency %; bacen_ptax holds: %', COALESCE(p_currency, 'NULL'), COALESCE(v_known, '(none)')
            USING ERRCODE = '22023';
    END IF;

    v_from := COALESCE(p_from, (v_to - INTERVAL '12 months')::date);
    IF v_from > v_to THEN
        RAISE EXCEPTION 'ptax: p_from (%) is after p_to (%)', v_from, v_to
            USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    -- One page + one, then assert_row_cap REFUSES (22023). No cursor.
    WITH page AS (
        SELECT x.reference_date AS d, x.buy_rate AS b, x.sell_rate AS s
        FROM public.bacen_ptax x
        WHERE x.currency = v_cur
          AND x.reference_date BETWEEN v_from AND v_to
        ORDER BY x.reference_date
        LIMIT 1001
    )
    SELECT g.d, v_cur, g.b, g.s, ('brl_per_' || lower(v_cur))::text, 'bacen_ptax'::text
    FROM page g
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'ptax')
    ORDER BY g.d
    LIMIT 1000;
END;
$fn$;

REVOKE ALL ON FUNCTION api.ptax(TEXT, DATE, DATE) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.ptax(TEXT, DATE, DATE) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION api.ptax(TEXT, DATE, DATE) TO silo_api;

COMMENT ON FUNCTION api.ptax(TEXT, DATE, DATE) IS
    'BACEN''s PTAX rate for one currency, oldest first: buy_rate (compra) and sell_rate (venda) as published, BRL per ONE unit of the currency (JPY and ARS included; unit says so), one row per business day. BACEN prints up to five bulletins a day and the ingest keeps the last one received, which for a completed day is the Fechamento PTAX (measured 2026-09-22/23: USD venda equals SGS 1 and Olinda''s Fechamento to four decimals); the bulletin type is not stored. p_currency is an ISO code held in bacen_ptax; an unknown one raises 22023 listing the currencies held. Nothing is derived or filled — no mid rate, no cross rate, a holiday has no row. Default window the 12 months before p_to or today. More than 1000 rows RAISES 22023 (never trimmed): narrow p_from/p_to.';

COMMIT;
