-- =============================================================================
-- 41_api_share_counts.sql
-- A listed company's share count and free float through time, as filed with
-- CVM (catalog v86, #1161). Migration 87 holds the three landing tables.
--
--   api.share_counts  issued (paid-in) shares ON / PN / total, plus treasury
--                     shares where the form has them, one row per filed
--                     period and source:
--                       * cvm_itr / cvm_dfp: ITR / DFP composição do capital,
--                         quarterly, from 2020 (cia_share_count). CVM's ITR and
--                         DFP zips before 2020 do not carry this member.
--                       * cvm_fre: FRE capital social, yearly, from 2010
--                         (cia_fre_capital), the "Capital Integralizado" row.
--                         The FRE has no treasury count: those columns are NULL.
--   api.free_float    FRE distribuição do capital, yearly, from 2010
--                     (cia_fre_free_float): shares in circulation ON / PN /
--                     total, their percent of each class as the company filed
--                     it, and the shareholder counts.
--
-- VERSIONS. A company refiles a form; every version is stored. Both functions
-- serve the newest version of each (company, period, source). That is NOT
-- point-in-time: a refiled count replaces the first one.
--
-- NOTHING IS DERIVED. No count is computed from another one, no period is
-- filled forward, and a value the form leaves empty stays NULL. In the FRE, a
-- version can list more than one "Capital Integralizado" row; the row with the
-- newest approval date (then the highest CVM row id) is served.
--
-- COMPANY. p_id is required and resolves as api.financials resolves it: a
-- ticker through CVM's FCA map (active listings), a 14-digit CNPJ or a CVM
-- code, never a name. The counts are per company, not per ticker: PETR3 and
-- PETR4 return the same rows. An id that resolves to nothing returns no rows.
--
-- PRIVILEGES, ROW CAP: 26's. SECURITY DEFINER, empty pinned search_path, every
-- relation schema-qualified; EXECUTE revoked from PUBLIC, granted to anon /
-- authenticated and silo_api. One page plus one row, then api.assert_row_cap
-- REFUSES with 22023 above 1000 rows. One company holds far fewer.
--
-- Ordering: after 19 (api.assert_row_cap, api.company_ref).
-- =============================================================================

BEGIN;
SET statement_timeout = '30s';

DO $guard$
BEGIN
    IF to_regprocedure('api.assert_row_cap(bigint, boolean, text)') IS NULL
       OR to_regprocedure('api.company_ref(text)') IS NULL THEN
        RAISE EXCEPTION '41_api_share_counts.sql needs api.assert_row_cap and api.company_ref from 19_api_contract.sql; apply 19 first';
    END IF;
    IF to_regclass('public.cia_share_count') IS NULL
       OR to_regclass('public.cia_fre_capital') IS NULL
       OR to_regclass('public.cia_fre_free_float') IS NULL THEN
        RAISE EXCEPTION '41_api_share_counts.sql serves cia_share_count, cia_fre_capital and cia_fre_free_float; apply migration 87 first';
    END IF;
END
$guard$;

-- ---------------------------------------------------------------------------
-- api.share_counts — issued and treasury shares, newest period first
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION api.share_counts(
    p_id   TEXT,                  -- ticker (FCA map, active listings), 14-digit CNPJ or CVM code
    p_from DATE DEFAULT NULL,     -- first reference date; NULL = no lower bound
    p_to   DATE DEFAULT NULL      -- last reference date, inclusive; NULL = no upper bound
)
RETURNS TABLE (
    cd_cvm          TEXT,      -- CVM code of the company
    cnpj            TEXT,      -- the company's CNPJ
    company         TEXT,      -- cia_company's registered name
    reference_date  DATE,      -- the period the form reports (quarter end; FRE: its reference date)
    version         INT,       -- the newest Versao held for the period
    shares_on       NUMERIC,   -- issued ordinary shares (ON)
    shares_pn       NUMERIC,   -- issued preferred shares (PN)
    shares_total    NUMERIC,   -- issued shares, total
    treasury_on     NUMERIC,   -- ordinary shares in treasury (NULL on cvm_fre)
    treasury_pn     NUMERIC,   -- preferred shares in treasury (NULL on cvm_fre)
    treasury_total  NUMERIC,   -- shares in treasury, total (NULL on cvm_fre)
    source          TEXT       -- cvm_itr | cvm_dfp | cvm_fre
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $fn$
#variable_conflict use_column
DECLARE
    v_id TEXT := NULLIF(btrim(COALESCE(p_id, '')), '');
BEGIN
    IF v_id IS NULL THEN
        RAISE EXCEPTION 'share_counts: p_id is required (a ticker, a 14-digit CNPJ or a CVM code)'
            USING ERRCODE = '22023';
    END IF;
    IF p_from IS NOT NULL AND p_to IS NOT NULL AND p_from > p_to THEN
        RAISE EXCEPTION 'share_counts: p_from (%) is after p_to (%)', p_from, p_to
            USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    WITH ref AS (
        SELECT r.cd_cvm, r.cnpj, r.company FROM api.company_ref(v_id) r
    ),
    quarterly AS (
        SELECT DISTINCT ON (s.doc_type, s.dt_refer)
               s.dt_refer, s.versao, s.qt_ordin, s.qt_pref, s.qt_total,
               s.qt_ordin_tesouro, s.qt_pref_tesouro, s.qt_total_tesouro,
               'cvm_' || s.doc_type AS src
        FROM public.cia_share_count s
        WHERE s.cnpj_cia = (SELECT ref.cnpj FROM ref)
          AND (p_from IS NULL OR s.dt_refer >= p_from)
          AND (p_to   IS NULL OR s.dt_refer <= p_to)
        ORDER BY s.doc_type, s.dt_refer, s.versao DESC NULLS LAST
    ),
    fre_version AS (
        -- The newest FRE version of each reference date.
        SELECT DISTINCT ON (f.data_refer) f.data_refer, f.versao
        FROM public.cia_fre_capital f
        WHERE f.cnpj_cia = (SELECT ref.cnpj FROM ref)
          AND (p_from IS NULL OR f.data_refer >= p_from)
          AND (p_to   IS NULL OR f.data_refer <= p_to)
        ORDER BY f.data_refer, f.versao DESC NULLS LAST
    ),
    yearly AS (
        SELECT DISTINCT ON (f.data_refer)
               f.data_refer, f.versao, f.qt_ordin, f.qt_pref, f.qt_total
        FROM public.cia_fre_capital f
        JOIN fre_version v
          ON v.data_refer = f.data_refer
         AND v.versao IS NOT DISTINCT FROM f.versao
        WHERE f.cnpj_cia = (SELECT ref.cnpj FROM ref)
          AND f.tipo_capital = 'Capital Integralizado'
        ORDER BY f.data_refer, f.dt_autorizacao DESC NULLS LAST,
                 f.id_capital_social DESC NULLS LAST
    ),
    all_rows AS (
        SELECT q.dt_refer AS d, q.versao AS v, q.qt_ordin AS o, q.qt_pref AS p,
               q.qt_total AS t, q.qt_ordin_tesouro AS tro, q.qt_pref_tesouro AS trp,
               q.qt_total_tesouro AS trt, q.src
        FROM quarterly q
        UNION ALL
        SELECT y.data_refer, y.versao, y.qt_ordin, y.qt_pref, y.qt_total,
               NULL::numeric, NULL::numeric, NULL::numeric, 'cvm_fre'
        FROM yearly y
    ),
    -- One page + one, then assert_row_cap REFUSES (22023). No cursor.
    page AS (
        SELECT a.* FROM all_rows a
        ORDER BY a.d DESC, a.src
        LIMIT 1001
    )
    SELECT ref.cd_cvm, ref.cnpj, ref.company, g.d, g.v, g.o, g.p, g.t,
           g.tro, g.trp, g.trt, g.src
    FROM page g CROSS JOIN ref
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'share_counts')
    ORDER BY g.d DESC, g.src
    LIMIT 1000;
END;
$fn$;

REVOKE ALL ON FUNCTION api.share_counts(TEXT, DATE, DATE) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.share_counts(TEXT, DATE, DATE) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION api.share_counts(TEXT, DATE, DATE) TO silo_api;

COMMENT ON FUNCTION api.share_counts(TEXT, DATE, DATE) IS
    'A listed company''s issued share count through time, as filed with CVM: ON, PN and total, plus treasury shares where the form has them. source = cvm_itr / cvm_dfp (composição do capital, quarterly, from 2020) or cvm_fre (FRE capital social, Capital Integralizado, yearly, from 2010; no treasury count, those columns NULL). The newest version of each period is served, which is not point-in-time. Nothing is derived or filled forward; an empty value stays NULL. Counts are per company, not per ticker. p_id is required and resolves as api.financials resolves it (ticker through CVM''s FCA map, 14-digit CNPJ or CVM code, never a name); an id that resolves to nothing returns no rows. p_from / p_to bound the reference date (NULL = no bound). Newest period first. More than 1000 rows RAISES 22023 (never trimmed).';

-- ---------------------------------------------------------------------------
-- api.free_float — shares in circulation, newest reference date first
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION api.free_float(
    p_id   TEXT,                  -- ticker (FCA map, active listings), 14-digit CNPJ or CVM code
    p_from DATE DEFAULT NULL,     -- first reference date; NULL = no lower bound
    p_to   DATE DEFAULT NULL      -- last reference date, inclusive; NULL = no upper bound
)
RETURNS TABLE (
    cd_cvm                TEXT,      -- CVM code of the company
    cnpj                  TEXT,      -- the company's CNPJ
    company               TEXT,      -- cia_company's registered name
    reference_date        DATE,      -- the FRE's reference date, not a filing date
    version               INT,       -- the newest Versao held for the date
    float_on              NUMERIC,   -- ordinary shares in circulation
    float_on_pct          NUMERIC,   -- percent of the ordinary shares, as filed
    float_pn              NUMERIC,   -- preferred shares in circulation
    float_pn_pct          NUMERIC,   -- percent of the preferred shares, as filed
    float_total           NUMERIC,   -- shares in circulation, total
    float_total_pct       NUMERIC,   -- percent of all shares, as filed
    holders_individual    INT,       -- shareholders who are individuals
    holders_corporate     INT,       -- shareholders who are legal entities
    holders_institutional INT,       -- institutional investors
    last_meeting_date     DATE,      -- the last shareholders' meeting
    source                TEXT       -- cvm_fre
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $fn$
#variable_conflict use_column
DECLARE
    v_id TEXT := NULLIF(btrim(COALESCE(p_id, '')), '');
BEGIN
    IF v_id IS NULL THEN
        RAISE EXCEPTION 'free_float: p_id is required (a ticker, a 14-digit CNPJ or a CVM code)'
            USING ERRCODE = '22023';
    END IF;
    IF p_from IS NOT NULL AND p_to IS NOT NULL AND p_from > p_to THEN
        RAISE EXCEPTION 'free_float: p_from (%) is after p_to (%)', p_from, p_to
            USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    WITH ref AS (
        SELECT r.cd_cvm, r.cnpj, r.company FROM api.company_ref(v_id) r
    ),
    -- One page + one, then assert_row_cap REFUSES (22023). No cursor.
    page AS (
        SELECT DISTINCT ON (f.data_refer) f.*
        FROM public.cia_fre_free_float f
        WHERE f.cnpj_cia = (SELECT ref.cnpj FROM ref)
          AND (p_from IS NULL OR f.data_refer >= p_from)
          AND (p_to   IS NULL OR f.data_refer <= p_to)
        ORDER BY f.data_refer DESC, f.versao DESC NULLS LAST
        LIMIT 1001
    )
    SELECT ref.cd_cvm, ref.cnpj, ref.company, g.data_refer, g.versao,
           g.qt_ordin_circ, g.pct_ordin_circ, g.qt_pref_circ, g.pct_pref_circ,
           g.qt_total_circ, g.pct_total_circ, g.n_acionistas_pf,
           g.n_acionistas_pj, g.n_acionistas_inst, g.dt_ultima_assembleia,
           'cvm_fre'::text
    FROM page g CROSS JOIN ref
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'free_float')
    ORDER BY g.data_refer DESC
    LIMIT 1000;
END;
$fn$;

REVOKE ALL ON FUNCTION api.free_float(TEXT, DATE, DATE) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.free_float(TEXT, DATE, DATE) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION api.free_float(TEXT, DATE, DATE) TO silo_api;

COMMENT ON FUNCTION api.free_float(TEXT, DATE, DATE) IS
    'A listed company''s free float through time, as filed in CVM''s FRE (distribuição do capital, yearly, from 2010): shares in circulation ON, PN and total, the percent of each class as the company filed it, and its shareholder counts (individuals, legal entities, institutional investors). Shares in circulation exclude the controller, its related parties, management and treasury. The newest version of each reference date is served, which is not point-in-time; reference_date is not a filing date. Nothing is derived; an empty value stays NULL. p_id is required and resolves as api.financials resolves it; an id that resolves to nothing returns no rows. p_from / p_to bound the reference date (NULL = no bound). Newest first. More than 1000 rows RAISES 22023 (never trimmed).';

COMMIT;
