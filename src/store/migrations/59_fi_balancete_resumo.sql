-- Migration 59: one row per fund and month from the FI balancete.
--
-- WHY. cvm_fi_balancete holds every COFI account every fund files, about
-- 2.2M rows a month since 2019 (31 GB with its key, the largest table in the
-- database), and no page or api function reads it. Its value is the
-- balance-sheet and income totals, which fit in one row per fund and month.
-- This table holds those totals; the account-level table is retired later,
-- once the summary is backfilled and checked month by month
-- (docs/planning/OPEN_ITEMS.md item 10).
--
-- WHAT THE CODES ARE. Checked on 2026-06-30 against all 25,434 funds that
-- filed, and present for every fund on 2019-06-30:
--
--   10000007  group 1  assets
--   30000001  group 3  memorandum accounts, debit side
--   40000008  group 4  liabilities
--   60000002  group 6  equity, excluding the result of the open fiscal year
--   70000009  group 7  revenue, accumulated since the fund's fiscal-year start
--   80000006  group 8  expenses, same accumulation, filed as negative values
--   90000003  group 9  memorandum accounts, credit side
--
-- Identities that held for every fund on 2026-06-30:
--   group 1 = group 4 + group 6 + group 7 + group 8        (25,061 of 25,061
--             funds with a daily NAV that day)
--   group 3 = group 9
--   39999993 = group 1 + group 3;  99999995 = groups 4 + 6 + 7 + 8 + 9
-- And group 6 + group 7 + group 8 equals the same day's vl_patrim_liq in
-- cvm_fi_diario within 0.1% for 24,408 of those 25,061 funds.
--
-- Groups 7 and 8 restart at each fund's own fiscal-year start, which is not
-- January for every fund. They are stored as filed. A month's flow is derived
-- in the analytical layer, never here.
--
-- A group a fund did not file is NULL, never zero.

BEGIN;

CREATE TABLE IF NOT EXISTS cvm_fi_balancete_resumo (
    cnpj                   TEXT          NOT NULL CHECK (char_length(cnpj) = 14),
    dt_comptc              DATE          NOT NULL,
    tp_fundo_classe        TEXT,
    plano_conta_balcte     TEXT,
    vl_ativo               NUMERIC(28,2),   -- 10000007
    vl_compensacao_ativa   NUMERIC(28,2),   -- 30000001
    vl_passivo             NUMERIC(28,2),   -- 40000008
    vl_patrim_liq          NUMERIC(28,2),   -- 60000002
    vl_receitas            NUMERIC(28,2),   -- 70000009, accumulated
    vl_despesas            NUMERIC(28,2),   -- 80000006, accumulated, negative
    vl_compensacao_passiva NUMERIC(28,2),   -- 90000003
    n_contas               INTEGER       NOT NULL CHECK (n_contas > 0),
    fetched_at             TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fi_balancete_resumo UNIQUE (cnpj, dt_comptc)
);

CREATE INDEX IF NOT EXISTS ix_fi_balancete_resumo_date
    ON cvm_fi_balancete_resumo (dt_comptc);

-- Landing tables carry no client grant (12_grants_and_rls.sql).
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon')
       AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        EXECUTE 'REVOKE ALL ON cvm_fi_balancete_resumo FROM anon, authenticated';
    END IF;
END $$;

COMMENT ON TABLE cvm_fi_balancete_resumo IS
    'FI balancete group totals, one row per fund and month, as filed (COFI codes in migration 59). vl_receitas and vl_despesas accumulate from each fund''s own fiscal-year start; vl_patrim_liq excludes that open result. n_contas is the number of accounts the fund filed that month.';

COMMIT;
