-- =============================================================================
-- Migration 05 — cia_account.coluna_df (W7 DMPL fix)
--
-- The DMPL statement members (Demonstração das Mutações do Patrimônio Líquido)
-- carry an extra CSV column, COLUNA_DF, that the other statement types do not:
-- the same (cd_conta) line appears once per equity component column, e.g.
-- "Capital Social Integralizado", "Reservas de Lucro", "Lucros/Prejuízos
-- Acumulados", "Patrimônio Líquido". COLUNA_DF is therefore part of a DMPL
-- row's natural key.
--
-- The W5 uq_cia_account key did NOT include it, so DMPL rows collapsed ~85%
-- under last-wins upsert dedup (observed: 239k -> 29k on dfp_2023 DMPL_con).
-- This migration adds the column and folds it into the unique key so DMPL rows
-- are preserved. For all non-DMPL members COLUNA_DF is NULL; with
-- NULLS NOT DISTINCT those NULLs collapse to a single value, so their existing
-- uniqueness behaviour is unchanged.
--
-- Idempotent: ADD COLUMN IF NOT EXISTS, and the UNIQUE key is rebuilt only when
-- the existing uq_cia_account does NOT already include coluna_df. Rebuilding a
-- UNIQUE constraint on the partitioned parent validates every child partition
-- (full scan + ACCESS EXCLUSIVE lock), so the guard makes replays (e.g. repeated
-- backfill dispatches) a no-op once the new key is in place.
-- =============================================================================

ALTER TABLE cia_account
    ADD COLUMN IF NOT EXISTS coluna_df TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'cia_account'::regclass
          AND conname  = 'uq_cia_account'
          AND pg_get_constraintdef(oid) ILIKE '%coluna_df%'
    ) THEN
        ALTER TABLE cia_account DROP CONSTRAINT IF EXISTS uq_cia_account;
        ALTER TABLE cia_account ADD CONSTRAINT uq_cia_account UNIQUE NULLS NOT DISTINCT
            (cd_cvm, doc_type, grupo, escopo, dt_refer, ordem_exerc, coluna_df, cd_conta, versao);
    END IF;
END $$;
