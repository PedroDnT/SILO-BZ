-- =============================================================================
-- Migration 04 — CIA_ABERTA domain (W5 scaffold)
--
-- Creates four tables for listed-company (Domain B) data:
--
--   cia_company  — company registry from CAD, one row per cd_cvm
--   cia_filing   — ITR/DFP/IPE filing headers (what was submitted and when)
--   cia_account  — line-item account data from ITR/DFP financial statements
--                  PARTITIONED BY RANGE (dt_refer) with yearly partitions
--   cia_event    — IPE press events (Eventual Press Events)
--
-- Design principles (same as existing schema):
--   • All DDL is idempotent (IF NOT EXISTS / NULLS NOT DISTINCT)
--   • JSONB `raw` preserves original CSV fields for audit and re-processing
--   • UNIQUE constraints enable ON CONFLICT upserts without gaps
--   • cia_account partitioned by dt_refer year (high row volume expected)
--   • BRIN indexes on dt_refer for monotonically-appended date columns
--   • No ingestion code in this migration — scaffold only
-- =============================================================================

-- ---------------------------------------------------------------------------
-- cia_company — listed company registry (from CAD endpoint)
-- Source: https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv
-- One row per company; static file refreshed periodically by CVM.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cia_company (
    cd_cvm      TEXT         PRIMARY KEY,
    cnpj_cia    TEXT,
    denom_cia   TEXT,
    setor       TEXT,
    segmento    TEXT,
    situacao    TEXT,
    raw         JSONB,
    fetched_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cia_company_cnpj
    ON cia_company (cnpj_cia);
CREATE INDEX IF NOT EXISTS idx_cia_company_situacao
    ON cia_company (situacao);

-- ---------------------------------------------------------------------------
-- cia_filing — filing headers (ITR / DFP / IPE submissions)
-- Source: ITR/DFP yearly ZIPs, general header CSV member (_cia_aberta_{YYYY}.csv)
--         and IPE yearly CSVs.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cia_filing (
    id          BIGSERIAL    PRIMARY KEY,
    cd_cvm      TEXT         NOT NULL,
    doc_type    TEXT         NOT NULL,  -- itr | dfp | ipe
    dt_refer    DATE         NOT NULL,
    versao      INT,
    id_doc      TEXT,
    dt_receb    DATE,
    link_doc    TEXT,
    CONSTRAINT uq_cia_filing UNIQUE (cd_cvm, doc_type, dt_refer, versao)
);

CREATE INDEX IF NOT EXISTS idx_cia_filing_cdcvm
    ON cia_filing (cd_cvm, doc_type, dt_refer DESC);

-- ---------------------------------------------------------------------------
-- cia_account — line-item financial account data from ITR and DFP
-- Source: ITR/DFP yearly ZIPs — BPA/BPP/DRE/DFC_MD/DFC_MI/DMPL/DRA/DVA members
--         (both _con_ consolidated and _ind_ individual variants)
--
-- Partitioned by dt_refer (reference date) using RANGE partitioning.
-- Yearly partitions cover 2010-2026; rows beyond 2026 land in cia_account_future.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cia_account (
    id              BIGSERIAL,
    cd_cvm          TEXT         NOT NULL,
    cnpj_cia        TEXT,
    doc_type        TEXT         NOT NULL,  -- itr | dfp
    grupo           TEXT         NOT NULL,  -- BPA | BPP | DRE | DFC_MD | DFC_MI | DMPL | DRA | DVA | composicao_capital | parecer
    escopo          TEXT         NOT NULL,  -- con | ind
    dt_refer        DATE         NOT NULL,
    ordem_exerc     TEXT,                   -- ULTIMO | PENULTIMO
    dt_ini_exerc    DATE,
    dt_fim_exerc    DATE,
    cd_conta        TEXT         NOT NULL,
    ds_conta        TEXT,
    vl_conta        NUMERIC(28,2),
    escala_moeda    TEXT,
    st_conta_fixa   CHAR(1),
    versao          INT,
    raw             JSONB,
    CONSTRAINT uq_cia_account UNIQUE NULLS NOT DISTINCT
        (cd_cvm, doc_type, grupo, escopo, dt_refer, ordem_exerc, cd_conta, versao)
) PARTITION BY RANGE (dt_refer);

-- Indexes on the partitioned parent — propagate to all child partitions.
CREATE INDEX IF NOT EXISTS idx_cia_account_cdcvm_date
    ON cia_account (cd_cvm, dt_refer DESC);
CREATE INDEX IF NOT EXISTS idx_cia_account_conta
    ON cia_account (cd_conta);
-- BRIN index for the monotonically-appended dt_refer pattern.
CREATE INDEX IF NOT EXISTS idx_cia_account_dtrefer_brin
    ON cia_account USING BRIN (dt_refer);

-- ---------------------------------------------------------------------------
-- cia_account yearly partitions (2010-2026)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cia_account_2010 PARTITION OF cia_account
    FOR VALUES FROM ('2010-01-01') TO ('2011-01-01');

CREATE TABLE IF NOT EXISTS cia_account_2011 PARTITION OF cia_account
    FOR VALUES FROM ('2011-01-01') TO ('2012-01-01');

CREATE TABLE IF NOT EXISTS cia_account_2012 PARTITION OF cia_account
    FOR VALUES FROM ('2012-01-01') TO ('2013-01-01');

CREATE TABLE IF NOT EXISTS cia_account_2013 PARTITION OF cia_account
    FOR VALUES FROM ('2013-01-01') TO ('2014-01-01');

CREATE TABLE IF NOT EXISTS cia_account_2014 PARTITION OF cia_account
    FOR VALUES FROM ('2014-01-01') TO ('2015-01-01');

CREATE TABLE IF NOT EXISTS cia_account_2015 PARTITION OF cia_account
    FOR VALUES FROM ('2015-01-01') TO ('2016-01-01');

CREATE TABLE IF NOT EXISTS cia_account_2016 PARTITION OF cia_account
    FOR VALUES FROM ('2016-01-01') TO ('2017-01-01');

CREATE TABLE IF NOT EXISTS cia_account_2017 PARTITION OF cia_account
    FOR VALUES FROM ('2017-01-01') TO ('2018-01-01');

CREATE TABLE IF NOT EXISTS cia_account_2018 PARTITION OF cia_account
    FOR VALUES FROM ('2018-01-01') TO ('2019-01-01');

CREATE TABLE IF NOT EXISTS cia_account_2019 PARTITION OF cia_account
    FOR VALUES FROM ('2019-01-01') TO ('2020-01-01');

CREATE TABLE IF NOT EXISTS cia_account_2020 PARTITION OF cia_account
    FOR VALUES FROM ('2020-01-01') TO ('2021-01-01');

CREATE TABLE IF NOT EXISTS cia_account_2021 PARTITION OF cia_account
    FOR VALUES FROM ('2021-01-01') TO ('2022-01-01');

CREATE TABLE IF NOT EXISTS cia_account_2022 PARTITION OF cia_account
    FOR VALUES FROM ('2022-01-01') TO ('2023-01-01');

CREATE TABLE IF NOT EXISTS cia_account_2023 PARTITION OF cia_account
    FOR VALUES FROM ('2023-01-01') TO ('2024-01-01');

CREATE TABLE IF NOT EXISTS cia_account_2024 PARTITION OF cia_account
    FOR VALUES FROM ('2024-01-01') TO ('2025-01-01');

CREATE TABLE IF NOT EXISTS cia_account_2025 PARTITION OF cia_account
    FOR VALUES FROM ('2025-01-01') TO ('2026-01-01');

CREATE TABLE IF NOT EXISTS cia_account_2026 PARTITION OF cia_account
    FOR VALUES FROM ('2026-01-01') TO ('2027-01-01');

-- Catch-all for future years; add explicit partitions annually.
CREATE TABLE IF NOT EXISTS cia_account_future PARTITION OF cia_account
    FOR VALUES FROM ('2027-01-01') TO (MAXVALUE);

-- ---------------------------------------------------------------------------
-- cia_event — IPE press events
-- Source: https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/IPE/DADOS/ipe_cia_aberta_{YYYY}.zip
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cia_event (
    id              BIGSERIAL    PRIMARY KEY,
    cd_cvm          TEXT         NOT NULL,
    cnpj_cia        TEXT,
    data_refer      DATE,
    data_entrega    TIMESTAMPTZ,
    categoria       TEXT,
    tipo            TEXT,
    especie         TEXT,
    assunto         TEXT,
    protocolo       TEXT,
    versao          INT,
    link_download   TEXT,
    CONSTRAINT uq_cia_event UNIQUE (protocolo, versao)
);

CREATE INDEX IF NOT EXISTS idx_cia_event_cdcvm
    ON cia_event (cd_cvm, data_refer DESC);
CREATE INDEX IF NOT EXISTS idx_cia_event_categoria
    ON cia_event (categoria, data_entrega DESC);
