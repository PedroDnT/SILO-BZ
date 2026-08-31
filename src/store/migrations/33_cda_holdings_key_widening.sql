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
-- REPLAY ON A LIVE TABLE (Backfill #24, run 33449184287). schema.sql runs
-- FIRST and already installs the widened unique index. This file used to
-- UPDATE, then DROP/CREATE that index. The UPDATE was:
--
--     SET tp_fundo = NULLIF(raw->>'TP_FUNDO', ''),
--         tp_negoc = NULLIF(raw->>'TP_NEGOC', '')
--     WHERE tp_fundo IS NULL OR tp_negoc IS NULL
--
-- `_strip_raw_duplicates` has already removed typed keys from `raw`, so a
-- row with tp_fundo='FI' and tp_negoc NULL was reset to (NULL, NULL) and
-- collided with a sibling that was already (NULL, NULL) under
-- NULLS NOT DISTINCT:
--
--     ERROR:  duplicate key value violates unique constraint "uq_fi_cda_cotas"
--     DETAIL: Key (..., tp_fundo, ..., tp_negoc)=(32300050000180, 2023-10-01,
--             null, 43809974000123, Cotas de Fundos, null) already exists.
--
-- COALESCE never overwrites a typed value. NOT EXISTS skips a fill that
-- would land on a key another row already holds (a narrow-key remnant next
-- to a later wide-key ingest of the same position). The unique index is
-- dropped BEFORE the backfill — the original intent of this file, before
-- schema.sql started creating the wide index first — and recreated after.
--
-- Idempotent: guarded ADD COLUMN / DROP ... IF EXISTS / CREATE ... IF NOT
-- EXISTS, so the daily bootstrap can run it repeatedly.
-- =============================================================================

ALTER TABLE cvm_fi_cda_acoes ADD COLUMN IF NOT EXISTS tp_fundo TEXT;
ALTER TABLE cvm_fi_cda_cotas ADD COLUMN IF NOT EXISTS tp_fundo TEXT;
ALTER TABLE cvm_fi_cda_cotas ADD COLUMN IF NOT EXISTS tp_negoc TEXT;

-- schema.sql may already have installed the widened unique index. Drop it
-- before the backfill so a fill cannot fail mid-UPDATE; recreate after.
DROP INDEX IF EXISTS uq_fi_cda_acoes;
ALTER TABLE cvm_fi_cda_cotas DROP CONSTRAINT IF EXISTS uq_fi_cda_cotas;
DROP INDEX IF EXISTS uq_fi_cda_cotas;

-- Recover the new key columns from the preserved source row. NULLIF keeps an
-- empty CSV cell as NULL rather than promoting '' to a distinct key value.
-- COALESCE: never overwrite a value the current field map already stored.
UPDATE cvm_fi_cda_acoes AS t
   SET tp_fundo = COALESCE(
           t.tp_fundo,
           NULLIF(COALESCE(t.raw ->> 'TP_FUNDO_CLASSE', t.raw ->> 'TP_FUNDO'), '')
       )
 WHERE t.tp_fundo IS NULL
   AND NOT EXISTS (
        SELECT 1
          FROM cvm_fi_cda_acoes AS o
         WHERE o.id IS DISTINCT FROM t.id
           AND o.cnpj = t.cnpj
           AND o.period = t.period
           AND o.tp_aplic IS NOT DISTINCT FROM t.tp_aplic
           AND o.tp_ativo IS NOT DISTINCT FROM t.tp_ativo
           AND o.cd_ativo IS NOT DISTINCT FROM t.cd_ativo
           AND o.tp_negoc IS NOT DISTINCT FROM t.tp_negoc
           AND o.tp_fundo IS NOT DISTINCT FROM COALESCE(
                   t.tp_fundo,
                   NULLIF(COALESCE(t.raw ->> 'TP_FUNDO_CLASSE', t.raw ->> 'TP_FUNDO'), '')
               )
   );

UPDATE cvm_fi_cda_cotas AS t
   SET tp_fundo = COALESCE(
           t.tp_fundo,
           NULLIF(COALESCE(t.raw ->> 'TP_FUNDO_CLASSE', t.raw ->> 'TP_FUNDO'), '')
       ),
       tp_negoc = COALESCE(
           t.tp_negoc,
           NULLIF(t.raw ->> 'TP_NEGOC', '')
       )
 WHERE (t.tp_fundo IS NULL OR t.tp_negoc IS NULL)
   AND NOT EXISTS (
        SELECT 1
          FROM cvm_fi_cda_cotas AS o
         WHERE o.id IS DISTINCT FROM t.id
           AND o.cnpj = t.cnpj
           AND o.period = t.period
           AND o.cnpj_cota = t.cnpj_cota
           AND o.tp_aplic IS NOT DISTINCT FROM t.tp_aplic
           AND o.tp_fundo IS NOT DISTINCT FROM COALESCE(
                   t.tp_fundo,
                   NULLIF(COALESCE(t.raw ->> 'TP_FUNDO_CLASSE', t.raw ->> 'TP_FUNDO'), '')
               )
           AND o.tp_negoc IS NOT DISTINCT FROM COALESCE(
                   t.tp_negoc,
                   NULLIF(t.raw ->> 'TP_NEGOC', '')
               )
   );

-- Block 4: replace the narrow index. NULLS NOT DISTINCT is mandatory — every
-- one of tp_fundo, tp_ativo, cd_ativo and tp_negoc is empty on a minority of
-- rows, and the default NULL semantics would let duplicates straight through
-- the constraint this audit exists to enforce.
CREATE UNIQUE INDEX IF NOT EXISTS uq_fi_cda_acoes
    ON cvm_fi_cda_acoes (cnpj, period, tp_fundo, tp_aplic, tp_ativo, cd_ativo, tp_negoc)
    NULLS NOT DISTINCT;

-- Block 2: migration 32 made this a table CONSTRAINT, so it is dropped as one
-- (above). The replacement is an index, for the same NULLS NOT DISTINCT reason.
CREATE UNIQUE INDEX IF NOT EXISTS uq_fi_cda_cotas
    ON cvm_fi_cda_cotas (cnpj, period, tp_fundo, cnpj_cota, tp_aplic, tp_negoc)
    NULLS NOT DISTINCT;

COMMENT ON COLUMN cvm_fi_cda_acoes.tp_fundo IS
    'Fund type as filed (FI, FIF, ...). Part of the unique key: in 2005 one CNPJ filed under two types with different positions.';
COMMENT ON COLUMN cvm_fi_cda_cotas.tp_fundo IS
    'Fund type as filed (FI, FIF, ...). Part of the unique key.';
COMMENT ON COLUMN cvm_fi_cda_cotas.tp_negoc IS
    'Trading intent as filed. Part of the unique key: a fund holds the same fund under two intents with different positions.';
