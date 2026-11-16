-- Migration 87: share counts and the free float of listed companies (#1161).
-- The same DDL is in schema.sql. Append-only: a change is a new migration.

BEGIN;

-- Share counts and the free float of listed companies (#1161), as CVM
-- publishes them. Three CSV members, each read as filed:
--   cia_share_count     ITR / DFP composição do capital (2020 on): issued and
--                       treasury shares, ON / PN / total, per filed period.
--   cia_fre_capital     FRE capital social (2010 on): shares per capital type
--                       (emitido, subscrito, integralizado, autorizado).
--   cia_fre_free_float  FRE distribuição do capital (2010 on): shares in
--                       circulation (free float), ON / PN / total and percent.
-- Every Versao is kept; readers take the newest. Keys come from the source.
CREATE TABLE IF NOT EXISTS cia_share_count (
    id                BIGSERIAL    PRIMARY KEY,
    cnpj_cia          TEXT         NOT NULL,
    doc_type          TEXT         NOT NULL CHECK (doc_type IN ('itr', 'dfp')),
    dt_refer          DATE         NOT NULL,
    versao            INT,
    qt_ordin          NUMERIC(20, 0),
    qt_pref           NUMERIC(20, 0),
    qt_total          NUMERIC(20, 0),
    qt_ordin_tesouro  NUMERIC(20, 0),
    qt_pref_tesouro   NUMERIC(20, 0),
    qt_total_tesouro  NUMERIC(20, 0),
    raw               JSONB        NOT NULL DEFAULT '{}'::jsonb,
    fetched_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_cia_share_count UNIQUE NULLS NOT DISTINCT (cnpj_cia, doc_type, dt_refer, versao)
);

CREATE INDEX IF NOT EXISTS idx_cia_share_count_cnpj_date
    ON cia_share_count (cnpj_cia, dt_refer DESC);

COMMENT ON TABLE cia_share_count IS
    'CVM ITR / DFP composição do capital (2020 on): issued (paid-in) and treasury share counts per company, ON / PN / total, per filed period and version, as filed. Served by api.share_counts.';

CREATE TABLE IF NOT EXISTS cia_fre_capital (
    id                   BIGSERIAL    PRIMARY KEY,
    cnpj_cia             TEXT         NOT NULL,
    data_refer           DATE         NOT NULL,
    versao               INT,
    id_documento         TEXT,
    id_capital_social    TEXT,
    tipo_capital         TEXT,
    dt_autorizacao       DATE,
    valor_capital        NUMERIC(28, 2),
    prazo_integralizacao TEXT,
    qt_ordin             NUMERIC(20, 0),
    qt_pref              NUMERIC(20, 0),
    qt_total             NUMERIC(20, 0),
    raw                  JSONB        NOT NULL DEFAULT '{}'::jsonb,
    fetched_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_cia_fre_capital UNIQUE NULLS NOT DISTINCT (cnpj_cia, data_refer, versao, id_capital_social)
);

CREATE INDEX IF NOT EXISTS idx_cia_fre_capital_cnpj_date
    ON cia_fre_capital (cnpj_cia, data_refer DESC);

COMMENT ON TABLE cia_fre_capital IS
    'CVM FRE capital social (2010 on): share counts ON / PN / total per capital type (tipo_capital: emitido, subscrito, integralizado, autorizado), per form version, as filed. data_refer is the form''s reference date, not a filing date. Served by api.share_counts.';

CREATE TABLE IF NOT EXISTS cia_fre_free_float (
    id                   BIGSERIAL    PRIMARY KEY,
    cnpj_cia             TEXT         NOT NULL,
    data_refer           DATE         NOT NULL,
    versao               INT,
    id_documento         TEXT,
    n_acionistas_pf      INT,
    n_acionistas_pj      INT,
    n_acionistas_inst    INT,
    qt_ordin_circ        NUMERIC(20, 0),
    pct_ordin_circ       NUMERIC(12, 6),
    qt_pref_circ         NUMERIC(20, 0),
    pct_pref_circ        NUMERIC(12, 6),
    qt_total_circ        NUMERIC(20, 0),
    pct_total_circ       NUMERIC(12, 6),
    dt_ultima_assembleia DATE,
    raw                  JSONB        NOT NULL DEFAULT '{}'::jsonb,
    fetched_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_cia_fre_free_float UNIQUE NULLS NOT DISTINCT (cnpj_cia, data_refer, versao)
);

CREATE INDEX IF NOT EXISTS idx_cia_fre_free_float_cnpj_date
    ON cia_fre_free_float (cnpj_cia, data_refer DESC);

COMMENT ON TABLE cia_fre_free_float IS
    'CVM FRE distribuição do capital (2010 on): shares in circulation (the free float: not held by the controller, its related parties, management or treasury), ON / PN / total and percent, with shareholder counts, per form version, as filed. data_refer is the form''s reference date, not a filing date. Served by api.free_float.';

COMMIT;
