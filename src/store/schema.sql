-- =============================================================================
-- CVM + BACEN schema  —  Supabase / PostgreSQL 14+
--
-- Design principles:
--   • Proper DATE / NUMERIC types for all date and monetary columns
--   • JSONB `raw` column preserves every original CSV field (audit / re-processing)
--   • cvm_fi_diario is partitioned by year  (≈400k rows/month → 5M+ rows/year)
--   • BRIN indexes on date columns of large tables (monotonic append pattern)
--   • cvm_ingest_log tracks every ingest run for idempotence and gap detection
--   • All upserts rely on named UNIQUE constraints so ON CONFLICT is explicit
-- =============================================================================

-- ---------------------------------------------------------------------------
-- Ingest audit log  (populated by ingestor, not by the API)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cvm_ingest_log (
    id            BIGSERIAL    PRIMARY KEY,
    run_id        UUID         NOT NULL DEFAULT gen_random_uuid(),
    entity        TEXT         NOT NULL,   -- fi | fidc | fip | fiagro | fii | securit
    doc_type      TEXT         NOT NULL,
    period_year   INT,
    period_month  INT,
    rows_upserted INT          NOT NULL DEFAULT 0,
    status        TEXT         NOT NULL DEFAULT 'ok',  -- ok | error | skipped
    error_msg     TEXT,
    started_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    finished_at   TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_ingest_log_entity_doc
    ON cvm_ingest_log (entity, doc_type, period_year DESC, period_month DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_ingest_log_run
    ON cvm_ingest_log (run_id);

-- ---------------------------------------------------------------------------
-- FI — daily fund snapshot  (INF_DIARIO, ~400k rows/month)
-- Partitioned by year so each year is a ~5M-row segment with its own index.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cvm_fi_diario (
    id            BIGSERIAL,
    cnpj          TEXT         NOT NULL CHECK (char_length(cnpj) = 14),
    tp_fundo      TEXT,                      -- fund class label
    dt_comptc     DATE         NOT NULL,
    vl_total      NUMERIC(20,6),
    vl_quota      NUMERIC(20,12),
    vl_patrim_liq NUMERIC(20,6),
    captc_dia     NUMERIC(20,6),
    resg_dia      NUMERIC(20,6),
    nr_cotst      INT,
    raw           JSONB        NOT NULL,
    fetched_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fi_diario UNIQUE (cnpj, dt_comptc)
) PARTITION BY RANGE (dt_comptc);

-- Year partitions  (add new ones each January)
CREATE TABLE IF NOT EXISTS cvm_fi_diario_2019 PARTITION OF cvm_fi_diario
    FOR VALUES FROM ('2019-01-01') TO ('2020-01-01');
CREATE TABLE IF NOT EXISTS cvm_fi_diario_2020 PARTITION OF cvm_fi_diario
    FOR VALUES FROM ('2020-01-01') TO ('2021-01-01');
CREATE TABLE IF NOT EXISTS cvm_fi_diario_2021 PARTITION OF cvm_fi_diario
    FOR VALUES FROM ('2021-01-01') TO ('2022-01-01');
CREATE TABLE IF NOT EXISTS cvm_fi_diario_2022 PARTITION OF cvm_fi_diario
    FOR VALUES FROM ('2022-01-01') TO ('2023-01-01');
CREATE TABLE IF NOT EXISTS cvm_fi_diario_2023 PARTITION OF cvm_fi_diario
    FOR VALUES FROM ('2023-01-01') TO ('2024-01-01');
CREATE TABLE IF NOT EXISTS cvm_fi_diario_2024 PARTITION OF cvm_fi_diario
    FOR VALUES FROM ('2024-01-01') TO ('2025-01-01');
CREATE TABLE IF NOT EXISTS cvm_fi_diario_2025 PARTITION OF cvm_fi_diario
    FOR VALUES FROM ('2025-01-01') TO ('2026-01-01');
CREATE TABLE IF NOT EXISTS cvm_fi_diario_2026 PARTITION OF cvm_fi_diario
    FOR VALUES FROM ('2026-01-01') TO ('2027-01-01');
CREATE TABLE IF NOT EXISTS cvm_fi_diario_future PARTITION OF cvm_fi_diario
    FOR VALUES FROM ('2027-01-01') TO (MAXVALUE);

-- BRIN index: efficient for monotonically inserted date data
CREATE INDEX IF NOT EXISTS idx_fi_diario_dt    ON cvm_fi_diario USING BRIN (dt_comptc);
CREATE INDEX IF NOT EXISTS idx_fi_diario_cnpj  ON cvm_fi_diario (cnpj);

-- ---------------------------------------------------------------------------
-- FI — portfolio composition  (CDA, monthly ZIP with multiple CSVs)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cvm_fi_cda (
    id            BIGSERIAL    PRIMARY KEY,
    cnpj          TEXT         NOT NULL CHECK (char_length(cnpj) = 14),
    period        DATE         NOT NULL,   -- first day of month  e.g. 2024-03-01
    tp_aplic      TEXT,                    -- asset application type
    tp_ativo      TEXT,                    -- asset type
    vl_merc_pos_final NUMERIC(20,6),
    raw           JSONB        NOT NULL,
    fetched_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fi_cda UNIQUE (cnpj, period, tp_aplic, tp_ativo)
);
CREATE INDEX IF NOT EXISTS idx_fi_cda_cnpj   ON cvm_fi_cda (cnpj);
CREATE INDEX IF NOT EXISTS idx_fi_cda_period ON cvm_fi_cda (period DESC);

-- ---------------------------------------------------------------------------
-- FI — monthly investor profile  (PERFIL_MENSAL)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cvm_fi_perfil (
    id            BIGSERIAL    PRIMARY KEY,
    cnpj          TEXT         NOT NULL CHECK (char_length(cnpj) = 14),
    period        DATE         NOT NULL,
    raw           JSONB        NOT NULL,
    fetched_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fi_perfil UNIQUE (cnpj, period)
);
CREATE INDEX IF NOT EXISTS idx_fi_perfil_cnpj   ON cvm_fi_perfil (cnpj);
CREATE INDEX IF NOT EXISTS idx_fi_perfil_period ON cvm_fi_perfil (period DESC);

-- ---------------------------------------------------------------------------
-- FIDC — monthly snapshot  (INF_MENSAL, monthly ZIP)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cvm_fidc_mensal (
    id            BIGSERIAL    PRIMARY KEY,
    cnpj          TEXT         NOT NULL CHECK (char_length(cnpj) = 14),
    period        DATE         NOT NULL,
    vl_total      NUMERIC(20,6),
    vl_quota      NUMERIC(20,12),
    vl_patrim_liq NUMERIC(20,6),
    vl_inadimpl   NUMERIC(20,6),
    nr_cotst      INT,
    raw           JSONB        NOT NULL,
    fetched_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fidc_mensal UNIQUE (cnpj, period)
);
CREATE INDEX IF NOT EXISTS idx_fidc_mensal_cnpj   ON cvm_fidc_mensal (cnpj);
CREATE INDEX IF NOT EXISTS idx_fidc_mensal_period ON cvm_fidc_mensal (period DESC);
CREATE INDEX IF NOT EXISTS idx_fidc_mensal_delinq
    ON cvm_fidc_mensal (period DESC) WHERE vl_inadimpl IS NOT NULL;

-- ---------------------------------------------------------------------------
-- FIDC — tranche-level quota, return, and performance  (tabs X_2 + X_3 + X_6)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cvm_fidc_tranche (
    id                 BIGSERIAL    PRIMARY KEY,
    cnpj               TEXT         NOT NULL,
    period             DATE         NOT NULL,
    classe_serie       TEXT         NOT NULL,
    qt_cota            NUMERIC(20,8),
    vl_cota            NUMERIC(20,8),
    vl_rentab_mes      NUMERIC(10,6),
    pr_desemp_esperado NUMERIC(10,6),
    pr_desemp_real     NUMERIC(10,6),
    raw                JSONB,
    fetched_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fidc_tranche UNIQUE (cnpj, period, classe_serie)
);
CREATE INDEX IF NOT EXISTS idx_fidc_tranche_cnpj   ON cvm_fidc_tranche (cnpj);
CREATE INDEX IF NOT EXISTS idx_fidc_tranche_period ON cvm_fidc_tranche (period DESC);

-- ---------------------------------------------------------------------------
-- FIDC — tranche-level flows  (tab_X_4: captações / resgates per series)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cvm_fidc_tranche_flows (
    id           BIGSERIAL    PRIMARY KEY,
    cnpj         TEXT         NOT NULL,
    period       DATE         NOT NULL,
    classe_serie TEXT         NOT NULL,
    tp_oper      TEXT         NOT NULL,
    vl_total     NUMERIC(20,6),
    qt_cota      NUMERIC(20,8),
    fetched_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fidc_tranche_flows UNIQUE (cnpj, period, classe_serie, tp_oper)
);
CREATE INDEX IF NOT EXISTS idx_fidc_tranche_flows_cnpj   ON cvm_fidc_tranche_flows (cnpj);
CREATE INDEX IF NOT EXISTS idx_fidc_tranche_flows_period ON cvm_fidc_tranche_flows (period DESC);

-- ---------------------------------------------------------------------------
-- FIDC — delinquency aging buckets  (tab_VI: credits without risk)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cvm_fidc_aging (
    id                   BIGSERIAL    PRIMARY KEY,
    cnpj                 TEXT         NOT NULL,
    period               DATE         NOT NULL,
    vl_prazo_30          NUMERIC(20,6),
    vl_prazo_60          NUMERIC(20,6),
    vl_prazo_90          NUMERIC(20,6),
    vl_prazo_120         NUMERIC(20,6),
    vl_prazo_150         NUMERIC(20,6),
    vl_prazo_180         NUMERIC(20,6),
    vl_prazo_360         NUMERIC(20,6),
    vl_prazo_720         NUMERIC(20,6),
    vl_prazo_1080        NUMERIC(20,6),
    vl_prazo_maior_1080  NUMERIC(20,6),
    vl_inad_30           NUMERIC(20,6),
    vl_inad_60           NUMERIC(20,6),
    vl_inad_90           NUMERIC(20,6),
    vl_inad_120          NUMERIC(20,6),
    vl_inad_150          NUMERIC(20,6),
    vl_inad_180          NUMERIC(20,6),
    vl_inad_360          NUMERIC(20,6),
    vl_inad_720          NUMERIC(20,6),
    vl_inad_1080         NUMERIC(20,6),
    vl_inad_maior_1080   NUMERIC(20,6),
    vl_total_inad        NUMERIC(20,6),
    raw                  JSONB,
    fetched_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fidc_aging UNIQUE (cnpj, period)
);
CREATE INDEX IF NOT EXISTS idx_fidc_aging_cnpj   ON cvm_fidc_aging (cnpj);
CREATE INDEX IF NOT EXISTS idx_fidc_aging_period ON cvm_fidc_aging (period DESC);

-- ---------------------------------------------------------------------------
-- FIAGRO — monthly snapshot  (INF_MENSAL, monthly ZIP, from 2025-05)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cvm_fiagro_mensal (
    id            BIGSERIAL    PRIMARY KEY,
    cnpj          TEXT         NOT NULL CHECK (char_length(cnpj) = 14),
    period        DATE         NOT NULL,
    vl_total      NUMERIC(20,6),
    vl_quota      NUMERIC(20,12),
    vl_patrim_liq NUMERIC(20,6),
    vl_inadimpl   NUMERIC(20,6),
    nr_cotst      INT,
    raw           JSONB        NOT NULL,
    fetched_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fiagro_mensal UNIQUE (cnpj, period)
);
CREATE INDEX IF NOT EXISTS idx_fiagro_mensal_cnpj   ON cvm_fiagro_mensal (cnpj);
CREATE INDEX IF NOT EXISTS idx_fiagro_mensal_period ON cvm_fiagro_mensal (period DESC);

-- ---------------------------------------------------------------------------
-- FIP — periodic reports  (inf_trimestral 2010-2023, inf_quadrimestral 2024+)
-- Generic structure: key CNPJ/period, full data in JSONB
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cvm_fip_periodic (
    id            BIGSERIAL    PRIMARY KEY,
    cnpj          TEXT,
    doc_type      TEXT         NOT NULL,   -- inf_trimestral | inf_quadrimestral
    period_year   INT          NOT NULL,
    vl_patrim_liq NUMERIC(20,6),
    raw           JSONB        NOT NULL,
    fetched_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fip_periodic UNIQUE NULLS NOT DISTINCT (cnpj, doc_type, period_year)
);
CREATE INDEX IF NOT EXISTS idx_fip_periodic_cnpj      ON cvm_fip_periodic (cnpj) WHERE cnpj IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_fip_periodic_type_year ON cvm_fip_periodic (doc_type, period_year DESC);

-- ---------------------------------------------------------------------------
-- FII — monthly general summary  (mensal_geral, yearly ZIP)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cvm_fii_mensal (
    id            BIGSERIAL    PRIMARY KEY,
    cnpj          TEXT         NOT NULL,
    period        DATE         NOT NULL,   -- Data_Referencia parsed to first-of-month
    doc_subtype   TEXT         NOT NULL DEFAULT 'geral',  -- geral | ativo_passivo
    vl_patrim_liq NUMERIC(20,6),
    raw           JSONB        NOT NULL,
    fetched_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fii_mensal UNIQUE (cnpj, period, doc_subtype)
);
CREATE INDEX IF NOT EXISTS idx_fii_mensal_cnpj   ON cvm_fii_mensal (cnpj);
CREATE INDEX IF NOT EXISTS idx_fii_mensal_period ON cvm_fii_mensal (period DESC);

ALTER TABLE cvm_fii_mensal
    ADD COLUMN IF NOT EXISTS nr_cotst               INT,
    ADD COLUMN IF NOT EXISTS vl_ativo               NUMERIC(20,6),
    ADD COLUMN IF NOT EXISTS cotas_emitidas         NUMERIC(20,6),
    ADD COLUMN IF NOT EXISTS vl_patrimonial_cotas   NUMERIC(20,6),
    ADD COLUMN IF NOT EXISTS pct_rentab_efetiva_mes NUMERIC(10,6),
    ADD COLUMN IF NOT EXISTS pct_rentab_patrimonial NUMERIC(10,6),
    ADD COLUMN IF NOT EXISTS pct_dividend_yield_mes NUMERIC(10,6),
    ADD COLUMN IF NOT EXISTS pct_amortizacao_mes    NUMERIC(10,6),
    ADD COLUMN IF NOT EXISTS rendimentos_distribuir NUMERIC(20,6);

-- ---------------------------------------------------------------------------
-- FII — periodic reports  (trimestral, anual, dfin — yearly files)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cvm_fii_periodic (
    id            BIGSERIAL    PRIMARY KEY,
    cnpj          TEXT,
    doc_type      TEXT         NOT NULL,   -- trimestral | anual | dfin
    period_year   INT          NOT NULL,
    raw           JSONB        NOT NULL,
    fetched_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fii_periodic UNIQUE NULLS NOT DISTINCT (cnpj, doc_type, period_year)
);
CREATE INDEX IF NOT EXISTS idx_fii_periodic_cnpj      ON cvm_fii_periodic (cnpj) WHERE cnpj IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_fii_periodic_type_year ON cvm_fii_periodic (doc_type, period_year DESC);

-- ---------------------------------------------------------------------------
-- SECURIT — monthly emissions  (cra_mensal, cri_mensal, ots_mensal — yearly ZIP)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cvm_securit_mensal (
    id              BIGSERIAL    PRIMARY KEY,
    instrument_type TEXT         NOT NULL,   -- cra_mensal | cri_mensal | ots_mensal
    period_year     INT          NOT NULL,
    cnpj_securit    TEXT,
    dt_emissao      DATE,
    dt_vencto       DATE,
    vl_emissao      NUMERIC(20,6),
    vl_unit         NUMERIC(20,6),
    qt_titulos      NUMERIC(20,0),
    vl_total        NUMERIC(20,6),
    tp_ativo        TEXT,
    raw             JSONB        NOT NULL,
    fetched_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_securit_mensal UNIQUE NULLS NOT DISTINCT
        (instrument_type, period_year, cnpj_securit, dt_emissao, dt_vencto, vl_emissao)
);
CREATE INDEX IF NOT EXISTS idx_securit_mensal_cnpj      ON cvm_securit_mensal (cnpj_securit) WHERE cnpj_securit IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_securit_mensal_type_year ON cvm_securit_mensal (instrument_type, period_year DESC);
CREATE INDEX IF NOT EXISTS idx_securit_mensal_tp_ativo  ON cvm_securit_mensal (tp_ativo) WHERE tp_ativo IS NOT NULL;

-- ---------------------------------------------------------------------------
-- SECURIT — per-series status, rating, and yield  (classe CSV)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cvm_securit_serie (
    id                        BIGSERIAL    PRIMARY KEY,
    instrument_type           TEXT         NOT NULL,
    cnpj_securit              TEXT,
    codigo_identificacao      TEXT         NOT NULL,
    data_referencia           DATE         NOT NULL,
    classe                    TEXT,
    numero_serie              INT,
    tipo_oferta               TEXT,
    codigo_cetip              TEXT,
    codigo_isin               TEXT,
    data_vencimento           DATE,
    situacao                  TEXT,
    valor_total_integralizado NUMERIC(20,6),
    taxa_juros                TEXT,
    pagamento_periodicidade   TEXT,
    quantidade_certificados   NUMERIC(20,0),
    valor_certificados        NUMERIC(20,6),
    rendimentos               NUMERIC(20,6),
    amortizacoes              NUMERIC(20,6),
    rentabilidade             NUMERIC(20,8),
    classificacao_risco_atual TEXT,
    indice_subordinacao_minimo NUMERIC(10,6),
    raw                       JSONB,
    fetched_at                TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_securit_serie UNIQUE NULLS NOT DISTINCT
        (instrument_type, cnpj_securit, codigo_identificacao, data_referencia, numero_serie)
);
CREATE INDEX IF NOT EXISTS idx_securit_serie_cnpj     ON cvm_securit_serie (cnpj_securit);
CREATE INDEX IF NOT EXISTS idx_securit_serie_isin     ON cvm_securit_serie (codigo_isin);
CREATE INDEX IF NOT EXISTS idx_securit_serie_situacao ON cvm_securit_serie (situacao, data_referencia DESC);

-- ---------------------------------------------------------------------------
-- SECURIT — monthly cash flows by tranche  (fluxo_caixa CSV)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cvm_securit_fluxo (
    id                                BIGSERIAL    PRIMARY KEY,
    instrument_type                   TEXT         NOT NULL,
    cnpj_securit                      TEXT,
    codigo_identificacao              TEXT         NOT NULL,
    data_referencia                   DATE         NOT NULL,
    recebimentos_direitos_creditorios NUMERIC(20,6),
    pagamentos_despesas               NUMERIC(20,6),
    pagamentos_classe_senior          NUMERIC(20,6),
    pagamentos_senior_principal       NUMERIC(20,6),
    pagamentos_senior_juros           NUMERIC(20,6),
    pagamentos_mezanino               NUMERIC(20,6),
    pagamentos_mezanino_principal     NUMERIC(20,6),
    pagamentos_mezanino_juros         NUMERIC(20,6),
    pagamentos_junior                 NUMERIC(20,6),
    pagamentos_junior_principal       NUMERIC(20,6),
    pagamentos_junior_juros           NUMERIC(20,6),
    variacao_liquida_caixa            NUMERIC(20,6),
    raw                               JSONB,
    fetched_at                        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_securit_fluxo UNIQUE NULLS NOT DISTINCT
        (instrument_type, cnpj_securit, codigo_identificacao, data_referencia)
);
CREATE INDEX IF NOT EXISTS idx_securit_fluxo_cnpj ON cvm_securit_fluxo (cnpj_securit);
CREATE INDEX IF NOT EXISTS idx_securit_fluxo_date ON cvm_securit_fluxo (data_referencia DESC);

-- ---------------------------------------------------------------------------
-- SECURIT — financial statements  (dfin_cra, dfin_cri — yearly CSV)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cvm_securit_dfin (
    id              BIGSERIAL    PRIMARY KEY,
    instrument_type TEXT         NOT NULL,   -- dfin_cra | dfin_cri
    period_year     INT          NOT NULL,
    cnpj_securit    TEXT,
    raw             JSONB        NOT NULL,
    fetched_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_securit_dfin UNIQUE NULLS NOT DISTINCT (instrument_type, period_year, cnpj_securit)
);
CREATE INDEX IF NOT EXISTS idx_securit_dfin_cnpj      ON cvm_securit_dfin (cnpj_securit) WHERE cnpj_securit IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_securit_dfin_type_year ON cvm_securit_dfin (instrument_type, period_year DESC);

-- ---------------------------------------------------------------------------
-- BACEN: SGS time series  (SELIC, IPCA, CDI, IGP-M, USD/BRL, …)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bacen_sgs (
    id             BIGSERIAL    PRIMARY KEY,
    series_code    INT          NOT NULL,
    series_name    TEXT         NOT NULL,
    reference_date DATE         NOT NULL,
    value          NUMERIC,
    fetched_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_bacen_sgs UNIQUE (series_code, reference_date)
);
CREATE INDEX IF NOT EXISTS idx_sgs_code_date ON bacen_sgs (series_code, reference_date DESC);
CREATE INDEX IF NOT EXISTS idx_sgs_name_date ON bacen_sgs (series_name, reference_date DESC);

-- ---------------------------------------------------------------------------
-- BACEN: PTAX exchange rates
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bacen_ptax (
    id             BIGSERIAL    PRIMARY KEY,
    currency       TEXT         NOT NULL,
    reference_date DATE         NOT NULL,
    buy_rate       NUMERIC,
    sell_rate      NUMERIC,
    fetched_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_bacen_ptax UNIQUE (currency, reference_date)
);
CREATE INDEX IF NOT EXISTS idx_ptax_currency_date ON bacen_ptax (currency, reference_date DESC);

-- ---------------------------------------------------------------------------
-- BACEN: Focus / market expectations
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bacen_expectativas (
    id             BIGSERIAL    PRIMARY KEY,
    endpoint_name  TEXT         NOT NULL,
    indicador      TEXT,
    reference_date DATE,
    median         NUMERIC,
    mean_val       NUMERIC,
    std_dev        NUMERIC,
    raw            JSONB        NOT NULL,
    fetched_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_bacen_expectativas UNIQUE NULLS NOT DISTINCT (endpoint_name, indicador, reference_date)
);
CREATE INDEX IF NOT EXISTS idx_expectativas_endpoint_indicador
    ON bacen_expectativas (endpoint_name, indicador, reference_date DESC);
