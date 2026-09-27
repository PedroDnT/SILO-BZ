-- 42_fnet_document.sql — the B3 Fundos.NET (FNET) document register, with versions.
--
-- Two tables, mirrored verbatim into schema.sql (which stays canonical).
-- Idempotent (IF NOT EXISTS + named UNIQUE constraints) and psql-clean: CI
-- applies with -v ON_ERROR_STOP=1. Backlog item B1 in
-- docs/planning/COMPETITIVE_GAPS.md §7; the endpoint contract is in
-- src/fetchers/fnet_fetcher.py.
--
-- WHY THIS EXISTS
-- ---------------
-- CVM's dados.cvm CSVs are republished in place: a restated informe replaces
-- the original, and CVM's FIDC files carry no version field at all. FNET keeps
-- every version as its own document, says whether it is the original (AP), a
-- voluntary restatement (RE) or one CVM required (RC), and keeps superseded
-- versions listed. This register is the only public record of FIDC
-- restatements, and its delivery timestamps are what filing punctuality is
-- measured against. Metadata only: no document bodies are stored.
--
-- fnet_document — one row per FNET document id (each version is a new id).
--   Grain: fnet_id. Values as FNET publishes them. reference_date is parsed
--   only from dd/mm/yyyy (that day) or mm/yyyy (first of the month);
--   anything else stays NULL beside reference_raw. delivered_at is FNET's
--   dataEntrega, São Paulo local time, stored as printed (no zone).
--   status is AS OF fetched_at: a document fetched while active reads AC
--   until a later fetch sees it superseded (IC).
--   fund_name is FNET's label and is NEVER joined on — see the next table.
CREATE TABLE IF NOT EXISTS fnet_document (
    id               BIGSERIAL    PRIMARY KEY,
    fnet_id          BIGINT       NOT NULL CHECK (fnet_id > 0),
    fund_name        TEXT,
    fundo_ou_classe  TEXT,
    categoria        TEXT,
    tipo_documento   TEXT,
    especie          TEXT,
    reference_raw    TEXT,
    reference_format TEXT,
    reference_date   DATE,
    delivered_at     TIMESTAMP    NOT NULL,
    versao           INT          NOT NULL CHECK (versao >= 1),
    modalidade       TEXT,
    status           TEXT,
    situacao         TEXT,
    alta_prioridade  BOOLEAN,
    raw              JSONB,
    fetched_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fnet_document UNIQUE (fnet_id)
);
CREATE INDEX IF NOT EXISTS idx_fnet_document_delivered ON fnet_document (delivered_at DESC);
CREATE INDEX IF NOT EXISTS idx_fnet_document_modalidade ON fnet_document (modalidade, delivered_at DESC);
CREATE INDEX IF NOT EXISTS idx_fnet_document_type_ref ON fnet_document (tipo_documento, reference_date);

-- fnet_document_filter — "FNET returned this document for this query filter".
--   FNET's search rows carry NO fund CNPJ (cnpjFundo is null on every row,
--   even when the query filters on it) and no fund type. Both are known only
--   because the ingest ASKED for them, so that is what is recorded:
--     filter_name = 'tipoFundo', filter_value = '1' (FII) | '2' (FIDC) | '3' (ETF)
--     filter_name = 'cnpjFundo', filter_value = the 14-digit CNPJ queried
--   A document's fund CNPJ is a row here or it is unknown. It is never
--   inferred from fund_name (CLAUDE.md: no name matching, ever).
CREATE TABLE IF NOT EXISTS fnet_document_filter (
    id            BIGSERIAL    PRIMARY KEY,
    fnet_id       BIGINT       NOT NULL,
    filter_name   TEXT         NOT NULL CHECK (filter_name IN ('tipoFundo', 'cnpjFundo')),
    filter_value  TEXT         NOT NULL,
    fetched_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fnet_document_filter UNIQUE (fnet_id, filter_name, filter_value),
    CONSTRAINT ck_fnet_filter_cnpj CHECK (filter_name <> 'cnpjFundo' OR filter_value ~ '^[0-9]{14}$')
);
CREATE INDEX IF NOT EXISTS idx_fnet_filter_value ON fnet_document_filter (filter_name, filter_value);
