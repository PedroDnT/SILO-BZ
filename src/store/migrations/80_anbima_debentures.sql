-- ANBIMA public debenture pages, #1006. Collected under the owner's ANBIMA
-- permission (ADR 0004), which covers collection and storage only: no serving
-- grant, never in schema api, serve/, the MCP or the dashboard.
-- anbima_debenture_capture holds one row per page read in a run (capture_id is
-- the cvm_ingest_log run UUID). The raw page text is kept only when the parse
-- failed, so a layout change can be debugged. The three data tables store
-- values as published, with the capture that last wrote them. The indicative
-- rate is ANBIMA's model value, not a trade.
BEGIN;
CREATE TABLE IF NOT EXISTS anbima_debenture_capture (
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
    CONSTRAINT uq_anbima_debenture_capture UNIQUE (capture_id, codigo, page),
    CONSTRAINT ck_anbima_debenture_capture_evidence CHECK (
        (status IN ('parsed', 'no_data') AND payload_sha256 IS NOT NULL AND error IS NULL)
        OR (status = 'parse_error' AND raw_text IS NOT NULL AND error IS NOT NULL)
        OR (status = 'fetch_error' AND error IS NOT NULL)
    )
);
CREATE TABLE IF NOT EXISTS anbima_debenture (
    codigo                   TEXT NOT NULL CHECK (btrim(codigo) <> ''),
    isin                     TEXT,
    serie                    TEXT,
    emissao                  TEXT,
    emissor                  TEXT NOT NULL,
    emissor_cnpj             TEXT NOT NULL CHECK (emissor_cnpj ~ '^\d{14}$'),
    setor                    TEXT,
    remuneracao              TEXT NOT NULL,
    indexador                TEXT,
    forma_remuneracao        TEXT CHECK (forma_remuneracao IN ('spread', 'percentual', 'prefixado')),
    taxa_remuneracao_pct     NUMERIC,
    data_emissao             DATE NOT NULL,
    data_vencimento          DATE NOT NULL,
    data_inicio_rentabilidade DATE,
    proxima_repactuacao      DATE,
    expressao_papel          TEXT,
    quantidade_serie_emissao NUMERIC,
    volume_serie_emissao_brl NUMERIC,
    vne_brl                  NUMERIC,
    vna_brl                  NUMERIC,
    quantidade_mercado_b3    NUMERIC,
    estoque_mercado_b3_brl   NUMERIC,
    volume_emissao_brl       NUMERIC,
    quantidade_emissao       NUMERIC,
    resgate_antecipado       BOOLEAN,
    lei_12431                BOOLEAN,
    lei_12431_artigo         TEXT,
    coordenador_lider        TEXT,
    coordenador_lider_cnpj   TEXT,
    agente_fiduciario        TEXT,
    agente_fiduciario_cnpj   TEXT,
    banco_mandatario         TEXT,
    banco_mandatario_cnpj    TEXT,
    garantia                 TEXT,
    capture_id               UUID NOT NULL,
    observed_at              TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_anbima_debenture UNIQUE (codigo)
);
CREATE INDEX IF NOT EXISTS idx_anbima_debenture_isin ON anbima_debenture (isin);
CREATE TABLE IF NOT EXISTS anbima_debenture_event (
    codigo              TEXT NOT NULL CHECK (btrim(codigo) <> ''),
    data_evento         DATE NOT NULL,
    evento              TEXT NOT NULL CHECK (btrim(evento) <> ''),
    data_liquidacao     DATE,
    percentual_taxa_pct NUMERIC,
    valor_pago_brl      NUMERIC,
    status              TEXT,
    capture_id          UUID NOT NULL,
    observed_at         TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_anbima_debenture_event UNIQUE (codigo, data_evento, evento)
);
CREATE TABLE IF NOT EXISTS anbima_debenture_indicative (
    codigo              TEXT NOT NULL CHECK (btrim(codigo) <> ''),
    data_referencia     DATE NOT NULL,
    intervalo_min_pct   NUMERIC,
    intervalo_max_pct   NUMERIC,
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
    CONSTRAINT uq_anbima_debenture_indicative UNIQUE (codigo, data_referencia)
);
CREATE INDEX IF NOT EXISTS idx_anbima_debenture_indicative_date
    ON anbima_debenture_indicative (data_referencia DESC);
COMMENT ON TABLE anbima_debenture_capture IS
    'One ANBIMA public debenture page read per run (capture_id = cvm_ingest_log run_id). raw_text is kept only for parse_error. observed_at is SILO retrieval time.';
COMMENT ON TABLE anbima_debenture IS
    'Latest characteristics of each debenture as ANBIMA publishes them (data.anbima.com.br/debentures/<codigo>/caracteristicas). remuneracao is the published text; indexador, forma_remuneracao and taxa_remuneracao_pct are split from it and NULL when the text is not recognised. Private: no serving grant.';
COMMENT ON TABLE anbima_debenture_event IS
    'Event agenda (interest, amortisation, maturity) as published. A later capture updates a row; an event ANBIMA drops keeps its old capture_id, so read the rows of the latest capture per codigo. Private.';
COMMENT ON TABLE anbima_debenture_indicative IS
    'ANBIMA indicative prices for the last 5 sessions, as published, captured forward only. taxa_indicativa_pct is an ANBIMA model value, not a trade; for percentual (% DI) bonds every rate is a percent of DI. Private.';
ALTER TABLE anbima_debenture_capture ENABLE ROW LEVEL SECURITY;
ALTER TABLE anbima_debenture ENABLE ROW LEVEL SECURITY;
ALTER TABLE anbima_debenture_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE anbima_debenture_indicative ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON anbima_debenture_capture, anbima_debenture, anbima_debenture_event,
    anbima_debenture_indicative FROM PUBLIC;
DO $grants$
DECLARE role_name TEXT;
BEGIN
    FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated', 'silo_api'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
            EXECUTE format('REVOKE ALL ON anbima_debenture_capture, anbima_debenture, '
                           'anbima_debenture_event, anbima_debenture_indicative FROM %I', role_name);
        END IF;
    END LOOP;
END
$grants$;
COMMIT;
