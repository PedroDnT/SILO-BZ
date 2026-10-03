-- Migration 67: the CVM 175 levels fundo -> classe -> subclasse, keyed on the
-- registry's own identifiers (issue #543, part of map #510).
--
-- WHY. registro_fundo.csv and registro_classe.csv (both in
-- FI/CAD/DADOS/registro_fundo_classe.zip) land in cvm_fund_registry on
-- (cnpj, entity_type). CVM usually reuses the fund's CNPJ for its class, and the
-- class type maps to the same entity_type, so the class row upserts onto its
-- fund's row and replaces its `raw`, where the fund's ID_Registro_Fundo was kept. On
-- 2026-10-03 only 132 of 36,770 class rows found a fund row with their
-- ID_Registro_Fundo, and all 132 are classes whose CNPJ differs from the
-- fund's. registro_subclasse.csv was not ingested at all.
--
-- WHAT. Three tables, one per file, each keyed on the ids CVM publishes:
--   cvm_registro_fundo     UNIQUE (id_registro_fundo)
--   cvm_registro_classe    UNIQUE (id_registro_classe), carries id_registro_fundo
--   cvm_registro_subclasse UNIQUE (id_registro_classe, id_subclasse)
-- A class reaches its fund by id_registro_fundo and a subclass its class by
-- id_registro_classe, never by matching CNPJs. The ids are TEXT, as filed.
--
-- WHY NOT A NEW KEY ON cvm_fund_registry. 17 dashboard sources and 8 analytical
-- files (dim_fund, api.portfolio_* among them) read that table one row per
-- (cnpj, entity_type); a level column in its key would fan every one of those
-- joins out. And a subclass has no CNPJ (registro_subclasse.csv publishes none;
-- Res. CVM 175 Art. 5 § 5 gives it none), so it cannot be a row of a table whose
-- key starts with a NOT NULL cnpj without inventing one. cvm_fund_registry is
-- left exactly as it was; no existing row or key changes here.
--
-- NO FOREIGN KEYS on the ids: the three files are loaded one after the other
-- and CVM may list a class whose fund row is absent; such a class keeps its row
-- with the id as filed, and the join simply finds nothing.
--
-- Landing tables carry no client grant (12_grants_and_rls.sql sweeps cvm_*).

BEGIN;

CREATE TABLE IF NOT EXISTS cvm_registro_fundo (
    id                 BIGSERIAL   PRIMARY KEY,
    id_registro_fundo  TEXT        NOT NULL,
    cnpj_fundo         TEXT        CHECK (cnpj_fundo IS NULL OR char_length(cnpj_fundo) = 14),
    codigo_cvm         TEXT,
    tipo_fundo         TEXT,
    denominacao_social TEXT,
    situacao           TEXT,
    data_registro      DATE,
    data_cancelamento  DATE,
    raw                JSONB       NOT NULL,
    fetched_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_registro_fundo UNIQUE (id_registro_fundo)
);
CREATE INDEX IF NOT EXISTS ix_registro_fundo_cnpj ON cvm_registro_fundo (cnpj_fundo);

CREATE TABLE IF NOT EXISTS cvm_registro_classe (
    id                   BIGSERIAL   PRIMARY KEY,
    id_registro_classe   TEXT        NOT NULL,
    id_registro_fundo    TEXT        NOT NULL,
    cnpj_classe          TEXT        CHECK (cnpj_classe IS NULL OR char_length(cnpj_classe) = 14),
    codigo_cvm           TEXT,
    tipo_classe          TEXT,
    denominacao_social   TEXT,
    situacao             TEXT,
    data_registro        DATE,
    classificacao        TEXT,
    classe_cotas         BOOLEAN,
    classificacao_anbima TEXT,
    raw                  JSONB       NOT NULL,
    fetched_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_registro_classe UNIQUE (id_registro_classe)
);
CREATE INDEX IF NOT EXISTS ix_registro_classe_fundo ON cvm_registro_classe (id_registro_fundo);
CREATE INDEX IF NOT EXISTS ix_registro_classe_cnpj  ON cvm_registro_classe (cnpj_classe);

CREATE TABLE IF NOT EXISTS cvm_registro_subclasse (
    id                 BIGSERIAL   PRIMARY KEY,
    id_registro_classe TEXT        NOT NULL,
    id_subclasse       TEXT        NOT NULL,
    codigo_cvm         TEXT,
    denominacao_social TEXT,
    situacao           TEXT,
    publico_alvo       TEXT,
    raw                JSONB       NOT NULL,
    fetched_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_registro_subclasse UNIQUE (id_registro_classe, id_subclasse)
);
CREATE INDEX IF NOT EXISTS ix_registro_subclasse_id ON cvm_registro_subclasse (id_subclasse);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon')
       AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        EXECUTE 'REVOKE ALL ON cvm_registro_fundo, cvm_registro_classe, cvm_registro_subclasse FROM anon, authenticated';
    END IF;
END $$;

COMMENT ON TABLE cvm_registro_fundo IS
    'CVM 175 fund level: registro_fundo.csv of registro_fundo_classe.zip, one row per ID_Registro_Fundo, as filed (migration 67). The parent of cvm_registro_classe. The same file also feeds cvm_fund_registry, which is keyed on (cnpj, entity_type) and cannot hold the hierarchy.';
COMMENT ON COLUMN cvm_registro_fundo.id_registro_fundo IS
    'ID_Registro_Fundo: CVM''s registry id for the fund, as filed. cvm_registro_classe.id_registro_fundo points here.';
COMMENT ON COLUMN cvm_registro_fundo.cnpj_fundo IS
    'CNPJ_Fundo, punctuation stripped.';

COMMENT ON TABLE cvm_registro_classe IS
    'CVM 175 class level: registro_classe.csv of registro_fundo_classe.zip, one row per ID_Registro_Classe, as filed (migration 67). id_registro_fundo is the registry''s own link to the parent fund (cvm_registro_fundo); never match a class to a fund by CNPJ.';
COMMENT ON COLUMN cvm_registro_classe.id_registro_classe IS
    'ID_Registro_Classe: CVM''s registry id for the class, as filed. cvm_registro_subclasse.id_registro_classe points here.';
COMMENT ON COLUMN cvm_registro_classe.id_registro_fundo IS
    'ID_Registro_Fundo as filed on the class row: the parent fund, cvm_registro_fundo.id_registro_fundo.';
COMMENT ON COLUMN cvm_registro_classe.cnpj_classe IS
    'CNPJ_Classe, punctuation stripped. Usually equal to the fund''s CNPJ (CVM reuses it for a single class); that equality is data, not the link.';
COMMENT ON COLUMN cvm_registro_classe.classe_cotas IS
    'Classe_Cotas: S = TRUE, N = FALSE, empty = NULL (it is empty outside FIF classes). S marks a classe de investimento em cotas, at least 95% of NAV in quotas of other classes (Res. CVM 175 Anexo I Art. 2 VI). Any other value fails the ingest instead of being guessed.';
COMMENT ON COLUMN cvm_registro_classe.classificacao_anbima IS
    'Classificacao_Anbima, free text as filed.';

COMMENT ON TABLE cvm_registro_subclasse IS
    'CVM 175 subclass level: registro_subclasse.csv of registro_fundo_classe.zip, one row per (ID_Registro_Classe, ID_Subclasse), as filed (migration 67). The file has no CNPJ and none is stamped here: a subclass''s CNPJ is its class''s, reached through id_registro_classe.';
COMMENT ON COLUMN cvm_registro_subclasse.id_subclasse IS
    'ID_Subclasse as filed: the code the informe diário, the lâmina and the CDA publish as ID_SUBCLASSE.';

COMMIT;
