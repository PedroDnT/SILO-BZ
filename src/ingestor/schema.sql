-- =============================================================================
-- Supabase schema for CVM + BACEN historical data
-- Run once via: psql $SUPABASE_DB_URL -f src/ingestor/schema.sql
-- =============================================================================

-- ---------------------------------------------------------------------------
-- CVM: Fund registrations (cadastral) — FIDC, FIP, FIAGRO
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cvm_cadastral (
    id            BIGSERIAL PRIMARY KEY,
    entity        TEXT        NOT NULL,           -- fidc | fip | fiagro
    year          INT         NOT NULL,
    cnpj          TEXT        NOT NULL,           -- 14 digits, no punctuation
    denom_social  TEXT,
    dt_reg        TEXT,                           -- stored as-is from CSV
    dt_cancel     TEXT,
    sit           TEXT,
    tp_fundo      TEXT,
    raw           JSONB       NOT NULL,
    fetched_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_cvm_cadastral UNIQUE (entity, cnpj, year)
);
CREATE INDEX IF NOT EXISTS idx_cvm_cadastral_cnpj
    ON cvm_cadastral (cnpj);
CREATE INDEX IF NOT EXISTS idx_cvm_cadastral_entity_year
    ON cvm_cadastral (entity, year DESC);
CREATE INDEX IF NOT EXISTS idx_cvm_cadastral_sit
    ON cvm_cadastral (sit) WHERE sit IS NOT NULL;

-- ---------------------------------------------------------------------------
-- CVM: Monthly snapshots — FIDC, FIAGRO (mensal ZIP)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cvm_mensal (
    id            BIGSERIAL PRIMARY KEY,
    entity        TEXT        NOT NULL,           -- fidc | fiagro
    cnpj          TEXT        NOT NULL,
    period        TEXT        NOT NULL,           -- DT_COMPTC e.g. "2024-01-31"
    vl_total      TEXT,                           -- raw string; cast in queries
    vl_quota      TEXT,
    vl_patrim_liq TEXT,
    vl_inadimpl   TEXT,
    nr_cotst      TEXT,
    raw           JSONB       NOT NULL,
    fetched_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_cvm_mensal UNIQUE (entity, cnpj, period)
);
CREATE INDEX IF NOT EXISTS idx_cvm_mensal_cnpj
    ON cvm_mensal (cnpj);
CREATE INDEX IF NOT EXISTS idx_cvm_mensal_entity_period
    ON cvm_mensal (entity, period DESC);
CREATE INDEX IF NOT EXISTS idx_cvm_mensal_delinq
    ON cvm_mensal (entity, period DESC) WHERE vl_inadimpl IS NOT NULL;

-- ---------------------------------------------------------------------------
-- CVM: Periodic data — trimestral, anual, inf_trimestral, inf_quadrimestral, dfin
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cvm_periodic (
    id            BIGSERIAL PRIMARY KEY,
    entity        TEXT        NOT NULL,
    doc_type      TEXT        NOT NULL,
    year          INT         NOT NULL,
    cnpj          TEXT,
    raw           JSONB       NOT NULL,
    fetched_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_cvm_periodic_cnpj
    ON cvm_periodic (cnpj) WHERE cnpj IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_cvm_periodic_entity_type_year
    ON cvm_periodic (entity, doc_type, year DESC);

-- ---------------------------------------------------------------------------
-- CVM: SECURIT emissions — CRA, CRI, OTS, LCA, LCI
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cvm_securit_emissions (
    id              BIGSERIAL PRIMARY KEY,
    instrument_type TEXT        NOT NULL,     -- cra_mensal | cri_mensal | ots_mensal | lca_mensal | lci_mensal
    year            INT         NOT NULL,
    cnpj_securit    TEXT,
    dt_emissao      TEXT,
    dt_vencto       TEXT,
    vl_emissao      TEXT,
    vl_unit         TEXT,
    qt_titulos      TEXT,
    vl_total        TEXT,
    tp_ativo        TEXT,
    raw             JSONB       NOT NULL,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_securit_cnpj
    ON cvm_securit_emissions (cnpj_securit) WHERE cnpj_securit IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_securit_type_year
    ON cvm_securit_emissions (instrument_type, year DESC);
CREATE INDEX IF NOT EXISTS idx_securit_tp_ativo
    ON cvm_securit_emissions (tp_ativo) WHERE tp_ativo IS NOT NULL;

-- ---------------------------------------------------------------------------
-- BACEN: SGS time series (SELIC, IPCA, CDI, IGP-M, USD/BRL, …)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bacen_sgs (
    id             BIGSERIAL PRIMARY KEY,
    series_code    INT         NOT NULL,
    series_name    TEXT        NOT NULL,      -- e.g. "SELIC_META"
    reference_date DATE        NOT NULL,
    value          NUMERIC,
    fetched_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_bacen_sgs UNIQUE (series_code, reference_date)
);
CREATE INDEX IF NOT EXISTS idx_sgs_code_date
    ON bacen_sgs (series_code, reference_date DESC);
CREATE INDEX IF NOT EXISTS idx_sgs_name_date
    ON bacen_sgs (series_name, reference_date DESC);

-- ---------------------------------------------------------------------------
-- BACEN: PTAX exchange rates
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bacen_ptax (
    id             BIGSERIAL PRIMARY KEY,
    currency       TEXT        NOT NULL,      -- e.g. "USD", "EUR"
    reference_date DATE        NOT NULL,
    buy_rate       NUMERIC,
    sell_rate      NUMERIC,
    fetched_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_bacen_ptax UNIQUE (currency, reference_date)
);
CREATE INDEX IF NOT EXISTS idx_ptax_currency_date
    ON bacen_ptax (currency, reference_date DESC);

-- ---------------------------------------------------------------------------
-- BACEN: Focus / market expectations
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bacen_expectativas (
    id             BIGSERIAL PRIMARY KEY,
    endpoint_name  TEXT        NOT NULL,      -- e.g. "ExpectativasMercadoAnuais"
    indicador      TEXT,                      -- e.g. "IPCA", "Selic"
    reference_date DATE,
    median         NUMERIC,
    mean_val       NUMERIC,
    std_dev        NUMERIC,
    raw            JSONB       NOT NULL,
    fetched_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_expectativas_endpoint_indicador
    ON bacen_expectativas (endpoint_name, indicador, reference_date DESC);
