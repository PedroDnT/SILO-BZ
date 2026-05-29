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
-- Idempotent: ADD COLUMN IF NOT EXISTS + DROP CONSTRAINT IF EXISTS before ADD.
-- Recreating a UNIQUE constraint on the partitioned parent propagates to every
-- child partition automatically.
-- =============================================================================

ALTER TABLE cia_account
    ADD COLUMN IF NOT EXISTS coluna_df TEXT;

ALTER TABLE cia_account
    DROP CONSTRAINT IF EXISTS uq_cia_account;

ALTER TABLE cia_account
    ADD CONSTRAINT uq_cia_account UNIQUE NULLS NOT DISTINCT
        (cd_cvm, doc_type, grupo, escopo, dt_refer, ordem_exerc, coluna_df, cd_conta, versao);
