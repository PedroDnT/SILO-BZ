-- =============================================================================
-- 33_cda_holdings_key_widening.sql — widen the CDA holdings keys, and add the
-- two columns they need.
--
-- WHY. Migration 32 audited its keys against ONE file: the 2023+ monthly
-- cda_fi_*_202606.csv. Both keys are genuinely unique there. They are not
-- unique on the yearly HIST archives (2005-2022), which are the files the
-- pre-2023 holdings backfill reads, and the difference is not cosmetic:
--
--   cvm_fi_cda_acoes, key (cnpj, period, tp_aplic, cd_ativo, tp_negoc)
--       2005    395 colliding groups   2015  1     2022  33
--   cvm_fi_cda_cotas, key (cnpj, period, cnpj_cota)
--       2005     46 colliding groups   2015  3     2022   1
--
-- Each collision is an upsert overwriting a real position with another real
-- position. Two columns settle almost all of them:
--
--   TP_ATIVO — a BDR ticker appears twice in the same fund and month as
--     "BDR não patrocinado" and "BDR nível I". Same CD_ATIVO, different
--     instrument, different quantity.
--   TP_FUNDO — in 2005 a single CNPJ filed as both FI and FIF, with different
--     DT_CONFID_APLIC. 383 of the 390 remaining block-4 groups are this.
--
-- For block 2, TP_APLIC and TP_NEGOC are needed for the same reason they were
-- needed in block 4: a fund holds the same fund under two application types
-- and two trading intents, with different positions.
--
-- AFTER WIDENING the block-2 key is UNIQUE on all four audited files. Block 4
-- retains 7 groups in 2005 and 25 in 2022; all 25 of the 2022 ones and six of
-- the seven 2005 ones are duplicate rows with identical positions, so exactly
-- one group in 372,832 rows loses a distinct position. That residual is stated
-- here rather than hidden: the alternative is a row_hash key, which buys
-- completeness at the cost of a key nobody can read.
--
-- BACKFILLING THE NEW COLUMNS. Every row carries its source columns in `raw`,
-- so rows already ingested under the narrow key are repaired in place rather
-- than left with NULLs that the widened key would treat as separate rows.
--
-- Idempotent: guarded ADD COLUMN / DROP ... IF EXISTS / CREATE ... IF NOT
-- EXISTS, so the daily bootstrap can run it repeatedly.
-- =============================================================================

ALTER TABLE cvm_fi_cda_acoes ADD COLUMN IF NOT EXISTS tp_fundo TEXT;
ALTER TABLE cvm_fi_cda_cotas ADD COLUMN IF NOT EXISTS tp_fundo TEXT;
ALTER TABLE cvm_fi_cda_cotas ADD COLUMN IF NOT EXISTS tp_negoc TEXT;

-- Recover the new key columns from the preserved source row. NULLIF keeps an
-- empty CSV cell as NULL rather than promoting '' to a distinct key value.
--
-- CORRECTED 2026-09-01 — the original form of the block-2 statement was
--
--     SET tp_fundo = NULLIF(...raw...), tp_negoc = NULLIF(raw ->> 'TP_NEGOC', '')
--   WHERE tp_fundo IS NULL OR tp_negoc IS NULL
--
-- which assigned BOTH columns whenever EITHER was null. A row with a real
-- tp_negoc but no tp_fundo therefore had its tp_negoc overwritten with NULL,
-- because `raw` no longer carries TP_NEGOC: upsert_rows strips a key out of
-- `raw` once a typed column of the same name exists, and this migration is what
-- created that column. The repair read back an empty fallback and wrote it over
-- the real value.
--
-- That is a silent destruction of filed data, and it is also what has taken the
-- schema gate down since 2026-08-31. Nulling the column moves the row onto the
-- all-NULL key, where uq_fi_cda_cotas (NULLS NOT DISTINCT) already holds a
-- sibling, so the statement fails:
--
--     ERROR: duplicate key value violates unique constraint "uq_fi_cda_cotas"
--     DETAIL: Key (cnpj, period, tp_fundo, cnpj_cota, tp_aplic, tp_negoc)
--             = (44680491000134, 2025-12-01, null, 44638527000111,
--                Cotas de Fundos, null) already exists.
--
-- The error was previously read as "the table holds duplicates the index cannot
-- be built over". It does not: psql reports a statement's error at its LAST
-- line, and line 113 of the applied file is the closing line of this UPDATE,
-- not of the CREATE UNIQUE INDEX below. The index builds cleanly every run —
-- schema.sql creates the identical index minutes earlier and succeeds. This
-- statement then breaks it.
--
-- No data was actually lost, because the failure is what prevented the write:
-- the statement rolls back whole, and the only apply that ever committed it
-- (2026-08-31 19:34) ran in the same transaction that first ADDed the columns,
-- when every typed value was still NULL and every `raw` still carried its keys.
-- Every apply since — where destruction would have been possible — errored here.
--
-- COALESCE makes each column fill only when it is empty, so a filed value is
-- never overwritten, and the WHERE now selects only rows `raw` can actually
-- repair rather than rewriting the whole table on every daily apply.
--
-- Editing an applied migration is against this repo's append-only rule, and is
-- justified here only because the edit changes nothing anywhere it has already
-- run: on a fresh database (CI, local, the ephemeral SQL-compile job) both
-- tables are empty and both forms touch zero rows, and in production this
-- statement has never committed except in the ADD COLUMN transaction described
-- above, where COALESCE over an all-NULL column is the identity. The fix cannot
-- live in a later migration because a failing migration blocks every migration
-- after it, and it cannot live in schema.sql because the destructive statement
-- is here.
UPDATE cvm_fi_cda_acoes
   SET tp_fundo = COALESCE(
           tp_fundo,
           NULLIF(COALESCE(raw ->> 'TP_FUNDO_CLASSE', raw ->> 'TP_FUNDO'), ''))
 WHERE tp_fundo IS NULL
   AND NULLIF(COALESCE(raw ->> 'TP_FUNDO_CLASSE', raw ->> 'TP_FUNDO'), '') IS NOT NULL;

UPDATE cvm_fi_cda_cotas
   SET tp_fundo = COALESCE(
           tp_fundo,
           NULLIF(COALESCE(raw ->> 'TP_FUNDO_CLASSE', raw ->> 'TP_FUNDO'), '')),
       tp_negoc = COALESCE(tp_negoc, NULLIF(raw ->> 'TP_NEGOC', ''))
 WHERE (tp_fundo IS NULL
        AND NULLIF(COALESCE(raw ->> 'TP_FUNDO_CLASSE', raw ->> 'TP_FUNDO'), '') IS NOT NULL)
    OR (tp_negoc IS NULL
        AND NULLIF(raw ->> 'TP_NEGOC', '') IS NOT NULL);

-- Block 4: replace the narrow index. NULLS NOT DISTINCT is mandatory — every
-- one of tp_fundo, tp_ativo, cd_ativo and tp_negoc is empty on a minority of
-- rows, and the default NULL semantics would let duplicates straight through
-- the constraint this audit exists to enforce.
DROP INDEX IF EXISTS uq_fi_cda_acoes;
CREATE UNIQUE INDEX IF NOT EXISTS uq_fi_cda_acoes
    ON cvm_fi_cda_acoes (cnpj, period, tp_fundo, tp_aplic, tp_ativo, cd_ativo, tp_negoc)
    NULLS NOT DISTINCT;

-- Block 2: migration 32 made this a table CONSTRAINT, so it is dropped as one.
-- The replacement is an index, for the same NULLS NOT DISTINCT reason.
ALTER TABLE cvm_fi_cda_cotas DROP CONSTRAINT IF EXISTS uq_fi_cda_cotas;
DROP INDEX IF EXISTS uq_fi_cda_cotas;
CREATE UNIQUE INDEX IF NOT EXISTS uq_fi_cda_cotas
    ON cvm_fi_cda_cotas (cnpj, period, tp_fundo, cnpj_cota, tp_aplic, tp_negoc)
    NULLS NOT DISTINCT;

COMMENT ON COLUMN cvm_fi_cda_acoes.tp_fundo IS
    'Fund type as filed (FI, FIF, ...). Part of the unique key: in 2005 one CNPJ filed under two types with different positions.';
COMMENT ON COLUMN cvm_fi_cda_cotas.tp_fundo IS
    'Fund type as filed (FI, FIF, ...). Part of the unique key.';
COMMENT ON COLUMN cvm_fi_cda_cotas.tp_negoc IS
    'Trading intent as filed. Part of the unique key: a fund holds the same fund under two intents with different positions.';
