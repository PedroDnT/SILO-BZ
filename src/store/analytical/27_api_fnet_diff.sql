-- 27_api_fnet_diff.sql — the FNET restatement diffs reach the API (catalog v40, B4 slice 1).
--
-- api.fund_restatement_diff: one row per field that differs between a
-- re-filed FNET document (versao > 1) and the version it replaced, over
-- fnet_document_pair / fnet_document_diff (migration 46). The pairing is
-- EXACTLY api.fund_restatements' stated group key (24_api_fnet.sql), so a
-- diff pair is always a row fund_restatements already serves. Slice 1 covers
-- FIDC informe mensal estruturado only (docs/planning/DOCUMENTS.md §11,
-- decision 3); other document types have no pair row and are served by
-- fund_restatements with diff_status NULL.
--
-- What a row is: old_value / new_value are the leaf TEXT as printed;
-- old_num / new_num only when the leaf's number rule parsed it, and delta
-- only when both did. field_path addresses repeated blocks by the checked-in
-- key registry; match_basis = 'position' flags a block matched by order
-- (decision 8), served, never hidden. cvm_column is NULL until the crosswalk
-- exists (decision 7). Both source_urls are FNET's own download links.
--
-- Access: anon + authenticated + silo_api, like fund_restatements. The
-- landing tables stay revoked (12_grants_and_rls.sql). Requires p_cnpj or
-- p_fnet_id; more than 1000 rows RAISES 22023 (never trimmed) — one
-- restatement is at most a few hundred fields, so pin p_fnet_id or narrow the
-- delivery window.

BEGIN;

DROP FUNCTION IF EXISTS api.fund_restatement_diff(TEXT, DATE, DATE, TEXT, BIGINT);
CREATE OR REPLACE FUNCTION api.fund_restatement_diff(
    p_cnpj    TEXT   DEFAULT NULL,   -- one fund (its cnpjFundo link); required unless p_fnet_id
    p_from    DATE   DEFAULT NULL,   -- first delivery day of the RESTATED document
    p_to      DATE   DEFAULT NULL,   -- last delivery day, inclusive
    p_tipo    TEXT   DEFAULT NULL,   -- tipo_documento, exact text as FNET publishes it; NULL = any in scope
    p_fnet_id BIGINT DEFAULT NULL    -- one restated document; required unless p_cnpj
)
RETURNS TABLE (
    fnet_id               BIGINT,     -- the restated document (versao > 1)
    prev_fnet_id          BIGINT,     -- the version it replaced (same group key as fund_restatements)
    cnpj                  TEXT,       -- the cnpjFundo link that made the pair; never a name
    tipo_documento        TEXT,
    reference_raw         TEXT,
    versao                INT,
    modalidade            TEXT,       -- RE voluntary | RC CVM-required, as published
    delivered_at          TIMESTAMP,
    previous_delivered_at TIMESTAMP,
    lag_days              INT,
    field_path            TEXT,       -- canonical path; repeated blocks by key, e.g. .../CLASSE_SENIOR[Série 1;]/QT_COTISTAS
    block                 TEXT,       -- first-level section, e.g. LISTA_INFORM/PATRLIQ
    leaf                  TEXT,
    change_kind           TEXT,       -- changed | added | removed | nil_to_value | value_to_nil
    old_value             TEXT,       -- as printed; NULL when absent or nil
    new_value             TEXT,
    delta                 NUMERIC,    -- new_num - old_num; NULL unless both parsed under the number rule
    match_basis           TEXT,       -- path | key | position (position = matched by order, approximate by construction)
    cvm_column            TEXT,       -- NULL until the crosswalk exists
    diff_version          TEXT,
    source_url            TEXT,       -- FNET download link for fnet_id
    previous_source_url   TEXT
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $fn$
#variable_conflict use_column
DECLARE
    v_cnpj TEXT := NULLIF(regexp_replace(COALESCE(p_cnpj, ''), '\D', '', 'g'), '');
BEGIN
    IF p_cnpj IS NOT NULL AND btrim(p_cnpj) <> ''
       AND (v_cnpj IS NULL OR v_cnpj !~ '^[0-9]{14}$') THEN
        RAISE EXCEPTION
            'fund_restatement_diff: p_cnpj must be a fund''s 14-digit CNPJ, got % (find one with search_funds or lookup)',
            p_cnpj
            USING ERRCODE = '22023';
    END IF;
    IF v_cnpj IS NULL AND p_fnet_id IS NULL THEN
        RAISE EXCEPTION
            'fund_restatement_diff: give p_cnpj (one fund) or p_fnet_id (one restated document, from fund_restatements); a market-wide field diff is not a query'
            USING ERRCODE = '22023';
    END IF;
    IF p_from IS NOT NULL AND p_to IS NOT NULL AND p_from > p_to THEN
        RAISE EXCEPTION 'fund_restatement_diff: p_from (%) is after p_to (%)', p_from, p_to
            USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    WITH pairs AS (
        SELECT x.fnet_id, x.prev_fnet_id, x.cnpj, x.diff_version,
               d.tipo_documento, d.reference_raw, d.versao, d.modalidade, d.delivered_at,
               p.delivered_at AS previous_delivered_at
        FROM public.fnet_document_pair x
        JOIN public.fnet_document d ON d.fnet_id = x.fnet_id
        JOIN public.fnet_document p ON p.fnet_id = x.prev_fnet_id
        WHERE x.status = 'compared'
          AND (p_fnet_id IS NULL OR x.fnet_id = p_fnet_id)
          AND (v_cnpj IS NULL OR x.cnpj = v_cnpj)
          AND (p_tipo IS NULL OR d.tipo_documento = p_tipo)
          AND (p_from IS NULL OR d.delivered_at >= p_from::timestamp)
          AND (p_to   IS NULL OR d.delivered_at < (p_to + 1)::timestamp)
    ),
    -- One page + one, then assert_row_cap REFUSES (22023). No cursor.
    page AS (
        SELECT pr.fnet_id, pr.prev_fnet_id, pr.cnpj, pr.tipo_documento, pr.reference_raw,
               pr.versao, pr.modalidade, pr.delivered_at, pr.previous_delivered_at,
               (pr.delivered_at::date - pr.previous_delivered_at::date) AS lag_days,
               f.field_path, f.block, f.leaf, f.change_kind, f.old_value, f.new_value,
               (f.new_num - f.old_num) AS delta, f.match_basis, f.cvm_column, f.diff_version
        FROM pairs pr
        JOIN public.fnet_document_diff f
          ON f.fnet_id = pr.fnet_id AND f.prev_fnet_id = pr.prev_fnet_id
        ORDER BY pr.delivered_at DESC, pr.fnet_id DESC, f.field_path
        LIMIT 1001
    )
    SELECT g.fnet_id, g.prev_fnet_id, g.cnpj, g.tipo_documento, g.reference_raw,
           g.versao, g.modalidade, g.delivered_at, g.previous_delivered_at, g.lag_days,
           g.field_path, g.block, g.leaf, g.change_kind, g.old_value, g.new_value,
           g.delta, g.match_basis, g.cvm_column, g.diff_version,
           'https://fnet.bmfbovespa.com.br/fnet/publico/downloadDocumento?id=' || g.fnet_id::text,
           'https://fnet.bmfbovespa.com.br/fnet/publico/downloadDocumento?id=' || g.prev_fnet_id::text
    FROM page g
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'fund_restatement_diff')
    ORDER BY g.delivered_at DESC, g.fnet_id DESC, g.field_path
    LIMIT 1000;
END;
$fn$;

REVOKE ALL ON FUNCTION api.fund_restatement_diff(TEXT, DATE, DATE, TEXT, BIGINT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.fund_restatement_diff(TEXT, DATE, DATE, TEXT, BIGINT) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION api.fund_restatement_diff(TEXT, DATE, DATE, TEXT, BIGINT) TO silo_api;
COMMENT ON FUNCTION api.fund_restatement_diff(TEXT, DATE, DATE, TEXT, BIGINT) IS
    'Field-by-field diff of a re-filed FNET document (versao > 1) against the version it replaced, one row per differing field: FIDC informe mensal estruturado only (slice 1). The pair is the one fund_restatements states (same group key: cnpj link, categoria, tipo_documento, especie, reference_raw; highest lower versao, greatest fnet_id on a tie), so its diff_status = compared marks which rows have a diff here. old_value / new_value are the XML leaf text AS PRINTED (FIDC mixes comma and dot decimals within one document); delta only when both sides parsed under the number rule. field_path addresses repeated blocks (tranches, cedentes) by their declared keys; match_basis = position flags a block matched by ORDER because it had no key or a duplicate one — approximate by construction, served flagged, never hidden. cvm_column is NULL until the path-to-column crosswalk exists. This compares FNET''s versions of a document, not CVM''s CSVs; tab VIII (debtors) is not in the public XML, so its restatements are invisible here. Requires p_cnpj or p_fnet_id. More than 1000 rows RAISES 22023 (never trimmed): pin p_fnet_id or narrow the delivery window.';

COMMIT;
