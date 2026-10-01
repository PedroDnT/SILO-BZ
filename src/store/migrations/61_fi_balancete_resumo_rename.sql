-- Migration 61: cvm_fi_balancete_resumo.vl_patrim_liq -> vl_patrimonio_sem_resultado.
--
-- WHY. The column holds COFI group 6 (60000002), which excludes the result of
-- the open fiscal year. Group 6 + revenue + expenses is the NAV; group 6 alone
-- runs about 5% below cvm_fi_diario.vl_patrim_liq at the median (2026-06-30).
-- Sharing that column's name invited the comparison. Renamed before any reader
-- or api function used it. Conditional, so it is a no-op on a database built
-- from schema.sql, which already has the new name.

BEGIN;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'cvm_fi_balancete_resumo'
          AND column_name = 'vl_patrim_liq'
    ) THEN
        ALTER TABLE cvm_fi_balancete_resumo
            RENAME COLUMN vl_patrim_liq TO vl_patrimonio_sem_resultado;
    END IF;
END $$;

COMMENT ON TABLE cvm_fi_balancete_resumo IS
    'FI balancete group totals and administrative-expense accounts (fees), one row per fund and month, as filed (COFI codes in migration 59). Revenue, expenses and every fee column accumulate from each fund''s own fiscal-year start; vl_patrimonio_sem_resultado excludes that open result, and it plus vl_receitas plus vl_despesas is the NAV. An account not filed is NULL. n_contas is the number of accounts the fund filed that month.';

COMMIT;
