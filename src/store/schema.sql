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
    -- CVM-175 subclasse under one CNPJ_FUNDO_CLASSE, e.g. distinct pools of
    -- money sharing a CNPJ. '' (not NULL) for funds with no subclasse, so the
    -- UNIQUE constraint below actually catches duplicates for them — see
    -- migrations/17_fi_diario_subclasse_key.sql.
    id_subclasse  TEXT         NOT NULL DEFAULT '',
    dt_comptc     DATE         NOT NULL,
    vl_total      NUMERIC(20,6),
    vl_quota      NUMERIC(20,12),
    vl_patrim_liq NUMERIC(20,6),
    captc_dia     NUMERIC(20,6),
    resg_dia      NUMERIC(20,6),
    nr_cotst      INT,
    raw           JSONB        NOT NULL,
    fetched_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fi_diario UNIQUE (cnpj, dt_comptc, id_subclasse)
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
    qt_cota            NUMERIC(28,8),  -- raw CVM TAB_X_QT_COTA reaches 6.9e13
    vl_cota            NUMERIC(28,8),  -- kept parallel to qt_cota
    vl_rentab_mes      NUMERIC(20,6),  -- raw CVM has dirty values up to 1.6e8 (validate downstream)
    pr_desemp_esperado NUMERIC(20,6),  -- same: raw CVM percentage fields contain garbage outliers
    pr_desemp_real     NUMERIC(20,6),  -- same
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
    qt_cota      NUMERIC(28,8),  -- same overflow as cvm_fidc_tranche.qt_cota
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
    vl_quota      NUMERIC(28,6),   -- Valor_Patrimonial_Cotas can be a total AUM, not a unit price
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
    ADD COLUMN IF NOT EXISTS cotas_emitidas         NUMERIC(28,6),  -- raw FII cotas reach 6.46e14
    ADD COLUMN IF NOT EXISTS vl_patrimonial_cotas   NUMERIC(20,6),
    ADD COLUMN IF NOT EXISTS pct_rentab_efetiva_mes NUMERIC(20,6),  -- widened: raw CVM pct outliers
    ADD COLUMN IF NOT EXISTS pct_rentab_patrimonial NUMERIC(20,6),  -- same
    ADD COLUMN IF NOT EXISTS pct_dividend_yield_mes NUMERIC(20,6),  -- same
    ADD COLUMN IF NOT EXISTS pct_amortizacao_mes    NUMERIC(20,6),  -- same
    ADD COLUMN IF NOT EXISTS rendimentos_distribuir NUMERIC(20,6);

-- ---------------------------------------------------------------------------
-- FII — periodic reports  (yearly files)
--   doc_type: trimestral_geral | trimestral_complemento | anual | dfin
--   ('trimestral' is retired — see migration 15: it ingested the wrong ZIP member)
--   The uniqueness key is widened to include data_referencia by migration 15
--   (mirrored in the ALTER block at the end of this file) because trimestral_*
--   is quarterly and dfin ships several filings per fund per year.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cvm_fii_periodic (
    id            BIGSERIAL    PRIMARY KEY,
    cnpj          TEXT,
    doc_type      TEXT         NOT NULL,
    period_year   INT          NOT NULL,
    raw           JSONB        NOT NULL,
    fetched_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fii_periodic UNIQUE NULLS NOT DISTINCT (cnpj, doc_type, period_year)
);
CREATE INDEX IF NOT EXISTS idx_fii_periodic_cnpj      ON cvm_fii_periodic (cnpj) WHERE cnpj IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_fii_periodic_type_year ON cvm_fii_periodic (doc_type, period_year DESC);

-- ---------------------------------------------------------------------------
-- FII — property register  (INF_TRIMESTRAL _imovel_ member — migration 15)
--
-- A separate table because the grain differs from cvm_fii_periodic: many
-- properties per fund per quarter (20,227 rows in the 2025 archive alone).
-- row_hash is a sha256 over the source row — CVM publishes no property id and
-- the file legitimately repeats identical descriptive rows, so every descriptive
-- key collides and would drop real rows on upsert. See
-- src/parsers/field_maps/fii_imovel.py for the measured collision counts.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cvm_fii_imovel (
    id                  BIGSERIAL    PRIMARY KEY,
    cnpj                TEXT         NOT NULL CHECK (char_length(cnpj) = 14),
    data_referencia     DATE         NOT NULL,
    row_hash            TEXT         NOT NULL,
    versao              INT,
    classe              TEXT,
    nome_imovel         TEXT,
    endereco            TEXT,
    area                NUMERIC(20,6),
    numero_unidades     INT,
    outras_caracteristicas TEXT,
    pr_vacancia         NUMERIC(20,8),
    pr_inadimplencia    NUMERIC(20,8),
    pr_receitas_fii     NUMERIC(20,8),
    pr_locado           NUMERIC(20,8),
    pr_vendido          NUMERIC(20,8),
    pr_conclusao_obras_realizado NUMERIC(20,8),
    pr_conclusao_obras_previsto  NUMERIC(20,8),
    custo_construcao_realizado   NUMERIC(20,6),
    custo_construcao_previsto    NUMERIC(20,6),
    pr_imovel_total_investido    NUMERIC(20,8),
    period_year         INT          NOT NULL,
    raw                 JSONB        NOT NULL,
    fetched_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fii_imovel UNIQUE (cnpj, data_referencia, row_hash)
);
CREATE INDEX IF NOT EXISTS idx_fii_imovel_cnpj   ON cvm_fii_imovel (cnpj);
CREATE INDEX IF NOT EXISTS idx_fii_imovel_period ON cvm_fii_imovel (data_referencia DESC);
CREATE INDEX IF NOT EXISTS idx_fii_imovel_classe ON cvm_fii_imovel (classe) WHERE classe IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_fii_imovel_vacancia
    ON cvm_fii_imovel (data_referencia DESC) WHERE pr_vacancia IS NOT NULL;

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
-- Fund registry — DENOM_SOCIAL, SIT/DT_REG from CVM cadastral CSVs
-- Sourced from cad_fi.csv (FI), cad_fii.csv (FII), seeded from FIDC raw data.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cvm_fund_registry (
    id           BIGSERIAL    PRIMARY KEY,
    cnpj         TEXT         NOT NULL CHECK (char_length(cnpj) = 14),
    entity_type  TEXT         NOT NULL,   -- fi | fii | fidc | fip | fiagro | securit
    fund_name    TEXT,
    status       TEXT,
    tp_fundo     TEXT,
    dt_reg       DATE,
    dt_cancel    DATE,
    admin_cnpj   TEXT,                       -- administrator CNPJ (14 digits)
    admin_name   TEXT,                       -- administrator legal name
    gestor_id    TEXT,                       -- gestor CPF (PF) or CNPJ (PJ)
    gestor_name  TEXT,                       -- gestor (portfolio manager) name
    raw          JSONB,
    fetched_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fund_registry UNIQUE (cnpj, entity_type)
);
CREATE INDEX IF NOT EXISTS idx_fund_registry_cnpj   ON cvm_fund_registry (cnpj);
CREATE INDEX IF NOT EXISTS idx_fund_registry_entity ON cvm_fund_registry (entity_type, status);
CREATE INDEX IF NOT EXISTS idx_fund_registry_admin  ON cvm_fund_registry (admin_name);
CREATE INDEX IF NOT EXISTS idx_fund_registry_gestor ON cvm_fund_registry (gestor_name);

-- ---------------------------------------------------------------------------
-- FI — monthly balance sheet  (BALANCETE, monthly ZIP)
--
-- CSV columns (actual 2025-01 sample):
--   TP_FUNDO_CLASSE ; CNPJ_FUNDO_CLASSE ; DT_COMPTC
--   PLANO_CONTA_BALCTE ; CD_CONTA_BALCTE ; VL_SALDO_BALCTE
--
-- Natural key: (cnpj, dt_comptc, cd_conta_balcte)
-- One row per fund × reference date × account code.
-- ---------------------------------------------------------------------------
-- `id` is a plain BIGSERIAL, deliberately NOT a PRIMARY KEY: migration 22
-- dropped that constraint after pg_stat_user_indexes showed its 2.5 GB index
-- had served 0 queries across 112M inserts (statistics never reset). The
-- natural key lives in uq_fi_balancete, which is what ON CONFLICT uses; `id`
-- is a surrogate nothing in this repo reads. Keep it unconstrained on a fresh
-- database so schema.sql and a migrated one agree.
CREATE TABLE IF NOT EXISTS cvm_fi_balancete (
    id                 BIGSERIAL,
    cnpj               TEXT         NOT NULL CHECK (char_length(cnpj) = 14),
    dt_comptc          DATE         NOT NULL,
    plano_conta_balcte TEXT,                    -- chart-of-accounts plan code (e.g. COFI)
    cd_conta_balcte    TEXT         NOT NULL,   -- account code
    vl_saldo_balcte    NUMERIC(28,2),           -- account balance (monetary total)
    tp_fundo_classe    TEXT,                    -- fund class type flag
    raw                JSONB        NOT NULL,
    fetched_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fi_balancete UNIQUE (cnpj, dt_comptc, cd_conta_balcte)
);
-- Only the date index. idx_fi_balancete_cnpj (redundant — uq_fi_balancete
-- already leads with cnpj) and idx_fi_balancete_conta were dropped in
-- migration 22; both had 0 scans over the life of the database. Do not
-- re-add them without evidence from pg_stat_user_indexes that a real query
-- needs them: every index here is paid for on all ~2M rows of every monthly
-- slice.
CREATE INDEX IF NOT EXISTS idx_fi_balancete_date   ON cvm_fi_balancete (dt_comptc DESC);

-- ---------------------------------------------------------------------------
-- Additive column migrations for typed-field lifts (idempotent).
-- ---------------------------------------------------------------------------

-- cvm_fidc_mensal: add tp_fundo (source: TP_FUNDO_CLASSE / TP_FUNDO)
ALTER TABLE cvm_fidc_mensal
    ADD COLUMN IF NOT EXISTS tp_fundo TEXT;

-- cvm_fiagro_mensal: add tp_fundo (source: Tipo_Fundo_Classe / TP_FUNDO_CLASSE)
ALTER TABLE cvm_fiagro_mensal
    ADD COLUMN IF NOT EXISTS tp_fundo TEXT;

-- cvm_fii_mensal: add tp_fundo (source: Tipo_Fundo_Classe)
ALTER TABLE cvm_fii_mensal
    ADD COLUMN IF NOT EXISTS tp_fundo TEXT;

-- cvm_fi_perfil: lift high-signal fields from raw JSONB
ALTER TABLE cvm_fi_perfil
    ADD COLUMN IF NOT EXISTS mod_var                          TEXT,
    ADD COLUMN IF NOT EXISTS vedac_taxa_perfm                 TEXT,
    ADD COLUMN IF NOT EXISTS pr_var_carteira                  NUMERIC(20,6),
    ADD COLUMN IF NOT EXISTS prazo_carteira_titulo            NUMERIC(20,6),
    ADD COLUMN IF NOT EXISTS pr_variacao_diaria_cota          NUMERIC(20,6),
    ADD COLUMN IF NOT EXISTS pr_variacao_diaria_cota_estresse NUMERIC(20,6),
    ADD COLUMN IF NOT EXISTS pr_ativo_cred_priv               NUMERIC(20,6),
    ADD COLUMN IF NOT EXISTS pr_ativo_emissor_ligado          NUMERIC(20,6),
    ADD COLUMN IF NOT EXISTS pr_patrim_liq_maior_cotst        NUMERIC(20,6),
    ADD COLUMN IF NOT EXISTS nr_cotst_pf_pb                   INT,
    ADD COLUMN IF NOT EXISTS nr_cotst_pj_financ               INT,
    ADD COLUMN IF NOT EXISTS nr_cotst_pj_nao_financ_pb        INT,
    ADD COLUMN IF NOT EXISTS nr_cotst_pj_nao_financ_varejo    INT,
    ADD COLUMN IF NOT EXISTS nr_cotst_banco                   INT,
    ADD COLUMN IF NOT EXISTS nr_cotst_fi_clube                INT,
    ADD COLUMN IF NOT EXISTS nr_cotst_distrib                 INT;

-- cvm_fi_perfil (migration 14): the rest of the PERFIL_MENSAL matrix.
-- The block above stopped at 7 of the 16 NR_COTST_* buckets and omitted
-- NR_COTST_PF_VAREJO (retail individuals) entirely, plus every PR_PL_COTST_*
-- share-of-PL field, the comitente concentration block and the liquidity block.
-- All of them are present in every vintage of the source CSV (verified against
-- perfil_mensal_fi_202012 and _202512, 106/107 fields) and were sitting unused
-- in `raw`.
ALTER TABLE cvm_fi_perfil
    ADD COLUMN IF NOT EXISTS nr_cotst_pf_varejo            INT,
    ADD COLUMN IF NOT EXISTS nr_cotst_corretora_distrib    INT,
    ADD COLUMN IF NOT EXISTS nr_cotst_invnr                INT,
    ADD COLUMN IF NOT EXISTS nr_cotst_eapc                 INT,
    ADD COLUMN IF NOT EXISTS nr_cotst_efpc                 INT,
    ADD COLUMN IF NOT EXISTS nr_cotst_rpps                 INT,
    ADD COLUMN IF NOT EXISTS nr_cotst_segur                INT,
    ADD COLUMN IF NOT EXISTS nr_cotst_capitaliz            INT,
    ADD COLUMN IF NOT EXISTS nr_cotst_outro                INT;

ALTER TABLE cvm_fi_perfil
    ADD COLUMN IF NOT EXISTS pr_pl_cotst_pf_pb                 NUMERIC(20,8),
    ADD COLUMN IF NOT EXISTS pr_pl_cotst_pf_varejo             NUMERIC(20,8),
    ADD COLUMN IF NOT EXISTS pr_pl_cotst_pj_nao_financ_pb      NUMERIC(20,8),
    ADD COLUMN IF NOT EXISTS pr_pl_cotst_pj_nao_financ_varejo  NUMERIC(20,8),
    ADD COLUMN IF NOT EXISTS pr_pl_cotst_banco                 NUMERIC(20,8),
    ADD COLUMN IF NOT EXISTS pr_pl_cotst_corretora_distrib     NUMERIC(20,8),
    ADD COLUMN IF NOT EXISTS pr_pl_cotst_pj_financ             NUMERIC(20,8),
    ADD COLUMN IF NOT EXISTS pr_pl_cotst_invnr                 NUMERIC(20,8),
    ADD COLUMN IF NOT EXISTS pr_pl_cotst_eapc                  NUMERIC(20,8),
    ADD COLUMN IF NOT EXISTS pr_pl_cotst_efpc                  NUMERIC(20,8),
    ADD COLUMN IF NOT EXISTS pr_pl_cotst_rpps                  NUMERIC(20,8),
    ADD COLUMN IF NOT EXISTS pr_pl_cotst_segur                 NUMERIC(20,8),
    ADD COLUMN IF NOT EXISTS pr_pl_cotst_capitaliz             NUMERIC(20,8),
    ADD COLUMN IF NOT EXISTS pr_pl_cotst_fi_clube              NUMERIC(20,8),
    ADD COLUMN IF NOT EXISTS pr_pl_cotst_distrib               NUMERIC(20,8),
    ADD COLUMN IF NOT EXISTS pr_pl_cotst_outro                 NUMERIC(20,8);

ALTER TABLE cvm_fi_perfil
    ADD COLUMN IF NOT EXISTS pr_comitente_1      NUMERIC(20,8),
    ADD COLUMN IF NOT EXISTS pr_comitente_2      NUMERIC(20,8),
    ADD COLUMN IF NOT EXISTS pr_comitente_3      NUMERIC(20,8),
    ADD COLUMN IF NOT EXISTS comitente_ligado_1  BOOLEAN,
    ADD COLUMN IF NOT EXISTS comitente_ligado_2  BOOLEAN,
    ADD COLUMN IF NOT EXISTS comitente_ligado_3  BOOLEAN;

ALTER TABLE cvm_fi_perfil
    ADD COLUMN IF NOT EXISTS nr_dia_cinqu_perc            NUMERIC(20,6),
    ADD COLUMN IF NOT EXISTS nr_dia_cem_perc              NUMERIC(20,6),
    ADD COLUMN IF NOT EXISTS st_liqdez                    TEXT,
    ADD COLUMN IF NOT EXISTS pr_patrim_liq_convtd_caixa   NUMERIC(20,8);

CREATE INDEX IF NOT EXISTS idx_fi_perfil_pf_varejo
    ON cvm_fi_perfil (period DESC) WHERE nr_cotst_pf_varejo IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_fi_perfil_maior_cotst
    ON cvm_fi_perfil (period DESC) WHERE pr_patrim_liq_maior_cotst IS NOT NULL;

-- cvm_securit_fluxo: lift extra cashflow categories
ALTER TABLE cvm_securit_fluxo
    ADD COLUMN IF NOT EXISTS recebimentos_alienacao_caixa NUMERIC(20,6),
    ADD COLUMN IF NOT EXISTS outros_recebimentos          NUMERIC(20,6),
    ADD COLUMN IF NOT EXISTS aquisicao_caixa              NUMERIC(20,6),
    ADD COLUMN IF NOT EXISTS aquisicao_novos_creditos     NUMERIC(20,6),
    ADD COLUMN IF NOT EXISTS outros_pagamentos            NUMERIC(20,6);

-- cvm_securit_serie: lift schedule / indexer / subordination columns
ALTER TABLE cvm_securit_serie
    ADD COLUMN IF NOT EXISTS indice_subordinacao_data_base DATE,
    ADD COLUMN IF NOT EXISTS pagamento_mes_base            TEXT,
    ADD COLUMN IF NOT EXISTS periodicidade_amortizacao     TEXT,
    ADD COLUMN IF NOT EXISTS taxas_indexadores             TEXT,
    ADD COLUMN IF NOT EXISTS nivel_subordinacao            TEXT;

-- cvm_fii_periodic: property-level columns.
-- NOTE (migration 15): these came from the ALIENACAO_IMOVEL member that the old
-- broken `trimestral` config was accidentally ingesting. They are kept so the
-- historic rows stay readable, but nothing writes them any more — the property
-- register now lands in cvm_fii_imovel at its own grain.
ALTER TABLE cvm_fii_periodic
    ADD COLUMN IF NOT EXISTS data_referencia      DATE,
    ADD COLUMN IF NOT EXISTS nome_imovel          TEXT,
    ADD COLUMN IF NOT EXISTS endereco             TEXT,
    ADD COLUMN IF NOT EXISTS area                 NUMERIC(20,6),
    ADD COLUMN IF NOT EXISTS numero_unidades      INT,
    ADD COLUMN IF NOT EXISTS percentual_imovel_pl NUMERIC(20,8);

-- cvm_fii_periodic (migration 15): GERAL + COMPLEMENTO member columns
ALTER TABLE cvm_fii_periodic
    ADD COLUMN IF NOT EXISTS versao              INT,
    ADD COLUMN IF NOT EXISTS data_entrega        DATE,
    ADD COLUMN IF NOT EXISTS nome_fundo          TEXT,
    ADD COLUMN IF NOT EXISTS tp_fundo            TEXT,
    ADD COLUMN IF NOT EXISTS publico_alvo        TEXT,
    ADD COLUMN IF NOT EXISTS codigo_isin         TEXT,
    ADD COLUMN IF NOT EXISTS cotas_emitidas      NUMERIC(28,8),
    ADD COLUMN IF NOT EXISTS fundo_exclusivo     BOOLEAN,
    ADD COLUMN IF NOT EXISTS mandato             TEXT,
    ADD COLUMN IF NOT EXISTS segmento_atuacao    TEXT,
    ADD COLUMN IF NOT EXISTS tipo_gestao         TEXT,
    ADD COLUMN IF NOT EXISTS prazo_duracao       TEXT,
    ADD COLUMN IF NOT EXISTS nome_administrador  TEXT,
    ADD COLUMN IF NOT EXISTS cnpj_administrador  TEXT;

ALTER TABLE cvm_fii_periodic
    ADD COLUMN IF NOT EXISTS pr_indexador_igpm                NUMERIC(20,8),
    ADD COLUMN IF NOT EXISTS pr_indexador_inpc                NUMERIC(20,8),
    ADD COLUMN IF NOT EXISTS pr_indexador_ipca                NUMERIC(20,8),
    ADD COLUMN IF NOT EXISTS pr_indexador_incc                NUMERIC(20,8),
    ADD COLUMN IF NOT EXISTS ativo_liquidez_disponibilidades  NUMERIC(20,6),
    ADD COLUMN IF NOT EXISTS ativo_liquidez_titulos_publicos  NUMERIC(20,6),
    ADD COLUMN IF NOT EXISTS ativo_liquidez_titulos_privados  NUMERIC(20,6),
    ADD COLUMN IF NOT EXISTS ativo_liquidez_fundos_renda_fixa NUMERIC(20,6);

CREATE INDEX IF NOT EXISTS idx_fii_periodic_segmento
    ON cvm_fii_periodic (segmento_atuacao) WHERE segmento_atuacao IS NOT NULL;

-- cvm_fii_periodic (migration 15): the uniqueness key must include
-- data_referencia — trimestral_* is quarterly and dfin files several times a
-- year, so the year-grain key silently overwrote all but the last filing.
-- DROP IF EXISTS + ADD keeps this idempotent across re-applies.
ALTER TABLE cvm_fii_periodic DROP CONSTRAINT IF EXISTS uq_fii_periodic;

ALTER TABLE cvm_fii_periodic
    ADD CONSTRAINT uq_fii_periodic UNIQUE NULLS NOT DISTINCT
        (cnpj, doc_type, period_year, data_referencia);

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
    -- Forecast horizon (DataReferencia): a year for the annual endpoints,
    -- month/year for the monthly ones. Part of the natural key — one survey
    -- date carries one forecast PER horizon, so omitting it collapses ~97% of
    -- the published data to an arbitrary survivor. See migration 16.
    horizon        TEXT,
    raw            JSONB        NOT NULL,
    fetched_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    -- horizon is DataReferencia. baseCalculo and Suavizada are *not* in the
    -- key: the fetcher filters to baseCalculo=0 (and Suavizada='N' on the
    -- Inflacao12/13-24 endpoints). A filter regression would silently collide
    -- again — do not "fix" that by widening the key without also storing the
    -- extra dimension; the intended grain is one 30-day unsmoothed statistic
    -- per (endpoint, indicador, survey date, horizon).
    CONSTRAINT uq_bacen_expectativas UNIQUE NULLS NOT DISTINCT (endpoint_name, indicador, reference_date, horizon)
);
CREATE INDEX IF NOT EXISTS idx_expectativas_endpoint_indicador
    ON bacen_expectativas (endpoint_name, indicador, reference_date DESC);
-- idx_expectativas_horizon is NOT created here on purpose. schema.sql runs
-- before the migrations on every apply, and CREATE TABLE IF NOT EXISTS is a
-- no-op on a database where bacen_expectativas already exists (production
-- did) -- so the horizon column this index needs does not exist yet at this
-- point in the run; only migration 16's ALTER TABLE adds it. A CREATE INDEX
-- here failed with "column horizon does not exist" on exactly that path.
-- Migration 16 creates the index itself (CREATE INDEX IF NOT EXISTS) right
-- after adding the column, which is correct on both a fresh database (the
-- CREATE TABLE above already has horizon, migration 16's ALTER is a no-op,
-- the index gets created once) and an upgrading one (column added, then
-- indexed, in the right order).

-- ---------------------------------------------------------------------------
-- ETF market snapshots scraped from etfsbrasil.com.br (see migration 12_etf_market.sql).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS etf_market_snapshot (
    ticker            TEXT          NOT NULL,
    snapshot_date     DATE          NOT NULL,
    source            TEXT          NOT NULL DEFAULT 'etfsbrasil',
    cnpj              TEXT,
    isin              TEXT,
    fund_name         TEXT,
    categoria         TEXT,
    regiao            TEXT,
    indice            TEXT,
    provedor_indice   TEXT,
    taxa_adm_pct      NUMERIC(10, 4),
    nav               NUMERIC(20, 6),   -- BRL (page shows R$ MM; ×1e6 on ingest)
    cotistas          INTEGER,
    price             NUMERIC(20, 6),
    ret_ytd_pct       NUMERIC(12, 4),
    ret_12m_pct       NUMERIC(12, 4),
    ret_36m_pct       NUMERIC(12, 4),
    vol_12m_pct       NUMERIC(12, 4),
    sharpe_12m        NUMERIC(12, 4),
    max_drawdown_pct  NUMERIC(12, 4),
    launch_date       DATE,
    raw               JSONB,
    scraped_at        TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_etf_market_snapshot UNIQUE (ticker, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_etf_market_snapshot_date   ON etf_market_snapshot (snapshot_date DESC);
CREATE INDEX IF NOT EXISTS idx_etf_market_snapshot_ticker ON etf_market_snapshot (ticker, snapshot_date DESC);

-- ---------------------------------------------------------------------------
-- ANBIMA "Boletim de Fundos de Investimento" — monthly metrics for every ANBIMA
-- class (Renda Fixa, Ações, Multimercados, Cambial, Previdência, ETF, FIDC, FIP,
-- FIAGRO, FII, Off Shore) and ~110 ANBIMA types. See migration
-- 13_anbima_all_classes.sql, which widened this from the ETF-only
-- anbima_etf_class_monthly of migration 09 and keeps that name alive as a view.
--
-- Values are stored exactly as published: monetary metrics in R$ milhões (NOT
-- full BRL), rentabilidade in percentage points (4.37 = 4.37 %).
--
-- The `level` column is part of the key on purpose: in the type sheets the
-- labels "Cambial", "FIP" and "FIAGRO" each appear BOTH as a class aggregate and
-- as an ANBIMA type of the very same name. Keying on the name alone let the type
-- row silently overwrite the class aggregate.
--   'category' → class aggregate row       (anbima_type_id IS NULL)
--   'type'     → ANBIMA type row           (anbima_type_id set when published)
--   'total'    → industry total row, stored with anbima_category = 'TOTAL'
--
-- ORDERING NOTE: the compatibility view anbima_etf_class_monthly is created by
-- migration 13, NOT here. Migration 09 runs between this file and 13 and
-- unconditionally re-creates anbima_etf_class_monthly as a table with indexes;
-- CREATE INDEX against a view is a hard error, so the view must not exist while
-- 09 runs. The guarded drop below clears it on every apply and 13 re-creates it.
-- ---------------------------------------------------------------------------
DO $anbima_compat_view$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'public'
           AND c.relname = 'anbima_etf_class_monthly'
           AND c.relkind = 'v'
    ) THEN
        DROP VIEW public.anbima_etf_class_monthly;
    END IF;
END
$anbima_compat_view$;

CREATE TABLE IF NOT EXISTS anbima_class_monthly (
    reference_date          DATE            NOT NULL,
    anbima_category         TEXT            NOT NULL,
    anbima_type_id          INT,
    anbima_type_name        TEXT            NOT NULL,
    metric                  TEXT            NOT NULL,
    value                   NUMERIC(20, 6),
    level                   TEXT            NOT NULL DEFAULT 'category',
    source_sheet            TEXT,
    boletim_ref             TEXT,
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT anbima_class_monthly_pkey
        PRIMARY KEY (reference_date, anbima_category, anbima_type_name, metric, level)
);

CREATE INDEX IF NOT EXISTS idx_anbima_class_cat_type_metric
    ON anbima_class_monthly (anbima_category, anbima_type_name, metric, reference_date DESC);
CREATE INDEX IF NOT EXISTS idx_anbima_class_metric_date
    ON anbima_class_monthly (metric, reference_date DESC);
CREATE INDEX IF NOT EXISTS idx_anbima_class_boletim_ref
    ON anbima_class_monthly (boletim_ref);

-- ---------------------------------------------------------------------------
-- B3 COTAHIST — daily exchange quotes (see migration 18_b3_cotahist.sql)
--
-- Public yearly/daily zip from B3 (not CVM). One row per
-- (codneg, trade_date, tpmerc, codbdi, prazot) as published. Prices are
-- unadjusted. Join to cia_*/cvm_* is deferred (ISIN + ticker are stored).
-- ---------------------------------------------------------------------------
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
-- UNIQUE (codneg, trade_date, …) already covers all-market ticker+date lookups.
-- Serve path is cash (tpmerc='010'); a partial covering index keeps option rows
-- (the bulk of COTAHIST) out of the quote-card plan.
CREATE INDEX IF NOT EXISTS idx_b3_cotahist_vista
    ON b3_cotahist (codneg, trade_date DESC)
    INCLUDE (
        preco_abertura, preco_maximo, preco_minimo, preco_fechamento,
        volume, negocios, quantidade, isin
    )
    WHERE tpmerc = '010';
CREATE INDEX IF NOT EXISTS idx_b3_cotahist_isin
    ON b3_cotahist (isin) WHERE isin IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_b3_cotahist_tpmerc_dt
    ON b3_cotahist (tpmerc, trade_date DESC);
-- Option serve path (api.option_chain / api.option_history, migration 21):
-- options (tpmerc 070/080) are ~89% of each session, so per-codneg lookups get
-- the same partial-index treatment as vista. Termo ('030') deliberately has no
-- index: ~135 rows/session; idx_b3_cotahist_tpmerc_dt already narrows it.
CREATE INDEX IF NOT EXISTS idx_b3_cotahist_option
    ON b3_cotahist (codneg, trade_date DESC)
    WHERE tpmerc IN ('070', '080');

COMMENT ON TABLE b3_cotahist IS
    'B3 COTAHIST register-01 quotes. Unadjusted. Natural key (codneg, trade_date, tpmerc, codbdi, prazot).';
COMMENT ON COLUMN b3_cotahist.tpmerc IS
    'Market type: 010 vista, 020 fracionario, 070/080 options, 030 termo.';
COMMENT ON COLUMN b3_cotahist.prazot IS
    'Forward-market term in days; empty string for cash market (part of UNIQUE).';

-- Read-side cash tape. Dashboards / Data API should query this, not the parent
-- (parent is ~options-heavy). Filter is the same predicate as idx_b3_cotahist_vista.
CREATE OR REPLACE VIEW vw_b3_quote_vista AS
SELECT
    codneg,
    trade_date,
    codbdi,
    prazot,
    nome_resumido,
    especi,
    moeda,
    preco_abertura,
    preco_maximo,
    preco_minimo,
    preco_medio,
    preco_fechamento,
    oferta_compra,
    oferta_venda,
    negocios,
    quantidade,
    volume,
    isin,
    fator_cotacao,
    source,
    fetched_at
FROM b3_cotahist
WHERE tpmerc = '010';

COMMENT ON VIEW vw_b3_quote_vista IS
    'Cash-market (tpmerc=010) COTAHIST quotes. Unadjusted. Grain is still (codneg, trade_date, codbdi, prazot); board 02 is the standard lot.';

-- DB-side instrument taxonomy (migration 23 keeps this text in sync). Keep the
-- landing fact at B3's register-01 grain: the view derives type, fund-quota
-- subtype, share class and listing segment from published TPMERC/CODBDI/ESPECI
-- while preserving every source field. See migration 23 for the validation
-- evidence (CODBDI split vs cvm_etf_registry; ESPECI class vs ISIN class code).
CREATE OR REPLACE VIEW vw_b3_instrument_typed AS
SELECT
    q.*,
    CASE
        WHEN q.tpmerc = '070' THEN 'option_call'
        WHEN q.tpmerc = '080' THEN 'option_put'
        WHEN q.tpmerc = '012' THEN 'option_exercise_call'
        WHEN q.tpmerc = '013' THEN 'option_exercise_put'
        WHEN q.tpmerc = '017' THEN 'auction'
        WHEN q.tpmerc = '030' THEN 'forward'
        WHEN q.tpmerc IN ('010', '020', '021') THEN
            CASE
                WHEN UPPER(COALESCE(q.especi, '')) LIKE 'DR%'  THEN 'bdr'
                WHEN UPPER(COALESCE(q.especi, '')) LIKE 'UNT%' THEN 'unit'
                WHEN UPPER(COALESCE(q.especi, '')) LIKE 'CI%'
                  OR UPPER(COALESCE(q.especi, '')) LIKE 'FIDC%' THEN 'fund_quota'
                WHEN UPPER(COALESCE(q.especi, '')) LIKE 'ON%'
                  OR UPPER(COALESCE(q.especi, '')) LIKE 'PN%'  THEN 'equity'
                ELSE 'cash_security'
            END
        ELSE 'other'
    END AS instrument_type,
    CASE
        WHEN q.tpmerc IN ('010', '020', '021')
         AND (UPPER(COALESCE(q.especi, '')) LIKE 'CI%'
           OR UPPER(COALESCE(q.especi, '')) LIKE 'FIDC%') THEN
            CASE
                WHEN q.codbdi IN ('05', '12') THEN 'fii'
                WHEN q.codbdi = '13' THEN 'fiagro'
                WHEN q.codbdi = '14' THEN
                    CASE WHEN UPPER(COALESCE(q.especi, '')) LIKE 'FIDC%'
                         THEN 'fidc' ELSE 'etf' END
                ELSE NULL
            END
        ELSE NULL
    END AS instrument_subtype,
    CASE
        WHEN split_part(btrim(COALESCE(q.especi, '')), ' ', 1)
             IN ('ON', 'PN', 'PNA', 'PNB', 'PNC', 'PND', 'UNT')
        THEN split_part(btrim(q.especi), ' ', 1)
        ELSE NULL
    END AS share_class,
    CASE
        WHEN btrim(substr(COALESCE(q.especi, ''), 9, 2))
             IN ('NM', 'N1', 'N2', 'MA', 'M2', 'MB')
        THEN btrim(substr(q.especi, 9, 2))
        ELSE NULL
    END AS governance_segment
FROM b3_cotahist q;

COMMENT ON VIEW vw_b3_instrument_typed IS
    'COTAHIST rows classified from published TPMERC/CODBDI/ESPECI only. tpmerc 012/013 are option exercise EVENTS (not quotes); 017 is an auction print. fund_quota is split into etf/fii/fidc/fiagro via instrument_subtype using CODBDI board codes (validated vs cvm_etf_registry); NULL when the board carries no family signal. Grain and natural key unchanged.';
COMMENT ON COLUMN vw_b3_instrument_typed.instrument_type IS
    'option_call | option_put | option_exercise_call | option_exercise_put | auction | forward | bdr | unit | fund_quota | equity | cash_security | other';
COMMENT ON COLUMN vw_b3_instrument_typed.instrument_subtype IS
    'fund_quota family from CODBDI: etf (14) | fii (05/12) | fiagro (13) | fidc (14 + ESPECI FIDC*). NULL for non-fund rows and for boards with no family signal (odd lot 93/96). Never guessed from ticker shape.';
COMMENT ON COLUMN vw_b3_instrument_typed.share_class IS
    'Share class token from ESPECI: ON | PN | PNA | PNB | PNC | PND | UNT. Cross-checked against the ISIN class code (chars 10-11: OR/PR/PA/PB/PC) with zero disagreements on the 2026-08 cash tape. NULL when ESPECI carries no recognized class.';
COMMENT ON COLUMN vw_b3_instrument_typed.governance_segment IS
    'B3 listing segment from ESPECI cols 9-10: NM (Novo Mercado) | N1 | N2 | MA | M2 | MB. NULL when absent.';

-- ---------------------------------------------------------------------------
-- B3 corporate events (migration 26). Published splits/groupings/bonuses/
-- dividends per ISIN. No adjustment factor is derived here - see the
-- migration header for why the convention must be verified first.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS b3_corporate_event (
    id                BIGSERIAL PRIMARY KEY,
    -- B3's 4-letter issuing company code (PETR, MGLU). Not the ticker: one
    -- issuer carries several tickers, and the events are per ISIN.
    issuing_company   TEXT        NOT NULL,
    -- The join key to b3_cotahist.isin. Published on every event row.
    isin              TEXT        NOT NULL,
    -- stock = changes the share count (adjustment-relevant)
    -- cash  = dividends / JCP (total-return relevant, not price-adjustment)
    -- subscription = rights offering
    event_class       TEXT        NOT NULL
        CHECK (event_class IN ('stock', 'cash', 'subscription')),
    -- B3's own label, upper-cased: DESDOBRAMENTO, GRUPAMENTO, BONIFICACAO,
    -- DIVIDENDO, JRS CAP PROPRIO, SUBSCRICAO. Stored as published — this
    -- table does not translate or bucket it.
    label             TEXT        NOT NULL,
    -- lastDatePrior: the LAST session on which the old entitlement still
    -- applied. The ex-date is the following TRADING session, which is a
    -- calendar question, so the derivation is left to the consumer and B3's
    -- own field is what gets stored.
    last_date_prior   DATE,
    approved_on       DATE,
    -- Published verbatim. See the header: the convention varies by label and
    -- is NOT interpreted here.
    factor            NUMERIC(28, 12),
    -- Cash events only: per-share amount.
    rate              NUMERIC(28, 12),
    payment_date      DATE,
    raw               JSONB       NOT NULL,
    source            TEXT        NOT NULL DEFAULT 'b3_listed_companies',
    fetched_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Idempotency. An event is identified by what B3 publishes about it; NULLS NOT
-- DISTINCT so rows with a missing date or factor still collide instead of
-- duplicating on every re-fetch.
CREATE UNIQUE INDEX IF NOT EXISTS uq_b3_corporate_event
    ON b3_corporate_event (isin, label, last_date_prior, approved_on, factor, rate)
    NULLS NOT DISTINCT;

CREATE INDEX IF NOT EXISTS idx_b3_corporate_event_isin_date
    ON b3_corporate_event (isin, last_date_prior DESC);

CREATE INDEX IF NOT EXISTS idx_b3_corporate_event_class
    ON b3_corporate_event (event_class, label);

COMMENT ON TABLE b3_corporate_event IS
    'Published B3 corporate actions per ISIN (splits, groupings, bonuses, cash dividends, subscriptions). Fields verbatim from B3''s listed-companies proxy. No adjustment factor is derived here: B3''s factor convention varies by label and is not yet verified against the tape, so quotes stay unadjusted and honest rather than rescaled by a guess.';

-- Events joined to the tape, so the factor convention can be CHECKED rather
-- than assumed: for each share-count event, what did the close actually do
-- across it? This view is the evidence for that verification and a research
-- surface in its own right; it applies no adjustment.
CREATE OR REPLACE VIEW vw_b3_share_count_event AS
SELECT
    e.issuing_company,
    e.isin,
    e.label,
    e.last_date_prior,
    e.approved_on,
    e.factor,
    -- The last cash print on or before the entitlement date, and the first one
    -- after it. Their ratio is what any candidate factor convention has to
    -- reproduce.
    (SELECT b.preco_fechamento / NULLIF(b.fator_cotacao, 0)
       FROM public.b3_cotahist b
      WHERE b.isin = e.isin AND b.tpmerc = '010'
        AND b.trade_date <= e.last_date_prior
      ORDER BY b.trade_date DESC, b.codbdi
      LIMIT 1)                                    AS close_unit_before,
    (SELECT b.preco_fechamento / NULLIF(b.fator_cotacao, 0)
       FROM public.b3_cotahist b
      WHERE b.isin = e.isin AND b.tpmerc = '010'
        AND b.trade_date > e.last_date_prior
      ORDER BY b.trade_date, b.codbdi
      LIMIT 1)                                    AS close_unit_after,
    e.raw
FROM b3_corporate_event e
WHERE e.event_class = 'stock';

COMMENT ON VIEW vw_b3_share_count_event IS
    'Share-count events (splits/groupings/bonuses) with the unit close on each side of the entitlement date. Evidence for verifying B3''s per-label factor convention against the tape before any adjusted price series is served. Applies no adjustment itself.';

-- ---------------------------------------------------------------------------
-- B3 instrument typing v3 (migration 27): index/right/bonus split out of the
-- residual bucket; fund subtype falls back to the ISIN's own classified
-- sessions so an ETF survives a board-code change.
-- ---------------------------------------------------------------------------
-- Per-ISIN subtype, learned from the sessions where CODBDI is decisive.
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_b3_isin_subtype AS
SELECT
    t.isin,
    -- Modal subtype: an ISIN whose board codes disagree across its history
    -- takes the one it printed under most often, and ties break
    -- deterministically by name so the view is stable between refreshes.
    (ARRAY_AGG(t.subtype ORDER BY t.n DESC, t.subtype))[1] AS subtype,
    SUM(t.n)                                               AS classified_sessions
FROM (
    SELECT
        q.isin,
        CASE
            WHEN q.codbdi IN ('05', '12') THEN 'fii'
            WHEN q.codbdi = '13'          THEN 'fiagro'
            WHEN q.codbdi = '14'          THEN
                CASE WHEN UPPER(COALESCE(q.especi, '')) LIKE 'FIDC%'
                     THEN 'fidc' ELSE 'etf' END
        END        AS subtype,
        COUNT(*)   AS n
    FROM public.b3_cotahist q
    WHERE q.tpmerc IN ('010', '020', '021')
      AND q.isin IS NOT NULL
      AND q.codbdi IN ('05', '12', '13', '14')
      AND (UPPER(COALESCE(q.especi, '')) LIKE 'CI%'
        OR UPPER(COALESCE(q.especi, '')) LIKE 'FIDC%')
    GROUP BY 1, 2
) t
WHERE t.subtype IS NOT NULL
GROUP BY t.isin;

-- UNIQUE so the LEFT JOIN below cannot multiply rows of the tape, and so the
-- refresh can run CONCURRENTLY without blocking readers.
CREATE UNIQUE INDEX IF NOT EXISTS uq_b3_isin_subtype ON mv_b3_isin_subtype (isin);

COMMENT ON MATERIALIZED VIEW mv_b3_isin_subtype IS
    'ISIN -> fund subtype (etf/fii/fiagro/fidc), learned only from sessions whose CODBDI is decisive. Lets an instrument keep its identity across sessions where B3 printed it under a different board code (measured: BOVA11/BOVV11/IVVB11 under codbdi 02 from 2019-08-19 to 2019-12-30).';

CREATE OR REPLACE VIEW vw_b3_instrument_typed AS
SELECT
    q.*,
    CASE
        WHEN q.tpmerc = '070' THEN 'option_call'
        WHEN q.tpmerc = '080' THEN 'option_put'
        WHEN q.tpmerc = '012' THEN 'option_exercise_call'
        WHEN q.tpmerc = '013' THEN 'option_exercise_put'
        WHEN q.tpmerc = '017' THEN 'auction'
        WHEN q.tpmerc = '030' THEN 'forward'
        WHEN q.tpmerc IN ('010', '020', '021') THEN
            CASE
                WHEN UPPER(COALESCE(q.especi, '')) LIKE 'DR%'  THEN 'bdr'
                WHEN UPPER(COALESCE(q.especi, '')) LIKE 'UNT%' THEN 'unit'
                WHEN UPPER(COALESCE(q.especi, '')) LIKE 'CI%'
                  OR UPPER(COALESCE(q.especi, '')) LIKE 'FIDC%' THEN 'fund_quota'
                WHEN UPPER(COALESCE(q.especi, '')) LIKE 'ON%'
                  OR UPPER(COALESCE(q.especi, '')) LIKE 'PN%'  THEN 'equity'
                -- New in v3, each from a published ESPECI prefix that was
                -- previously falling into the residual bucket.
                -- 'index' also requires the ISIN's IND instrument segment, so a
                -- ticker merely starting with IBO cannot become an index.
                WHEN UPPER(COALESCE(q.especi, '')) LIKE 'IBO%'
                 AND COALESCE(q.isin, '') LIKE 'BR____IND%'   THEN 'index'
                WHEN UPPER(COALESCE(q.especi, '')) LIKE 'DIR%' THEN 'right'
                WHEN UPPER(COALESCE(q.especi, '')) LIKE 'BNS%' THEN 'bonus'
                -- Residual, and now genuinely residual: whatever ESPECI B3
                -- prints that none of the above names.
                ELSE 'cash_security'
            END
        ELSE 'other'
    END AS instrument_type,
    CASE
        WHEN q.tpmerc IN ('010', '020', '021')
         AND (UPPER(COALESCE(q.especi, '')) LIKE 'CI%'
           OR UPPER(COALESCE(q.especi, '')) LIKE 'FIDC%') THEN
            COALESCE(
                CASE
                    WHEN q.codbdi IN ('05', '12') THEN 'fii'
                    WHEN q.codbdi = '13' THEN 'fiagro'
                    WHEN q.codbdi = '14' THEN
                        CASE WHEN UPPER(COALESCE(q.especi, '')) LIKE 'FIDC%'
                             THEN 'fidc' ELSE 'etf' END
                    ELSE NULL
                END,
                -- Same ISIN, same instrument: recover the subtype from the
                -- sessions where the board code was decisive.
                m.subtype
            )
        ELSE NULL
    END AS instrument_subtype,
    CASE
        WHEN q.tpmerc IN ('010', '020', '021')
         AND (UPPER(COALESCE(q.especi, '')) LIKE 'ON%'
           OR UPPER(COALESCE(q.especi, '')) LIKE 'PN%')
         AND SPLIT_PART(BTRIM(COALESCE(q.especi, '')), ' ', 1)
             IN ('ON', 'PN', 'PNA', 'PNB', 'PNC', 'PND', 'UNT')
        THEN SPLIT_PART(BTRIM(COALESCE(q.especi, '')), ' ', 1)
        ELSE NULL
    END AS share_class,
    CASE
        WHEN BTRIM(COALESCE(SUBSTR(q.especi, 9, 2), '')) IN ('NM','N1','N2','MA','M2','MB')
        THEN BTRIM(SUBSTR(q.especi, 9, 2))
        ELSE NULL
    END AS governance_segment
FROM public.b3_cotahist q
LEFT JOIN mv_b3_isin_subtype m ON m.isin = q.isin;

COMMENT ON VIEW vw_b3_instrument_typed IS
    'B3 COTAHIST rows classified from PUBLISHED fields only (TPMERC, ESPECI, CODBDI, ISIN). v3: index/right/bonus split out of the residual cash_security bucket, and fund subtype falls back to the ISIN''s own classified sessions so an ETF stays an ETF across a board-code change.';
