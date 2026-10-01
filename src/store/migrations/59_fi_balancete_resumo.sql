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
-- EXPENSE ACCOUNTS. From the COFI chart of accounts (Instrução CVM 438,
-- consolidated text, section "Elenco de Contas"; code 8.1.7.81.00-1 is stored
-- as 81781001). All are inside group 8, accumulated and negative like it:
--
--   81700006  8.1.7.00.00-6  despesas administrativas (all of the below)
--   81754007  8.1.7.54.00-7  despesas de serviços do sistema financeiro
--   81763005  8.1.7.63.00-5  despesas de serviços técnicos especializados
--   81781001  8.1.7.81.00-1  despesas de taxa de administração do fundo
--   81781056  8.1.7.81.05-6    taxa de administração efetiva
--   81781104  8.1.7.81.10-4    taxa de gestão
--   81781252  8.1.7.81.25-2    despesa com distribuição
--   81782000  8.1.7.82.00-0  despesas de taxa de desempenho/performance
--   81783009  8.1.7.83.00-9  despesas de taxa de ingresso e saída
--
-- On 2026-06-30, 81781001 was filed by 23,214 funds and summed to
-- R$-23.67bn, equal to the sum of its sub-accounts; 81782000 by 3,585 funds.
-- The sub-accounts 81781159 (consultoria), 81781207 (controladoria) and
-- 81781300 are small and stay inside 81781001; 81781300 is not in that text.
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
    vl_desp_administrativas      NUMERIC(28,2),   -- 81700006
    vl_desp_servicos_financeiros NUMERIC(28,2),   -- 81754007
    vl_desp_servicos_tecnicos    NUMERIC(28,2),   -- 81763005
    vl_taxa_administracao        NUMERIC(28,2),   -- 81781001
    vl_taxa_adm_efetiva          NUMERIC(28,2),   -- 81781056
    vl_taxa_gestao               NUMERIC(28,2),   -- 81781104
    vl_taxa_distribuicao         NUMERIC(28,2),   -- 81781252
    vl_taxa_performance          NUMERIC(28,2),   -- 81782000
    vl_taxa_ingresso_saida       NUMERIC(28,2),   -- 81783009
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
    'FI balancete group totals and administrative-expense accounts (fees), one row per fund and month, as filed (COFI codes in migration 59). Revenue, expenses and every fee column accumulate from each fund''s own fiscal-year start; vl_patrim_liq excludes that open result. An account not filed is NULL. n_contas is the number of accounts the fund filed that month.';

COMMIT;
