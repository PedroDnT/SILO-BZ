-- 35_cda_debentures.sql — CDA block 6: fund -> corporate credit.
--
-- WHAT THIS ADDS. Blocks 4 and 2 gave the fund->equity and fund->fund edges.
-- Block 6 is the third: which company's debt a fund holds, at what maturity,
-- indexed to what, at what spread. CPF_CNPJ_EMISSOR is the issuer's own CNPJ, so
-- it joins straight to the cia_* listed-company universe. The CSV is a member of
-- the same archive `cda` already downloads, so it costs no extra fetch.
--
-- UNIQUE-KEY AUDIT, measured on the real published files of both eras
-- (cda_fi_BLC_6_2015.csv, 253,563 rows; cda_fi_BLC_6_202606.csv, 3,279 rows):
--
--     key                                  2015 unique      202606 unique
--     cnpj+period                          27,076 (89.3% lost)   624 (81.0%)
--     + tp_fundo                           27,076 (89.3%)        624 (81.0%)
--     + tp_aplic + tp_ativo                28,991 (88.6%)        810 (75.3%)
--     + cpf_cnpj_emissor                  188,634 (25.6%)      1,812 (44.7%)
--     + dt_venc                           213,406 (15.8%)      2,982 ( 9.1%)
--     + tp_negoc                          213,441 (15.8%)      2,984 ( 9.0%)
--     + row_hash          (shipped)       253,563 ( 0.0%)      3,279 ( 0.0%)
--
-- WHY row_hash. Block 4 has CD_ATIVO, one published column naming the
-- instrument. A debenture has none. What remains after (issuer, maturity) is a
-- second series of the same issuer maturing the same day at a different coupon:
-- the residual groups separate on PR_CUPOM_POSFX (16,910 groups in 2015),
-- CD_INDEXADOR_POSFX (761) and PR_TAXA_PREFX (432). Those are different
-- securities holding different money. Stopping the key at tp_negoc would discard
-- 15.8% of every historical file — the same failure blocks 4, 2 and FIP were
-- each fixed for.
--
-- Putting the four rate columns in the key instead also reaches 0% loss, but it
-- makes four nullable NUMERICs load-bearing for identity and a key ending in a
-- coupon rate cannot serve a range scan. row_hash goes LAST, after a natural key
-- that still supports (fund, period) and (issuer, period) lookups.
--
-- row_hash is safe here in the way that matters: full-row uniqueness equals row
-- count in both files, so no two source rows are byte-identical and the digest
-- never silently merges two real positions.
--
-- This table is new in this migration, so there is no upgrade path to recover
-- from and no narrower index to drop first.

CREATE TABLE IF NOT EXISTS cvm_fi_cda_debentures (
    id                  BIGSERIAL   PRIMARY KEY,
    cnpj                TEXT        NOT NULL CHECK (char_length(cnpj) = 14),
    period              DATE        NOT NULL,
    tp_fundo            TEXT,
    denom_social        TEXT,
    tp_aplic            TEXT,
    tp_ativo            TEXT,
    tp_negoc            TEXT,
    emissor_ligado      TEXT,
    -- No 14-digit CHECK: PF_PJ_EMISSOR says this may hold a CPF, and a CNPJ
    -- constraint would reject a real filing.
    pf_pj_emissor       TEXT,
    cpf_cnpj_emissor    TEXT,
    emissor             TEXT,
    dt_venc             DATE,
    titulo_posfx        TEXT,
    cd_indexador_posfx  TEXT,
    ds_indexador_posfx  TEXT,
    pr_indexador_posfx  NUMERIC(20,6),
    pr_cupom_posfx      NUMERIC(20,6),
    pr_taxa_prefx       NUMERIC(20,6),
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

CREATE INDEX IF NOT EXISTS idx_fi_cda_deb_emissor
    ON cvm_fi_cda_debentures (cpf_cnpj_emissor, period DESC);
CREATE INDEX IF NOT EXISTS idx_fi_cda_deb_fund
    ON cvm_fi_cda_debentures (cnpj, period DESC);

COMMENT ON TABLE cvm_fi_cda_debentures IS
    'FI debenture holdings, CDA block 6. One row per (fund, month, issuer, maturity, series). cpf_cnpj_emissor is the issuer''s own CPF/CNPJ, so this is the join between the fund universe and the corporate-credit issuer. Values are as filed; no adjustment applied.';
