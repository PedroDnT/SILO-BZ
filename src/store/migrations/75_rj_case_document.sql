-- Recuperação judicial (RJ) cases and the links to their documents, #845
-- (epic #841). LINKS ONLY: no file is downloaded or stored.
--
-- rj_case: one row per (process, source). The same process can be listed by
-- an administrador judicial (AJ) website and, later (#846), by DJEN or a state
-- list; each source keeps its own row, so provenance is never overwritten.
-- numero_processo is the 20-digit CNJ number as printed by the source, with
-- the punctuation removed; a case whose source prints no CNJ number is not
-- stored (a key is never synthesized). devedor_cnpj is stored only when the
-- source prints it; it is never inferred from the name.
--
-- rj_document: one row per (process, url). A link enters only from a case
-- page that was fetched with HTTP 200 and that shows the process number.
-- tipo comes from rules on the title; titulo is kept as published.
--
-- first_seen_at is set once (DEFAULT, never written by the collector);
-- last_seen_at is the start of the newest run that saw the row. A new document
-- is a row whose first_seen_at falls on the day of the run.
--
-- No client grant: these are landing tables. Personal data (CPF, e-mail,
-- creditor or employee names) is never parsed out of the documents.

BEGIN;

CREATE TABLE IF NOT EXISTS rj_case (
    id               BIGSERIAL    PRIMARY KEY,
    numero_processo  TEXT         NOT NULL CHECK (numero_processo ~ '^[0-9]{20}$'),
    source           TEXT         NOT NULL CHECK (btrim(source) <> ''),
    tribunal         TEXT,
    vara             TEXT,
    classe           TEXT,
    devedor_nome     TEXT,
    devedor_cnpj     TEXT         CHECK (devedor_cnpj ~ '^[0-9]{14}$'),
    aj_name          TEXT,
    aj_case_url      TEXT,
    first_seen_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_seen_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_rj_case UNIQUE (numero_processo, source)
);
CREATE INDEX IF NOT EXISTS idx_rj_case_last_seen ON rj_case (source, last_seen_at DESC);

CREATE TABLE IF NOT EXISTS rj_document (
    id               BIGSERIAL    PRIMARY KEY,
    numero_processo  TEXT         NOT NULL CHECK (numero_processo ~ '^[0-9]{20}$'),
    url              TEXT         NOT NULL CHECK (url ~ '^https?://'),
    tipo             TEXT         NOT NULL CHECK (tipo IN (
                         'peticao_inicial', 'relacao_credores_devedor', 'relacao_credores_aj',
                         'plano', 'aditivo_plano', 'rma', 'qgc', 'ata_agc', 'edital_agc',
                         'decisao_deferimento', 'sentenca_concessao',
                         'demonstracoes_contabeis', 'outros')),
    titulo           TEXT,
    source           TEXT         NOT NULL CHECK (btrim(source) <> ''),
    found_on         TEXT         NOT NULL,
    data_publicacao  DATE,
    http_status      INT,
    first_seen_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_seen_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_rj_document UNIQUE (numero_processo, url)
);
CREATE INDEX IF NOT EXISTS idx_rj_document_first_seen ON rj_document (first_seen_at DESC);
CREATE INDEX IF NOT EXISTS idx_rj_document_source ON rj_document (source, last_seen_at DESC);

COMMENT ON TABLE rj_case IS
    'RJ / extrajudicial cases, one row per (CNJ process number, source), as the source prints them. devedor_cnpj only when printed, never inferred. first_seen_at is set once; last_seen_at is the newest run that listed the case. Landing table, no client grant (#845).';
COMMENT ON TABLE rj_document IS
    'Links to RJ case documents found on a fetched case page that shows the process number. Links only, never files. tipo is a title rule; titulo is as published; found_on is the page the link was read from. first_seen_at on the run day = a new document. Landing table, no client grant (#845).';

ALTER TABLE rj_case ENABLE ROW LEVEL SECURITY;
ALTER TABLE rj_document ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON rj_case, rj_document FROM PUBLIC;
DO $grants$
DECLARE role_name TEXT;
BEGIN
    FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated', 'silo_api'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
            EXECUTE format('REVOKE ALL ON rj_case, rj_document FROM %I', role_name);
        END IF;
    END LOOP;
END
$grants$;

COMMIT;
