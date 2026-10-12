-- =============================================================================
-- 34_api_rj_listed.sql
-- The recuperação judicial (RJ) and extrajudicial documents that LISTED
-- companies file with CVM, served through schema `api` (catalog v75, #842,
-- epic #841). No new fetch: everything is already in cia_event (CVM IPE).
--
--   public.rj_listed_documents  internal view, one row per IPE protocol (its
--                               newest version) that is an RJ document.
--   api.rj_listed_documents     the read over it: every company or one, a
--                               delivery-date window, one doc_type.
--
-- WHAT COUNTS AS AN RJ DOCUMENT. Two signals, and `signal` says which one:
--   * `categoria` — CVM's own category "Informações de Companhias em
--     Recuperação Judicial ou Extrajudicial" (petição inicial, plano,
--     contas demonstrativas mensais, sentenças, assembleia de credores, ...);
--   * `fato_relevante` — a Fato Relevante whose Assunto names a judicial or
--     extrajudicial recovery or the "recuperandas". The category alone misses
--     these: measured 2026-10-12, 49 such Fatos Relevantes from 20 companies
--     in 2026 (deferimento do processamento, ajuizamento, homologação ...).
--     The match is on the subject text as filed, so a filing whose Assunto
--     does not say it is not found, and the rare subject that says it about
--     something else is found.
-- Falência ("Informações Companhias em Falência") is not an RJ document and
-- is not served here; api.company_events serves it.
--
-- COMPANY STATUS. Every row also carries the company's CVM cadastro situation
-- (SIT_EMISSOR and DT_INI_SIT_EMISSOR from cia_company.raw), as filed. It is a
-- second signal, not the first: the cadastro lags the filings (Grupo Casas
-- Bahia filed for RJ on 2026-08-16 and the cadastro still read "FASE
-- OPERACIONAL" on 2026-10-12). A company is "in RJ per IPE" when it has rows
-- here, "per cadastro" when cadastro_status names a recovery.
--
-- DATES. delivery_date is Data_Entrega, the filing date. reference_date is
-- Data_Referencia as filed and is NOT a filing date: in 2026, 715 IPE rows
-- carry a future reference date, one of them in 3036. The window is the
-- delivery date only.
--
-- NOTHING IS DERIVED. Every text field is CVM's, as filed; source_url is the
-- document's link on CVM's RAD. One row per protocol at its newest version,
-- as api.company_events serves it.
--
-- PRIVILEGES, ROW CAP: 26's. The view carries no client grant (it reads
-- landing tables). The function is SECURITY DEFINER with an empty pinned
-- search_path, every relation schema-qualified; EXECUTE revoked from PUBLIC,
-- granted to anon / authenticated and to silo_api. One page plus one row, then
-- api.assert_row_cap REFUSES with 22023 above 1000 — never trimmed, no cursor:
-- narrow the window, pin a company or a doc_type.
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
        RAISE EXCEPTION '34_api_rj_listed.sql needs api.assert_row_cap and api.company_ref from 19_api_contract.sql; apply 19 first';
    END IF;
    IF to_regclass('public.cia_event') IS NULL
       OR to_regclass('public.cia_company') IS NULL THEN
        RAISE EXCEPTION '34_api_rj_listed.sql serves cia_event and cia_company; apply the schema and migrations first';
    END IF;
END
$guard$;

-- ---------------------------------------------------------------------------
-- rj_listed_documents — internal view, one row per RJ protocol
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW public.rj_listed_documents AS
WITH latest AS (
    -- One row per protocol: its newest version.
    SELECT DISTINCT ON (e.protocolo)
           e.cd_cvm, e.cnpj_cia, e.data_entrega, e.data_refer, e.categoria,
           e.tipo, e.especie, e.assunto, e.protocolo, e.versao, e.link_download
    FROM public.cia_event e
    WHERE e.categoria = 'Informações de Companhias em Recuperação Judicial ou Extrajudicial'
       OR (e.categoria = 'Fato Relevante'
           AND e.assunto ~* '(recupera\S*\s+(extra)?judicial|recuperand)')
    ORDER BY e.protocolo, e.versao DESC NULLS LAST
)
SELECT l.cd_cvm,
       l.cnpj_cia                                   AS cnpj,
       c.denom_cia                                  AS company,
       (l.data_entrega AT TIME ZONE 'UTC')::date    AS delivery_date,
       l.data_refer                                 AS reference_date,
       l.categoria                                  AS category,
       l.tipo                                       AS doc_type,
       l.especie                                    AS species,
       l.assunto                                    AS subject,
       l.protocolo                                  AS protocol,
       l.versao                                     AS version,
       l.link_download                              AS source_url,
       CASE WHEN l.categoria = 'Fato Relevante'
            THEN 'fato_relevante' ELSE 'categoria' END AS signal,
       NULLIF(btrim(c.raw->>'SIT_EMISSOR'), '')     AS cadastro_status,
       CASE WHEN c.raw->>'DT_INI_SIT_EMISSOR' ~ '^\d{4}-\d{2}-\d{2}$'
            THEN (c.raw->>'DT_INI_SIT_EMISSOR')::date END AS cadastro_status_since
FROM latest l
LEFT JOIN public.cia_company c ON c.cd_cvm = l.cd_cvm;

REVOKE ALL ON public.rj_listed_documents FROM PUBLIC;

COMMENT ON VIEW public.rj_listed_documents IS
    'Internal (no client grant): the RJ / extrajudicial documents listed companies file with CVM IPE, one row per protocol at its newest version. signal = categoria (CVM''s RJ category) or fato_relevante (a Fato Relevante whose Assunto names the recovery). cadastro_status is cia_company SIT_EMISSOR as filed, a lagging second signal. Served by api.rj_listed_documents.';

-- ---------------------------------------------------------------------------
-- api.rj_listed_documents — the read, newest delivery first
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION api.rj_listed_documents(
    p_id       TEXT DEFAULT NULL,    -- ticker (FCA map, active listings), 14-digit CNPJ or CVM code; NULL = every company
    p_from     DATE DEFAULT NULL,    -- first delivery day; NULL = 12 months before p_to (or today)
    p_to       DATE DEFAULT NULL,    -- last delivery day, inclusive; NULL = today
    p_doc_type TEXT DEFAULT NULL     -- one Tipo exactly as CVM labels it (e.g. Petição Inicial); NULL = every type
)
RETURNS TABLE (
    cd_cvm                TEXT,    -- CVM code of the company
    cnpj                  TEXT,    -- the filing's own CNPJ_Companhia, as filed
    company               TEXT,    -- cia_company's registered name
    delivery_date         DATE,    -- Data_Entrega: the filing date
    reference_date        DATE,    -- Data_Referencia, as filed; not a filing date
    category              TEXT,    -- Categoria, as filed
    doc_type              TEXT,    -- Tipo, as filed (NULL on a Fato Relevante)
    species               TEXT,    -- Especie, as filed
    subject               TEXT,    -- Assunto, as filed
    protocol              TEXT,    -- Protocolo_Entrega
    version               INT,     -- the newest Versao held for the protocol
    source_url            TEXT,    -- Link_Download: the document on CVM's RAD
    signal                TEXT,    -- categoria | fato_relevante
    cadastro_status       TEXT,    -- cia_company SIT_EMISSOR, as filed (lags the filings)
    cadastro_status_since DATE,    -- cia_company DT_INI_SIT_EMISSOR
    source                TEXT
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $fn$
#variable_conflict use_column
DECLARE
    v_id    TEXT := NULLIF(btrim(COALESCE(p_id, '')), '');
    v_type  TEXT := NULLIF(btrim(COALESCE(p_doc_type, '')), '');
    v_to    DATE := COALESCE(p_to, CURRENT_DATE);
    v_from  DATE;
    v_known TEXT;
BEGIN
    v_from := COALESCE(p_from, (v_to - INTERVAL '12 months')::date);
    IF v_from > v_to THEN
        RAISE EXCEPTION 'rj_listed_documents: p_from (%) is after p_to (%)', v_from, v_to
            USING ERRCODE = '22023';
    END IF;

    IF v_type IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM public.rj_listed_documents d WHERE d.doc_type = v_type
    ) THEN
        SELECT string_agg(t.doc_type, ', ' ORDER BY t.doc_type)
          INTO v_known
          FROM (SELECT DISTINCT d.doc_type FROM public.rj_listed_documents d
                WHERE d.doc_type IS NOT NULL) t;
        RAISE EXCEPTION
            'unknown RJ doc_type %; the RJ documents hold: %', p_doc_type, COALESCE(v_known, '(none)')
            USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    WITH ref AS (
        SELECT r.cd_cvm FROM api.company_ref(v_id) r
    ),
    -- One page + one, then assert_row_cap REFUSES (22023). No cursor.
    page AS (
        SELECT d.*
        FROM public.rj_listed_documents d
        WHERE (v_id IS NULL OR d.cd_cvm IN (SELECT ref.cd_cvm FROM ref))
          AND (v_type IS NULL OR d.doc_type = v_type)
          AND d.delivery_date BETWEEN v_from AND v_to
        ORDER BY d.delivery_date DESC, d.protocol DESC
        LIMIT 1001
    )
    SELECT g.cd_cvm, g.cnpj, g.company, g.delivery_date, g.reference_date,
           g.category, g.doc_type, g.species, g.subject, g.protocol, g.version,
           g.source_url, g.signal, g.cadastro_status, g.cadastro_status_since,
           'cvm_ipe'::text
    FROM page g
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'rj_listed_documents')
    ORDER BY g.delivery_date DESC, g.protocol DESC
    LIMIT 1000;
END;
$fn$;

REVOKE ALL ON FUNCTION api.rj_listed_documents(TEXT, DATE, DATE, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.rj_listed_documents(TEXT, DATE, DATE, TEXT) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION api.rj_listed_documents(TEXT, DATE, DATE, TEXT) TO silo_api;

COMMENT ON FUNCTION api.rj_listed_documents(TEXT, DATE, DATE, TEXT) IS
    'Recuperação judicial and extrajudicial documents of LISTED companies, as filed with CVM IPE (cia_event): petição inicial, plano, contas demonstrativas mensais, sentenças, assembleia de credores and the rest, plus the Fatos Relevantes whose subject names the recovery (signal = categoria | fato_relevante). Newest delivery first, one row per protocol at its newest version, every text field as filed, source_url the document''s link on CVM''s RAD. Each row also carries the company''s CVM cadastro situation (cadastro_status, cadastro_status_since), a second signal that lags the filings. p_id NULL = every company; otherwise resolved exactly as api.financials resolves it (ticker through CVM''s FCA map, 14-digit CNPJ or CVM code, never a name); an id that resolves to nothing returns no rows. Window = delivery date, default the 12 months before p_to or today; reference_date is not a filing date. p_doc_type matches CVM''s Tipo exactly and an unknown one raises 22023 listing the types held. Falência documents are not here (api.company_events serves them). Private companies are not here. More than 1000 rows RAISES 22023 (never trimmed): narrow the window, pin p_id or p_doc_type.';

COMMIT;
