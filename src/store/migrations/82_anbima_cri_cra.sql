-- ANBIMA public CRI and CRA pages, #1014. Same permission and same rules as
-- the debentures (migration 80): collection and storage only, no serving
-- grant, never in schema api, serve/, the MCP or the dashboard. Separate
-- tables, not the debenture ones: a CRI/CRA has a devedor and a securitizadora,
-- not an emissor, and its rate table has no indicative interval.
-- anbima_cri_cra_capture holds one row per page read in a run (capture_id is
-- the cvm_ingest_log run UUID); raw_text is kept only for a parse failure.
-- The devedor and cedente have no CNPJ on the page, so none is stored.
BEGIN;
CREATE TABLE IF NOT EXISTS anbima_cri_cra_capture (
    capture_id     UUID NOT NULL,
    codigo         TEXT NOT NULL CHECK (btrim(codigo) <> ''),
    page           TEXT NOT NULL CHECK (page IN ('caracteristicas', 'agenda', 'precos')),
    observed_at    TIMESTAMPTZ NOT NULL,
    source_url     TEXT NOT NULL,
    status         TEXT NOT NULL CHECK (status IN ('parsed', 'no_data', 'fetch_error', 'parse_error')),
    rows_parsed    INTEGER NOT NULL DEFAULT 0 CHECK (rows_parsed >= 0),
    payload_sha256 TEXT CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
    raw_text       TEXT,
    error          TEXT,
    CONSTRAINT uq_anbima_cri_cra_capture UNIQUE (capture_id, codigo, page),
    CONSTRAINT ck_anbima_cri_cra_capture_evidence CHECK (
        (status IN ('parsed', 'no_data') AND payload_sha256 IS NOT NULL AND error IS NULL)
        OR (status = 'parse_error' AND raw_text IS NOT NULL AND error IS NOT NULL)
        OR (status = 'fetch_error' AND error IS NOT NULL)
    )
);
CREATE TABLE IF NOT EXISTS anbima_cri_cra (
    codigo                    TEXT NOT NULL CHECK (btrim(codigo) <> ''),
    tipo                      TEXT NOT NULL CHECK (tipo IN ('CRI', 'CRA')),
    isin                      TEXT,
    serie                     TEXT,
    emissao                   TEXT,
    devedor                   TEXT,
    cedente                   TEXT,
    securitizadora            TEXT NOT NULL,
    securitizadora_cnpj       TEXT NOT NULL CHECK (securitizadora_cnpj ~ '^\d{14}$'),
    remuneracao               TEXT NOT NULL,
    indexador                 TEXT,
    forma_remuneracao         TEXT CHECK (forma_remuneracao IN ('spread', 'percentual', 'prefixado')),
    taxa_remuneracao_pct      NUMERIC,
    data_emissao              DATE NOT NULL,
    data_vencimento           DATE NOT NULL,
    data_inicio_rentabilidade DATE,
    expressao_papel           TEXT,
    quantidade_serie_emissao  NUMERIC,
    volume_serie_emissao_brl  NUMERIC,
    vne_brl                   NUMERIC,
    vna_brl                   NUMERIC,
    quantidade_emissao        NUMERIC,
    volume_emissao_brl        NUMERIC,
    resgate_antecipado        BOOLEAN,
    classe                    TEXT,
    concentracao              TEXT,
    categoria                 TEXT,
    setor                     TEXT,
    tipo_lastro               TEXT,
    coordenador_lider         TEXT,
    coordenador_lider_cnpj    TEXT,
    agente_fiduciario         TEXT,
    agente_fiduciario_cnpj    TEXT,
    capture_id                UUID NOT NULL,
    observed_at               TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_anbima_cri_cra UNIQUE (codigo)
);
CREATE INDEX IF NOT EXISTS idx_anbima_cri_cra_isin ON anbima_cri_cra (isin);
CREATE TABLE IF NOT EXISTS anbima_cri_cra_event (
    codigo              TEXT NOT NULL CHECK (btrim(codigo) <> ''),
    data_evento         DATE NOT NULL,
    evento              TEXT NOT NULL CHECK (btrim(evento) <> ''),
    data_liquidacao     DATE,
    percentual_taxa_pct NUMERIC,
    valor_pago_brl      NUMERIC,
    status              TEXT,
    capture_id          UUID NOT NULL,
    observed_at         TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_anbima_cri_cra_event UNIQUE (codigo, data_evento, evento)
);
CREATE TABLE IF NOT EXISTS anbima_cri_cra_indicative (
    codigo              TEXT NOT NULL CHECK (btrim(codigo) <> ''),
    data_referencia     DATE NOT NULL,
    taxa_compra_pct     NUMERIC,
    taxa_venda_pct      NUMERIC,
    taxa_indicativa_pct NUMERIC,
    desvio_padrao       NUMERIC,
    duration_du         NUMERIC,
    pct_pu_par          NUMERIC,
    pu_indicativo_brl   NUMERIC,
    pct_reune           NUMERIC,
    referencia_ntnb     DATE,
    capture_id          UUID NOT NULL,
    observed_at         TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_anbima_cri_cra_indicative UNIQUE (codigo, data_referencia)
);
CREATE INDEX IF NOT EXISTS idx_anbima_cri_cra_indicative_date
    ON anbima_cri_cra_indicative (data_referencia DESC);
COMMENT ON TABLE anbima_cri_cra_capture IS
    'One ANBIMA public CRI/CRA page read per run (capture_id = cvm_ingest_log run_id). raw_text is kept only for parse_error. observed_at is SILO retrieval time.';
COMMENT ON TABLE anbima_cri_cra IS
    'Latest characteristics of each CRI and CRA as ANBIMA publishes them (data.anbima.com.br/certificado-de-recebiveis/<codigo>/caracteristicas). The issuer is the securitizadora; the devedor has no CNPJ on the page. remuneracao is the published text; indexador, forma_remuneracao and taxa_remuneracao_pct are split from it and NULL when the text is not recognised. Private: no serving grant.';
COMMENT ON TABLE anbima_cri_cra_event IS
    'CRI/CRA event agenda (interest, amortisation, maturity) as published. An event ANBIMA drops keeps its old capture_id, so read the rows of the latest capture per codigo. Private.';
COMMENT ON TABLE anbima_cri_cra_indicative IS
    'ANBIMA CRI/CRA indicative prices for the last 5 sessions, as published, captured forward only. taxa_indicativa_pct is an ANBIMA model value, not a trade; for a DI-indexed CRI/CRA it is the spread over DI (or the percent of DI). Private.';
ALTER TABLE anbima_cri_cra_capture ENABLE ROW LEVEL SECURITY;
ALTER TABLE anbima_cri_cra ENABLE ROW LEVEL SECURITY;
ALTER TABLE anbima_cri_cra_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE anbima_cri_cra_indicative ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON anbima_cri_cra_capture, anbima_cri_cra, anbima_cri_cra_event,
    anbima_cri_cra_indicative FROM PUBLIC;
DO $grants$
DECLARE role_name TEXT;
BEGIN
    FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated', 'silo_api'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
            EXECUTE format('REVOKE ALL ON anbima_cri_cra_capture, anbima_cri_cra, '
                           'anbima_cri_cra_event, anbima_cri_cra_indicative FROM %I', role_name);
        END IF;
    END LOOP;
END
$grants$;
COMMIT;
