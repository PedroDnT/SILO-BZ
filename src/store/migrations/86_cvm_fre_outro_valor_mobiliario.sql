-- CVM FRE, item "outros valores mobiliários" (#1164): debenture and other
-- debt issues of listed companies, with issue date, maturity, quantity, value and
-- outstanding balance. Values as filed; unmapped columns in raw.
BEGIN;
CREATE TABLE IF NOT EXISTS cvm_fre_outro_valor_mobiliario (
    cnpj_cia              TEXT NOT NULL CHECK (cnpj_cia ~ '^\d{14}$'),
    data_refer            DATE NOT NULL,
    versao                INT  NOT NULL,
    id_documento          TEXT NOT NULL,
    row_hash              TEXT NOT NULL,
    nome_companhia        TEXT,
    valor_mobiliario      TEXT,
    identificacao         TEXT,
    data_emissao          DATE,
    data_vencimento       DATE,
    quantidade            NUMERIC,
    valor                 NUMERIC,
    saldo_devedor         NUMERIC,
    restricao_circulacao  BOOLEAN,
    conversibilidade      BOOLEAN,
    resgatavel            BOOLEAN,
    caracteristicas_divida TEXT,
    raw                   JSONB NOT NULL DEFAULT '{}'::jsonb,
    fetched_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_cvm_fre_outro_valor_mobiliario
        UNIQUE (cnpj_cia, data_refer, versao, id_documento, row_hash)
);
CREATE INDEX IF NOT EXISTS idx_cvm_fre_ovm_cnpj
    ON cvm_fre_outro_valor_mobiliario (cnpj_cia, data_refer DESC, versao DESC);
COMMENT ON TABLE cvm_fre_outro_valor_mobiliario IS
    'FRE item "outros valores mobiliários" (fre_cia_aberta_outro_valor_mobiliario_<year>.csv, 2010 on): one row per issue (debentures, commercial notes, CRI, ...) of a listed company, every FRE version, as filed. The file has no unique row key, so row_hash (sha256 of the source row) ends the key. Rate and indexer exist only as free text (caracteristicas_divida); they are not parsed. Landing table, no client grant.';
ALTER TABLE cvm_fre_outro_valor_mobiliario ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON cvm_fre_outro_valor_mobiliario FROM PUBLIC;
DO $grants$
DECLARE role_name TEXT;
BEGIN
    FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated', 'silo_api'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
            EXECUTE format('REVOKE ALL ON cvm_fre_outro_valor_mobiliario FROM %I', role_name);
        END IF;
    END LOOP;
END
$grants$;
COMMIT;
