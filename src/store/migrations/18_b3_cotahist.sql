-- =============================================================================
-- Migration 18 — B3 COTAHIST daily exchange quotes
--
-- B3 publishes unadjusted historical quotations as public zip files
-- (COTAHIST_A{year}.ZIP / COTAHIST_D{ddmmyyyy}.ZIP), not via CVM. This is the
-- landing table at the source grain of register type 01. Join to cia_* / cvm_*
-- is deferred; ISIN and ticker (codneg) are stored for that later match.
--
-- Idempotent: CREATE TABLE IF NOT EXISTS + named UNIQUE. schema.sql carries the
-- same DDL so a fresh apply-schema path creates the table even if this file
-- were skipped; this migration covers databases that already have schema.sql
-- applied from before this change.
-- =============================================================================

CREATE TABLE IF NOT EXISTS b3_cotahist (
    id                  BIGSERIAL,
    codneg              TEXT         NOT NULL,
    trade_date          DATE         NOT NULL,
    tpmerc              TEXT         NOT NULL,
    codbdi              TEXT         NOT NULL,
    prazot              TEXT         NOT NULL DEFAULT '',
    nome_resumido       TEXT,
    especi              TEXT,
    moeda               TEXT,
    preco_abertura      NUMERIC(20,6),
    preco_maximo        NUMERIC(20,6),
    preco_minimo        NUMERIC(20,6),
    preco_medio         NUMERIC(20,6),
    preco_fechamento    NUMERIC(20,6),
    oferta_compra       NUMERIC(20,6),
    oferta_venda        NUMERIC(20,6),
    negocios            INT,
    quantidade          NUMERIC(28,0),
    volume              NUMERIC(28,2),
    preco_exercicio     NUMERIC(20,6),
    data_vencimento     DATE,
    fator_cotacao       INT,
    isin                TEXT,
    source              TEXT         NOT NULL DEFAULT 'b3_cotahist',
    raw                 JSONB        NOT NULL,
    fetched_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_b3_cotahist UNIQUE (codneg, trade_date, tpmerc, codbdi, prazot)
) PARTITION BY RANGE (trade_date);

CREATE TABLE IF NOT EXISTS b3_cotahist_pre2019 PARTITION OF b3_cotahist
    FOR VALUES FROM (MINVALUE) TO ('2019-01-01');
CREATE TABLE IF NOT EXISTS b3_cotahist_2019 PARTITION OF b3_cotahist
    FOR VALUES FROM ('2019-01-01') TO ('2020-01-01');
CREATE TABLE IF NOT EXISTS b3_cotahist_2020 PARTITION OF b3_cotahist
    FOR VALUES FROM ('2020-01-01') TO ('2021-01-01');
CREATE TABLE IF NOT EXISTS b3_cotahist_2021 PARTITION OF b3_cotahist
    FOR VALUES FROM ('2021-01-01') TO ('2022-01-01');
CREATE TABLE IF NOT EXISTS b3_cotahist_2022 PARTITION OF b3_cotahist
    FOR VALUES FROM ('2022-01-01') TO ('2023-01-01');
CREATE TABLE IF NOT EXISTS b3_cotahist_2023 PARTITION OF b3_cotahist
    FOR VALUES FROM ('2023-01-01') TO ('2024-01-01');
CREATE TABLE IF NOT EXISTS b3_cotahist_2024 PARTITION OF b3_cotahist
    FOR VALUES FROM ('2024-01-01') TO ('2025-01-01');
CREATE TABLE IF NOT EXISTS b3_cotahist_2025 PARTITION OF b3_cotahist
    FOR VALUES FROM ('2025-01-01') TO ('2026-01-01');
CREATE TABLE IF NOT EXISTS b3_cotahist_2026 PARTITION OF b3_cotahist
    FOR VALUES FROM ('2026-01-01') TO ('2027-01-01');
CREATE TABLE IF NOT EXISTS b3_cotahist_future PARTITION OF b3_cotahist
    FOR VALUES FROM ('2027-01-01') TO (MAXVALUE);

CREATE INDEX IF NOT EXISTS idx_b3_cotahist_dt
    ON b3_cotahist USING BRIN (trade_date);
CREATE INDEX IF NOT EXISTS idx_b3_cotahist_codneg
    ON b3_cotahist (codneg, trade_date DESC);
CREATE INDEX IF NOT EXISTS idx_b3_cotahist_isin
    ON b3_cotahist (isin) WHERE isin IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_b3_cotahist_tpmerc_dt
    ON b3_cotahist (tpmerc, trade_date DESC);

COMMENT ON TABLE b3_cotahist IS
    'B3 COTAHIST register-01 quotes. Unadjusted. Natural key (codneg, trade_date, tpmerc, codbdi, prazot).';
COMMENT ON COLUMN b3_cotahist.tpmerc IS
    'Market type: 010 vista, 020 fracionario, 070/080 options, 030 termo.';
COMMENT ON COLUMN b3_cotahist.prazot IS
    'Forward-market term in days; empty string for cash market (part of UNIQUE).';
