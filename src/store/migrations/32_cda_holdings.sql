-- =============================================================================
-- 32_cda_holdings.sql — fund holdings from CDA blocks 4 (equities) and 2 (fund
-- quotas).
--
-- WHAT WAS MISSING. cvm_fi_cda holds the portfolio AGGREGATED by asset class:
-- one number per (fund, month, tp_aplic, tp_ativo). The monthly CDA archive we
-- already download contains eight blocks; only BLC_1 (títulos públicos) was
-- ever parsed, which is 5.1% of the archive by size. The holdings themselves —
-- what each fund actually owns — were downloaded and discarded on every run.
--
-- WHY THESE TWO BLOCKS. Block 4 carries CD_ATIVO, the B3 ticker, which is the
-- only edge in the warehouse joining the fund universe to the quote tape.
-- Block 2 carries CNPJ_FUNDO_CLASSE_COTA, turning the fund universe into a
-- graph and exposing EMISSOR_LIGADO — the published related-party flag the
-- captive-vehicle screen currently has to infer.
--
-- Blocks 3, 5, 7 and 8 are deliberately not here. Block 8 (Disponibilidades) is
-- 28.9% of the archive for cash balances and a description of "Outros"; block 6
-- (debêntures) has no security identifier and still collides 244 times on a
-- ten-column key, so it needs the row_hash treatment cvm_fii_imovel uses and
-- deserves its own migration rather than being tacked onto this one.
--
-- KEYS ARE AUDITED, NOT ASSUMED. Against the real cda_fi_*_202606.csv files:
--   BLC_4  cnpj+period+cd_ativo                        3,972 collisions
--          cnpj+period+tp_aplic+cd_ativo+tp_negoc      UNIQUE
--   BLC_2  cnpj+period+cnpj_cota                       UNIQUE
-- TP_APLIC is not constant within block 4: the same fund holds the same ticker
-- under six application types with different quantities, and 3,883 colliding
-- groups differ in VL_MERC_POS_FINAL. Dropping it from the key would lose
-- position value on upsert.
--
-- Idempotent: CREATE TABLE IF NOT EXISTS + named UNIQUE constraints, so the
-- daily bootstrap can run this repeatedly.
-- =============================================================================

CREATE TABLE IF NOT EXISTS cvm_fi_cda_acoes (
    id                  BIGSERIAL   PRIMARY KEY,
    cnpj                TEXT        NOT NULL CHECK (char_length(cnpj) = 14),
    period              DATE        NOT NULL,   -- first day of month
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

-- NULLS NOT DISTINCT: cd_ativo and tp_negoc are empty on a minority of rows,
-- and without it Postgres would treat every such row as distinct and let
-- duplicates through the constraint the audit exists to enforce.
CREATE UNIQUE INDEX IF NOT EXISTS uq_fi_cda_acoes
    ON cvm_fi_cda_acoes (cnpj, period, tp_aplic, cd_ativo, tp_negoc)
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
    tp_aplic            TEXT,
    tp_ativo            TEXT,
    emissor_ligado      TEXT,                   -- 'S' = same economic group
    qt_pos_final        NUMERIC(28,6),
    vl_merc_pos_final   NUMERIC(20,2),
    vl_custo_pos_final  NUMERIC(20,2),
    qt_aquis_negoc      NUMERIC(28,6),
    vl_aquis_negoc      NUMERIC(20,2),
    qt_venda_negoc      NUMERIC(28,6),
    vl_venda_negoc      NUMERIC(20,2),
    raw                 JSONB       NOT NULL,
    fetched_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fi_cda_cotas UNIQUE (cnpj, period, cnpj_cota)
);

-- The reverse edge: who holds this fund.
CREATE INDEX IF NOT EXISTS idx_fi_cda_cotas_held
    ON cvm_fi_cda_cotas (cnpj_cota, period DESC);

COMMENT ON TABLE cvm_fi_cda_cotas IS
    'FI fund-of-fund holdings, CDA block 2. One row per (holder fund, month, held fund). emissor_ligado is CVM''s published related-party flag, not an inference.';
