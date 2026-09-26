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
    entity        TEXT         NOT NULL,   -- fi | fidc | fip | fiagro | fii | securit | cia_aberta | etf | anbima_etf | b3 | bacen
    doc_type      TEXT         NOT NULL,
    period_year   INT,
    period_month  INT,
    rows_upserted INT          NOT NULL DEFAULT 0,
    status        TEXT         NOT NULL DEFAULT 'ok',  -- ok | error | skipped
    error_msg     TEXT,
    started_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    finished_at   TIMESTAMPTZ,
    -- Lineage (migration 44): which code produced the slice. git_sha is
    -- GITHUB_SHA, NULL when unset — never invented. parser_version is
    -- src.pipeline.ingest_log.PARSER_VERSION, bumped when a parser or field
    -- map changes what a stored value means.
    git_sha        TEXT,
    parser_version TEXT
);
-- An existing database never re-runs the CREATE TABLE above, so the lineage
-- columns are also reachable from schema.sql alone (tests/test_schema_upgrade_path.py).
ALTER TABLE cvm_ingest_log ADD COLUMN IF NOT EXISTS git_sha TEXT, ADD COLUMN IF NOT EXISTS parser_version TEXT;
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
-- CDA holdings (blocks 4 and 2). See migrations/32_cda_holdings.sql for the
-- unique-key audit that produced these constraints.
CREATE TABLE IF NOT EXISTS cvm_fi_cda_acoes (
    -- No PRIMARY KEY on id: migration 37 dropped it (517 MB, never scanned;
    -- the upsert arbiter is uq_fi_cda_acoes). Same treatment as balancete
    -- after migration 22. Declared here without it so a fresh database does
    -- not build the index only for the migration to drop it.
    id                  BIGSERIAL,
    cnpj                TEXT        NOT NULL CHECK (char_length(cnpj) = 14),
    period              DATE        NOT NULL,   -- first day of month
    tp_fundo            TEXT,                   -- FI / FIF as filed; part of the key
    tp_aplic            TEXT        NOT NULL,   -- application type; part of the key
    tp_ativo            TEXT,
    tp_negoc            TEXT,                   -- "Para negociação" etc.
    cd_ativo            TEXT,                   -- B3 ticker, e.g. ITUB3
    cd_isin             TEXT,
    ds_ativo            TEXT,
    emissor_ligado      TEXT,                   -- 'S' / 'N' related-party flag
    qt_pos_final        NUMERIC(28,6),
    vl_merc_pos_final   NUMERIC(20,2),
    vl_custo_pos_final  NUMERIC(20,2),
    qt_aquis_negoc      NUMERIC(28,6),
    vl_aquis_negoc      NUMERIC(20,2),
    qt_venda_negoc      NUMERIC(28,6),
    vl_venda_negoc      NUMERIC(20,2),
    raw                 JSONB       NOT NULL,
    fetched_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- CREATE TABLE IF NOT EXISTS is a no-op when the table already exists (the
-- live warehouse was created by migration 32 without tp_fundo). schema.sql
-- runs BEFORE migrations, so the unique index below would fail with
-- `column "tp_fundo" does not exist` and migration 33 would never run.
-- Backfill #18 (run 33428561498) died here three times; the apply-schema
-- retry loop misread it as lock contention. ADD COLUMN first. Guarded at
-- apply time so a later replay does not take AccessExclusiveLock.
-- Columns added after this table first shipped (migration 33). On an existing
-- database the CREATE TABLE above is a no-op, so the index below would
-- reference a column that does not exist yet — schema.sql runs BEFORE the
-- migrations. Every post-CREATE column needs its own guarded ALTER here.
ALTER TABLE cvm_fi_cda_acoes ADD COLUMN IF NOT EXISTS tp_fundo TEXT;

-- NULLS NOT DISTINCT: cd_ativo and tp_negoc are empty on a minority of rows,
-- and without it Postgres would treat every such row as distinct and let
-- duplicates through the constraint the audit exists to enforce.
DROP INDEX IF EXISTS uq_fi_cda_acoes;
CREATE UNIQUE INDEX IF NOT EXISTS uq_fi_cda_acoes
    ON cvm_fi_cda_acoes (cnpj, period, tp_fundo, tp_aplic, tp_ativo, cd_ativo, tp_negoc)
    NULLS NOT DISTINCT;

-- The join everyone will actually make: which funds held this ticker.
CREATE INDEX IF NOT EXISTS idx_fi_cda_acoes_ativo
    ON cvm_fi_cda_acoes (cd_ativo, period DESC);

COMMENT ON TABLE cvm_fi_cda_acoes IS
    'FI equity holdings, CDA block 4. One row per (fund, month, application type, ticker, trading intent). cd_ativo is the published B3 ticker, so this is the join between the fund universe and the quote tape. Values are as filed; no adjustment applied.';

CREATE TABLE IF NOT EXISTS cvm_fi_cda_cotas (
    id                  BIGSERIAL   PRIMARY KEY,
    cnpj                TEXT        NOT NULL CHECK (char_length(cnpj) = 14),
    period              DATE        NOT NULL,
    cnpj_cota           TEXT        NOT NULL CHECK (char_length(cnpj_cota) = 14),
    nm_fundo_cota       TEXT,
    tp_fundo            TEXT,                   -- part of the key
    tp_aplic            TEXT,
    tp_ativo            TEXT,
    tp_negoc            TEXT,                   -- part of the key
    emissor_ligado      TEXT,                   -- 'S' = same economic group
    qt_pos_final        NUMERIC(28,6),
    vl_merc_pos_final   NUMERIC(20,2),
    vl_custo_pos_final  NUMERIC(20,2),
    qt_aquis_negoc      NUMERIC(28,6),
    vl_aquis_negoc      NUMERIC(20,2),
    qt_venda_negoc      NUMERIC(28,6),
    vl_venda_negoc      NUMERIC(20,2),
    raw                 JSONB       NOT NULL,
    fetched_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Same replay trap as cvm_fi_cda_acoes: migration 32 created this table
-- without tp_fundo / tp_negoc. The unique index names both.
ALTER TABLE cvm_fi_cda_cotas ADD COLUMN IF NOT EXISTS tp_fundo TEXT;
ALTER TABLE cvm_fi_cda_cotas ADD COLUMN IF NOT EXISTS tp_negoc TEXT;

-- Same reason as cvm_fi_cda_acoes above: migration 33 added these.
ALTER TABLE cvm_fi_cda_cotas ADD COLUMN IF NOT EXISTS tp_fundo TEXT;
ALTER TABLE cvm_fi_cda_cotas ADD COLUMN IF NOT EXISTS tp_negoc TEXT;
ALTER TABLE cvm_fi_cda_cotas DROP CONSTRAINT IF EXISTS uq_fi_cda_cotas;

-- A guard, not the fix for the 2026-08-31 gate outage. It was added as that fix
-- and the diagnosis was wrong, so the reasoning is corrected here rather than
-- left to mislead the next reader.
--
-- What the failing apply log showed was
--
--   duplicate key ... (cnpj, period, tp_fundo, cnpj_cota, tp_aplic, tp_negoc)
--   = (32300050000180, 2023-10-01, null, 43809974000123, Cotas de Fundos, null)
--
-- reported at line 113 of the applied migration 33, which was read as its
-- CREATE UNIQUE INDEX failing over pre-existing duplicates. psql reports a
-- statement's error at its LAST line, and line 113 is the closing line of the
-- UPDATE above that index, not of the index itself. The table holds no
-- duplicates: the CREATE UNIQUE INDEX below builds over the same rows minutes
-- earlier in this very file, and succeeds, every run. Migration 33's repair
-- UPDATE then nulled a filed tp_negoc — `raw` no longer carries TP_NEGOC once
-- the typed column exists — and collided the row with its all-NULL sibling.
-- That statement is fixed in place; see the note there.
--
-- This block is kept because the invariant is still worth asserting: a
-- duplicate here means the index cannot be built at all, which takes down every
-- ingest, and finding out during an apply is expensive. It removed 0 rows on
-- production (no NOTICE in the 2026-09-01 10:28 log), so it is cheap insurance
-- rather than a live repair. If it ever does fire, removing the older copies is
-- what ON CONFLICT DO UPDATE would itself have produced had the index existed
-- when they were written: the newest row per key is the current truth, and the
-- superseded copies are the ones an upsert discards. The count is raised as a
-- NOTICE so an operator sees it in the apply log rather than discovering it
-- later.
DO $cotas_dedup$
DECLARE
    v_removed BIGINT;
BEGIN
    IF to_regclass('public.cvm_fi_cda_cotas') IS NULL THEN
        RETURN;
    END IF;
    WITH ranked AS (
        SELECT id,
               row_number() OVER (
                   PARTITION BY cnpj, period, tp_fundo, cnpj_cota, tp_aplic, tp_negoc
                   ORDER BY fetched_at DESC, id DESC
               ) AS rn
          FROM cvm_fi_cda_cotas
    ), doomed AS (
        DELETE FROM cvm_fi_cda_cotas t
         USING ranked r
         WHERE t.id = r.id AND r.rn > 1
        RETURNING 1
    )
    SELECT count(*) INTO v_removed FROM doomed;
    IF v_removed > 0 THEN
        RAISE NOTICE
            'cvm_fi_cda_cotas: removed % superseded duplicate row(s) before building uq_fi_cda_cotas (kept the newest per key, as ON CONFLICT DO UPDATE would have)',
            v_removed;
    END IF;
END
$cotas_dedup$;

DROP INDEX IF EXISTS uq_fi_cda_cotas;
CREATE UNIQUE INDEX IF NOT EXISTS uq_fi_cda_cotas
    ON cvm_fi_cda_cotas (cnpj, period, tp_fundo, cnpj_cota, tp_aplic, tp_negoc)
    NULLS NOT DISTINCT;

-- The reverse edge: who holds this fund.
CREATE INDEX IF NOT EXISTS idx_fi_cda_cotas_held
    ON cvm_fi_cda_cotas (cnpj_cota, period DESC);

COMMENT ON TABLE cvm_fi_cda_cotas IS
    'FI fund-of-fund holdings, CDA block 2. One row per (holder fund, month, held fund). emissor_ligado is CVM''s published related-party flag, not an inference.';


-- CDA block 6 — debenture holdings. See migrations/35_cda_debentures.sql for the
-- unique-key audit measured on both file eras.
CREATE TABLE IF NOT EXISTS cvm_fi_cda_debentures (
    id                  BIGSERIAL   PRIMARY KEY,
    cnpj                TEXT        NOT NULL CHECK (char_length(cnpj) = 14),
    period              DATE        NOT NULL,   -- first day of month
    tp_fundo            TEXT,                   -- FI / FIF as filed; part of the key
    denom_social        TEXT,
    tp_aplic            TEXT,                   -- "Debêntures" / "Debêntures conversíveis"
    tp_ativo            TEXT,                   -- "Debênture simples" etc.
    tp_negoc            TEXT,
    emissor_ligado      TEXT,                   -- 'S' / 'N' related-party flag, as published
    -- The issuer. PF_PJ_EMISSOR says which of CPF/CNPJ cpf_cnpj_emissor holds,
    -- so it is stored as published text with no 14-digit CHECK: a CPF issuer is
    -- a real filing and a CNPJ constraint would reject it.
    pf_pj_emissor       TEXT,
    cpf_cnpj_emissor    TEXT,
    emissor             TEXT,
    dt_venc             DATE,                   -- maturity; part of the key
    titulo_posfx        TEXT,
    cd_indexador_posfx  TEXT,                   -- 'DI1', 'IPCA', …
    ds_indexador_posfx  TEXT,
    pr_indexador_posfx  NUMERIC(20,6),          -- % of the indexer
    pr_cupom_posfx      NUMERIC(20,6),          -- spread over it
    pr_taxa_prefx       NUMERIC(20,6),          -- pre-fixed rate instead
    titulo_cetip        TEXT,
    titulo_garantia     TEXT,
    cnpj_instituicao_financ_coobr TEXT,
    qt_pos_final        NUMERIC(28,6),
    vl_merc_pos_final   NUMERIC(20,2),
    vl_custo_pos_final  NUMERIC(20,2),
    qt_aquis_negoc      NUMERIC(28,6),
    vl_aquis_negoc      NUMERIC(20,2),
    qt_venda_negoc      NUMERIC(28,6),
    vl_venda_negoc      NUMERIC(20,2),
    -- Tiebreaker, LAST in the key. A debenture has no CD_ATIVO, and two series
    -- of one issuer maturing the same day at different coupons are different
    -- securities holding different money. See the field map for the audit.
    row_hash            TEXT        NOT NULL,
    raw                 JSONB       NOT NULL,
    fetched_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- NULLS NOT DISTINCT: dt_venc, tp_negoc and tp_ativo are empty on a minority of
-- rows; without it Postgres treats every such row as distinct and the constraint
-- stops enforcing anything.
CREATE UNIQUE INDEX IF NOT EXISTS uq_fi_cda_debentures
    ON cvm_fi_cda_debentures
       (cnpj, period, tp_fundo, tp_aplic, tp_ativo, cpf_cnpj_emissor, dt_venc,
        tp_negoc, row_hash)
    NULLS NOT DISTINCT;

-- The join this table exists for: which funds hold this issuer's paper.
CREATE INDEX IF NOT EXISTS idx_fi_cda_deb_emissor
    ON cvm_fi_cda_debentures (cpf_cnpj_emissor, period DESC);
CREATE INDEX IF NOT EXISTS idx_fi_cda_deb_fund
    ON cvm_fi_cda_debentures (cnpj, period DESC);

COMMENT ON TABLE cvm_fi_cda_debentures IS
    'FI debenture holdings, CDA block 6. One row per (fund, month, issuer, maturity, series). cpf_cnpj_emissor is the issuer''s own CPF/CNPJ, so this is the join between the fund universe and the corporate-credit issuer. Values are as filed; no adjustment applied.';


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
-- FIDC — receivables portfolio by sector  (tab_II: total + 32 sector lines)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cvm_fidc_setor (
    id                       BIGSERIAL    PRIMARY KEY,
    cnpj                     TEXT         NOT NULL CHECK (char_length(cnpj) = 14),
    period                   DATE         NOT NULL,
    vl_carteira              NUMERIC(20,6),
    vl_a_indust              NUMERIC(20,6),
    vl_b_imobil              NUMERIC(20,6),
    vl_c_comerc              NUMERIC(20,6),
    vl_c1_comerc             NUMERIC(20,6),
    vl_c2_varejo             NUMERIC(20,6),
    vl_c3_arrend             NUMERIC(20,6),
    vl_d_serv                NUMERIC(20,6),
    vl_d1_serv               NUMERIC(20,6),
    vl_d2_serv_publico       NUMERIC(20,6),
    vl_d3_serv_educ          NUMERIC(20,6),
    vl_d4_entret             NUMERIC(20,6),
    vl_e_agroneg             NUMERIC(20,6),
    vl_f_financ              NUMERIC(20,6),
    vl_f1_cred_pessoa        NUMERIC(20,6),
    vl_f2_cred_pessoa_consig NUMERIC(20,6),
    vl_f3_cred_corp          NUMERIC(20,6),
    vl_f4_midmarket          NUMERIC(20,6),
    vl_f5_veiculo            NUMERIC(20,6),
    vl_f6_imobil_empresa     NUMERIC(20,6),
    vl_f7_imobil_resid       NUMERIC(20,6),
    vl_f8_outro              NUMERIC(20,6),
    vl_g_credito             NUMERIC(20,6),
    vl_h_factor              NUMERIC(20,6),
    vl_h1_pessoa             NUMERIC(20,6),
    vl_h2_corp               NUMERIC(20,6),
    vl_i_setor_publico       NUMERIC(20,6),
    vl_i1_precat             NUMERIC(20,6),
    vl_i2_tribut             NUMERIC(20,6),
    vl_i3_royalties          NUMERIC(20,6),
    vl_i4_outro              NUMERIC(20,6),
    vl_j_judicial            NUMERIC(20,6),
    vl_k_marca               NUMERIC(20,6),
    raw                      JSONB,
    fetched_at               TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fidc_setor UNIQUE (cnpj, period)
);
CREATE INDEX IF NOT EXISTS idx_fidc_setor_cnpj   ON cvm_fidc_setor (cnpj);
CREATE INDEX IF NOT EXISTS idx_fidc_setor_period ON cvm_fidc_setor (period DESC);

-- ---------------------------------------------------------------------------
-- FIDC — SCR risk-rating ladder  (tab_X: AA..H by debtor and by operation)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cvm_fidc_scr (
    id               BIGSERIAL    PRIMARY KEY,
    cnpj             TEXT         NOT NULL CHECK (char_length(cnpj) = 14),
    period           DATE         NOT NULL,
    vl_devedor_aa    NUMERIC(20,6),
    vl_devedor_a     NUMERIC(20,6),
    vl_devedor_b     NUMERIC(20,6),
    vl_devedor_c     NUMERIC(20,6),
    vl_devedor_d     NUMERIC(20,6),
    vl_devedor_e     NUMERIC(20,6),
    vl_devedor_f     NUMERIC(20,6),
    vl_devedor_g     NUMERIC(20,6),
    vl_devedor_h     NUMERIC(20,6),
    vl_oper_aa       NUMERIC(20,6),
    vl_oper_a        NUMERIC(20,6),
    vl_oper_b        NUMERIC(20,6),
    vl_oper_c        NUMERIC(20,6),
    vl_oper_d        NUMERIC(20,6),
    vl_oper_e        NUMERIC(20,6),
    vl_oper_f        NUMERIC(20,6),
    vl_oper_g        NUMERIC(20,6),
    vl_oper_h        NUMERIC(20,6),
    vl_debito_tribut NUMERIC(20,6),
    raw              JSONB,
    fetched_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fidc_scr UNIQUE (cnpj, period)
);
CREATE INDEX IF NOT EXISTS idx_fidc_scr_cnpj   ON cvm_fidc_scr (cnpj);
CREATE INDEX IF NOT EXISTS idx_fidc_scr_period ON cvm_fidc_scr (period DESC);

-- ---------------------------------------------------------------------------
-- FIDC — the 25 largest sacados, anonymized  (tab_VIII: one row per rank)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cvm_fidc_sacado (
    id         BIGSERIAL    PRIMARY KEY,
    cnpj       TEXT         NOT NULL CHECK (char_length(cnpj) = 14),
    period     DATE         NOT NULL,
    -- CVM's rank as filed (1..25). Never recomputed from valor.
    seq        INT          NOT NULL,
    valor      NUMERIC(20,6),
    fetched_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fidc_sacado UNIQUE (cnpj, period, seq)
);
CREATE INDEX IF NOT EXISTS idx_fidc_sacado_cnpj   ON cvm_fidc_sacado (cnpj);
CREATE INDEX IF NOT EXISTS idx_fidc_sacado_period ON cvm_fidc_sacado (period DESC);

-- ---------------------------------------------------------------------------
-- FIDC — named cedente concentration  (tab_I blocks A/B, slots 1..9, unpivoted)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cvm_fidc_cedente (
    id                BIGSERIAL    PRIMARY KEY,
    cnpj              TEXT         NOT NULL CHECK (char_length(cnpj) = 14),
    period            DATE         NOT NULL,
    -- A = receivables acquired with substantial retention of risks and
    -- benefits by the cedente (TAB_I2A); B = without (TAB_I2B).
    bloco             TEXT         NOT NULL CHECK (bloco IN ('A', 'B')),
    -- CVM's slot 1..9 as filed.
    seq               INT          NOT NULL,
    -- The cedente's own CPF or CNPJ, digits only. No 14-digit CHECK: the
    -- source column is CPF_CNPJ and a CPF is a real filing.
    cpf_cnpj_cedente  TEXT         NOT NULL,
    pr_cedente        NUMERIC(20,6),
    fetched_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fidc_cedente UNIQUE (cnpj, period, bloco, seq)
);
CREATE INDEX IF NOT EXISTS idx_fidc_cedente_cnpj    ON cvm_fidc_cedente (cnpj);
CREATE INDEX IF NOT EXISTS idx_fidc_cedente_period  ON cvm_fidc_cedente (period DESC);
-- The join column: which funds buy from this originator.
CREATE INDEX IF NOT EXISTS idx_fidc_cedente_cedente ON cvm_fidc_cedente (cpf_cnpj_cedente);

-- ---------------------------------------------------------------------------
-- FIDC — guarantees on the credit rights  (tab_X_7: value and %, as filed)
-- Migration 45. From 2019-11; key audit and the unstated denominator are in
-- the migration header.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cvm_fidc_garantia (
    id           BIGSERIAL    PRIMARY KEY,
    cnpj         TEXT         NOT NULL CHECK (char_length(cnpj) = 14),
    period       DATE         NOT NULL,
    -- TAB_X_VL_GARANTIA_DIRCRED, as filed.
    vl_garantia  NUMERIC(20,6),
    -- TAB_X_PR_GARANTIA_DIRCRED, as filed; the denominator is CVM's, unstated.
    pr_garantia  NUMERIC(20,6),
    raw          JSONB,
    fetched_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fidc_garantia UNIQUE (cnpj, period)
);
CREATE INDEX IF NOT EXISTS idx_fidc_garantia_cnpj   ON cvm_fidc_garantia (cnpj);
CREATE INDEX IF NOT EXISTS idx_fidc_garantia_period ON cvm_fidc_garantia (period DESC);

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
    id             BIGSERIAL    PRIMARY KEY,
    cnpj           TEXT,
    doc_type       TEXT         NOT NULL,  -- inf_trimestral | inf_quadrimestral
    period         DATE,                   -- the filing's own DT_COMPTC
    period_year    INT          NOT NULL,
    classe_cota    TEXT,                   -- share class A/B/C; part of the key
    row_hash       TEXT,                   -- tiebreaker for restated filings
    tp_fundo       TEXT,
    denom_social   TEXT,
    vl_patrim_liq  NUMERIC(20,6),
    qt_cota        NUMERIC(28,8),
    vl_patrim_cota NUMERIC(28,8),
    nr_cotst       NUMERIC(20,2),
    vl_cap_comprom NUMERIC(20,2),
    vl_cap_subscr  NUMERIC(20,2),
    vl_cap_integr  NUMERIC(20,2),
    raw            JSONB        NOT NULL,
    fetched_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Added by migration 34; guarded here because schema.sql runs before the
-- migrations and the CREATE TABLE above is a no-op on an existing database.
ALTER TABLE cvm_fip_periodic ADD COLUMN IF NOT EXISTS period         DATE;
ALTER TABLE cvm_fip_periodic ADD COLUMN IF NOT EXISTS classe_cota    TEXT;
ALTER TABLE cvm_fip_periodic ADD COLUMN IF NOT EXISTS row_hash       TEXT;
ALTER TABLE cvm_fip_periodic ADD COLUMN IF NOT EXISTS tp_fundo       TEXT;
ALTER TABLE cvm_fip_periodic ADD COLUMN IF NOT EXISTS denom_social   TEXT;
ALTER TABLE cvm_fip_periodic ADD COLUMN IF NOT EXISTS qt_cota        NUMERIC(28,8);
ALTER TABLE cvm_fip_periodic ADD COLUMN IF NOT EXISTS vl_patrim_cota NUMERIC(28,8);
ALTER TABLE cvm_fip_periodic ADD COLUMN IF NOT EXISTS nr_cotst       NUMERIC(20,2);
ALTER TABLE cvm_fip_periodic ADD COLUMN IF NOT EXISTS vl_cap_comprom NUMERIC(20,2);
ALTER TABLE cvm_fip_periodic ADD COLUMN IF NOT EXISTS vl_cap_subscr  NUMERIC(20,2);
ALTER TABLE cvm_fip_periodic ADD COLUMN IF NOT EXISTS vl_cap_integr  NUMERIC(20,2);
ALTER TABLE cvm_fip_periodic DROP CONSTRAINT IF EXISTS uq_fip_periodic;

-- Recover the key columns from the preserved source row before the index is
-- built. Order matters: the new key DROPS period_year, so until these run every
-- year of a fund has (period, classe_cota, row_hash) = (NULL, NULL, NULL) and
-- NULLS NOT DISTINCT makes them all duplicates of each other.
UPDATE cvm_fip_periodic
   SET period = NULLIF(raw ->> 'DT_COMPTC', '')::DATE
 WHERE period IS NULL
   AND NULLIF(raw ->> 'DT_COMPTC', '') IS NOT NULL;

UPDATE cvm_fip_periodic
   SET classe_cota = NULLIF(raw ->> 'CLASSE_COTA', '')
 WHERE classe_cota IS NULL;

-- The marker carries the row's own id. A constant would make every legacy row
-- of a fund identical under the new key — which is precisely the collapse this
-- change exists to end. `raw` holds only the columns the OLD field map did not
-- consume, so the real digest cannot be recomputed here; the next ingest of
-- that slice writes it as a new row and these remain distinguishable as the
-- pre-fix remnant.
UPDATE cvm_fip_periodic
   SET row_hash = 'pre-migration-34:' || id::TEXT
 WHERE row_hash IS NULL;

-- A FIP yearly CSV holds every filing of the year (4 quarters, or 3
-- quadrimestral periods) and one row per share class inside each. Keying on
-- period_year alone discarded 72-77% of every published file.
DROP INDEX IF EXISTS uq_fip_periodic;
CREATE UNIQUE INDEX IF NOT EXISTS uq_fip_periodic
    ON cvm_fip_periodic (cnpj, doc_type, period, classe_cota, row_hash)
    NULLS NOT DISTINCT;
CREATE INDEX IF NOT EXISTS idx_fip_periodic_cnpj      ON cvm_fip_periodic (cnpj) WHERE cnpj IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_fip_periodic_type_year ON cvm_fip_periodic (doc_type, period_year DESC);
CREATE INDEX IF NOT EXISTS idx_fip_periodic_period    ON cvm_fip_periodic (period DESC);

-- ---------------------------------------------------------------------------
-- FII — monthly general summary  (mensal_geral, yearly ZIP)
--   The key gains versao (migration 43, mirrored in the ALTER block near the
--   end of this file): every CVM version of a filing is kept. Read one row per
--   (cnpj, period, doc_subtype) through vw_fii_mensal_latest.
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
--   is quarterly and dfin ships several filings per fund per year. Migration
--   43 then adds versao, so every CVM version is kept. Read one row per former
--   key through vw_fii_periodic_latest.
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
    -- Net assets as published for THIS record, with its own as-of date: a class
    -- row carries the class PL, a fund row the fund PL. Never read the value
    -- without the date (migration 28).
    vl_patrim_liq NUMERIC(20,2),
    dt_patrim_liq DATE,
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
--
-- cvm_fii_mensal / cvm_fii_periodic (migration 43): versao — CVM's `Versao` —
-- is in both keys, so every restatement of a filing is kept as its own row
-- instead of overwriting the original. NULLS NOT DISTINCT keeps rows that
-- carry no version deduping exactly as before. The swaps are catalog-guarded
-- (a no-op once the key names versao). An unconditional re-ADD of a narrower
-- key would fail as soon as two versions of one filing are stored.
-- Readers go through vw_fii_mensal_latest / vw_fii_periodic_latest (one row
-- per former key, highest versao), created by migration 43 and deliberately
-- not here: on a fresh database migration 01 retypes cvm_fii_mensal columns
-- after this file, and a view over the table would block that ALTER.
-- The versao backfill from raw and its column comments also live only in 43
-- (the comment is the backfill's run-once marker).
ALTER TABLE cvm_fii_mensal
    ADD COLUMN IF NOT EXISTS versao INT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'cvm_fii_mensal'::regclass
          AND conname  = 'uq_fii_mensal'
          AND pg_get_constraintdef(oid) ILIKE '%versao%'
    ) THEN
        ALTER TABLE cvm_fii_mensal DROP CONSTRAINT IF EXISTS uq_fii_mensal;
        ALTER TABLE cvm_fii_mensal ADD CONSTRAINT uq_fii_mensal
            UNIQUE NULLS NOT DISTINCT (cnpj, period, doc_subtype, versao);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'cvm_fii_periodic'::regclass
          AND conname  = 'uq_fii_periodic'
          AND pg_get_constraintdef(oid) ILIKE '%versao%'
    ) THEN
        ALTER TABLE cvm_fii_periodic DROP CONSTRAINT IF EXISTS uq_fii_periodic;
        ALTER TABLE cvm_fii_periodic ADD CONSTRAINT uq_fii_periodic
            UNIQUE NULLS NOT DISTINCT (cnpj, doc_type, period_year, data_referencia, versao);
    END IF;
END $$;

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
-- IBGE: the IPCA item tree with weights (SIDRA tables 1419 + 7060)
-- ---------------------------------------------------------------------------
-- BACEN's SGS has the group VARIATIONS; IBGE alone publishes the WEIGHTS, and
-- contribution = weight × variation. Grain (reference_month, item_code) where
-- item_code is SIDRA's c315 code (7169 = Índice geral); item_number is IBGE's
-- structure number ('1', '11', '1101', '1101002'; NULL for the general index)
-- and level its depth (0 geral … 4 subitem). Values as published, in percent;
-- "..." / "-" / "X" are NULL. See migration 41 for the verified contract.
CREATE TABLE IF NOT EXISTS ibge_ipca_item_monthly (
    id                 BIGSERIAL     PRIMARY KEY,
    reference_month    DATE          NOT NULL,
    item_code          INT           NOT NULL,
    item_number        TEXT,
    item_name          TEXT          NOT NULL,
    level              SMALLINT      NOT NULL,
    variacao_mensal    NUMERIC(12,4),
    peso_mensal        NUMERIC(12,4),
    variacao_acum_ano  NUMERIC(12,4),
    variacao_acum_12m  NUMERIC(12,4),
    sidra_table        INT           NOT NULL,
    fetched_at         TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_ibge_ipca_item_monthly UNIQUE (reference_month, item_code),
    CONSTRAINT ck_ibge_ipca_item_level CHECK (level BETWEEN 0 AND 4)
);
CREATE INDEX IF NOT EXISTS idx_ibge_ipca_item_level_month
    ON ibge_ipca_item_monthly (level, reference_month DESC);
CREATE INDEX IF NOT EXISTS idx_ibge_ipca_item_number_month
    ON ibge_ipca_item_monthly (item_number, reference_month DESC);

-- B3 Fundos.NET document register with versions (migration 42; contract in
-- src/fetchers/fnet_fetcher.py).
-- fnet_document — one row per FNET document id (each version is a new id).
--   Grain: fnet_id. Values as FNET publishes them. reference_date is parsed
--   only from dd/mm/yyyy (that day) or mm/yyyy (first of the month);
--   anything else stays NULL beside reference_raw. delivered_at is FNET's
--   dataEntrega, São Paulo local time, stored as printed (no zone).
--   status is AS OF fetched_at: a document fetched while active reads AC
--   until a later fetch sees it superseded (IC).
--   fund_name is FNET's label and is NEVER joined on — see the next table.
CREATE TABLE IF NOT EXISTS fnet_document (
    id               BIGSERIAL    PRIMARY KEY,
    fnet_id          BIGINT       NOT NULL CHECK (fnet_id > 0),
    fund_name        TEXT,
    fundo_ou_classe  TEXT,
    categoria        TEXT,
    tipo_documento   TEXT,
    especie          TEXT,
    reference_raw    TEXT,
    reference_format TEXT,
    reference_date   DATE,
    delivered_at     TIMESTAMP    NOT NULL,
    versao           INT          NOT NULL CHECK (versao >= 1),
    modalidade       TEXT,
    status           TEXT,
    situacao         TEXT,
    alta_prioridade  BOOLEAN,
    raw              JSONB,
    fetched_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fnet_document UNIQUE (fnet_id)
);
CREATE INDEX IF NOT EXISTS idx_fnet_document_delivered ON fnet_document (delivered_at DESC);
CREATE INDEX IF NOT EXISTS idx_fnet_document_modalidade ON fnet_document (modalidade, delivered_at DESC);
CREATE INDEX IF NOT EXISTS idx_fnet_document_type_ref ON fnet_document (tipo_documento, reference_date);

-- fnet_document_filter — "FNET returned this document for this query filter".
--   FNET's search rows carry NO fund CNPJ (cnpjFundo is null on every row,
--   even when the query filters on it) and no fund type. Both are known only
--   because the ingest ASKED for them, so that is what is recorded:
--     filter_name = 'tipoFundo', filter_value = '1' (FII) | '2' (FIDC) | '3' (ETF)
--     filter_name = 'cnpjFundo', filter_value = the 14-digit CNPJ queried
--   A document's fund CNPJ is a row here or it is unknown. It is never
--   inferred from fund_name (CLAUDE.md: no name matching, ever).
CREATE TABLE IF NOT EXISTS fnet_document_filter (
    id            BIGSERIAL    PRIMARY KEY,
    fnet_id       BIGINT       NOT NULL,
    filter_name   TEXT         NOT NULL CHECK (filter_name IN ('tipoFundo', 'cnpjFundo')),
    filter_value  TEXT         NOT NULL,
    fetched_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fnet_document_filter UNIQUE (fnet_id, filter_name, filter_value),
    CONSTRAINT ck_fnet_filter_cnpj CHECK (filter_name <> 'cnpjFundo' OR filter_value ~ '^[0-9]{14}$')
);
CREATE INDEX IF NOT EXISTS idx_fnet_filter_value ON fnet_document_filter (filter_name, filter_value);

-- FNET restatement diffs (migration 46; design docs/planning/DOCUMENTS.md,
-- parse and diff src/parsers/fnet_xml.py, queue src/pipeline/fnet_diff.py).
-- Hashes and diffs only: no document body is stored.
-- fnet_document_body — one row per downloaded document body.
--   Grain: fnet_id. Every column comes from the HTTP response or the document
--   itself. sha256 is of the bytes as served; canonical_sha256 of the parsed,
--   whitespace-free form the diff compares (fnet_xml.canonical_lines), so two
--   bodies that differ only in indentation share it. declared_cnpj_raw /
--   declared_reference_raw are the XML's own NR_CNPJ_FUNDO / DT_COMPT as
--   printed; declared_cnpj is the digits only when there are exactly 14,
--   otherwise NULL (decision 5: a 13-digit CNPJ is never padded).
--   parse_status: ok | not_xml (a PDF, say) | parse_error | unsupported_root.
CREATE TABLE IF NOT EXISTS fnet_document_body (
    id                      BIGSERIAL    PRIMARY KEY,
    fnet_id                 BIGINT       NOT NULL CHECK (fnet_id > 0),
    content_type            TEXT,
    bytes                   INT          NOT NULL CHECK (bytes >= 0),
    sha256                  TEXT         NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    canonical_sha256        TEXT         CHECK (canonical_sha256 ~ '^[0-9a-f]{64}$'),
    filename                TEXT,
    root_element            TEXT,
    schema_version          TEXT,
    declared_cnpj_raw       TEXT,
    declared_cnpj           TEXT         CHECK (declared_cnpj ~ '^[0-9]{14}$'),
    declared_reference_raw  TEXT,
    leaf_count              INT          CHECK (leaf_count >= 0),
    parse_status            TEXT         NOT NULL
        CHECK (parse_status IN ('ok', 'not_xml', 'parse_error', 'unsupported_root')),
    parse_error             TEXT,
    fetched_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fnet_document_body UNIQUE (fnet_id),
    CONSTRAINT ck_fnet_body_parsed CHECK (
        parse_status <> 'ok' OR (canonical_sha256 IS NOT NULL AND leaf_count IS NOT NULL))
);

-- fnet_document_pair — one row per re-filed document (versao > 1): the
--   predecessor it was compared with, or why it could not be.
--   Grain: (fnet_id, prev_fnet_id); NULLS NOT DISTINCT (as migration 43) lets
--   an unpairable document hold exactly one row with prev_fnet_id NULL.
--   The predecessor is chosen by api.fund_restatements' own group key
--   (analytical 24): same cnpjFundo link, categoria, tipo_documento, especie
--   and reference_raw; the highest lower versao, the greatest fnet_id on a
--   tie. pair_rule names that rule. cnpj is the link that made the pair,
--   never a name. A pair that compared clean is status 'compared' with
--   n_changed = 0, so "no change" and "not compared" are never the same row.
--   Statuses that are waits (unpairable_no_link: the fortnightly sweep has
--   not linked the fund yet; no_predecessor: the register holds no lower
--   version yet) are retried on later runs; the rest are terminal for their
--   diff_version.
CREATE TABLE IF NOT EXISTS fnet_document_pair (
    id                   BIGSERIAL    PRIMARY KEY,
    fnet_id              BIGINT       NOT NULL CHECK (fnet_id > 0),
    prev_fnet_id         BIGINT       CHECK (prev_fnet_id > 0 AND prev_fnet_id <> fnet_id),
    cnpj                 TEXT         CHECK (cnpj ~ '^[0-9]{14}$'),
    pair_rule            TEXT         NOT NULL,
    status               TEXT         NOT NULL CHECK (status IN (
        'compared', 'unpairable_no_link', 'unpairable_no_reference', 'no_predecessor',
        'body_not_xml', 'parse_error', 'unsupported_root', 'declared_mismatch',
        'body_hash_mismatch')),
    detail               TEXT,
    n_changed            INT          CHECK (n_changed >= 0),
    n_added              INT          CHECK (n_added >= 0),
    n_removed            INT          CHECK (n_removed >= 0),
    identical_bytes      BOOLEAN,
    identical_canonical  BOOLEAN,
    diff_version         INT          NOT NULL CHECK (diff_version >= 1),
    compared_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fnet_document_pair UNIQUE NULLS NOT DISTINCT (fnet_id, prev_fnet_id),
    CONSTRAINT ck_fnet_pair_compared CHECK (
        status <> 'compared'
        OR (prev_fnet_id IS NOT NULL AND n_changed IS NOT NULL
            AND n_added IS NOT NULL AND n_removed IS NOT NULL)),
    CONSTRAINT ck_fnet_pair_unpaired CHECK (
        status NOT IN ('unpairable_no_link', 'unpairable_no_reference', 'no_predecessor')
        OR prev_fnet_id IS NULL)
);
CREATE INDEX IF NOT EXISTS idx_fnet_pair_cnpj ON fnet_document_pair (cnpj);

-- fnet_document_diff — one row per leaf that differs within a compared pair.
--   Grain: (fnet_id, prev_fnet_id, field_path). field_path is relative to the
--   root; repeated blocks are addressed by their declared key
--   (CLASSE_SENIOR[SERIE=Série 1]) or, lacking one, by position ([#2]), and
--   match_basis says which (path | key | position: position rows are
--   approximate by construction, flagged and never hidden). old_value /
--   new_value are the text exactly as printed (NULL for nil or absent);
--   old_num / new_num only where the leaf's number rule parses it, never
--   coerced. cvm_column / silo_column stay NULL until the crosswalk exists
--   (decision 7).
CREATE TABLE IF NOT EXISTS fnet_document_diff (
    id             BIGSERIAL    PRIMARY KEY,
    fnet_id        BIGINT       NOT NULL CHECK (fnet_id > 0),
    prev_fnet_id   BIGINT       NOT NULL CHECK (prev_fnet_id > 0),
    field_path     TEXT         NOT NULL,
    block          TEXT         NOT NULL,
    leaf           TEXT         NOT NULL,
    change_kind    TEXT         NOT NULL
        CHECK (change_kind IN ('changed', 'added', 'removed', 'nil_to_value', 'value_to_nil')),
    old_value      TEXT,
    new_value      TEXT,
    old_num        NUMERIC,
    new_num        NUMERIC,
    match_basis    TEXT         NOT NULL CHECK (match_basis IN ('path', 'key', 'position')),
    cvm_column     TEXT,
    silo_column    TEXT,
    diff_version   INT          NOT NULL CHECK (diff_version >= 1),
    CONSTRAINT uq_fnet_document_diff UNIQUE (fnet_id, prev_fnet_id, field_path)
);

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
-- ISIN-keyed lookup (migration 36). idx_b3_cotahist_isin is unordered and
-- idx_b3_cotahist_vista is keyed on codneg with isin only as payload, so
-- "last close on or before date D for this ISIN" had no index and scanned the
-- instrument's whole history. That is the lookup vw_b3_share_count_event makes
-- twice per corporate event, and the one any event-sourced adjustment needs.
CREATE INDEX IF NOT EXISTS idx_b3_cotahist_isin_dt
    ON b3_cotahist (isin, trade_date DESC)
    INCLUDE (preco_fechamento, fator_cotacao)
    WHERE tpmerc = '010' AND isin IS NOT NULL;
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
--
-- WITH NO DATA is load-bearing. CREATE MATERIALIZED VIEW ... AS SELECT
-- (implicit WITH DATA) inserts the composite type into pg_type and holds
-- that insert uncommitted for the whole b3_cotahist scan. A concurrent
-- schema apply does not see the uncommitted relation, tries to CREATE the
-- same name, and waits on pg_type_typname_nsp_index until lock_timeout —
-- Daily CVM Ingest #184 (run 33180429771) failed three times at this
-- statement with exactly that error. CREATE WITH NO DATA commits the type
-- in milliseconds; population is the REFRESH below (empty only) or the
-- 06:12 UTC pg_cron CONCURRENTLY job. Do not fold the SELECT back into
-- CREATE. Migration 27 keeps the original WITH DATA text (historical
-- migrations are not edited); apply-time rewrite in guard_noop_ddl.py
-- adds WITH NO DATA there too.
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
GROUP BY t.isin
WITH NO DATA;

-- UNIQUE so the LEFT JOIN below cannot multiply rows of the tape, and so the
-- refresh can run CONCURRENTLY without blocking readers.
CREATE UNIQUE INDEX IF NOT EXISTS uq_b3_isin_subtype ON mv_b3_isin_subtype (isin);

-- First populate is a SEPARATE statement from CREATE so the composite type
-- is already committed before we scan b3_cotahist. Skip when already
-- populated (daily replay). Do not SELECT from the matview to decide —
-- an unpopulated MV (WITH NO DATA, not yet REFRESH-ed) raises
-- "has not been populated" (SQL compile on this PR). relispopulated is
-- the catalog flag. Non-concurrent: CONCURRENTLY cannot run inside a
-- DO block. Subsequent refreshes are pg_cron CONCURRENTLY
-- (08_cron_schedules.sql).
DO $silo_refresh_mv_b3_isin_subtype$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relname = 'mv_b3_isin_subtype'
      AND c.relkind = 'm'
      AND NOT c.relispopulated
  ) THEN
    REFRESH MATERIALIZED VIEW public.mv_b3_isin_subtype;
  END IF;
END
$silo_refresh_mv_b3_isin_subtype$;

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

-- ---------------------------------------------------------------------------
-- mv_b3_monthly_activity — monthly COTAHIST aggregates (migration 30)
--
-- Exists so the dashboard stops aggregating the full 2019-2026 tape on every
-- build. Five sources did; on 2026-08-28 that ran the production build past
-- Vercel's 45-minute ceiling and the site did not rebuild. The same scans held
-- AccessShareLock long enough to kill two schema applies the same day.
--
-- GROUPING SETS because COUNT(DISTINCT ...) does not re-aggregate; `grain` is
-- an explicit label because a NULL subtype means "rolled up" on one row and
-- "this instrument has no subtype" on another. Declared AFTER
-- vw_b3_instrument_typed's final definition below, so it is created here only
-- once that view exists — see the ordering note in migration 30.
-- ---------------------------------------------------------------------------
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_b3_monthly_activity AS
WITH src AS (
    SELECT
        date_trunc('month', v.trade_date)::date AS period,
        v.trade_date,
        v.codneg,
        v.tpmerc,
        v.instrument_type,
        v.instrument_subtype,
        v.volume,
        v.preco_fechamento,
        CASE
            WHEN v.tpmerc IN ('010', '020', '021') THEN 'cash'
            WHEN v.tpmerc IN ('070', '080')        THEN 'option'
            WHEN v.tpmerc IN ('012', '013')        THEN 'option_exercise'
            WHEN v.tpmerc = '030'                  THEN 'forward'
            WHEN v.tpmerc = '017'                  THEN 'auction'
            ELSE 'other'
        END AS market_segment
    FROM vw_b3_instrument_typed v
)
SELECT
    CASE
        WHEN GROUPING(s.instrument_subtype) = 0 THEN 'subtype'
        WHEN GROUPING(s.instrument_type)    = 0 THEN 'type'
        WHEN GROUPING(s.tpmerc)             = 0 THEN 'tpmerc'
        ELSE                                         'segment'
    END                                                              AS grain,
    s.period,
    s.market_segment,
    s.tpmerc,
    s.instrument_type,
    s.instrument_subtype,
    SUM(s.volume)                                                    AS volume,
    COUNT(DISTINCT s.codneg)                                         AS n_tickers,
    COUNT(DISTINCT s.trade_date)                                     AS n_sessions,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY s.preco_fechamento)  AS median_close
FROM src s
GROUP BY GROUPING SETS (
    -- monthly volume by board code, and the option call/put split
    (s.period, s.market_segment, s.tpmerc),
    -- distinct series across a whole segment: a call and a put are different
    -- codneg, but that is a fact about B3's naming, not something to lean on
    (s.period, s.market_segment),
    -- volume and ticker counts per instrument type (cash boards)
    (s.period, s.market_segment, s.tpmerc, s.instrument_type),
    -- ETF/FII splits and the ETF median close
    (s.period, s.market_segment, s.tpmerc, s.instrument_type, s.instrument_subtype)
)
WITH NO DATA;

-- REFRESH ... CONCURRENTLY (pg_cron, 08_cron_schedules.sql) requires a unique
-- index. NULLS NOT DISTINCT: the rolled-up grains carry NULLs in the columns
-- they roll up, and without it those rows would not be unique to the index.
CREATE UNIQUE INDEX IF NOT EXISTS uq_b3_monthly_activity
    ON mv_b3_monthly_activity (grain, period, market_segment, tpmerc,
                               instrument_type, instrument_subtype)
    NULLS NOT DISTINCT;

CREATE INDEX IF NOT EXISTS idx_b3_monthly_activity_grain
    ON mv_b3_monthly_activity (grain, period);

DO $silo_refresh_mv_b3_monthly_activity$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relname = 'mv_b3_monthly_activity'
      AND c.relkind = 'm'
      AND NOT c.relispopulated
  ) THEN
    REFRESH MATERIALIZED VIEW mv_b3_monthly_activity;
  END IF;
END
$silo_refresh_mv_b3_monthly_activity$;

COMMENT ON MATERIALIZED VIEW mv_b3_monthly_activity IS
  'Monthly COTAHIST aggregates at four grains (see the grain column). Exists so the dashboard stops scanning the full tape on every build — that cost a production deploy on 2026-08-28. Refreshed daily by pg_cron; filter on grain, never on NULL.';

-- ===========================================================================
-- ---------------------------------------------------------------------------
-- B3 securities lending (BTC/BTB) and investor-type participation.
--
-- WHY THESE TABLES EXIST AS A RATCHET
-- -----------------------------------
-- B3 publishes all of this free, with no auth, through the BDI export API
-- (see src/fetchers/b3_bdi_fetcher.py for the verified contract) — but it
-- retains only a ~21-BUSINESS-DAY ROLLING WINDOW. Verified 2026-09-16:
-- 2026-08-17 returns data, 2026-08-14 returns "Nenhum resultado", and a
-- request spanning 2024-01-02..2026-09-10 comes back HTTP 200 with 5.2 MB
-- containing exactly 18 sessions. There is no archive: the legacy
-- requestname API still serves >1 year but knows none of these tables, and
-- the pesquisapregao bulletin archive returns empty zips.
--
-- So unlike every CVM table in this schema, a gap here is PERMANENT. A missed
-- cron run is not "re-run the backfill", it is a hole in the series forever.
-- That is why run_backfill offers no lending option and why
-- scripts/check_staleness.py must escalate a gap in these tables harder than
-- a gap in a CVM one.
-- ---------------------------------------------------------------------------

-- Open short interest per ticker. Source table: BTBLendingOpenPosition.
--
-- THE 'Total' TRAP. For every (date, ticker, tipo) B3 publishes the per-market
-- rows AND a Mercado = 'Total' row that is exactly their sum — 1036 of 1036
-- groups on 2026-09-10 carried one. SUM(saldo_brl) over this table is
-- therefore 2x the real short balance. Every published row is kept (integrity
-- rule 3: we do not drop what the source published), and `is_total` marks
-- B3's own aggregate so a consumer cannot double-count by accident. Read the
-- is_total rows, or the others, never both.
CREATE TABLE IF NOT EXISTS b3_lending_open_position (
    id                BIGSERIAL PRIMARY KEY,
    trade_date        DATE         NOT NULL,
    -- "Código IF" — the B3 ticker (PETR4). Joins b3_cotahist.codneg.
    codneg            TEXT         NOT NULL,
    isin              TEXT,
    empresa           TEXT,
    -- "Tipo de empréstimo" is B3's specification code for the security
    -- (ON, ON NM, PN N2, DRE, CI ...), not a kind of loan. Part of the key
    -- because one ticker can carry more than one.
    tipo_emprestimo   TEXT         NOT NULL,
    -- Registro | Neg. Eletrônica D+0 | Neg. Eletrônica D+1 | ETF Renda Fixa | Total
    mercado           TEXT         NOT NULL,
    is_total          BOOLEAN      NOT NULL DEFAULT FALSE,
    -- Shares on loan and their market value. NUMERIC(28,4) rather than an
    -- integer: B3 publishes integers today, and a scale of 0 would silently
    -- ROUND a fractional quantity if that ever changed.
    saldo_quantidade  NUMERIC(28, 4),
    preco_medio       NUMERIC(20, 6),
    saldo_brl         NUMERIC(28, 2),
    source            TEXT         NOT NULL DEFAULT 'b3_bdi',
    raw               JSONB        NOT NULL,
    fetched_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_b3_lending_open_position
        UNIQUE (trade_date, codneg, tipo_emprestimo, mercado)
);

CREATE INDEX IF NOT EXISTS idx_b3_lending_open_position_codneg
    ON b3_lending_open_position (codneg, trade_date DESC);
-- The analytical layer only ever reads B3's own aggregate, and it reads it
-- one session at a time.
CREATE INDEX IF NOT EXISTS idx_b3_lending_open_position_total
    ON b3_lending_open_position (trade_date DESC, codneg)
    WHERE is_total;

COMMENT ON TABLE b3_lending_open_position IS
    'Open securities-lending positions per ticker (B3 BTBLendingOpenPosition), i.e. the short balance. B3 retains ~21 business days, so this table can only ever be as deep as the daily job has been running — there is no backfill. Mercado = ''Total'' rows are B3''s own sum of the other markets: filter on is_total or you will double-count.';

-- Lending rates per ticker. Source table: BTBLoanBalance.
--
-- Rates are annualized percentage points as published (0.15 = 0,15% a.a.),
-- the same convention as anbima_class_monthly.rentabilidade_pct. The doador
-- (lender) and tomador (borrower) trios are distinguished by the export's
-- band row, never by column order — see src/parsers/b3_bdi.py.
CREATE TABLE IF NOT EXISTS b3_lending_rate (
    id                 BIGSERIAL    PRIMARY KEY,
    trade_date         DATE         NOT NULL,
    codneg             TEXT         NOT NULL,
    isin               TEXT,
    empresa            TEXT,
    mercado            TEXT         NOT NULL,
    num_contratos      INTEGER,
    quantidade         NUMERIC(28, 4),
    valor_brl          NUMERIC(28, 2),
    taxa_doador_min    NUMERIC(12, 4),
    taxa_doador_media  NUMERIC(12, 4),
    taxa_doador_max    NUMERIC(12, 4),
    taxa_tomador_min   NUMERIC(12, 4),
    taxa_tomador_media NUMERIC(12, 4),
    taxa_tomador_max   NUMERIC(12, 4),
    source             TEXT         NOT NULL DEFAULT 'b3_bdi',
    raw                JSONB        NOT NULL,
    fetched_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_b3_lending_rate UNIQUE (trade_date, codneg, mercado)
);

CREATE INDEX IF NOT EXISTS idx_b3_lending_rate_codneg
    ON b3_lending_rate (codneg, trade_date DESC);
CREATE INDEX IF NOT EXISTS idx_b3_lending_rate_date
    ON b3_lending_rate (trade_date DESC);

COMMENT ON TABLE b3_lending_rate IS
    'Registered securities-lending contracts and their annualized rates per ticker (B3 BTBLoanBalance). taxa_* are percentage points as published; media is B3''s trade-count-weighted average for the session. Same ~21-business-day retention as b3_lending_open_position.';

-- Daily investor-type participation. Source table: SharesInvesVolum.
--
-- MONTH-TO-DATE, T+2. Each export is cumulative from the first of the month
-- to the caption date, and the caption runs two sessions behind the request
-- (a 2026-09-10 request is captioned 08/09/2026). reference_date is the
-- CAPTION date — keying on the request date would file two different
-- snapshots on one day and manufacture a flow out of nothing.
--
-- Daily net flow is therefore a DERIVED first difference of consecutive
-- snapshots within a month (fact_investor_flow_daily), not a stored column.
--
-- Values are R$ thousands exactly as B3 publishes them; the column name says
-- so rather than rescaling into a unit the source never used.
CREATE TABLE IF NOT EXISTS b3_investor_participation (
    id                       BIGSERIAL    PRIMARY KEY,
    reference_date           DATE         NOT NULL,
    -- Institucionais | Instituições Financeiras | Investidor Estrangeiro |
    -- Investidores Individuais | Outros — B3's labels, stored as published.
    investor_type            TEXT         NOT NULL,
    compras_brl_mil          NUMERIC(28, 2),
    compras_participacao_pct NUMERIC(12, 4),
    vendas_brl_mil           NUMERIC(28, 2),
    vendas_participacao_pct  NUMERIC(12, 4),
    source                   TEXT         NOT NULL DEFAULT 'b3_bdi',
    raw                      JSONB        NOT NULL,
    fetched_at               TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_b3_investor_participation UNIQUE (reference_date, investor_type)
);

CREATE INDEX IF NOT EXISTS idx_b3_investor_participation_date
    ON b3_investor_participation (reference_date DESC);

COMMENT ON TABLE b3_investor_participation IS
    'Month-to-date buy/sell volume by investor type (B3 SharesInvesVolum), R$ thousands as published, dated by the export''s own "até o dia" caption (B3 publishes with a T+2 lag). Cumulative within a month and resets on the 1st — take first differences via fact_investor_flow_daily, never subtract across a month boundary.';

-- Previous-month investor participation by market. Source: SharesInvesVolumMonthly.
-- Only the latest month is ever available (past dates return "Nenhum
-- resultado"), so this table is also forward-only.
CREATE TABLE IF NOT EXISTS b3_investor_participation_monthly (
    id                BIGSERIAL    PRIMARY KEY,
    reference_month   DATE         NOT NULL,   -- first day of the month
    investor_type     TEXT         NOT NULL,
    -- À vista | A termo | Opções | Exercícios de opções | Blocos | Total geral
    market            TEXT         NOT NULL,
    valor_brl         NUMERIC(28, 2),
    participacao_pct  NUMERIC(12, 4),
    source            TEXT         NOT NULL DEFAULT 'b3_bdi',
    raw               JSONB        NOT NULL,
    fetched_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_b3_investor_participation_monthly
        UNIQUE (reference_month, investor_type, market)
);

COMMENT ON TABLE b3_investor_participation_monthly IS
    'Previous-month buy+sell volume by investor type and market segment (B3 SharesInvesVolumMonthly), R$ as published. Only the most recent month is retrievable, so history accrues one month per run.';

-- Index constituents with B3's free-float-adjusted share count and sector.
-- Source: sistemaswebb3-listados indexProxy GetPortfolioDay.
--
-- theoricalQty is the FREE FLOAT (the index's float-adjusted share count),
-- not shares outstanding — which is why dim_ticker_float prefers it and
-- records float_basis when it has to fall back.
CREATE TABLE IF NOT EXISTS b3_index_portfolio (
    id               BIGSERIAL    PRIMARY KEY,
    reference_date   DATE         NOT NULL,
    index_code       TEXT         NOT NULL,     -- IBOV, IBRA, SMLL, IBXX
    codneg           TEXT         NOT NULL,
    asset_name       TEXT,
    especificacao    TEXT,
    -- B3's own sector label ("Bens Indls / Mat Transporte"), returned only
    -- when the request asks for segment "2".
    b3_sector        TEXT,
    participacao_pct NUMERIC(12, 6),
    theoretical_qty  NUMERIC(28, 4),
    source           TEXT         NOT NULL DEFAULT 'b3_bdi',
    raw              JSONB        NOT NULL,
    fetched_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_b3_index_portfolio UNIQUE (reference_date, index_code, codneg)
);

CREATE INDEX IF NOT EXISTS idx_b3_index_portfolio_codneg
    ON b3_index_portfolio (codneg, reference_date DESC);

COMMENT ON TABLE b3_index_portfolio IS
    'B3 index theoretical portfolios: free-float-adjusted share count (theoretical_qty) and B3 sector per constituent. The only free, B3-published free float available; covers index members only (IBOV 76, IBRA ~148), which is why dim_ticker_float falls back to shares outstanding for the tail and labels which basis it used.';

-- Cash-market instrument registry. Source: InstrumentsEquities, filtered to
-- Mercado = 'EQUITY-CASH' (the raw export is ~110k rows/day, ~95% of them
-- option series that have no business here).
--
-- capital_social is the share count for that instrument class — the
-- denominator dim_ticker_float uses when a ticker is in no B3 index.
CREATE TABLE IF NOT EXISTS b3_instrument_registry (
    id               BIGSERIAL    PRIMARY KEY,
    reference_date   DATE         NOT NULL,
    instrumento      TEXT         NOT NULL,     -- the ticker (PETR4)
    ativo            TEXT,                      -- the issuer stem (PETR)
    descricao        TEXT,
    segmento         TEXT,
    mercado          TEXT,
    categoria        TEXT,                      -- SHARES | UNIT | BDR | ETF ...
    isin             TEXT,
    nome_instituicao TEXT,
    capital_social   NUMERIC(28, 4),
    nivel_governanca TEXT,                      -- NIVEL 1 | NIVEL 2 | NOVO MERCADO ...
    source           TEXT         NOT NULL DEFAULT 'b3_bdi',
    raw              JSONB        NOT NULL,
    fetched_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_b3_instrument_registry UNIQUE (reference_date, instrumento)
);

CREATE INDEX IF NOT EXISTS idx_b3_instrument_registry_instrumento
    ON b3_instrument_registry (instrumento, reference_date DESC);
CREATE INDEX IF NOT EXISTS idx_b3_instrument_registry_isin
    ON b3_instrument_registry (isin, reference_date DESC);

COMMENT ON TABLE b3_instrument_registry IS
    'B3 cash-market instrument registry (InstrumentsEquities, Mercado = EQUITY-CASH): ISIN, category, governance level and capital_social (shares outstanding for that class). Sourced daily; the option series in the raw export are not stored.';

-- ===========================================================================
-- ---------------------------------------------------------------------------
-- B3 securities-lending trades, one row per individual trade (BTBTrade).
--
-- The other lending tables say how much is on loan and at what rate.
-- This one says WHO traded it: every trade carries the brokerage on each leg.
--
-- READ THIS BEFORE INFERRING ANYTHING DIRECTIONAL
-- -----------------------------------------------
-- `doador` and `tomador` are BROKERAGES, not beneficial owners. Verified on
-- 2026-09-10: the whole session names only 33 distinct participants, and
-- 32,197 of 43,165 trades (74.6%) carry the SAME code on both legs — the
-- broker intermediating its own clients' book. So "XP borrowed 2m shares"
-- means XP's clients were net borrowers through XP, not that XP is short.
-- Anything published off this table has to say so, which is why
-- fact_lending_participant_daily carries `internal_trades` beside the totals
-- rather than quietly netting them away.
--
-- SIZE AND WHY IT IS PARTITIONED
-- ------------------------------
-- ~43k rows per session, ~5.9 MB of CSV — roughly 10M rows a year, an order
-- of magnitude more than every other table in migration 39 combined. Ranged
-- by trade_date like b3_cotahist so a year can be detached or vacuumed on its
-- own. Partitions run to 2029; beyond that rows land in `_future` and the
-- yearly rollover in docs/DATABASE_MAINTENANCE.md §6 applies to this table
-- too.
--
-- Same ~21-business-day retention and the same ratchet as migration 39: a
-- session not captured is gone. Worse here, because there is no aggregate to
-- fall back on — b3_lending_rate keeps the session's average rate, but the
-- individual trades behind it exist nowhere else.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS b3_lending_trade (
    id                BIGSERIAL,
    trade_date        DATE         NOT NULL,
    -- "Número do negócio". Unique within a session (verified: 0 duplicates in
    -- 43,165 rows), so it keys the row with its date. B3 publishes it with
    -- thousand separators ("113.392.202"); stored as the integer it is.
    numero_negocio    BIGINT       NOT NULL,
    codneg            TEXT         NOT NULL,
    quantidade        NUMERIC(28, 4),
    -- Annualized, in percentage points as published (40,00% -> 40.00), the
    -- same convention as b3_lending_rate.taxa_*.
    taxa_pct          NUMERIC(12, 4),
    -- Balcão | Eletrônico D+1 | Eletrônico D0. NOTE these labels differ from
    -- b3_lending_open_position.mercado ("Registro", "Neg. Eletrônica D+1"):
    -- B3 names the same venues differently across its own exports, so do not
    -- join the two on this column.
    mercado           TEXT,
    -- Wall clock as published. B3 names no timezone on this export, so the
    -- date and time stay separate rather than being fused into a timestamptz
    -- whose offset we would have had to invent.
    hora              TEXT,
    acao_atualizacao  TEXT,        -- "Novo (0)"; the field exists for amendments
    tipo_sessao       TEXT,        -- "Regular (1)"
    doador_codigo     TEXT,        -- lender leg: B3 participant code
    doador_nome       TEXT,
    tomador_codigo    TEXT,        -- borrower leg
    tomador_nome      TEXT,
    source            TEXT         NOT NULL DEFAULT 'b3_bdi',
    -- NO `raw` COLUMN, deliberately. Most landing tables here keep one because
    -- their CSV has dozens of columns and the field map selects a subset, so
    -- raw is where the rest survives. This export publishes exactly 13 columns
    -- and all 13 are typed above, making raw a re-encoding of the same values:
    -- measured at 324 of 506 bytes per row, 64% of the heap, ~4 GB a year for
    -- no information. cvm_fidc_cedente, cvm_fidc_sacado, bacen_sgs and four
    -- others omit it on the same grounds.
    --
    -- What raw would otherwise have caught — B3 adding a column — is caught
    -- instead by the parser, which logs every unmapped header label loudly
    -- rather than dropping it silently. Detection without the storage.
    fetched_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_b3_lending_trade UNIQUE (trade_date, numero_negocio)
) PARTITION BY RANGE (trade_date);

-- This table can only ever hold what the daily job has captured, and capture
-- starts the day it is deployed — so there is no history before 2026. The
-- MINVALUE partition exists anyway: a backfilled or mis-dated row must land
-- somewhere rather than abort the insert.
CREATE TABLE IF NOT EXISTS b3_lending_trade_pre2026 PARTITION OF b3_lending_trade
    FOR VALUES FROM (MINVALUE) TO ('2026-01-01');
CREATE TABLE IF NOT EXISTS b3_lending_trade_2026 PARTITION OF b3_lending_trade
    FOR VALUES FROM ('2026-01-01') TO ('2027-01-01');
CREATE TABLE IF NOT EXISTS b3_lending_trade_2027 PARTITION OF b3_lending_trade
    FOR VALUES FROM ('2027-01-01') TO ('2028-01-01');
CREATE TABLE IF NOT EXISTS b3_lending_trade_2028 PARTITION OF b3_lending_trade
    FOR VALUES FROM ('2028-01-01') TO ('2029-01-01');
CREATE TABLE IF NOT EXISTS b3_lending_trade_2029 PARTITION OF b3_lending_trade
    FOR VALUES FROM ('2029-01-01') TO ('2030-01-01');
CREATE TABLE IF NOT EXISTS b3_lending_trade_future PARTITION OF b3_lending_trade
    FOR VALUES FROM ('2030-01-01') TO (MAXVALUE);

CREATE INDEX IF NOT EXISTS idx_b3_lending_trade_codneg
    ON b3_lending_trade (codneg, trade_date DESC);
CREATE INDEX IF NOT EXISTS idx_b3_lending_trade_date
    ON b3_lending_trade (trade_date DESC);
-- The question this table exists to answer: what did one broker do.
CREATE INDEX IF NOT EXISTS idx_b3_lending_trade_tomador
    ON b3_lending_trade (tomador_codigo, trade_date DESC);
CREATE INDEX IF NOT EXISTS idx_b3_lending_trade_doador
    ON b3_lending_trade (doador_codigo, trade_date DESC);

COMMENT ON TABLE b3_lending_trade IS
    'Individual B3 securities-lending trades (BTBTrade): ticker, quantity, annualized rate, venue, time, and the brokerage on each leg. doador/tomador are BROKERS intermediating, not beneficial owners — ~75% of trades carry the same code on both legs. ~43k rows/session; same ~21-business-day source retention as the rest of the lending group, and no aggregate preserves the individual trades, so an uncaptured session is unrecoverable.';
