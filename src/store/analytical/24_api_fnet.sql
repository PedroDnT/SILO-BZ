-- =============================================================================
-- 24_api_fnet.sql
-- The B3 Fundos.NET (FNET) document register, served through schema `api`
-- (catalog v33; COMPETITIVE_GAPS.md §7 B1, DATA_INVENTORY.md §3).
--
--   api.fund_documents     every FNET document LINKED to one fund, newest
--                          delivery first, with a source_url a caller can open.
--   api.fund_restatements  restatement events: documents with versao > 1,
--                          each paired with the version it most plausibly
--                          replaced, and the lag between the two deliveries.
--
-- WHAT THE REGISTER IS (migration 42, src/fetchers/fnet_fetcher.py). CVM's
-- dados.cvm CSVs are republished in place, so a restated informe overwrites
-- the original there. FNET keeps every version as its OWN document id:
--   * versao      1 for the first filing, 2.. for each re-filing;
--   * modalidade  AP = Apresentação (original), RE = Reapresentação Espontânea
--                 (voluntary restatement), RC = Reapresentação por Exigência
--                 (a restatement CVM required) — served as published;
--   * status      AC active, IC inactive (superseded), CC cancelled — AS OF
--                 fetched_at: a document fetched while active reads AC until
--                 a later fetch sees it superseded;
--   * delivered_at FNET's dataEntrega, São Paulo local time, stored as printed.
-- Metadata only; no document body is stored. source_url is FNET's own public
-- download link for the id, so every row carries provenance a caller can open.
--
-- THE FUND IS KNOWN ONLY BY LINK. FNET rows carry NO CNPJ (cnpjFundo is null
-- on every row, even when the query filters on it) and no fund type. The
-- ingest records what it ASKED: fnet_document_filter holds "FNET returned this
-- id for cnpjFundo = X" (the fortnightly per-fund sweep) and "for tipoFundo =
-- 1/2/3" (the per-type daily crawl). A document's fund is a cnpjFundo row or it
-- is unknown. fund_name is FNET's label, served for reading and NEVER joined
-- on (CLAUDE.md: no name matching, ever). Because the sweep is fortnightly, a
-- document delivered this week may not be linked to its fund yet — it is in
-- the register and reaches fund_documents after the next sweep of that fund.
-- coverage()'s fnet_documents row says so.
--
-- FNET DOES NOT LINK VERSIONS. Nothing in a FNET row points a v2 at its v1, so
-- fund_restatements PAIRS them by a group key it states instead of inventing
-- a link:
--     (cnpj link, categoria, tipo_documento, especie, reference_raw)
-- previous_fnet_id is the document in the same group with the HIGHEST versao
-- below the restated one; if several share that versao — a group can
-- legitimately hold several v1 documents (an assembly convened twice for one
-- reference, two informes for one month under different especies that FNET
-- labels alike) — the GREATEST fnet_id among them wins, i.e. the latest
-- assigned id. categoria / tipo_documento / especie compare NULL-safe (IS NOT
-- DISTINCT FROM: a type FNET leaves blank is still one type); reference_raw
-- compares with plain `=`, so a document with NO reference text is never
-- paired — without a reference period two filings of one type are not the
-- same statement. A restated document with NO cnpjFundo link is still
-- returned (cnpj NULL) and its previous_* stay NULL: grouping it by fund_name
-- would be the name join this warehouse forbids.
--
-- ROW CAP. The api.assert_row_cap pattern from 19: fetch one page plus one row
-- (LIMIT 1001) and REFUSE with 22023 above 1000, never trim. No cursor: a
-- fund's documents over a year, or a month of restatements, is a window to
-- narrow, not a series to walk. Not tiered.
--
-- PRIVILEGES. Same model as 19: SECURITY DEFINER with an empty pinned
-- search_path, every relation schema-qualified; EXECUTE revoked from PUBLIC,
-- granted to anon / authenticated and to silo_api (the read bundle serve/
-- connects through), exactly as api.fidc_tranches is. The landing tables
-- fnet_document / fnet_document_filter carry no client grant.
--
-- Ordering: after 19 (api.assert_row_cap) and the schema (migration 42). The
-- guard below fails the apply loudly if either is missing.
-- =============================================================================

BEGIN;
-- Apply-time guard for this DDL transaction only (the runtime timeout is the
-- calling role's, as in 19).
SET statement_timeout = '30s';

DO $guard$
BEGIN
    IF to_regprocedure('api.assert_row_cap(bigint, boolean, text)') IS NULL THEN
        RAISE EXCEPTION '24_api_fnet.sql needs api.assert_row_cap from 19_api_contract.sql; apply 19 first';
    END IF;
    IF to_regclass('public.fnet_document') IS NULL
       OR to_regclass('public.fnet_document_filter') IS NULL THEN
        RAISE EXCEPTION '24_api_fnet.sql serves the FNET register; apply migration 42_fnet_document.sql first';
    END IF;
END
$guard$;

-- ---------------------------------------------------------------------------
-- fund_documents — one fund's FNET documents, newest delivery first
-- ---------------------------------------------------------------------------
-- Default window: the 12 months before p_to (or today), by delivery DATE
-- (delivered_at::date, São Paulo). An explicit p_from is served verbatim; a
-- NULL p_to leaves the window open at the top.
CREATE OR REPLACE FUNCTION api.fund_documents(
    p_cnpj TEXT,
    p_from DATE DEFAULT NULL,   -- first delivery day; NULL = 12 months before p_to (or today)
    p_to   DATE DEFAULT NULL,   -- last delivery day, inclusive; NULL = no upper bound
    p_tipo TEXT DEFAULT NULL    -- one tipo_documento, matched exactly as FNET labels it; NULL = every type
)
RETURNS TABLE (
    fnet_id        BIGINT,       -- FNET's document id; each version is a new id
    fund_name      TEXT,         -- FNET's label, as published; never a join key
    categoria      TEXT,
    tipo_documento TEXT,
    especie        TEXT,
    reference_raw  TEXT,         -- the reference period as FNET prints it
    reference_date DATE,         -- parsed from dd/mm/yyyy or mm/yyyy only; NULL otherwise
    delivered_at   TIMESTAMP,    -- dataEntrega, São Paulo local time, as printed
    versao         INT,          -- 1 = first filing; > 1 = a re-filing
    modalidade     TEXT,         -- AP original | RE voluntary restatement | RC CVM-required
    status         TEXT,         -- AC active | IC superseded | CC cancelled, AS OF fetched_at
    fetched_at     TIMESTAMPTZ,  -- when SILO last read this row from FNET
    source_url     TEXT          -- FNET's public download link for fnet_id
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $fn$
#variable_conflict use_column
DECLARE
    v_cnpj TEXT := NULLIF(regexp_replace(COALESCE(p_cnpj, ''), '\D', '', 'g'), '');
    v_tipo TEXT := NULLIF(btrim(COALESCE(p_tipo, '')), '');
    v_from DATE;
BEGIN
    IF v_cnpj IS NULL OR v_cnpj !~ '^[0-9]{14}$' THEN
        RAISE EXCEPTION
            'fund_documents needs p_cnpj, a fund''s 14-digit CNPJ: FNET documents are linked per fund (find one with search_funds or lookup)'
            USING ERRCODE = '22023';
    END IF;

    v_from := COALESCE(p_from, (COALESCE(p_to, CURRENT_DATE) - INTERVAL '12 months')::date);
    IF p_to IS NOT NULL AND v_from > p_to THEN
        RAISE EXCEPTION 'fund_documents: p_from (%) is after p_to (%)', v_from, p_to
            USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    -- The link row IS the fund: one (fnet_id, 'cnpjFundo', cnpj) row per
    -- document (uq_fnet_document_filter), so the join cannot fan out.
    -- One page + one, then assert_row_cap REFUSES (22023). No cursor.
    WITH page (fnet_id, fund_name, categoria, tipo_documento, especie,
               reference_raw, reference_date, delivered_at, versao,
               modalidade, status, fetched_at, source_url) AS (
        SELECT d.fnet_id, d.fund_name, d.categoria, d.tipo_documento, d.especie,
               d.reference_raw, d.reference_date, d.delivered_at, d.versao,
               d.modalidade, d.status, d.fetched_at,
               'https://fnet.bmfbovespa.com.br/fnet/publico/downloadDocumento?id=' || d.fnet_id::text
        FROM public.fnet_document_filter l
        JOIN public.fnet_document d ON d.fnet_id = l.fnet_id
        WHERE l.filter_name = 'cnpjFundo'
          AND l.filter_value = v_cnpj
          AND d.delivered_at >= v_from::timestamp
          AND (p_to IS NULL OR d.delivered_at < (p_to + 1)::timestamp)
          AND (v_tipo IS NULL OR d.tipo_documento = v_tipo)
        ORDER BY d.delivered_at DESC, d.fnet_id DESC
        LIMIT 1001
    )
    SELECT g.fnet_id, g.fund_name, g.categoria, g.tipo_documento, g.especie,
           g.reference_raw, g.reference_date, g.delivered_at, g.versao,
           g.modalidade, g.status, g.fetched_at, g.source_url
    FROM page g
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'fund_documents')
    ORDER BY g.delivered_at DESC, g.fnet_id DESC
    LIMIT 1000;
END;
$fn$;

REVOKE ALL ON FUNCTION api.fund_documents(TEXT, DATE, DATE, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.fund_documents(TEXT, DATE, DATE, TEXT)
    TO anon, authenticated;
GRANT EXECUTE ON FUNCTION api.fund_documents(TEXT, DATE, DATE, TEXT) TO silo_api;

COMMENT ON FUNCTION api.fund_documents(TEXT, DATE, DATE, TEXT) IS
    'Every B3 Fundos.NET (FNET) document LINKED to one fund, newest delivery first: fnet_id, fund_name (FNET''s label, never a join key), categoria, tipo_documento, especie, reference_raw / reference_date, delivered_at (São Paulo time, as printed), versao, modalidade (AP original, RE voluntary restatement, RC CVM-required), status (AC active, IC superseded, CC cancelled — AS OF fetched_at) and source_url, FNET''s public download link for the id. Metadata only. FNET rows carry NO CNPJ: a document belongs to this fund because FNET returned it for cnpjFundo = p_cnpj in SILO''s fortnightly per-fund sweep, never because of its name — so a document delivered since that fund''s last sweep is not listed yet (coverage() fnet_documents). Each version is its own fnet_id; restatement pairs are api.fund_restatements. Window = delivery date, default the 12 months before p_to (or today); p_tipo matches tipo_documento exactly. A CNPJ that is not 14 digits raises 22023. More than 1000 rows RAISES 22023 (never trimmed): narrow the window or pin p_tipo.';

-- ---------------------------------------------------------------------------
-- fund_restatements — re-filed documents, each paired with its predecessor
-- ---------------------------------------------------------------------------
-- One row per (restated document, cnpjFundo link): a document FNET returned
-- for two fund queries appears once per fund (none observed; nothing is
-- collapsed silently), and one with NO link appears once with cnpj NULL.
-- tipo_fundo is the tipoFundo link's label ('1' FII, '2' FIDC, '3' ETF),
-- comma-joined in that order in the (unobserved) case of several; NULL when
-- the document was never returned by a per-type crawl.
--
-- Window: with p_cnpj, p_from / p_to are served verbatim (NULL = unbounded,
-- the fund's whole restatement history); without p_cnpj, p_from defaults to
-- the 30 days before p_to (or today), so a market-wide call is a recent
-- window rather than a scan of the register.
CREATE OR REPLACE FUNCTION api.fund_restatements(
    p_cnpj       TEXT DEFAULT NULL,   -- one fund (its cnpjFundo links); NULL = every fund, in a delivery window
    p_from       DATE DEFAULT NULL,   -- first delivery day of the RESTATED document
    p_to         DATE DEFAULT NULL,   -- last delivery day, inclusive; NULL = no upper bound
    p_tipo_fundo TEXT DEFAULT NULL    -- FII | FIDC | ETF (FNET's tipoFundo link); NULL = any, unlinked included
)
RETURNS TABLE (
    fnet_id               BIGINT,     -- the restated document (versao > 1)
    cnpj                  TEXT,       -- from its cnpjFundo link; NULL = not linked to a fund yet
    tipo_fundo            TEXT,       -- FII | FIDC | ETF from its tipoFundo link; NULL = none
    fund_name             TEXT,       -- FNET's label, as published; never a join key
    tipo_documento        TEXT,
    reference_raw         TEXT,
    reference_date        DATE,
    versao                INT,        -- > 1 on every row
    modalidade            TEXT,       -- RE voluntary | RC CVM-required, as published
    delivered_at          TIMESTAMP,  -- São Paulo local time, as printed
    previous_fnet_id      BIGINT,     -- same group, highest lower versao, greatest fnet_id on a tie; NULL when unpaired
    previous_delivered_at TIMESTAMP,
    lag_days              INT         -- delivered_at::date - previous_delivered_at::date; NULL when unpaired
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $fn$
#variable_conflict use_column
DECLARE
    v_cnpj TEXT := NULLIF(regexp_replace(COALESCE(p_cnpj, ''), '\D', '', 'g'), '');
    v_tipo TEXT := NULLIF(upper(btrim(COALESCE(p_tipo_fundo, ''))), '');
    v_code TEXT;
    v_from DATE := p_from;
BEGIN
    IF p_cnpj IS NOT NULL AND btrim(p_cnpj) <> ''
       AND (v_cnpj IS NULL OR v_cnpj !~ '^[0-9]{14}$') THEN
        RAISE EXCEPTION
            'fund_restatements: p_cnpj must be a fund''s 14-digit CNPJ, got % (find one with search_funds or lookup; omit it for a market-wide window)',
            p_cnpj
            USING ERRCODE = '22023';
    END IF;

    IF v_tipo IS NOT NULL THEN
        v_code := CASE v_tipo WHEN 'FII' THEN '1' WHEN 'FIDC' THEN '2' WHEN 'ETF' THEN '3' END;
        IF v_code IS NULL THEN
            RAISE EXCEPTION
                'fund_restatements: p_tipo_fundo must be FII, FIDC or ETF (FNET''s tipoFundo 1, 2, 3), got %',
                p_tipo_fundo
                USING ERRCODE = '22023';
        END IF;
    END IF;

    IF v_cnpj IS NULL AND v_from IS NULL THEN
        v_from := COALESCE(p_to, CURRENT_DATE) - 30;
    END IF;
    IF v_from IS NOT NULL AND p_to IS NOT NULL AND v_from > p_to THEN
        RAISE EXCEPTION 'fund_restatements: p_from (%) is after p_to (%)', v_from, p_to
            USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    WITH restated AS (
        SELECT d.fnet_id, l.filter_value AS cnpj, d.fund_name, d.categoria,
               d.tipo_documento, d.especie, d.reference_raw, d.reference_date,
               d.versao, d.modalidade, d.delivered_at
        FROM public.fnet_document d
        -- LEFT: a restated document the sweep has not linked yet is still an
        -- event; it is served with cnpj NULL, never dropped.
        LEFT JOIN public.fnet_document_filter l
               ON l.fnet_id = d.fnet_id
              AND l.filter_name = 'cnpjFundo'
        WHERE d.versao > 1
          AND (v_cnpj IS NULL OR l.filter_value = v_cnpj)
          AND (v_from IS NULL OR d.delivered_at >= v_from::timestamp)
          AND (p_to   IS NULL OR d.delivered_at < (p_to + 1)::timestamp)
          AND (v_code IS NULL OR EXISTS (
                SELECT 1
                FROM public.fnet_document_filter t
                WHERE t.fnet_id = d.fnet_id
                  AND t.filter_name = 'tipoFundo'
                  AND t.filter_value = v_code))
    ),
    -- One page + one, then assert_row_cap REFUSES (22023). No cursor.
    page (fnet_id, cnpj, tipo_fundo, fund_name, tipo_documento, reference_raw,
          reference_date, versao, modalidade, delivered_at, previous_fnet_id,
          previous_delivered_at, lag_days) AS (
        SELECT r.fnet_id, r.cnpj, tf.tipo_fundo, r.fund_name, r.tipo_documento,
               r.reference_raw, r.reference_date, r.versao, r.modalidade,
               r.delivered_at, pv.fnet_id, pv.delivered_at,
               (r.delivered_at::date - pv.delivered_at::date)
        FROM restated r
        LEFT JOIN LATERAL (
            SELECT string_agg(
                       CASE t.filter_value WHEN '1' THEN 'FII' WHEN '2' THEN 'FIDC' WHEN '3' THEN 'ETF' END,
                       ',' ORDER BY t.filter_value) AS tipo_fundo
            FROM public.fnet_document_filter t
            WHERE t.fnet_id = r.fnet_id
              AND t.filter_name = 'tipoFundo'
              AND t.filter_value IN ('1', '2', '3')
        ) tf ON TRUE
        -- The pairing. FNET links no versions, so this is the stated group
        -- key: same fund LINK (never the name), same categoria / tipo /
        -- especie (NULL-safe), same reference text (plain `=`: no reference,
        -- no pair). Highest lower versao, then greatest fnet_id on a tie.
        -- r.cnpj IS NULL makes the join empty: an unlinked document stays
        -- unpaired rather than being grouped by its label.
        LEFT JOIN LATERAL (
            SELECT p.fnet_id, p.delivered_at
            FROM public.fnet_document_filter pl
            JOIN public.fnet_document p ON p.fnet_id = pl.fnet_id
            WHERE pl.filter_name = 'cnpjFundo'
              AND pl.filter_value = r.cnpj
              AND p.versao < r.versao
              AND p.categoria      IS NOT DISTINCT FROM r.categoria
              AND p.tipo_documento IS NOT DISTINCT FROM r.tipo_documento
              AND p.especie        IS NOT DISTINCT FROM r.especie
              AND p.reference_raw = r.reference_raw
            ORDER BY p.versao DESC, p.fnet_id DESC
            LIMIT 1
        ) pv ON TRUE
        ORDER BY r.delivered_at DESC, r.fnet_id DESC, r.cnpj
        LIMIT 1001
    )
    SELECT g.fnet_id, g.cnpj, g.tipo_fundo, g.fund_name, g.tipo_documento,
           g.reference_raw, g.reference_date, g.versao, g.modalidade,
           g.delivered_at, g.previous_fnet_id, g.previous_delivered_at, g.lag_days
    FROM page g
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'fund_restatements')
    ORDER BY g.delivered_at DESC, g.fnet_id DESC, g.cnpj
    LIMIT 1000;
END;
$fn$;

REVOKE ALL ON FUNCTION api.fund_restatements(TEXT, DATE, DATE, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.fund_restatements(TEXT, DATE, DATE, TEXT)
    TO anon, authenticated;
GRANT EXECUTE ON FUNCTION api.fund_restatements(TEXT, DATE, DATE, TEXT) TO silo_api;

COMMENT ON FUNCTION api.fund_restatements(TEXT, DATE, DATE, TEXT) IS
    'Restatement events from the B3 Fundos.NET (FNET) register: one row per document with versao > 1 (modalidade RE voluntary or RC CVM-required, as published), newest delivery first, with cnpj from its cnpjFundo link (NULL when SILO''s fortnightly sweep has not linked it yet — served, never dropped), tipo_fundo from its tipoFundo link (FII / FIDC / ETF; NULL when none), and previous_fnet_id / previous_delivered_at / lag_days for the version it most plausibly replaced. FNET DOES NOT LINK VERSIONS, so the pairing is by a stated group key — (cnpj link, categoria, tipo_documento, especie, reference_raw) — never by fund_name: previous is the group''s document with the highest versao below this one, the greatest fnet_id winning a tie, because a group can legitimately hold several v1 documents (assemblies). Unlinked documents and documents with no reference text are never paired (previous_* NULL). lag_days = delivery date minus the previous delivery date. Filter by p_cnpj (window verbatim, NULL = whole history) or by a delivery window (default the 30 days before p_to or today); p_tipo_fundo takes FII, FIDC or ETF and anything else raises 22023. More than 1000 rows RAISES 22023 (never trimmed): narrow the window or pin p_cnpj / p_tipo_fundo.';

COMMIT;
