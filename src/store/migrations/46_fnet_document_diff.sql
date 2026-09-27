-- 46_fnet_document_diff.sql — what a fund changed between versions of one FNET document.
--
-- Three tables, mirrored verbatim into schema.sql (which stays canonical).
-- Idempotent (IF NOT EXISTS + named UNIQUE constraints) and psql-clean: CI
-- applies with -v ON_ERROR_STOP=1. Backlog item B4; the design and Pedro's
-- decisions of 2026-09-26 are docs/planning/DOCUMENTS.md (§4, §11). The fetch
-- is FnetFetcher.download, the parse and diff src/parsers/fnet_xml.py, the
-- queue src/pipeline/fnet_diff.py (audit entity 'fnet', doc_type 'diff').
--
-- WHY THIS EXISTS
-- ---------------
-- fnet_document (migration 42) says THAT a fund re-filed a document; it cannot
-- say WHAT changed, because it holds no bodies. FNET keeps every version
-- downloadable, so the diff is computed from the two bodies and only the
-- difference is kept: decision 2 (b), hashes and diffs, no raw XML. A body can
-- be re-fetched by fnet_id, and its stored sha256 proves the re-fetch is the
-- same document; a body whose hash no longer matches is itself a finding,
-- logged as a pair status and never overwritten.
--
-- Slice 1 is the FIDC informe mensal (root DOC_ARQ) only (decision 3).
--
-- fnet_document_body — one row per downloaded document body.
--   Grain: fnet_id. Every column comes from the HTTP response or the document
--   itself. sha256 is of the bytes as served; canonical_sha256 of the parsed,
--   whitespace-free form the diff compares (fnet_xml.canonical_lines), so two
--   bodies that differ only in indentation share it. declared_cnpj_raw /
--   declared_reference_raw are the XML's own NR_CNPJ_FUNDO / DT_COMPT as
--   printed; declared_cnpj is the digits only when there are exactly 14,
--   otherwise NULL (decision 5: a 13-digit CNPJ is never padded).
--   parse_status: ok | not_xml (a PDF, say) | parse_error | unsupported_root.
CREATE TABLE IF NOT EXISTS fnet_document_body (
    id                      BIGSERIAL    PRIMARY KEY,
    fnet_id                 BIGINT       NOT NULL CHECK (fnet_id > 0),
    content_type            TEXT,
    bytes                   INT          NOT NULL CHECK (bytes >= 0),
    sha256                  TEXT         NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    canonical_sha256        TEXT         CHECK (canonical_sha256 ~ '^[0-9a-f]{64}$'),
    filename                TEXT,
    root_element            TEXT,
    schema_version          TEXT,
    declared_cnpj_raw       TEXT,
    declared_cnpj           TEXT         CHECK (declared_cnpj ~ '^[0-9]{14}$'),
    declared_reference_raw  TEXT,
    leaf_count              INT          CHECK (leaf_count >= 0),
    parse_status            TEXT         NOT NULL
        CHECK (parse_status IN ('ok', 'not_xml', 'parse_error', 'unsupported_root')),
    parse_error             TEXT,
    fetched_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fnet_document_body UNIQUE (fnet_id),
    CONSTRAINT ck_fnet_body_parsed CHECK (
        parse_status <> 'ok' OR (canonical_sha256 IS NOT NULL AND leaf_count IS NOT NULL))
);

-- fnet_document_pair — one row per re-filed document (versao > 1): the
--   predecessor it was compared with, or why it could not be.
--   Grain: (fnet_id, prev_fnet_id); NULLS NOT DISTINCT (as migration 43) lets
--   an unpairable document hold exactly one row with prev_fnet_id NULL.
--   The predecessor is chosen by api.fund_restatements' own group key
--   (analytical 24): same cnpjFundo link, categoria, tipo_documento, especie
--   and reference_raw; the highest lower versao, the greatest fnet_id on a
--   tie. pair_rule names that rule. cnpj is the link that made the pair,
--   never a name. A pair that compared clean is status 'compared' with
--   n_changed = 0, so "no change" and "not compared" are never the same row.
--   Statuses that are waits (unpairable_no_link: the fortnightly sweep has
--   not linked the fund yet; no_predecessor: the register holds no lower
--   version yet) are retried on later runs; the rest are terminal for their
--   diff_version.
CREATE TABLE IF NOT EXISTS fnet_document_pair (
    id                   BIGSERIAL    PRIMARY KEY,
    fnet_id              BIGINT       NOT NULL CHECK (fnet_id > 0),
    prev_fnet_id         BIGINT       CHECK (prev_fnet_id > 0 AND prev_fnet_id <> fnet_id),
    cnpj                 TEXT         CHECK (cnpj ~ '^[0-9]{14}$'),
    pair_rule            TEXT         NOT NULL,
    status               TEXT         NOT NULL CHECK (status IN (
        'compared', 'unpairable_no_link', 'unpairable_no_reference', 'no_predecessor',
        'body_not_xml', 'parse_error', 'unsupported_root', 'declared_mismatch',
        'body_hash_mismatch')),
    detail               TEXT,
    n_changed            INT          CHECK (n_changed >= 0),
    n_added              INT          CHECK (n_added >= 0),
    n_removed            INT          CHECK (n_removed >= 0),
    identical_bytes      BOOLEAN,
    identical_canonical  BOOLEAN,
    diff_version         INT          NOT NULL CHECK (diff_version >= 1),
    compared_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fnet_document_pair UNIQUE NULLS NOT DISTINCT (fnet_id, prev_fnet_id),
    CONSTRAINT ck_fnet_pair_compared CHECK (
        status <> 'compared'
        OR (prev_fnet_id IS NOT NULL AND n_changed IS NOT NULL
            AND n_added IS NOT NULL AND n_removed IS NOT NULL)),
    CONSTRAINT ck_fnet_pair_unpaired CHECK (
        status NOT IN ('unpairable_no_link', 'unpairable_no_reference', 'no_predecessor')
        OR prev_fnet_id IS NULL)
);
CREATE INDEX IF NOT EXISTS idx_fnet_pair_cnpj ON fnet_document_pair (cnpj);

-- fnet_document_diff — one row per leaf that differs within a compared pair.
--   Grain: (fnet_id, prev_fnet_id, field_path). field_path is relative to the
--   root; repeated blocks are addressed by their declared key
--   (CLASSE_SENIOR[SERIE=Série 1]) or, lacking one, by position ([#2]), and
--   match_basis says which (path | key | position: position rows are
--   approximate by construction, flagged and never hidden). old_value /
--   new_value are the text exactly as printed (NULL for nil or absent);
--   old_num / new_num only where the leaf's number rule parses it, never
--   coerced. cvm_column / silo_column stay NULL until the crosswalk exists
--   (decision 7).
CREATE TABLE IF NOT EXISTS fnet_document_diff (
    id             BIGSERIAL    PRIMARY KEY,
    fnet_id        BIGINT       NOT NULL CHECK (fnet_id > 0),
    prev_fnet_id   BIGINT       NOT NULL CHECK (prev_fnet_id > 0),
    field_path     TEXT         NOT NULL,
    block          TEXT         NOT NULL,
    leaf           TEXT         NOT NULL,
    change_kind    TEXT         NOT NULL
        CHECK (change_kind IN ('changed', 'added', 'removed', 'nil_to_value', 'value_to_nil')),
    old_value      TEXT,
    new_value      TEXT,
    old_num        NUMERIC,
    new_num        NUMERIC,
    match_basis    TEXT         NOT NULL CHECK (match_basis IN ('path', 'key', 'position')),
    cvm_column     TEXT,
    silo_column    TEXT,
    diff_version   INT          NOT NULL CHECK (diff_version >= 1),
    CONSTRAINT uq_fnet_document_diff UNIQUE (fnet_id, prev_fnet_id, field_path)
);
