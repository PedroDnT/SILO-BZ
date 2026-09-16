-- 38_fidc_concentration.sql — FIDC tabs I, II, VIII and X: who the fund buys
-- from, what sector it holds, who owes it, and how BACEN grades that.
--
-- WHAT THIS ADDS. The monthly FIDC ZIP has 18 members and the pipeline read six
-- (IV, VI, X_2, X_3, X_4, X_6). Four more carry the concentration and credit-
-- quality content this warehouse exists for:
--
--   tab_I    named cedentes — TAB_I2{A,B}12_CPF_CNPJ_CEDENTE_1..9 and their
--            share of the block. Real identifiers: on 2026-07, 1,368 funds file
--            a block-A cedente and 794 a block-B one (Caterpillar FIDC →
--            61064911000177 at 72.41%). Unpivoted into cvm_fidc_cedente.
--   tab_II   receivables portfolio by sector, plus TAB_II_VL_CARTEIRA, the
--            portfolio total. cvm_fidc_setor, wide.
--   tab_VIII the 25 largest sacados, anonymized: SEQUENCIAL 1..25 and VALOR.
--            cvm_fidc_sacado, one row per rank.
--   tab_X    the BACEN SCR grade ladder AA..H, by debtor and by operation.
--            cvm_fidc_scr, wide.
--
-- MEASURED, on the published files (every HIST archive 2013-2024 opened,
-- member by member, plus the 2025-2026 monthly ZIPs):
--   * The archive boundary (HIST ≤2024 / monthly 2025+) changes no header:
--     2024-12 and 2026-07 are identical column-for-column on all four tabs.
--     The headers DO change inside the HIST range, at three points:
--       tab_II   key column is CNPJ_FUNDO through 2019, CNPJ_FUNDO_CLASSE
--                after; the 33 value columns are the same from 2013-01.
--       tab_VIII six columns from 2013-01, unchanged.
--       tab_I    the 36 cedente slots TAB_I2{A,B}12_* exist from 2019-11.
--                2013-01..2019-10 is a 67-column form with a single
--                TAB_I2B1_CPF_CNPJ_CEDENTE_1..9 block whose values are
--                placeholders (99999999999999, 0) and whose block meaning
--                is not the A/B split; not ingested into this table.
--       tab_X    the member does not exist before 2023-10.
--     The backfill asks for each tab only from its first month
--     (_FIDC_TAB_FIRST_PERIOD in cvm_pipeline.py).
--   * Cedente identifiers are validated, not trusted: the slots carry
--     placeholders (2019-11: 13,827 of 14,587 filled slots are 0 or all-nine;
--     2024-12: 1,439 all-zero and 1,520 all-nine of 5,224; 2026-07: one slot
--     left, which matches the CVM-side "travas contra CNPJs inválidos" Uqbar
--     reported) and identifiers with a dropped leading zero (2026-07: 37
--     thirteen-digit, 2 twelve-digit, e.g. 6084614000185 → 06084614000185).
--     A placeholder is dropped and counted (ingest_fidc_cedente logs it).
--   * pr_cedente is stored AS FILED, like the tranche percentage fields: 9.1%
--     of 2026-07 slots are above 100 (max 19,771; 20,076,780 in 2024-12). The
--     identifier is the edge and stays; the share is range-checked by readers
--     (the dashboard reads [0,100] and prints what it set aside).
--     A short identifier is kept only when zero-padding it yields a CNPJ (or,
--     for ≤11 digits, a CPF) whose check digits verify — a recovered
--     formatting loss, not a guess; anything else is dropped and counted.
--   * tab_VIII is NOT a 2026 addition: same six columns, same rank ceiling of
--     25, in 2019, 2022, 2024, 2025 and 2026. What CVM's dictionary
--     (META/meta_inf_mensal_fidc_tab_VIII.txt) ships for VALOR and SEQUENCIAL is
--     a blank description. The shape (ceiling exactly 25, values descending on
--     2,978 of 3,043 funds in 2026-07, no debtor identifier) is the reading.
--   * cvm_fidc_mensal.vl_total was NULL on every 2025+ row: tab_IV ships six
--     columns and the portfolio total is not one of them. TAB_II_VL_CARTEIRA is
--     populated on 3,269 of 4,382 rows and is the same column the HIST path
--     already reads, so ingest_fidc_mensal now merges it in the way it merges
--     tab_VI. No schema change on cvm_fidc_mensal.
--
-- UNIQUE-KEY AUDIT (2026-07 files): tab_II and tab_X — zero duplicates on
-- (CNPJ_FUNDO_CLASSE, DT_COMPTC), 4,382 rows each; tab_VIII — zero duplicates on
-- (CNPJ_FUNDO_CLASSE, DT_COMPTC, SEQUENCIAL), 41,225 rows; tab_I — zero
-- duplicates on (CNPJ_FUNDO_CLASSE, DT_COMPTC), and the unpivot key adds the
-- source's own (block, slot).
--
-- STORED AS FILED. seq is CVM's rank, never recomputed from valor; the 65 funds
-- whose values are not monotonic stay as filed; a tab_I slot with a blank
-- identifier is not emitted. cpf_cnpj_cedente has no 14-digit CHECK because the
-- source column is CPF_CNPJ and 36 first slots in 2026-07 hold an 11-digit CPF.
--
-- These tables are new in this migration; no upgrade path.

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
