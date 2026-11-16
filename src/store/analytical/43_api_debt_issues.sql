-- =============================================================================
-- 43_api_debt_issues.sql
-- api.debt_issues(p_id, p_from, p_to): the debt issues a listed company
-- describes in its CVM FRE, item "outros valores mobiliários" (catalog v88,
-- #1164). Migration 86 holds the landing table cvm_fre_outro_valor_mobiliario.
--
-- WHAT A ROW IS. One issue as the company files it: debentures, commercial
-- notes, CRI, CRA, financial bills, subscription warrants. One row often holds
-- several series of one issue. CVM publishes no ticker, ISIN or series code,
-- so a row does NOT join to a traded debenture.
--
-- COVERAGE. Only companies that file an FRE (listed issuers). A closed company
-- that issues debentures files no FRE and is not here.
--
-- RATE AND INDEXER ARE NOT PARSED. The remuneration exists only as free text
-- (terms_text), written differently by each company. It is served as filed.
-- No rate, indexer or spread is derived from it.
--
-- VERSIONS. A company refiles its FRE; every version is stored. This serves
-- the newest version of each reference date, which is NOT point-in-time.
--
-- COMPANY. p_id is required and resolves as api.financials resolves it
-- (api.company_ref): a ticker through CVM's FCA map, a 14-digit CNPJ or a CVM
-- code, never a name. An id that resolves to nothing returns no rows.
--
-- PRIVILEGES, ROW CAP: 41's. SECURITY DEFINER, empty pinned search_path, every
-- relation schema-qualified; EXECUTE revoked from PUBLIC, granted to anon /
-- authenticated and silo_api. One page plus one row, then api.assert_row_cap
-- REFUSES with 22023 above 1000 rows: narrow p_from / p_to.
--
-- Ordering: after 19 (api.assert_row_cap, api.company_ref).
-- =============================================================================

BEGIN;
SET statement_timeout = '30s';

DO $guard$
BEGIN
    IF to_regprocedure('api.assert_row_cap(bigint, boolean, text)') IS NULL
       OR to_regprocedure('api.company_ref(text)') IS NULL THEN
        RAISE EXCEPTION '43_api_debt_issues.sql needs api.assert_row_cap and api.company_ref from 19_api_contract.sql; apply 19 first';
    END IF;
    IF to_regclass('public.cvm_fre_outro_valor_mobiliario') IS NULL THEN
        RAISE EXCEPTION '43_api_debt_issues.sql serves cvm_fre_outro_valor_mobiliario; apply migration 86 first';
    END IF;
END
$guard$;

CREATE OR REPLACE FUNCTION api.debt_issues(
    p_id   TEXT,                  -- ticker (FCA map, active listings), 14-digit CNPJ or CVM code
    p_from DATE DEFAULT NULL,     -- first FRE reference date; NULL = no lower bound
    p_to   DATE DEFAULT NULL      -- last FRE reference date, inclusive; NULL = no upper bound
)
RETURNS TABLE (
    cd_cvm              TEXT,      -- CVM code of the company
    cnpj                TEXT,      -- the company's CNPJ
    company             TEXT,      -- cia_company's registered name
    reference_date      DATE,      -- the FRE's reference date, not a filing date
    version             INT,       -- the newest Versao held for the date
    security_type       TEXT,      -- Debêntures, Nota Comercial, Certificados de Recebíveis Imobiliários ...
    issue_name          TEXT,      -- the company's own name for the issue, as filed
    issue_date          DATE,      -- Data_Emissao
    maturity_date       DATE,      -- Data_Vencimento (the last series, when the row holds several)
    quantity            NUMERIC,   -- units issued
    issue_value         NUMERIC,   -- BRL issued
    outstanding_balance NUMERIC,   -- Saldo_Devedor, BRL, at the reference date
    transfer_restricted BOOLEAN,   -- TRUE when filed "Sim"; NULL when left empty
    convertible         BOOLEAN,   -- TRUE when filed "Sim"; NULL when left empty
    redeemable          BOOLEAN,   -- TRUE when filed "Sim"; NULL when left empty
    terms_text          TEXT,      -- remuneration, maturity and default terms as free text, NOT parsed
    source              TEXT       -- cvm_fre
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
        RAISE EXCEPTION 'debt_issues: p_id is required (a ticker, a 14-digit CNPJ or a CVM code)'
            USING ERRCODE = '22023';
    END IF;
    IF p_from IS NOT NULL AND p_to IS NOT NULL AND p_from > p_to THEN
        RAISE EXCEPTION 'debt_issues: p_from (%) is after p_to (%)', p_from, p_to
            USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    WITH ref AS (
        SELECT r.cd_cvm, r.cnpj, r.company FROM api.company_ref(v_id) r
    ),
    newest AS (
        -- The newest FRE version of each reference date.
        SELECT DISTINCT ON (f.data_refer) f.data_refer, f.versao
        FROM public.cvm_fre_outro_valor_mobiliario f
        WHERE f.cnpj_cia = (SELECT ref.cnpj FROM ref)
          AND (p_from IS NULL OR f.data_refer >= p_from)
          AND (p_to   IS NULL OR f.data_refer <= p_to)
        ORDER BY f.data_refer, f.versao DESC
    ),
    -- One page + one, then assert_row_cap REFUSES (22023). No cursor.
    page AS (
        SELECT f.*
        FROM public.cvm_fre_outro_valor_mobiliario f
        JOIN newest n ON n.data_refer = f.data_refer AND n.versao = f.versao
        WHERE f.cnpj_cia = (SELECT ref.cnpj FROM ref)
        ORDER BY f.data_refer DESC, f.data_vencimento NULLS LAST, f.identificacao, f.row_hash
        LIMIT 1001
    )
    SELECT ref.cd_cvm, ref.cnpj, ref.company, g.data_refer, g.versao,
           g.valor_mobiliario, g.identificacao, g.data_emissao, g.data_vencimento,
           g.quantidade, g.valor, g.saldo_devedor, g.restricao_circulacao,
           g.conversibilidade, g.resgatavel, g.caracteristicas_divida,
           'cvm_fre'::text
    FROM page g CROSS JOIN ref
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'debt_issues')
    ORDER BY g.data_refer DESC, g.data_vencimento NULLS LAST, g.identificacao, g.row_hash
    LIMIT 1000;
END;
$fn$;

REVOKE ALL ON FUNCTION api.debt_issues(TEXT, DATE, DATE) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.debt_issues(TEXT, DATE, DATE) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION api.debt_issues(TEXT, DATE, DATE) TO silo_api;

COMMENT ON FUNCTION api.debt_issues(TEXT, DATE, DATE) IS
    'The debt issues (debentures, commercial notes, CRI, CRA, ...) a listed company describes in its CVM FRE, item outros valores mobiliários, yearly from 2010: security type, the issue name as filed, issue date, maturity, quantity, value issued, outstanding balance at the reference date, three flags, and terms_text. One row is one issue as filed, often several series; CVM publishes no ticker, ISIN or series code, so a row does not join to a traded debenture. Only companies that file an FRE (listed issuers) are covered. Rate and indexer exist only in terms_text, free text served as filed and NEVER parsed. The newest version of each reference date is served, which is not point-in-time; reference_date is not a filing date. An empty flag stays NULL. p_id is required and resolves as api.financials resolves it (ticker through CVM''s FCA map, 14-digit CNPJ or CVM code, never a name); an id that resolves to nothing returns no rows. p_from / p_to bound the reference date (NULL = no bound). Newest reference date first, then maturity. More than 1000 rows RAISES 22023 (never trimmed).';

COMMIT;
