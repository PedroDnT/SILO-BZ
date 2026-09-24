-- 45_fidc_collateral.sql — FIDC tab_X_7: guarantees on the fund's credit rights.
--
-- WHAT THIS ADDS. The monthly FIDC ZIP has 18 members; migration 38 brought
-- the pipeline to ten. tab_X_7 is the eleventh: per (fund, month), the value
-- of guarantees on the credit rights (TAB_X_VL_GARANTIA_DIRCRED) and a
-- percentage (TAB_X_PR_GARANTIA_DIRCRED). cvm_fidc_garantia, wide, the shape of
-- cvm_fidc_scr.
--
-- MEASURED, on the published files (every HIST archive 2013-2024 opened
-- member by member, plus every monthly ZIP 2025-01..2026-08; 82 months,
-- 188,476 rows):
--   * The member exists from 2019-11. 2013-01..2019-10 ship tab_X_1..X_6 and
--     no tab_X_7. _FIDC_TAB_FIRST_PERIOD["x7"] bounds the backfill there.
--   * Two headers: CNPJ_FUNDO (5 columns) through 2020-10, then
--     TP_FUNDO_CLASSE + CNPJ_FUNDO_CLASSE (6 columns) from 2020-11. The HIST /
--     monthly boundary at 2025-01 changes nothing. The two value columns are
--     the same throughout.
--   * CVM's dictionary (META/meta_inf_mensal_fidc_tab_X_7.txt) gives both value
--     columns a BLANK description, numeric(17,2). The percentage's denominator
--     is not stated and does not reconcile to one sibling total (VL / (PR/100)
--     is within 2% of tab_II TAB_II_VL_CARTEIRA for 6 of 28 filers in 2026-08,
--     19 of 42 in 2025-12). Stored as filed, never recomputed.
--   * Most funds file zeros: 28 of 4,383 rows in 2026-08 have VL > 0; 3,985 of
--     188,476 over the whole history. 9 rows (2022) leave both values blank and
--     are kept with NULLs. 51 rows file PR > 100 (max 562,714,580.15, 2020-12)
--     and are kept as filed. 4 rows file a negative value (2021-10, 2023-07,
--     2026-02, 2026-07); ingest_fidc_garantia drops and counts them.
--   * Every fund CNPJ is 14 digits with valid check digits; every DT_COMPTC
--     parses and falls in the file's own month.
--
-- UNIQUE-KEY AUDIT (all 188,476 rows):
--   (cnpj, period)                    211 duplicate rows (0.11%), in 24 months
--   (cnpj, period, tp_fundo_classe)     1 duplicate row
-- Every one of the 211 repeats the same VL and PR. 210 are a 'Fundo' and a
-- 'Classe' line for the same CNPJ (the CVM-175 adaptation); 1 is a
-- byte-identical line (37.606.580/0001-75, 2025-09). The third key would keep
-- the same fund twice and still collide, so the key is (cnpj, period), as on
-- cvm_fidc_setor / cvm_fidc_scr; upsert_rows collapses the repeats, losing no
-- value. TP_FUNDO_CLASSE and DENOM_SOCIAL stay in `raw`.
--
-- New table; no upgrade path. Landing table: no client grant
-- (12_grants_and_rls.sql revokes it by name and by the cvm_ prefix sweep).

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
