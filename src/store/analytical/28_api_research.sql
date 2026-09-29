-- =============================================================================
-- 28_api_research.sql
-- The research universe, served through schema `api` (catalog v43; the
-- research-seam spec, docs/planning/RESEARCH_SEAM.md §4; ticket #411):
--
--   api.research_universe   every ticker+ISIN pair of listed shares and units
--                           traded on the B3 cash market since 2019-01-02
--
-- WHY A MATERIALIZED VIEW. The universe is an aggregate over about 700,000
-- COTAHIST rows. Measured 2026-09-29 on the live database: the bare aggregate
-- takes 1.6 s warm, and `anon` has statement_timeout = 3 s, so a function that
-- scanned the tape per call would time out cold. The view is rebuilt by every
-- apply (like dim_fund) and refreshed by cron (08_cron_schedules.sql), so
-- last_observed and n_sessions LAG the tape by up to a day; built_at says when.
--
-- MEMBERSHIP is decided by the ISIN's own instrument code, characters 7-9:
--   ACN  shares (ON / PN and their classes)
--   CDA  units, and UNT the older unit code
-- with one extra clause for units: the ticker must end in 11, B3's convention
-- for units. Without it 6 non-units pass (BPAC13, three rows, unit
-- subscription receipts; AZUL97, AZUL98, AZUL99, which are not units). The
-- subscription receipts of shares (ISIN code R01 .. R21, tickers ending 9 or
-- 10) are excluded by the ISIN rule itself: `instrument_type = 'equity'` would
-- let about 100 of them in, because their ESPECI starts with ON / PN.
--
-- IDENTITY IS THE ISIN. A rename is a new ISIN, so a new row; nothing links
-- the two. A gap shows as n_sessions far below the calendar span (NATU3 is
-- one ISIN with no sessions from 2019-12 to 2025-07). NEOE3 and NEOE3B share
-- one ISIN (NEOE3B printed on one session, 2019-06-26): two rows, same isin.
--
-- NOTHING IS DERIVED FROM A NAME. cnpj comes from CVM's published FCA
-- ticker map (vw_company_ticker, migration 25), and cnpj_basis says how:
--   fca_ticker       the FCA row for that exact ticker, and only one CNPJ
--                    claims the ticker
--   fca_issuer_stem  the ticker's own 4-letter stem, when exactly one CNPJ
--                    holds an FCA ticker with that stem (an inference: the FCA
--                    never named THIS ticker; the basis column says so)
--   NULL             no link; cnpj and setor_current are NULL too
-- setor_current is cia_company.setor (CVM's cadastro) as of today, NULL when a
-- CNPJ carries more than one distinct setor. It is a current classification,
-- not the setor on a past date. cia_company.segmento is CVM's registration
-- category (Categoria A / B), not a market segment, so it is not served.
--
-- Listing and delisting dates are NOT served (FCA dates are not historical,
-- #373), and neither is is_active (vw_company_ticker marks dead tickers
-- active, #381): a caller reads "still trading" from last_observed.
-- =============================================================================

BEGIN;
SET statement_timeout = '5min';

DO $guard$
BEGIN
    IF to_regprocedure('api.assert_row_cap(bigint,boolean,text)') IS NULL THEN
        RAISE EXCEPTION '28_api_research.sql needs api.assert_row_cap from 19_api_contract.sql; apply 19 first';
    END IF;
    IF to_regclass('public.b3_cotahist') IS NULL
       OR to_regclass('public.vw_company_ticker') IS NULL
       OR to_regclass('public.cia_company') IS NULL THEN
        RAISE EXCEPTION '28_api_research.sql reads b3_cotahist, vw_company_ticker and cia_company; apply the schema and migrations first';
    END IF;
END
$guard$;

-- Dropped and re-created on every apply, like dim_fund: a definition change
-- lands at once, and the re-create is itself a refresh. Nothing depends on it
-- except api.research_universe, which is re-created below.
DROP MATERIALIZED VIEW IF EXISTS public.mv_research_universe CASCADE;

CREATE MATERIALIZED VIEW public.mv_research_universe AS
WITH tape AS (
    SELECT
        q.codneg,
        q.isin,
        min(q.trade_date)                                        AS first_observed,
        max(q.trade_date)                                        AS last_observed,
        -- Distinct sessions, not rows: the quote grain also carries board and
        -- term, so count(*) could count a session twice.
        count(DISTINCT q.trade_date)                             AS n_sessions
    FROM public.b3_cotahist q
    WHERE q.tpmerc = '010'
      AND q.trade_date >= DATE '2019-01-02'
      AND q.isin IS NOT NULL
      AND (
            substr(q.isin, 7, 3) = 'ACN'
         OR (substr(q.isin, 7, 3) IN ('CDA', 'UNT') AND q.codneg ~ '11$')
          )
    GROUP BY q.codneg, q.isin
),
-- FCA rows with a real B3 ticker shape only: the map also holds placeholders
-- ('0000', 'NÃO', 'NÃO HÁ') that would otherwise claim several CNPJs.
fca AS (
    SELECT vt.cnpj_cia, vt.codneg, left(vt.codneg, 4) AS stem
    FROM public.vw_company_ticker vt
    WHERE vt.codneg ~ '^[A-Z]{4}[0-9]{1,2}[A-Z]?$'
),
by_ticker AS (
    SELECT codneg, min(cnpj_cia) AS cnpj_cia
    FROM fca
    GROUP BY codneg
    HAVING count(DISTINCT cnpj_cia) = 1
),
by_stem AS (
    SELECT stem, min(cnpj_cia) AS cnpj_cia
    FROM fca
    GROUP BY stem
    HAVING count(DISTINCT cnpj_cia) = 1
),
setor AS (
    SELECT cnpj_cia, min(setor) AS setor
    FROM public.cia_company
    WHERE setor IS NOT NULL
    GROUP BY cnpj_cia
    HAVING count(DISTINCT setor) = 1
)
SELECT
    t.codneg                                        AS ticker,
    t.isin,
    -- From the ISIN's own instrument code, the same field membership uses, so
    -- the type is one value per pair whatever a session's ESPECI text said.
    CASE substr(t.isin, 7, 3) WHEN 'ACN' THEN 'equity' ELSE 'unit' END AS instrument_type,
    l.cnpj,
    l.cnpj_basis,
    t.first_observed,
    t.last_observed,
    t.n_sessions,
    s.setor                                         AS setor_current,
    now()                                           AS built_at
FROM tape t
LEFT JOIN by_ticker bt ON bt.codneg = t.codneg
LEFT JOIN by_stem   bs ON bs.stem = left(t.codneg, 4) AND bt.cnpj_cia IS NULL
CROSS JOIN LATERAL (
    SELECT
        coalesce(bt.cnpj_cia, bs.cnpj_cia) AS cnpj,
        CASE
            WHEN bt.cnpj_cia IS NOT NULL THEN 'fca_ticker'
            WHEN bs.cnpj_cia IS NOT NULL THEN 'fca_issuer_stem'
        END                                AS cnpj_basis
) l
LEFT JOIN setor s ON s.cnpj_cia = l.cnpj;

-- One row per pair: the unique index is also what lets cron refresh CONCURRENTLY.
CREATE UNIQUE INDEX uq_mv_research_universe ON public.mv_research_universe (ticker, isin);

COMMENT ON MATERIALIZED VIEW public.mv_research_universe IS
    'Internal (no client grant): one row per ticker+ISIN pair of shares and units on the B3 cash market since 2019-01-02, membership by the ISIN instrument code (ACN; CDA / UNT with a ticker ending 11). Read only through api.research_universe. Rebuilt by every analytical apply and refreshed daily, so last_observed lags the tape by up to a day.';

-- Smoke check, in the shape of dim_fund's: a warehouse with a tape has a universe.
DO $$
BEGIN
    IF (SELECT count(*) FROM public.mv_research_universe) = 0
       AND EXISTS (SELECT 1 FROM public.b3_cotahist WHERE tpmerc = '010' LIMIT 1) THEN
        IF current_setting('silo.ci_smoke_bypass', true) = 'on' THEN
            RAISE WARNING 'mv_research_universe smoke check skipped (silo.ci_smoke_bypass=on)';
        ELSE
            RAISE EXCEPTION 'mv_research_universe is empty although b3_cotahist holds cash quotes';
        END IF;
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- research_universe
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION api.research_universe()
RETURNS TABLE (
    ticker          TEXT,
    isin            TEXT,
    instrument_type TEXT,         -- 'equity' (ISIN code ACN) | 'unit' (CDA, UNT)
    cnpj            TEXT,         -- 14 digits, NULL when no FCA link
    cnpj_basis      TEXT,         -- 'fca_ticker' | 'fca_issuer_stem' | NULL
    first_observed  DATE,         -- first session SILO holds a trade for this pair (not a listing date)
    last_observed   DATE,         -- last such session (not a delisting date)
    n_sessions      INT,          -- distinct sessions with a trade; far below the span means a gap
    setor_current   TEXT,         -- CVM cadastro setor as of TODAY, NULL without a link
    built_at        TIMESTAMPTZ   -- when the view was last built or refreshed
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    WITH page AS (
        SELECT u.ticker, u.isin, u.instrument_type, u.cnpj, u.cnpj_basis,
               u.first_observed, u.last_observed, u.n_sessions::int AS n_sessions,
               u.setor_current, u.built_at
        FROM public.mv_research_universe u
        ORDER BY u.ticker, u.isin
        LIMIT 1001
    )
    SELECT g.ticker, g.isin, g.instrument_type, g.cnpj, g.cnpj_basis,
           g.first_observed, g.last_observed, g.n_sessions, g.setor_current, g.built_at
    FROM page g
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'research_universe')
    ORDER BY g.ticker, g.isin
    LIMIT 1000;
$$;

REVOKE ALL ON FUNCTION api.research_universe() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.research_universe() TO anon, authenticated;
GRANT EXECUTE ON FUNCTION api.research_universe() TO silo_api;

COMMENT ON FUNCTION api.research_universe() IS
    'The research universe: one row per ticker+ISIN pair of listed shares and units traded on the B3 cash market since 2019-01-02 (the start of the tape), ordered by ticker then ISIN. Membership is the ISIN''s own instrument code (ACN shares; CDA and UNT units, whose ticker must end in 11); subscription receipts, BDRs, funds and indices are outside it. The ISIN is the identity: a rename is a NEW row and nothing links it to the old one, and two tickers can share an ISIN (NEOE3 and NEOE3B). first_observed / last_observed / n_sessions are facts about SILO''s tape, not listing or delisting dates (FCA dates are not historical); n_sessions far below the calendar span is a gap (NATU3). cnpj comes from CVM''s published FCA ticker map and cnpj_basis says how: fca_ticker (that exact ticker), fca_issuer_stem (the ticker''s 4-letter stem, when exactly one CNPJ holds an FCA ticker with it: an inference), or NULL (no link; cnpj and setor_current are NULL). setor_current is CVM''s cadastro setor as of today, never the setor on a past date. Read the universe at a date T as the rows with first_observed <= T <= last_observed; a pair inside a gap still matches. Served from a view rebuilt daily: last_observed lags the tape by up to a day, built_at says when. Not trimmed: more than 1000 rows RAISES 22023.';

COMMIT;
