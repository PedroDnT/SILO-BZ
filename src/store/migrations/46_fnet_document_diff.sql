-- 46_fnet_document_diff.sql — FNET restatement diffs (B4, slice 1: FIDC informe mensal).
--
-- WHAT THIS ADDS. Three tables over the FNET register (migration 42): the
-- parsed shape of a downloaded structured document (no raw body, decision 2),
-- the pairing of each re-filing (versao > 1) with the version it replaced,
-- and one row per field that differs between the two. Design and the
-- measurements behind it: docs/planning/DOCUMENTS.md; the eight decisions
-- are its §11 (taken 2026-09-26).
--
-- PROVENANCE. Every column of fnet_document_body comes from the HTTP
-- response or the document itself. declared_cnpj is the XML's own fund CNPJ
-- only when it prints exactly 14 digits, else NULL with the text as printed
-- in declared_cnpj_raw (decision 5); it is checked against the cnpjFundo
-- LINK (status 'declared_mismatch') and is never itself a link (decision 4).
-- The pair's cnpj is the link that made the pair, never a name. field_path
-- addresses repeated blocks by the checked-in key registry
-- (src/parsers/fnet_xml_diff.py); a block with no key, or a duplicate key,
-- is matched by position and flagged match_basis = 'position' (decision 8).
-- old_num / new_num are NULL unless the leaf's number rule parses the text;
-- the text is never coerced.
--
-- IDEMPOTENT. Named UNIQUE constraints; upserts ON CONFLICT DO UPDATE. The
-- pair key is NULLS NOT DISTINCT (as migration 43) so an unpairable document
-- holds exactly one row with prev_fnet_id NULL. Audit: one cvm_ingest_log
-- row per run, entity 'fnet', doc_type 'diff'.
--
-- Landing tables: no client grant (12_grants_and_rls.sql revokes them by
-- name and by the fnet_ prefix sweep); served by api.fund_restatement_diff.

CREATE TABLE IF NOT EXISTS fnet_document_body (
    id                     BIGSERIAL    PRIMARY KEY,
    fnet_id                BIGINT       NOT NULL CHECK (fnet_id > 0),
    content_type           TEXT,                      -- as served
    bytes                  INTEGER      NOT NULL,
    sha256                 TEXT         NOT NULL,     -- of the bytes as served
    canonical_sha256       TEXT,                      -- of the parsed, whitespace-free form; NULL unless parse_status = 'ok'
    filename               TEXT,                      -- Content-Disposition, as served
    root_element           TEXT,                      -- DOC_ARQ (FIDC) / DadosEconomicoFinanceiros (FII)
    schema_version         TEXT,                      -- FIDC CAB_INFORM/VERSAO; NULL where none is declared
    declared_cnpj_raw      TEXT,                      -- the XML's own fund CNPJ, as printed
    declared_reference_raw TEXT,                      -- the XML's own reference (DT_COMPT / Competencia), as printed
    declared_cnpj          TEXT         CHECK (declared_cnpj IS NULL OR declared_cnpj ~ '^[0-9]{14}$'),
    leaf_count             INTEGER,
    parse_status           TEXT         NOT NULL CHECK (parse_status IN ('ok', 'not_xml', 'parse_error', 'unsupported_root')),
    parse_error            TEXT,
    fetched_at             TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fnet_document_body UNIQUE (fnet_id)
);

CREATE TABLE IF NOT EXISTS fnet_document_pair (
    id                  BIGSERIAL    PRIMARY KEY,
    fnet_id             BIGINT       NOT NULL CHECK (fnet_id > 0),   -- the re-filing (versao > 1)
    prev_fnet_id        BIGINT       CHECK (prev_fnet_id IS NULL OR prev_fnet_id > 0),
    cnpj                TEXT         CHECK (cnpj IS NULL OR cnpj ~ '^[0-9]{14}$'),  -- the cnpjFundo link that made the pair
    pair_rule           TEXT         NOT NULL DEFAULT 'group_key_v1',
    status              TEXT         NOT NULL CHECK (status IN (
                            'compared', 'unpairable_no_link', 'unpairable_no_reference',
                            'no_predecessor', 'body_not_xml', 'parse_error', 'declared_mismatch')),
    n_changed           INTEGER,
    n_added             INTEGER,
    n_removed           INTEGER,
    identical_bytes     BOOLEAN,
    identical_canonical BOOLEAN,
    diff_version        TEXT,
    compared_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fnet_document_pair UNIQUE NULLS NOT DISTINCT (fnet_id, prev_fnet_id)
);
CREATE INDEX IF NOT EXISTS idx_fnet_pair_cnpj   ON fnet_document_pair (cnpj);
CREATE INDEX IF NOT EXISTS idx_fnet_pair_status ON fnet_document_pair (status);

CREATE TABLE IF NOT EXISTS fnet_document_diff (
    id            BIGSERIAL    PRIMARY KEY,
    fnet_id       BIGINT       NOT NULL CHECK (fnet_id > 0),
    prev_fnet_id  BIGINT       NOT NULL CHECK (prev_fnet_id > 0),
    field_path    TEXT         NOT NULL,   -- canonical path; repeated blocks by key, e.g. .../CLASSE_SENIOR[Série 1;]/QT_COTISTAS
    block         TEXT,                    -- first-level section, e.g. LISTA_INFORM/PATRLIQ
    leaf          TEXT,
    change_kind   TEXT         NOT NULL CHECK (change_kind IN ('changed', 'added', 'removed', 'nil_to_value', 'value_to_nil')),
    old_value     TEXT,                    -- exactly as printed; NULL when absent or nil
    new_value     TEXT,
    old_num       NUMERIC,                 -- only when the number rule parses the text
    new_num       NUMERIC,
    match_basis   TEXT         NOT NULL CHECK (match_basis IN ('path', 'key', 'position')),
    cvm_column    TEXT,                    -- from the crosswalk once it exists (decision 7: deferred); NULL until then
    silo_column   TEXT,
    diff_version  TEXT         NOT NULL,
    CONSTRAINT uq_fnet_document_diff UNIQUE (fnet_id, prev_fnet_id, field_path)
);
CREATE INDEX IF NOT EXISTS idx_fnet_diff_pair ON fnet_document_diff (fnet_id, prev_fnet_id);
