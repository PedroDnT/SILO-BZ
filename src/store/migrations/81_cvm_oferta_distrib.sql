-- CVM public offerings (OFERTA/DISTRIB), #1005. Two snapshot members of one
-- zip, each on its source key. Values as filed; unmapped columns in raw.
-- No ISIN and no remuneration terms are in either file: the join to a traded
-- debenture goes through anbima_debenture (emissor_cnpj + emissao).
BEGIN;
CREATE TABLE IF NOT EXISTS cvm_oferta_distrib_160 (
    numero_requerimento    TEXT NOT NULL CHECK (btrim(numero_requerimento) <> ''),
    rito_requerimento      TEXT,
    numero_processo        TEXT,
    data_requerimento      DATE,
    data_registro          DATE,
    data_encerramento      DATE,
    status_requerimento    TEXT,
    valor_mobiliario       TEXT,
    tipo_requerimento      TEXT,
    cnpj_emissor           TEXT NOT NULL CHECK (cnpj_emissor ~ '^\d{14}$'),
    nome_emissor           TEXT,
    cnpj_lider             TEXT,
    nome_lider             TEXT,
    tipo_oferta            TEXT,
    emissao                TEXT,
    qtde_total_registrada  NUMERIC,
    valor_total_registrado NUMERIC,
    oferta_inicial         TEXT,
    publico_alvo           TEXT,
    titulo_incentivado     TEXT,
    titulo_sustentavel     TEXT,
    regime_distribuicao    TEXT,
    mercado_negociacao     TEXT,
    tipo_lastro            TEXT,
    regime_fiduciario      TEXT,
    tipo_societario        TEXT,
    agente_fiduciario      TEXT,
    data_deliberacao       DATE,
    source_file            TEXT NOT NULL,
    raw                    JSONB,
    ingested_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_cvm_oferta_distrib_160 UNIQUE (numero_requerimento)
);
CREATE INDEX IF NOT EXISTS idx_cvm_oferta_160_emissor
    ON cvm_oferta_distrib_160 (cnpj_emissor, emissao);
CREATE TABLE IF NOT EXISTS cvm_oferta_distrib_400 (
    numero_registro_oferta   TEXT NOT NULL CHECK (btrim(numero_registro_oferta) <> ''),
    serie                    TEXT NOT NULL CHECK (btrim(serie) <> ''),
    tipo_oferta              TEXT,
    tipo_componente          TEXT,
    numero_processo          TEXT,
    tipo_ativo               TEXT NOT NULL,
    rito_oferta              TEXT NOT NULL,
    modalidade_registro      TEXT,
    cnpj_emissor             TEXT CHECK (cnpj_emissor ~ '^\d{14}$'),
    nome_emissor             TEXT,
    cnpj_lider               TEXT,
    nome_lider               TEXT,
    data_protocolo           DATE,
    data_registro_oferta     DATE,
    data_inicio_oferta       DATE,
    data_encerramento_oferta DATE,
    emissao                  TEXT,
    classe_ativo             TEXT,
    especie_ativo            TEXT,
    forma_ativo              TEXT,
    data_emissao             DATE,
    data_vencimento          DATE,
    quantidade_total         NUMERIC,
    preco_unitario           NUMERIC,
    valor_total              NUMERIC,
    oferta_incentivo_fiscal  TEXT,
    atualizacao_monetaria    TEXT,
    juros                    TEXT,
    tipo_societario_emissor  TEXT,
    ultimo_comunicado        TEXT,
    data_comunicado          DATE,
    source_file              TEXT NOT NULL,
    raw                      JSONB,
    ingested_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_cvm_oferta_distrib_400 UNIQUE (numero_registro_oferta, serie)
);
CREATE INDEX IF NOT EXISTS idx_cvm_oferta_400_emissor
    ON cvm_oferta_distrib_400 (cnpj_emissor, emissao);
COMMENT ON TABLE cvm_oferta_distrib_160 IS
    'Every Resolução CVM 160 offering (2023 on, all security types), one row per Numero_Requerimento, as filed in oferta_resolucao_160.csv. No ISIN, series or remuneration. Landing table, no client grant.';
COMMENT ON TABLE cvm_oferta_distrib_400 IS
    'Registered ICVM 400 debenture offerings from the legacy oferta_distribuicao.csv, one row per (Numero_Registro_Oferta, Serie). ICVM 476 offerings have no natural key and are not loaded; a repeated key is dropped. cnpj_emissor is NULL when CVM published none (mostly before 2005). Landing table, no client grant.';
ALTER TABLE cvm_oferta_distrib_160 ENABLE ROW LEVEL SECURITY;
ALTER TABLE cvm_oferta_distrib_400 ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON cvm_oferta_distrib_160, cvm_oferta_distrib_400 FROM PUBLIC;
DO $grants$
DECLARE role_name TEXT;
BEGIN
    FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated', 'silo_api'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
            EXECUTE format('REVOKE ALL ON cvm_oferta_distrib_160, cvm_oferta_distrib_400 FROM %I', role_name);
        END IF;
    END LOOP;
END
$grants$;
COMMIT;
