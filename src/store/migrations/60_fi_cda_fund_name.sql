-- Migration 60: the fund name CVM files with each CDA row, kept once per fund
-- and month instead of on every holding.
--
-- WHY. CVM repeats DENOM_SOCIAL, the filing fund's name, on every row of the
-- CDA blocks. The ingest kept it inside `raw` on cvm_fi_cda (block 1),
-- cvm_fi_cda_acoes (block 4) and cvm_fi_cda_cotas (block 2), where it was most
-- of the column. Sampled read-only on 2026-10-01: removing it shrinks `raw` by
-- 89 bytes a row on acoes (188 -> 99), 99 on cotas (136 -> 37) and 85 on
-- block 1 (307 -> 222), about 4.8 GB over the three tables' ~52M rows.
-- Block 6 (cvm_fi_cda_debentures) maps the name to a typed column and is not
-- touched.
--
-- A 1% page sample of each table found no fund-month with two names and none
-- without one. The key still carries the name, so if CVM ever files two names
-- for one fund-month both are kept; nothing is overwritten.
--
-- The ingest writes here and no longer puts DENOM_SOCIAL in `raw`. Rows already
-- stored are moved by scripts/strip_cda_fund_name.py, which copies the names
-- here before removing them from `raw`.

BEGIN;

CREATE TABLE IF NOT EXISTS cvm_fi_cda_fund_name (
    cnpj          TEXT        NOT NULL CHECK (char_length(cnpj) = 14),
    period        DATE        NOT NULL,   -- first day of month, as the CDA tables
    denom_social  TEXT        NOT NULL,   -- DENOM_SOCIAL, as filed
    fetched_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fi_cda_fund_name UNIQUE (cnpj, period, denom_social)
);

-- Landing tables carry no client grant (12_grants_and_rls.sql).
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon')
       AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        EXECUTE 'REVOKE ALL ON cvm_fi_cda_fund_name FROM anon, authenticated';
    END IF;
END $$;

COMMENT ON TABLE cvm_fi_cda_fund_name IS
    'DENOM_SOCIAL as CVM filed it in the CDA blocks 1, 2 and 4, one row per fund, month and name (migration 60). Replaces the copy that sat in raw on every holding row.';

COMMIT;
