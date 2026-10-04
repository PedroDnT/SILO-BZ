-- Executed checks for the portfolio-diagnosis reads (31_api_portfolio.sql:
-- api.portfolio_resolve, api.portfolio_fees, api.portfolio_lookthrough, catalog
-- v51; portfolio_fees v52, the Extrato first; api.portfolio_movement, v54; ETFs, v56). Regex tests pin the SQL text; this proves it DOES the right thing on
-- rows. Synthetic CNPJs, inside a transaction that is rolled back, so it runs
-- on any database with the schema and the analytical layer applied (CI's
-- sql-compile job, or a scratch copy):
--
--   psql "$POSTGRES_URL" -v ON_ERROR_STOP=1 -f tests/sql/portfolio_behaviour.sql
--
-- The shapes pinned come from production, measured 2026-10-03: the XP Bancos
-- master / FIC pair told apart by quota only; the XP Bancos FIC reaching
-- Santander Cash Black three quota levels down (here with synthetic CNPJs and
-- values of the same shape); the fiscal-year reset month of the fee accounts.

BEGIN;

-- ---------------------------------------------------------------------------
-- The lâmina view (slice A, demo/lamina) may or may not exist on this branch
-- yet. The test pins the contract portfolio_fees reads, so it installs its own
-- stand-in for the transaction: cnpj, id_subclasse, dt_comptc, taxa_adm,
-- taxa_adm_min, taxa_adm_max, taxa_perfm (text), and the declared expense ratio
-- (pr_pl_despesa and its period). Rolled back with the rest. The Extrato is NOT
-- stubbed: its rows go into the real cvm_fi_extrato (migration 66) so the view
-- vw_fi_extrato_latest is exercised too.
-- ---------------------------------------------------------------------------
DROP VIEW IF EXISTS public.vw_fi_lamina_latest;
CREATE TABLE public.zz_lamina_stub (
    cnpj text, id_subclasse text, dt_comptc date,
    taxa_adm numeric, taxa_adm_min numeric, taxa_adm_max numeric, taxa_perfm text,
    pr_pl_despesa numeric, dt_ini_despesa date, dt_fim_despesa date
);
CREATE VIEW public.vw_fi_lamina_latest AS SELECT * FROM public.zz_lamina_stub;

-- ===========================================================================
-- Fixtures
-- ===========================================================================
-- Names. ALFA changed its legal name; the XP pair shares the words of its names.
INSERT INTO cvm_fi_cda_fund_name (cnpj, period, denom_social) VALUES
    ('11111111000191', '2023-05-01', 'ALFA RENDA FIXA FI'),
    ('11111111000191', '2026-05-01', 'ALFA CLASSE DE INVESTIMENTO RENDA FIXA RESP LIMITADA'),
    ('35377390000106', '2026-05-01', 'XP BANCOS FI FINANCEIRO RENDA FIXA REFERENCIADO DI CRÉDITO PRIVADO - RESPONSABILIDADE LIMITADA'),
    ('50088190000119', '2026-05-01', 'XP BANCOS FI EM COTAS DE FI FINANCEIRO RENDA FIXA REFERENCIADO DI CRÉDITO PRIVADO - RESP LIMITADA'),
    ('22222222000191', '2026-05-01', 'BETA AÇÕES BRASIL FUNDO DE INVESTIMENTO'),
    ('33333333000191', '2026-05-01', 'GAMA MULTIMERCADO CRÉDITO PRIVADO FI');
INSERT INTO cvm_fund_registry (cnpj, entity_type, fund_name, status) VALUES
    ('11111111000191', 'fi', 'ALFA CLASSE DE INVESTIMENTO RENDA FIXA RESP LIMITADA', 'Em Funcionamento Normal'),
    ('35377390000106', 'fi', 'XP BANCOS FI FINANCEIRO RENDA FIXA REFERENCIADO DI CRÉDITO PRIVADO - RESPONSABILIDADE LIMITADA', 'Em Funcionamento Normal'),
    ('50088190000119', 'fi', 'XP BANCOS FI EM COTAS DE FI FINANCEIRO RENDA FIXA REFERENCIADO DI CRÉDITO PRIVADO - RESP LIMITADA', 'Em Funcionamento Normal'),
    ('22222222000191', 'fi', 'BETA AÇÕES BRASIL FUNDO DE INVESTIMENTO', 'Em Funcionamento Normal');

-- Quotas on 2026-09-30 (the real pair: 1.952607 and 1.542011).
INSERT INTO cvm_fi_diario (cnpj, id_subclasse, dt_comptc, vl_quota, vl_patrim_liq, raw) VALUES
    ('35377390000106', '', '2026-09-30', 1.952607, 7940000000, '{}'),
    ('50088190000119', '', '2026-09-30', 1.542011, 1780000000, '{}');

-- NAVs on the last day of 2026-05 for the look-through funds (fact_fund_monthly
-- is refreshed below). ROOT is the XP-FIC-shaped fund; MASTER, CASH and SANT its
-- descendants; BIGF holds 1001 stocks (the page edge); NOCDA files nothing.
INSERT INTO cvm_fi_diario (cnpj, id_subclasse, dt_comptc, vl_quota, vl_patrim_liq, raw) VALUES
    ('50088190000119', '', '2026-05-29', 1.5, 2000, '{}'),
    ('35377390000106', '', '2026-05-29', 1.9, 1000, '{}'),
    ('54891935000134', '', '2026-05-29', 1.1, 500,  '{}'),
    ('37525998000158', '', '2026-05-29', 1.2, 800,  '{}'),
    ('44444444000191', '', '2026-05-29', 1.0, 100000, '{}'),
    ('55555555000191', '', '2026-05-29', 1.0, 100, '{}');

-- Block 2. ROOT -> MASTER (two rows, a split by tp_negoc, summed: 600 + 400),
-- ROOT -> SANT directly (a second path to the same fund), ROOT -> UNFILED (a
-- held fund with no CDA), MASTER -> CASH, CASH -> SANT, CASH -> MASTER (a cycle).
INSERT INTO cvm_fi_cda_cotas (cnpj, period, cnpj_cota, nm_fundo_cota, tp_fundo, tp_aplic, tp_negoc, vl_merc_pos_final, raw) VALUES
    ('50088190000119', '2026-05-01', '35377390000106', 'MASTER', 'FI', 'Cotas de Fundos', 'Para negociação', 600, '{}'),
    ('50088190000119', '2026-05-01', '35377390000106', 'MASTER', 'FI', 'Cotas de Fundos', 'Disponível para venda', 400, '{}'),
    ('50088190000119', '2026-05-01', '37525998000158', 'SANT',   'FI', 'Cotas de Fundos', 'Para negociação', 100, '{}'),
    ('50088190000119', '2026-05-01', '99999999000191', 'UNFILED','FI', 'Cotas de Fundos', 'Para negociação', 50, '{}'),
    ('35377390000106', '2026-05-01', '54891935000134', 'CASH',   'FI', 'Cotas de Fundos', 'Para negociação', 500, '{}'),
    ('54891935000134', '2026-05-01', '37525998000158', 'SANT',   'FI', 'Cotas de Fundos', 'Para negociação', 430, '{}'),
    ('54891935000134', '2026-05-01', '35377390000106', 'MASTER', 'FI', 'Cotas de Fundos', 'Para negociação', 10, '{}');
-- Block 1: ROOT holds an NTN-B and repo collateral; SANT holds an LFT.
INSERT INTO cvm_fi_cda (cnpj, period, tp_aplic, tp_ativo, vl_merc_pos_final, tp_fundo, tp_negoc, cd_isin, cd_selic, tp_titpub, dt_venc, raw) VALUES
    ('50088190000119', '2026-05-01', 'Títulos Públicos', 'Título público federal', 200, 'FI', 'Para negociação', 'BRSTNCNTB3D4', '760199', 'NOTAS DO TESOURO NACIONAL SERIE B', '2035-05-15', '{}'),
    ('50088190000119', '2026-05-01', 'Operações Compromissadas', 'Título público federal', 50, 'FI', 'Para negociação', 'BRSTNCLF1RK7', '210100', 'LETRAS FINANCEIRAS DO TESOURO', '2027-03-01', '{}'),
    ('37525998000158', '2026-05-01', 'Títulos Públicos', 'Título público federal', 400, 'FI', 'Para negociação', 'BRSTNCLF1RK7', '210100', 'LETRAS FINANCEIRAS DO TESOURO', '2027-03-01', '{}');
-- Block 4: MASTER holds a stock and a debenture (ISIN, issuer code TAEE).
INSERT INTO cvm_fi_cda_acoes (cnpj, period, tp_fundo, tp_aplic, tp_ativo, tp_negoc, cd_ativo, cd_isin, ds_ativo, vl_merc_pos_final, raw) VALUES
    ('35377390000106', '2026-05-01', 'FI', 'Ações', 'Ação ordinária', 'Para negociação', 'PETR3', 'BRPETRACNOR9', 'PETROBRAS ON', 100, '{}'),
    ('35377390000106', '2026-05-01', 'FI', 'Debêntures', 'Debênture', 'Para negociação', 'TAEE12', 'BRTAEEDBS0O9', 'TAESA DEB', 100, '{}');
-- BIGF: 1001 stocks, exactly one row over the page.
INSERT INTO cvm_fi_cda_acoes (cnpj, period, tp_fundo, tp_aplic, tp_ativo, tp_negoc, cd_ativo, cd_isin, vl_merc_pos_final, raw)
SELECT '44444444000191', '2026-05-01', 'FI', 'Ações', 'Ação ordinária', 'Para negociação',
       'ZZ' || lpad(g::text, 4, '0') || '3', NULL, 1, '{}'
FROM generate_series(1, 1001) g;
-- Block 6: MASTER holds private credit of a PJ issuer and of a CPF issuer.
INSERT INTO cvm_fi_cda_debentures (cnpj, period, tp_fundo, tp_aplic, tp_ativo, tp_negoc, pf_pj_emissor, cpf_cnpj_emissor, emissor, dt_venc, cd_indexador_posfx, titulo_cetip, vl_merc_pos_final, row_hash, raw) VALUES
    ('35377390000106', '2026-05-01', 'FI', 'Debêntures', 'Debênture simples', 'Para negociação', 'PJ', '60000000000100', 'EMISSORA PJ SA', '2031-01-15', 'DI1', 'DEB001', 50, 'h1', '{}'),
    ('35377390000106', '2026-05-01', 'FI', 'Debêntures', 'Debênture simples', 'Para negociação', 'PF', '12345678901',    'PESSOA FISICA',  '2031-01-15', 'IAP', 'DEB002', 10, 'h2', '{}');
-- A fund that is a root with no CDA at all: 55555555000191 (NAV only).

-- Block-2 filing counts for the default month: 10 filler funds file block 2 in
-- each of the 13 months 2025-05..2026-05 (2026-05 also holds the fixtures
-- above, so it is at least that), and 3 in 2026-06, which is incomplete.
INSERT INTO cvm_fi_cda_cotas (cnpj, period, cnpj_cota, tp_fundo, tp_aplic, tp_negoc, vl_merc_pos_final, raw)
SELECT 'F' || lpad(i::text, 13, '0'), m::date, '88888888000191', 'FI', 'Cotas de Fundos', 'Para negociação', 1, '{}'
FROM generate_series('2025-05-01'::date, '2026-05-01', interval '1 month') m,
     generate_series(1, 10) i;
INSERT INTO cvm_fi_cda_cotas (cnpj, period, cnpj_cota, tp_fundo, tp_aplic, tp_negoc, vl_merc_pos_final, raw)
SELECT 'F' || lpad(i::text, 13, '0'), '2026-06-01', '88888888000191', 'FI', 'Cotas de Fundos', 'Para negociação', 1, '{}'
FROM generate_series(1, 3) i;

REFRESH MATERIALIZED VIEW public.mv_fund_name_history;
REFRESH MATERIALIZED VIEW public.fact_fund_monthly;
REFRESH MATERIALIZED VIEW public.mv_fund_holdings_monthly;

-- Fees. FEE1 steady accrual; FEE2 the fiscal-year reset (the accumulated fee
-- falls) with nothing to confirm it; FEE3 the same, confirmed by cad_fi's
-- DT_INI_EXERC; FEE4 has no previous month. Accumulated fees are filed negative.
INSERT INTO cvm_fi_balancete_resumo (cnpj, dt_comptc, vl_patrimonio_sem_resultado, vl_receitas, vl_despesas, vl_taxa_administracao, vl_taxa_performance, n_contas) VALUES
    ('61000000000191', '2026-04-30', 120000, 0, 0, -1000, -100, 1),
    ('61000000000191', '2026-05-31', 120000, 0, 0, -1800, -250, 1),
    ('62000000000191', '2026-04-30', 8000000, 0, 0, -8791158.76, NULL, 1),
    ('62000000000191', '2026-05-31', 8000000, 0, 0, -700478.38, NULL, 1),
    ('63000000000191', '2026-04-30', 1800000, 0, 0, -3126836.49, NULL, 1),
    ('63000000000191', '2026-05-31', 1800000, 0, 0, -288925.95, NULL, 1),
    ('64000000000191', '2026-05-31', 500000, 0, 0, -2000, NULL, 1),
    ('65000000000191', '2026-04-30', 100000, 0, 0, -500, NULL, 1),
    ('65000000000191', '2026-05-31', 100000, 0, 0, -1000, NULL, 1);
INSERT INTO cvm_fund_registry (cnpj, entity_type, fund_name, taxa_adm, dt_ini_exerc) VALUES
    ('61000000000191', 'fi', 'FEE ONE', 1.5, NULL),
    ('63000000000191', 'fi', 'FEE THREE', NULL, '2026-05-01'),
    ('65000000000191', 'fi', 'FEE FIVE', 3.0, NULL);
-- Lâmina stand-in: LAM1 two classes, one fee; LAM2 two classes, two fees;
-- FEE5 a lâmina row that filed no fee (so cad_fi's 3.0 is the fallback).
INSERT INTO public.zz_lamina_stub VALUES
    ('66000000000191', 'A', '2026-03-01', 1.0, NULL, NULL, '20% sobre o que exceder o CDI'),
    ('66000000000191', 'B', '2026-03-01', 1.0, NULL, NULL, '20% sobre o que exceder o CDI'),
    ('67000000000191', 'A', '2026-02-01', 0.5, NULL, NULL, NULL),
    ('67000000000191', 'B', '2026-02-01', 2.0, NULL, NULL, NULL),
    ('65000000000191', 'A', '2026-01-01', NULL, NULL, NULL, NULL);
-- Two classes of LAM2 declare different expense ratios; LAM1 declares one for both.
UPDATE public.zz_lamina_stub SET pr_pl_despesa = 0.10, dt_ini_despesa = '2025-07-01', dt_fim_despesa = '2025-12-31'
 WHERE cnpj = '67000000000191' AND id_subclasse = 'A';
UPDATE public.zz_lamina_stub SET pr_pl_despesa = 0.20, dt_ini_despesa = '2025-07-01', dt_fim_despesa = '2025-12-31'
 WHERE cnpj = '67000000000191' AND id_subclasse = 'B';
UPDATE public.zz_lamina_stub SET pr_pl_despesa = 0.13, dt_ini_despesa = '2025-07-01', dt_fim_despesa = '2025-12-31'
 WHERE cnpj = '66000000000191';

-- The Extrato (real table, real view). Dates are relative to today so the ages are
-- exact whatever day this runs.
--   EXT1  a fee, a performance fee, an exit fee, an older version beside the newest,
--         and a lamina with a DIFFERENT fee and an expense ratio: the Extrato wins.
--   EXT2  a filed 0, and a lamina with a fee: the Extrato still wins, the 0 is flagged.
--   EXT3  14638.38 (a real scale error): withheld, the raw value in its own column.
--   EXT4  an Extrato row whose fee cell was not a number (NULL): falls to the lamina.
-- Catalog v55 (issue #552), the lâmina beside or after an Extrato of 0 or above 5:
--   EXT5  the Inter Corporate shape measured 2026-10-03 (36443522000105): Extrato
--         25.0 of 2024-05-03, lâmina 0.25 of 2026-08-31, newer: the lâmina is the
--         source (lamina_newer), the Extrato's 25 beside it, factor 100 flagged.
--   EXT6  Extrato 15 newer than a lâmina of 1.5: the Extrato stays the source (to
--         check), the lâmina beside it, factor 10 flagged.
--   EXT7  Extrato 15.3 against a lâmina of 1.5: ratio 10.2, no factor.
--   EXT8  the Inter BB FIC shape (50197313000150): Extrato 45.0 of 2024-05-03,
--         lâmina 0.06 of 2026-08-31: lamina_newer, ratio 750, no factor.
--   EXT9  the CFIN shape (08212681000163): Extrato 0 filed recently, lâmina 0.023
--         of 2024-08-31, older: the Extrato stays, the lâmina beside, no ratio.
INSERT INTO cvm_fi_extrato
    (cnpj, dt_comptc, source_file, tp_fundo_classe, classe_anbima, taxa_adm, taxa_custodia_max,
     existe_taxa_perfm, taxa_perfm, param_taxa_perfm, calc_taxa_perfm, inf_taxa_perfm,
     existe_taxa_ingresso, existe_taxa_saida, taxa_saida_pr, taxa_saida_real, raw)
VALUES
    ('71000000000191', CURRENT_DATE - 900, 'extrato_fi_2024.csv', 'CLASSES - FIF', 'AÇÕES - ATIVO - LIVRE', 2.0, 0.0, 'N', NULL, NULL, NULL, NULL, 'N', 'N', NULL, NULL, '{}'),
    ('71000000000191', CURRENT_DATE - 100, 'extrato_fi.csv',      'CLASSES - FIF', 'AÇÕES - ATIVO - LIVRE', 1.2, 0.05, 'S', 20.0, 'IBOVESPA', 'LINEAR', '20% sobre o que exceder o IBOVESPA', 'N', 'S', 1.5, NULL, '{}'),
    ('72000000000191', CURRENT_DATE - 30,  'extrato_fi.csv',      'FI',            'RENDA FIXA',            0.0, 0.0, 'N', NULL, NULL, NULL, NULL, 'N', 'N', NULL, NULL, '{}'),
    ('73000000000191', CURRENT_DATE - 400, 'extrato_fi.csv',      'FI',            'MULTIMERCADO',          14638.38, 0.0, 'N', NULL, NULL, NULL, NULL, 'N', 'N', NULL, NULL, '{}'),
    ('74000000000191', CURRENT_DATE - 10,  'extrato_fi.csv',      'FI',            'RENDA FIXA',            NULL, 0.0, 'N', NULL, NULL, NULL, NULL, 'N', 'N', NULL, NULL, '{}'),
    ('75000000000191', DATE '2024-05-03',  'extrato_fi_2024.csv', 'FI',            'RENDA FIXA',            25.0, 0.0, 'N', NULL, NULL, NULL, NULL, 'N', 'N', NULL, NULL, '{}'),
    ('76000000000191', CURRENT_DATE - 5,   'extrato_fi.csv',      'FI',            'RENDA FIXA',            15, 0.0, 'N', NULL, NULL, NULL, NULL, 'N', 'N', NULL, NULL, '{}'),
    ('77000000000191', CURRENT_DATE - 5,   'extrato_fi.csv',      'FI',            'RENDA FIXA',            15.3, 0.0, 'N', NULL, NULL, NULL, NULL, 'N', 'N', NULL, NULL, '{}'),
    ('78000000000191', DATE '2024-05-03',  'extrato_fi_2024.csv', 'FI',            'RENDA FIXA',            45.0, 0.0, 'N', NULL, NULL, NULL, NULL, 'N', 'N', NULL, NULL, '{}'),
    ('79000000000191', CURRENT_DATE - 1,   'extrato_fi.csv',      'FI',            'RENDA FIXA',            0.0, 0.0, 'N', NULL, NULL, NULL, NULL, 'N', 'N', NULL, NULL, '{}');
INSERT INTO public.zz_lamina_stub VALUES
    ('71000000000191', NULL, '2026-03-01', 0.9, NULL, NULL, 'lamina text', 1.5, '2025-04-01', '2025-09-30'),
    ('72000000000191', NULL, '2026-03-01', 0.5, NULL, NULL, NULL, NULL, NULL, NULL),
    ('74000000000191', NULL, '2026-03-01', 0.7, NULL, NULL, NULL, 0.4, '2025-04-01', '2025-09-30'),
    ('75000000000191', NULL, '2026-08-31', 0.25, NULL, NULL, NULL, NULL, NULL, NULL),
    ('76000000000191', NULL, '2026-03-01', 1.5, NULL, NULL, NULL, NULL, NULL, NULL),
    ('77000000000191', NULL, '2026-03-01', 1.5, NULL, NULL, NULL, NULL, NULL, NULL),
    ('78000000000191', NULL, '2026-08-31', 0.06, NULL, NULL, NULL, 0.48, '2025-09-01', '2026-08-31'),
    ('79000000000191', NULL, '2024-08-31', 0.023, NULL, NULL, NULL, NULL, NULL, NULL);

-- ===========================================================================
-- portfolio_resolve
-- ===========================================================================
DO $$
DECLARE
    r RECORD;
    n INT;
    a BOOLEAN;
BEGIN
    -- exact_current: case and accents ignored.
    SELECT * INTO r FROM api.portfolio_resolve(ARRAY['beta acoes brasil fundo de investimento']) WHERE rank = 1;
    IF r.candidate_cnpj IS DISTINCT FROM '22222222000191' OR r.match_kind <> 'exact_current'
       OR r.similarity <> 1 OR r.ambiguous THEN
        RAISE EXCEPTION 'exact_current: got % % % % %', r.candidate_cnpj, r.match_kind, r.similarity, r.ambiguous, r.reason;
    END IF;

    -- exact_history: a former legal name finds the fund, shown under its current name.
    SELECT * INTO r FROM api.portfolio_resolve(ARRAY['Alfa Renda Fixa FI']) WHERE rank = 1;
    IF r.candidate_cnpj IS DISTINCT FROM '11111111000191' OR r.match_kind <> 'exact_history'
       OR r.matched_period IS DISTINCT FROM DATE '2023-05-01'
       OR r.candidate_name NOT LIKE 'ALFA CLASSE%' OR r.ambiguous THEN
        RAISE EXCEPTION 'exact_history: got % % % % %', r.candidate_cnpj, r.match_kind, r.matched_period, r.candidate_name, r.ambiguous;
    END IF;

    -- A supplied CNPJ wins over a name that points elsewhere.
    SELECT * INTO r FROM api.portfolio_resolve(ARRAY['beta acoes brasil fundo de investimento'],
                                               ARRAY['11.111.111/0001-91']) WHERE rank = 1;
    IF r.candidate_cnpj IS DISTINCT FROM '11111111000191' OR r.match_kind <> 'cnpj' OR r.ambiguous THEN
        RAISE EXCEPTION 'cnpj wins: got % % %', r.candidate_cnpj, r.match_kind, r.ambiguous;
    END IF;

    -- The XP Bancos pair: the quota is the only thing that separates them.
    SELECT * INTO r FROM api.portfolio_resolve(ARRAY['XP Bancos'], NULL, ARRAY[1.542011::numeric],
                                               ARRAY[DATE '2026-09-30']) WHERE rank = 1;
    IF r.candidate_cnpj IS DISTINCT FROM '50088190000119' OR r.ambiguous OR r.quota_rel_diff > 0.0001 THEN
        RAISE EXCEPTION 'XP FIC by quota: got % amb=% diff=% (%)', r.candidate_cnpj, r.ambiguous, r.quota_rel_diff, r.reason;
    END IF;
    SELECT * INTO r FROM api.portfolio_resolve(ARRAY['XP Bancos'], NULL, ARRAY[1.952607::numeric],
                                               ARRAY[DATE '2026-09-30']) WHERE rank = 1;
    IF r.candidate_cnpj IS DISTINCT FROM '35377390000106' OR r.ambiguous THEN
        RAISE EXCEPTION 'XP master by quota: got % amb=% (%)', r.candidate_cnpj, r.ambiguous, r.reason;
    END IF;
    -- Without a quota: never picked silently. Both are returned, both flagged.
    SELECT count(*), bool_and(ambiguous) INTO n, a
      FROM api.portfolio_resolve(ARRAY['XP Bancos']) WHERE candidate_cnpj IN ('35377390000106', '50088190000119');
    IF n <> 2 OR NOT a THEN
        RAISE EXCEPTION 'XP without quota: % candidates, ambiguous=%', n, a;
    END IF;
    -- A quota that matches neither stays ambiguous and says so.
    SELECT * INTO r FROM api.portfolio_resolve(ARRAY['XP Bancos'], NULL, ARRAY[9.99::numeric],
                                               ARRAY[DATE '2026-09-30']) WHERE rank = 1;
    IF NOT r.ambiguous OR r.reason NOT LIKE '%AMBIGUOUS%' THEN
        RAISE EXCEPTION 'XP with a wrong quota must stay ambiguous: % %', r.ambiguous, r.reason;
    END IF;
    -- A quota date with no filing: no quota is invented.
    SELECT * INTO r FROM api.portfolio_resolve(ARRAY['XP Bancos'], NULL, ARRAY[1.542011::numeric],
                                               ARRAY[DATE '2026-09-29']) WHERE rank = 1;
    IF r.quota_on_date IS NOT NULL OR NOT r.ambiguous OR r.reason NOT LIKE '%no quota filed%' THEN
        RAISE EXCEPTION 'XP without a quota that day: % % %', r.quota_on_date, r.ambiguous, r.reason;
    END IF;

    -- Nothing like any name: no candidate, with a reason, not a nearest neighbour.
    SELECT * INTO r FROM api.portfolio_resolve(ARRAY['QQQQ ZZZZ WWWW']);
    IF r.candidate_cnpj IS NOT NULL OR r.reason NOT LIKE 'no candidate%' OR r.ambiguous THEN
        RAISE EXCEPTION 'unmatched line: % %', r.candidate_cnpj, r.reason;
    END IF;

    -- One row group per line, in line order.
    SELECT count(DISTINCT line_no) INTO n
      FROM api.portfolio_resolve(ARRAY['Alfa Renda Fixa FI', 'beta acoes brasil fundo de investimento', 'QQQQ ZZZZ']);
    IF n <> 3 THEN RAISE EXCEPTION 'three lines expected, got %', n; END IF;
    RAISE NOTICE 'portfolio_resolve OK';
END $$;

-- 201 lines are refused with the reason, 200 are served; parallel arrays must agree.
DO $$
DECLARE
    n INT;
BEGIN
    BEGIN
        PERFORM * FROM api.portfolio_resolve((SELECT array_agg('x' || g) FROM generate_series(1, 201) g));
        RAISE EXCEPTION '201 lines were served, expected a 22023 refusal';
    EXCEPTION WHEN sqlstate '22023' THEN
        IF SQLERRM NOT LIKE '%more than 200%' OR SQLERRM NOT LIKE '%To fix%' THEN
            RAISE EXCEPTION 'refusal without why/how: %', SQLERRM;
        END IF;
    END;
    SELECT count(*) INTO n FROM api.portfolio_resolve((SELECT array_agg('qqqq zzzz ' || g) FROM generate_series(1, 200) g));
    IF n <> 200 THEN RAISE EXCEPTION '200 lines expected one row each, got %', n; END IF;
    BEGIN
        PERFORM * FROM api.portfolio_resolve(ARRAY['a', 'b'], ARRAY['11111111000191']);
        RAISE EXCEPTION 'unequal arrays were served';
    EXCEPTION WHEN sqlstate '22023' THEN NULL;
    END;
    RAISE NOTICE 'portfolio_resolve refusals OK';
END $$;

-- ===========================================================================
-- portfolio_fees
-- ===========================================================================
DO $$
DECLARE
    r RECORD;
    n INT;
BEGIN
    -- FEE1: steady accrual. (1800 - 1000) x 12 / 120000 = 8% a year; performance 150.
    SELECT * INTO r FROM api.portfolio_fees(ARRAY['61000000000191']);
    IF r.month <> DATE '2026-05-31' OR r.nav <> 120000 OR r.adm_fee_flow <> 800
       OR r.adm_fee_pct_annual_est <> 8.0 OR r.perf_fee_flow <> 150 OR r.fiscal_reset_suspect
       OR r.estimate_label NOT LIKE 'estimate from the balancete accruals%not the disclosed fee' THEN
        RAISE EXCEPTION 'FEE1: % % % % % % %', r.month, r.nav, r.adm_fee_flow, r.adm_fee_pct_annual_est, r.perf_fee_flow, r.fiscal_reset_suspect, r.estimate_label;
    END IF;
    -- ... and its disclosed fee is cad_fi's, a separate column, never the estimate.
    IF r.disclosed_taxa_adm <> 1.5 OR r.disclosed_source <> 'cvm_fund_registry (cad_fi)'
       OR r.disclosed_as_of IS NULL OR r.disclosed_taxa_adm = r.adm_fee_pct_annual_est THEN
        RAISE EXCEPTION 'FEE1 disclosed: % % %', r.disclosed_taxa_adm, r.disclosed_source, r.disclosed_as_of;
    END IF;

    -- FEE2: the accumulated fee fell and nothing confirms a reset: flagged, no estimate.
    SELECT * INTO r FROM api.portfolio_fees(ARRAY['62000000000191']);
    IF NOT r.fiscal_reset_suspect OR r.adm_fee_flow IS NOT NULL OR r.adm_fee_pct_annual_est IS NOT NULL
       OR r.estimate_label NOT LIKE 'no estimate: the accumulated administration fee fell%' THEN
        RAISE EXCEPTION 'FEE2 reset: % % % %', r.fiscal_reset_suspect, r.adm_fee_flow, r.adm_fee_pct_annual_est, r.estimate_label;
    END IF;
    -- No disclosed fee anywhere: NULL (not zero) and it says so.
    IF r.disclosed_taxa_adm IS NOT NULL OR r.disclosed_source IS NOT NULL
       OR r.disclosed_note NOT LIKE '%not a zero fee%' THEN
        RAISE EXCEPTION 'FEE2 disclosed: % % %', r.disclosed_taxa_adm, r.disclosed_source, r.disclosed_note;
    END IF;

    -- FEE3: the same fall, but cad_fi's DT_INI_EXERC is in May: the month's accumulated value IS the accrual.
    SELECT * INTO r FROM api.portfolio_fees(ARRAY['63000000000191']);
    IF NOT r.fiscal_reset_suspect OR r.adm_fee_flow <> 288925.95
       OR r.adm_fee_pct_annual_est <> round(288925.95 * 12 / 1800000 * 100, 4)
       OR r.estimate_label NOT LIKE '%DT_INI_EXERC%' THEN
        RAISE EXCEPTION 'FEE3 confirmed reset: % % % %', r.fiscal_reset_suspect, r.adm_fee_flow, r.adm_fee_pct_annual_est, r.estimate_label;
    END IF;

    -- FEE4: no previous month, no estimate.
    SELECT * INTO r FROM api.portfolio_fees(ARRAY['64000000000191']);
    IF r.adm_fee_flow IS NOT NULL OR r.fiscal_reset_suspect OR r.estimate_label NOT LIKE 'no estimate: no balancete for the previous month%' THEN
        RAISE EXCEPTION 'FEE4: % % %', r.adm_fee_flow, r.fiscal_reset_suspect, r.estimate_label;
    END IF;

    -- A lâmina with one fee across its classes beats cad_fi; the age is in months.
    SELECT * INTO r FROM api.portfolio_fees(ARRAY['66000000000191']);
    IF r.disclosed_taxa_adm <> 1.0 OR r.disclosed_source <> 'cvm_fi_lamina' OR r.disclosed_as_of <> DATE '2026-03-01'
       OR r.disclosed_n_classes <> 2 OR r.disclosed_taxa_perfm NOT LIKE '20%'
       OR r.disclosed_age_months IS DISTINCT FROM 2 OR r.disclosed_note IS NOT NULL THEN
        RAISE EXCEPTION 'LAM1: % % % % % %', r.disclosed_taxa_adm, r.disclosed_source, r.disclosed_as_of, r.disclosed_n_classes, r.disclosed_age_months, r.disclosed_note;
    END IF;
    -- Classes that disagree: no single fee, the range and a note.
    SELECT * INTO r FROM api.portfolio_fees(ARRAY['67000000000191']);
    IF r.disclosed_taxa_adm IS NOT NULL OR r.disclosed_taxa_adm_min <> 0.5 OR r.disclosed_taxa_adm_max <> 2.0
       OR r.disclosed_note NOT LIKE '%different fees%' OR r.disclosed_source <> 'cvm_fi_lamina' THEN
        RAISE EXCEPTION 'LAM2: % % % % %', r.disclosed_taxa_adm, r.disclosed_taxa_adm_min, r.disclosed_taxa_adm_max, r.disclosed_note, r.disclosed_source;
    END IF;
    -- A lâmina row that filed no fee falls back to cad_fi (3.0), never to zero.
    SELECT * INTO r FROM api.portfolio_fees(ARRAY['65000000000191']);
    IF r.disclosed_taxa_adm <> 3.0 OR r.disclosed_source <> 'cvm_fund_registry (cad_fi)' THEN
        RAISE EXCEPTION 'LAM3 fallback: % %', r.disclosed_taxa_adm, r.disclosed_source;
    END IF;

    -- p_month names the balancete month; April of FEE1 has no previous month in the table.
    SELECT * INTO r FROM api.portfolio_fees(ARRAY['61000000000191'], DATE '2026-04-10');
    IF r.month <> DATE '2026-04-30' OR r.adm_fee_flow IS NOT NULL THEN
        RAISE EXCEPTION 'p_month: % %', r.month, r.adm_fee_flow;
    END IF;
    -- A fund with no balancete: a row, the label says why, nothing invented.
    SELECT * INTO r FROM api.portfolio_fees(ARRAY['68000000000191']);
    IF r.cnpj <> '68000000000191' OR r.month IS NOT NULL OR r.estimate_label NOT LIKE 'no estimate: no balancete filed%' THEN
        RAISE EXCEPTION 'no balancete: % % %', r.cnpj, r.month, r.estimate_label;
    END IF;
    -- The existing sources name themselves in the appended columns.
    SELECT * INTO r FROM api.portfolio_fees(ARRAY['61000000000191']);
    IF r.disclosed_origin <> 'cad_fi' OR r.filed_zero OR r.implausible_filed OR r.taxa_adm_filed_raw <> 1.5
       OR r.disclosed_age_days IS NOT NULL OR r.extrato_taxa_perfm IS NOT NULL OR r.lamina_pr_pl_despesa IS NOT NULL THEN
        RAISE EXCEPTION 'cad_fi origin: % % % % %', r.disclosed_origin, r.filed_zero, r.implausible_filed, r.taxa_adm_filed_raw, r.disclosed_age_days;
    END IF;
    SELECT * INTO r FROM api.portfolio_fees(ARRAY['66000000000191']);
    IF r.disclosed_origin <> 'lamina' OR r.disclosed_age_days <> CURRENT_DATE - DATE '2026-03-01'
       OR r.lamina_pr_pl_despesa <> 0.13 OR r.lamina_dt_ini_despesa <> DATE '2025-07-01'
       OR r.lamina_dt_fim_despesa <> DATE '2025-12-31' OR r.lamina_as_of <> DATE '2026-03-01'
       OR r.lamina_expense_note IS NOT NULL THEN
        RAISE EXCEPTION 'lamina origin and expense ratio: % % % % % %', r.disclosed_origin, r.disclosed_age_days, r.lamina_pr_pl_despesa, r.lamina_dt_ini_despesa, r.lamina_as_of, r.lamina_expense_note;
    END IF;
    -- Classes that declare different expense ratios: no single value, a note.
    SELECT * INTO r FROM api.portfolio_fees(ARRAY['67000000000191']);
    IF r.lamina_pr_pl_despesa IS NOT NULL OR r.lamina_expense_note NOT LIKE '%different expense ratios%'
       OR r.disclosed_origin <> 'lamina' THEN
        RAISE EXCEPTION 'LAM2 expense: % % %', r.lamina_pr_pl_despesa, r.lamina_expense_note, r.disclosed_origin;
    END IF;

    -- EXT1: the Extrato is the source, with the NEWEST version (1.2, not the older 2.0),
    -- ahead of the lamina's 0.9; performance, exit fees and the class note as filed;
    -- the expense ratio still comes from the lamina; the age is exact.
    SELECT * INTO r FROM api.portfolio_fees(ARRAY['71000000000191']);
    IF r.disclosed_origin <> 'extrato' OR r.disclosed_source <> 'cvm_fi_extrato'
       OR r.disclosed_taxa_adm <> 1.2 OR r.taxa_adm_filed_raw <> 1.2 OR r.filed_zero OR r.implausible_filed
       OR r.disclosed_taxa_adm_min <> 1.2 OR r.disclosed_taxa_adm_max <> 1.2
       OR r.disclosed_as_of <> CURRENT_DATE - 100 OR r.disclosed_age_days <> 100
       OR r.disclosed_n_classes <> 1 OR r.disclosed_note IS NOT NULL
       OR r.disclosed_taxa_perfm <> '20% sobre o que exceder o IBOVESPA'
       OR r.extrato_existe_taxa_perfm <> 'S' OR r.extrato_taxa_perfm <> 20 OR r.extrato_param_taxa_perfm <> 'IBOVESPA'
       OR r.extrato_calc_taxa_perfm <> 'LINEAR' OR r.extrato_inf_taxa_perfm <> '20% sobre o que exceder o IBOVESPA'
       OR r.extrato_existe_taxa_saida <> 'S' OR r.extrato_taxa_saida_pr <> 1.5
       OR r.extrato_existe_taxa_ingresso <> 'N' OR r.extrato_taxa_custodia_max <> 0.05
       OR r.extrato_tp_fundo_classe <> 'CLASSES - FIF' OR r.extrato_classe_anbima <> 'AÇÕES - ATIVO - LIVRE'
       OR r.extrato_class_note NOT LIKE 'class-level row (CVM 175)%no subclass fee is assumed' THEN
        RAISE EXCEPTION 'EXT1: % % % % % % % %', r.disclosed_origin, r.disclosed_taxa_adm, r.disclosed_as_of, r.disclosed_age_days, r.disclosed_taxa_perfm, r.extrato_taxa_perfm, r.extrato_class_note, r.disclosed_note;
    END IF;
    IF r.lamina_pr_pl_despesa <> 1.5 OR r.lamina_dt_fim_despesa <> DATE '2025-09-30' OR r.lamina_as_of <> DATE '2026-03-01' THEN
        RAISE EXCEPTION 'EXT1 expense ratio from the lamina: % % %', r.lamina_pr_pl_despesa, r.lamina_dt_fim_despesa, r.lamina_as_of;
    END IF;
    -- The estimate stays a separate, labelled column (no balancete here: nothing invented).
    IF r.adm_fee_pct_annual_est IS NOT NULL OR r.estimate_label NOT LIKE 'no estimate: no balancete filed%' THEN
        RAISE EXCEPTION 'EXT1 estimate: % %', r.adm_fee_pct_annual_est, r.estimate_label;
    END IF;

    -- EXT2: a filed 0 comes back as 0 with the flag, from the Extrato, NOT from the lamina's 0.5.
    SELECT * INTO r FROM api.portfolio_fees(ARRAY['72000000000191']);
    IF r.disclosed_origin <> 'extrato' OR r.disclosed_taxa_adm IS DISTINCT FROM 0 OR NOT r.filed_zero
       OR r.implausible_filed OR r.taxa_adm_filed_raw IS DISTINCT FROM 0
       OR r.disclosed_note NOT LIKE '%exactly 0%filed_zero%not informed%'
       OR r.extrato_class_note NOT LIKE 'fund-level row (ICVM 555)%' THEN
        RAISE EXCEPTION 'EXT2 filed zero: % % % % %', r.disclosed_origin, r.disclosed_taxa_adm, r.filed_zero, r.taxa_adm_filed_raw, r.disclosed_note;
    END IF;

    -- EXT3: 14638.38 is withheld (NULL fee, NULL range), flagged, the raw value kept apart.
    SELECT * INTO r FROM api.portfolio_fees(ARRAY['73000000000191']);
    IF r.disclosed_origin <> 'extrato' OR r.disclosed_taxa_adm IS NOT NULL OR NOT r.implausible_filed OR r.filed_zero
       OR r.taxa_adm_filed_raw <> 14638.38 OR r.disclosed_taxa_adm_min IS NOT NULL OR r.disclosed_taxa_adm_max IS NOT NULL
       OR r.disclosed_note NOT LIKE '%14638.38%scale error%taxa_adm_filed_raw%' THEN
        RAISE EXCEPTION 'EXT3 implausible: % % % % %', r.disclosed_origin, r.disclosed_taxa_adm, r.implausible_filed, r.taxa_adm_filed_raw, r.disclosed_note;
    END IF;

    -- EXT4: an Extrato row with no usable fee does not hide the lamina's 0.7.
    SELECT * INTO r FROM api.portfolio_fees(ARRAY['74000000000191']);
    IF r.disclosed_origin <> 'lamina' OR r.disclosed_taxa_adm <> 0.7 OR r.extrato_taxa_perfm IS NOT NULL
       OR r.extrato_tp_fundo_classe IS NOT NULL OR r.lamina_pr_pl_despesa <> 0.4 THEN
        RAISE EXCEPTION 'EXT4 fallback to the lamina: % % %', r.disclosed_origin, r.disclosed_taxa_adm, r.extrato_tp_fundo_classe;
    END IF;

    -- v55 (#552): which rule applied, and the other document's fee beside, as filed.
    SELECT * INTO r FROM api.portfolio_fees(ARRAY['71000000000191']);
    IF r.fee_resolution <> 'extrato' OR r.lamina_taxa_adm <> 0.9 OR r.extrato_taxa_adm_filed <> 1.2
       OR r.extrato_as_of <> CURRENT_DATE - 100 OR r.extrato_lamina_ratio <> 1.3333 OR r.extrato_scale_factor IS NOT NULL
       OR r.lamina_n_classes <> 1 THEN
        RAISE EXCEPTION 'EXT1 v55: % % % % %', r.fee_resolution, r.lamina_taxa_adm, r.extrato_taxa_adm_filed, r.extrato_lamina_ratio, r.extrato_scale_factor;
    END IF;
    -- EXT2: the 0 stays the Extrato's (the lamina of 2026-03-01 is older), the lamina's 0.5 beside it.
    SELECT * INTO r FROM api.portfolio_fees(ARRAY['72000000000191']);
    IF r.fee_resolution <> 'extrato_lamina_beside' OR r.lamina_taxa_adm <> 0.5 OR r.extrato_taxa_adm_filed <> 0
       OR r.extrato_lamina_ratio IS NOT NULL OR r.extrato_scale_factor IS NOT NULL THEN
        RAISE EXCEPTION 'EXT2 v55: % % % %', r.fee_resolution, r.lamina_taxa_adm, r.extrato_lamina_ratio, r.extrato_scale_factor;
    END IF;
    -- EXT3: no lamina at all: still to check, nothing beside, no ratio.
    SELECT * INTO r FROM api.portfolio_fees(ARRAY['73000000000191']);
    IF r.fee_resolution <> 'extrato_to_check' OR r.lamina_taxa_adm IS NOT NULL OR r.lamina_taxa_adm_min IS NOT NULL
       OR r.extrato_taxa_adm_filed <> 14638.38 OR r.extrato_lamina_ratio IS NOT NULL OR r.extrato_scale_factor IS NOT NULL THEN
        RAISE EXCEPTION 'EXT3 v55: % % %', r.fee_resolution, r.lamina_taxa_adm, r.extrato_scale_factor;
    END IF;
    -- EXT5 (Inter Corporate shape): the newer lamina is the source; the Extrato's 25 beside it, as filed.
    SELECT * INTO r FROM api.portfolio_fees(ARRAY['75000000000191']);
    IF r.fee_resolution <> 'lamina_newer' OR r.disclosed_origin <> 'lamina' OR r.disclosed_source <> 'cvm_fi_lamina'
       OR r.disclosed_taxa_adm <> 0.25 OR r.disclosed_as_of <> DATE '2026-08-31' OR r.taxa_adm_filed_raw <> 0.25
       OR r.filed_zero OR r.implausible_filed
       OR r.extrato_taxa_adm_filed <> 25.0 OR r.extrato_as_of <> DATE '2024-05-03'
       OR r.extrato_tp_fundo_classe IS NOT NULL OR r.extrato_class_note IS NOT NULL
       OR r.lamina_taxa_adm <> 0.25 OR r.extrato_lamina_ratio <> 100 OR r.extrato_scale_factor <> 100
       -- the lamina (2026-08) is later than the newest balancete month here (2026-05): age 0, never negative
       OR r.disclosed_age_months <> 0 OR r.lamina_age_months <> 0
       OR r.disclosed_note NOT LIKE 'the Extrato of 2024-05-03 filed an administration fee of 25 %lâmina of 2026-08-31, newer, discloses 0.25%lamina_newer%never rescaled' THEN
        RAISE EXCEPTION 'EXT5 lamina newer: % % % % % % % %', r.fee_resolution, r.disclosed_origin, r.disclosed_taxa_adm, r.disclosed_as_of,
            r.extrato_taxa_adm_filed, r.extrato_lamina_ratio, r.extrato_scale_factor, r.disclosed_note;
    END IF;
    -- EXT6: Extrato 15 newer than the lamina's 1.5: the Extrato stays (withheld, to check), factor 10 flagged.
    SELECT * INTO r FROM api.portfolio_fees(ARRAY['76000000000191']);
    IF r.fee_resolution <> 'extrato_lamina_beside' OR r.disclosed_origin <> 'extrato' OR r.disclosed_taxa_adm IS NOT NULL
       OR NOT r.implausible_filed OR r.taxa_adm_filed_raw <> 15 OR r.lamina_taxa_adm <> 1.5
       OR r.lamina_as_of <> DATE '2026-03-01' OR r.extrato_lamina_ratio <> 10 OR r.extrato_scale_factor <> 10 THEN
        RAISE EXCEPTION 'EXT6 factor 10: % % % % %', r.fee_resolution, r.disclosed_origin, r.lamina_taxa_adm, r.extrato_lamina_ratio, r.extrato_scale_factor;
    END IF;
    -- EXT7: 15.3 against 1.5 is not a factor of 10 within the rounding of two decimals.
    SELECT * INTO r FROM api.portfolio_fees(ARRAY['77000000000191']);
    IF r.fee_resolution <> 'extrato_lamina_beside' OR r.extrato_lamina_ratio <> 10.2 OR r.extrato_scale_factor IS NOT NULL THEN
        RAISE EXCEPTION 'EXT7 near miss: % % %', r.fee_resolution, r.extrato_lamina_ratio, r.extrato_scale_factor;
    END IF;
    -- EXT8 (Inter BB FIC shape): the newer lamina's 0.06 is the source; ratio 750, no factor.
    SELECT * INTO r FROM api.portfolio_fees(ARRAY['78000000000191']);
    IF r.fee_resolution <> 'lamina_newer' OR r.disclosed_taxa_adm <> 0.06 OR r.extrato_taxa_adm_filed <> 45.0
       OR r.extrato_lamina_ratio <> 750 OR r.extrato_scale_factor IS NOT NULL OR r.lamina_pr_pl_despesa <> 0.48 THEN
        RAISE EXCEPTION 'EXT8: % % % %', r.fee_resolution, r.disclosed_taxa_adm, r.extrato_lamina_ratio, r.extrato_scale_factor;
    END IF;
    -- EXT9 (CFIN shape): a fresh Extrato 0 and an older lamina 0.023: the Extrato stays, the lamina beside.
    SELECT * INTO r FROM api.portfolio_fees(ARRAY['79000000000191']);
    IF r.fee_resolution <> 'extrato_lamina_beside' OR r.disclosed_origin <> 'extrato' OR NOT r.filed_zero
       OR r.lamina_taxa_adm <> 0.023 OR r.lamina_as_of <> DATE '2024-08-31'
       OR r.extrato_lamina_ratio IS NOT NULL OR r.extrato_scale_factor IS NOT NULL THEN
        RAISE EXCEPTION 'EXT9: % % % %', r.fee_resolution, r.disclosed_origin, r.lamina_taxa_adm, r.lamina_as_of;
    END IF;
    -- A fund with only a lamina: its own fee is the source and the lamina_* columns repeat it.
    SELECT * INTO r FROM api.portfolio_fees(ARRAY['74000000000191']);
    IF r.fee_resolution <> 'lamina' OR r.lamina_taxa_adm <> 0.7 OR r.extrato_taxa_adm_filed IS NOT NULL THEN
        RAISE EXCEPTION 'EXT4 v55: % % %', r.fee_resolution, r.lamina_taxa_adm, r.extrato_taxa_adm_filed;
    END IF;

    -- A fund in no source: nothing disclosed, origin NULL, no flag raised, no invented number.
    SELECT * INTO r FROM api.portfolio_fees(ARRAY['62000000000191']);
    IF r.disclosed_origin IS NOT NULL OR r.filed_zero OR r.implausible_filed OR r.taxa_adm_filed_raw IS NOT NULL
       OR r.lamina_as_of IS NOT NULL OR r.lamina_expense_note IS NOT NULL
       OR r.fee_resolution IS NOT NULL OR r.lamina_taxa_adm IS NOT NULL OR r.extrato_taxa_adm_filed IS NOT NULL
       OR r.extrato_lamina_ratio IS NOT NULL OR r.extrato_scale_factor IS NOT NULL THEN
        RAISE EXCEPTION 'no source: % % %', r.disclosed_origin, r.filed_zero, r.taxa_adm_filed_raw;
    END IF;

    -- Several funds at once: one row each, every source in its own row.
    SELECT count(*) INTO n FROM api.portfolio_fees(ARRAY['71000000000191','72000000000191','73000000000191','74000000000191','66000000000191','61000000000191']);
    IF n <> 6 THEN RAISE EXCEPTION 'six funds, six rows expected, got %', n; END IF;
    RAISE NOTICE 'portfolio_fees OK';
END $$;

DO $$
BEGIN
    BEGIN
        PERFORM * FROM api.portfolio_fees((SELECT array_agg(lpad(g::text, 14, '0')) FROM generate_series(1, 201) g));
        RAISE EXCEPTION '201 CNPJs were served, expected a 22023 refusal';
    EXCEPTION WHEN sqlstate '22023' THEN
        IF SQLERRM NOT LIKE '%more than 200%' OR SQLERRM NOT LIKE '%To fix%' THEN
            RAISE EXCEPTION 'refusal without why/how: %', SQLERRM;
        END IF;
    END;
    BEGIN
        PERFORM * FROM api.portfolio_fees(ARRAY['not-a-cnpj']);
        RAISE EXCEPTION 'a malformed CNPJ was served';
    EXCEPTION WHEN sqlstate '22023' THEN NULL;
    END;
END $$;

-- ===========================================================================
-- portfolio_lookthrough
-- ===========================================================================
DO $$
DECLARE
    r RECORD;
    n INT;
    s NUMERIC;
BEGIN
    -- The default month is the last COMPLETE one: 2026-05 (13 filers), not 2026-06 (3).
    SELECT period INTO r FROM api.portfolio_lookthrough(ARRAY['50088190000119']) LIMIT 1;
    IF r.period IS DISTINCT FROM DATE '2026-05-01' THEN
        RAISE EXCEPTION 'default month: got %, want 2026-05-01', r.period;
    END IF;

    -- Depth: ROOT -> MASTER -> CASH -> SANT is three quota levels.
    SELECT max(depth) INTO n FROM api.portfolio_lookthrough(ARRAY['50088190000119'], DATE '2026-05-01');
    IF n <> 3 THEN RAISE EXCEPTION 'XP-shaped chain depth: got %, want 3', n; END IF;
    SELECT max(depth) INTO n FROM api.portfolio_lookthrough(ARRAY['50088190000119'], DATE '2026-05-01', 2);
    IF n <> 2 THEN RAISE EXCEPTION 'depth cap 2: got %', n; END IF;
    SELECT max(depth) INTO n FROM api.portfolio_lookthrough(ARRAY['50088190000119'], DATE '2026-05-01', 1);
    IF n <> 1 THEN RAISE EXCEPTION 'depth cap 1: got %', n; END IF;
    -- At the cap the quota is not expanded and the row says so.
    SELECT count(*) INTO n FROM api.portfolio_lookthrough(ARRAY['50088190000119'], DATE '2026-05-01', 1)
     WHERE asset_kind = 'fund_quota_depth_cap' AND holder_cnpj = '35377390000106';
    IF n < 1 THEN RAISE EXCEPTION 'depth_cap row missing'; END IF;

    -- Weights. MASTER = (600 + 400) / 2000 = 0.5 of the root; CASH = 0.5 x 500/1000 = 0.25;
    -- SANT through CASH = 0.25 x 430/500 = 0.215, and directly 100/2000 = 0.05 (a second path).
    SELECT * INTO r FROM api.portfolio_lookthrough(ARRAY['50088190000119'], DATE '2026-05-01')
     WHERE holder_cnpj = '50088190000119' AND asset_key = '35377390000106';
    IF r.value_brl <> 1000 OR r.weight_in_root <> 0.5 OR r.asset_kind <> 'fund_quota' OR r.depth <> 0 THEN
        RAISE EXCEPTION 'MASTER edge: % % % %', r.value_brl, r.weight_in_root, r.asset_kind, r.depth;
    END IF;
    SELECT * INTO r FROM api.portfolio_lookthrough(ARRAY['50088190000119'], DATE '2026-05-01')
     WHERE holder_cnpj = '54891935000134' AND asset_key = '37525998000158';
    IF r.weight_in_root <> 0.215 OR r.depth <> 2 OR r.path <> ARRAY['50088190000119', '35377390000106', '54891935000134'] THEN
        RAISE EXCEPTION 'SANT via CASH: % % %', r.weight_in_root, r.depth, r.path;
    END IF;
    -- SANT is reached by two paths: its LFT appears once per path, each with its weight.
    SELECT count(*), sum(weight_in_root) INTO n, s FROM api.portfolio_lookthrough(ARRAY['50088190000119'], DATE '2026-05-01')
     WHERE holder_cnpj = '37525998000158' AND asset_kind = 'government_bond';
    -- via CASH: 0.215 x 400/800 = 0.1075; direct: 0.05 x 400/800 = 0.025.
    IF n <> 2 OR s <> 0.1325 THEN RAISE EXCEPTION 'two paths to SANT: % rows, weight %', n, s; END IF;

    -- A fund that holds its own holder is a cycle, flagged, and not looked through again.
    SELECT count(*) INTO n FROM api.portfolio_lookthrough(ARRAY['50088190000119'], DATE '2026-05-01')
     WHERE asset_kind = 'fund_quota_cycle' AND is_cycle AND holder_cnpj = '54891935000134' AND asset_key = '35377390000106';
    IF n <> 1 THEN RAISE EXCEPTION 'cycle row: got %', n; END IF;
    SELECT count(*) INTO n FROM api.portfolio_lookthrough(ARRAY['50088190000119'], DATE '2026-05-01', 6)
     WHERE depth > 3;
    IF n <> 0 THEN RAISE EXCEPTION 'a cycle was followed: % rows below depth 3', n; END IF;

    -- A held fund with no CDA is unfiled, never invented.
    SELECT count(*) INTO n FROM api.portfolio_lookthrough(ARRAY['50088190000119'], DATE '2026-05-01')
     WHERE asset_kind = 'fund_quota_unfiled' AND asset_key = '99999999000191';
    IF n <> 1 THEN RAISE EXCEPTION 'unfiled quota row: got %', n; END IF;

    -- Leaves. Block 1: the NTN-B is a bond, the repo is NOT a holding and sits apart.
    SELECT * INTO r FROM api.portfolio_lookthrough(ARRAY['50088190000119'], DATE '2026-05-01')
     WHERE block = 1 AND holder_cnpj = '50088190000119' AND asset_kind = 'government_bond';
    IF r.tp_titpub <> 'NOTAS DO TESOURO NACIONAL SERIE B' OR r.maturity <> DATE '2035-05-15'
       OR r.isin <> 'BRSTNCNTB3D4' OR r.weight_in_root <> 0.1 THEN
        RAISE EXCEPTION 'NTN-B: % % % %', r.tp_titpub, r.maturity, r.isin, r.weight_in_root;
    END IF;
    SELECT count(*) INTO n FROM api.portfolio_lookthrough(ARRAY['50088190000119'], DATE '2026-05-01')
     WHERE asset_kind = 'repo' AND value_brl = 50 AND tp_aplic = 'Operações Compromissadas';
    IF n <> 1 THEN RAISE EXCEPTION 'repo exposure row: got %', n; END IF;
    SELECT count(*) INTO n FROM api.portfolio_lookthrough(ARRAY['50088190000119'], DATE '2026-05-01')
     WHERE asset_kind = 'government_bond' AND value_brl = 50;
    IF n <> 0 THEN RAISE EXCEPTION 'repo counted as a government bond'; END IF;
    -- Block 4: the debenture's issuer is the ISIN code, never a CNPJ; the stock is a stock.
    SELECT * INTO r FROM api.portfolio_lookthrough(ARRAY['50088190000119'], DATE '2026-05-01')
     WHERE block = 4 AND asset_kind = 'debenture';
    IF r.issuer_code <> 'TAEE' OR r.issuer_cnpj IS NOT NULL OR r.weight_in_root <> 0.05 THEN
        RAISE EXCEPTION 'block 4 debenture: % % %', r.issuer_code, r.issuer_cnpj, r.weight_in_root;
    END IF;
    SELECT count(*) INTO n FROM api.portfolio_lookthrough(ARRAY['50088190000119'], DATE '2026-05-01')
     WHERE block = 4 AND asset_kind = 'stock' AND asset_key = 'PETR3';
    IF n <> 1 THEN RAISE EXCEPTION 'block 4 stock: got %', n; END IF;
    -- Block 6: a PJ issuer carries its CNPJ and indexer; a CPF is never served as a CNPJ.
    SELECT * INTO r FROM api.portfolio_lookthrough(ARRAY['50088190000119'], DATE '2026-05-01')
     WHERE block = 6 AND asset_key = 'DEB001';
    IF r.issuer_cnpj <> '60000000000100' OR r.indexer_code <> 'DI1' OR r.maturity <> DATE '2031-01-15' THEN
        RAISE EXCEPTION 'block 6 PJ: % % %', r.issuer_cnpj, r.indexer_code, r.maturity;
    END IF;
    SELECT * INTO r FROM api.portfolio_lookthrough(ARRAY['50088190000119'], DATE '2026-05-01')
     WHERE block = 6 AND asset_key = 'DEB002';
    IF r.issuer_cnpj IS NOT NULL THEN RAISE EXCEPTION 'a CPF was served as issuer_cnpj: %', r.issuer_cnpj; END IF;

    -- A root with no CDA: one explicit row.
    SELECT * INTO r FROM api.portfolio_lookthrough(ARRAY['55555555000191'], DATE '2026-05-01');
    IF r.asset_kind <> 'no_cda_filing' OR r.block IS NOT NULL OR r.depth <> 0 THEN
        RAISE EXCEPTION 'no_cda_filing: % % %', r.asset_kind, r.block, r.depth;
    END IF;
    RAISE NOTICE 'portfolio_lookthrough OK';
END $$;

-- The page edge: 1001 rows refuse with why and how, 1000 serve.
DO $$
DECLARE
    n INT;
BEGIN
    BEGIN
        PERFORM * FROM api.portfolio_lookthrough(ARRAY['44444444000191'], DATE '2026-05-01');
        RAISE EXCEPTION '1001 rows were served, expected a 22023 refusal';
    EXCEPTION WHEN sqlstate '22023' THEN
        IF SQLERRM NOT LIKE '%more than 1000 rows%' OR SQLERRM NOT LIKE '%To fix%' THEN
            RAISE EXCEPTION 'refusal without why/how: %', SQLERRM;
        END IF;
    END;
    DELETE FROM cvm_fi_cda_acoes WHERE cnpj = '44444444000191' AND cd_ativo = 'ZZ10013';
    SELECT count(*) INTO n FROM api.portfolio_lookthrough(ARRAY['44444444000191'], DATE '2026-05-01');
    IF n <> 1000 THEN RAISE EXCEPTION '1000 rows expected, got %', n; END IF;
    BEGIN
        PERFORM * FROM api.portfolio_lookthrough(ARRAY['50088190000119'], NULL, 7);
        RAISE EXCEPTION 'p_max_depth 7 was served';
    EXCEPTION WHEN sqlstate '22023' THEN NULL;
    END;
    RAISE NOTICE 'portfolio_lookthrough page edge OK';
END $$;

-- ===========================================================================
-- portfolio_movement (catalog v54): a fund's month against its own ANBIMA class
-- ===========================================================================
-- Own months, so the completeness rule is true here whatever else the file seeded:
-- 2019-12 (previous) and 2020-01 (judged) are the first periods of the family
-- (no trailing window yet counts as complete), with the same number of funds.
-- Fixture classes (the Extrato's classe_anbima, as filed):
--   'TESTE - ALFA - LIVRE'  299 funds: 294 spread evenly around 1.00 % (core), ATT a
--                           moderate outlier (2.10 %), two extreme funds on each side (+40 / +35 and
--                           -40 / -35 %). The 1st / 99th percentile of 299 values sits inside the
--                           core, so the extremes are clamped in the class's mean and sd and are NOT
--                           clamped in their own value.
--   'TESTE - POUCOS'        10 funds: under the minimum of 30 peers.
--   'TESTE - ZERO'          31 funds that did not move: a zero standard deviation.
--   NOCLASS (Extrato row, no classe_anbima), NOEXT (no Extrato row), NOPREV (no quota in
--   the previous month), an ETF, a FIDC and an unknown CNPJ: each says why.
INSERT INTO cvm_fi_diario (cnpj, id_subclasse, dt_comptc, vl_quota, vl_patrim_liq, raw)
SELECT '81' || lpad(i::text, 12, '0'), '', d.dt, d.q, 1000000, '{}'
FROM generate_series(1, 294) i
CROSS JOIN LATERAL (VALUES
    (DATE '2019-12-31', 1.0::numeric),
    (DATE '2020-01-31', 1.0 + (1.00 + (i - 147.5) * 0.005) / 100)) AS d(dt, q);
INSERT INTO cvm_fi_diario (cnpj, id_subclasse, dt_comptc, vl_quota, vl_patrim_liq, raw)
SELECT f.cnpj, '', d.dt, CASE WHEN d.dt = DATE '2019-12-31' THEN 1.0 ELSE 1.0 + f.ret / 100 END, 1000000, '{}'
FROM (VALUES ('82000000000001', 2.10::numeric), ('82000000000002', 40.00), ('82000000000003', -40.00),
             ('82000000000004', 35.00), ('82000000000005', -35.00)) AS f(cnpj, ret)
CROSS JOIN (VALUES (DATE '2019-12-31'), (DATE '2020-01-31')) AS d(dt);
-- POUCOS (10), ZERO (31): previous quota 1, current 1 + ret / 100 (ZERO: unchanged).
INSERT INTO cvm_fi_diario (cnpj, id_subclasse, dt_comptc, vl_quota, vl_patrim_liq, raw)
SELECT '84' || lpad(i::text, 12, '0'), '', d.dt, CASE WHEN d.dt = DATE '2019-12-31' THEN 1.0 ELSE 1.0 + i / 100.0 END, 1000000, '{}'
FROM generate_series(1, 10) i CROSS JOIN (VALUES (DATE '2019-12-31'), (DATE '2020-01-31')) AS d(dt);
INSERT INTO cvm_fi_diario (cnpj, id_subclasse, dt_comptc, vl_quota, vl_patrim_liq, raw)
SELECT '85' || lpad(i::text, 12, '0'), '', d.dt, 1.0, 1000000, '{}'
FROM generate_series(1, 31) i CROSS JOIN (VALUES (DATE '2019-12-31'), (DATE '2020-01-31')) AS d(dt);
-- NOCLASS, NOEXT, NOPREV (only the judged month), the ETF.
INSERT INTO cvm_fi_diario (cnpj, id_subclasse, dt_comptc, vl_quota, vl_patrim_liq, raw) VALUES
    ('83000000000001', '', '2019-12-31', 1.0, 1000000, '{}'), ('83000000000001', '', '2020-01-31', 1.01, 1000000, '{}'),
    ('83000000000002', '', '2019-12-31', 1.0, 1000000, '{}'), ('83000000000002', '', '2020-01-31', 1.01, 1000000, '{}'),
    ('83000000000003', '', '2020-01-31', 1.01, 1000000, '{}'),
    ('83000000000004', '', '2019-12-31', 1.0, 1000000, '{}'), ('83000000000004', '', '2020-01-31', 1.01, 1000000, '{}');
INSERT INTO cvm_etf_registry (ticker, cnpj, fund_name) VALUES ('MVTS11', '83000000000004', 'movement ETF');
INSERT INTO cvm_fund_registry (cnpj, entity_type, fund_name, status) VALUES
    ('82000000000001', 'fi', 'MOVEMENT ATT', 'Em Funcionamento Normal'),
    ('83000000000005', 'fidc', 'MOVEMENT FIDC', 'Em Funcionamento Normal');

INSERT INTO cvm_fi_extrato (cnpj, dt_comptc, source_file, tp_fundo_classe, classe_anbima, taxa_adm, raw)
SELECT '81' || lpad(i::text, 12, '0'), CURRENT_DATE - 20, 'extrato_fi.csv', 'FI', 'TESTE - ALFA - LIVRE', 1.0, '{}'
FROM generate_series(1, 294) i;
INSERT INTO cvm_fi_extrato (cnpj, dt_comptc, source_file, tp_fundo_classe, classe_anbima, taxa_adm, raw) VALUES
    ('82000000000001', CURRENT_DATE - 20, 'extrato_fi.csv', 'FI', 'TESTE - ALFA - LIVRE', 1.0, '{}'),
    ('82000000000002', CURRENT_DATE - 20, 'extrato_fi.csv', 'FI', 'TESTE - ALFA - LIVRE', 1.0, '{}'),
    ('82000000000003', CURRENT_DATE - 20, 'extrato_fi.csv', 'FI', 'TESTE - ALFA - LIVRE', 1.0, '{}'),
    ('82000000000004', CURRENT_DATE - 20, 'extrato_fi.csv', 'FI', 'TESTE - ALFA - LIVRE', 1.0, '{}'),
    ('82000000000005', CURRENT_DATE - 20, 'extrato_fi.csv', 'FI', 'TESTE - ALFA - LIVRE', 1.0, '{}'),
    ('83000000000001', CURRENT_DATE - 20, 'extrato_fi.csv', 'FI', NULL, 1.0, '{}'),
    ('83000000000003', CURRENT_DATE - 20, 'extrato_fi.csv', 'FI', 'TESTE - ALFA - LIVRE', 1.0, '{}');
INSERT INTO cvm_fi_extrato (cnpj, dt_comptc, source_file, tp_fundo_classe, classe_anbima, taxa_adm, raw)
SELECT '84' || lpad(i::text, 12, '0'), CURRENT_DATE - 20, 'extrato_fi.csv', 'FI', 'TESTE - POUCOS', 1.0, '{}'
FROM generate_series(1, 10) i;
INSERT INTO cvm_fi_extrato (cnpj, dt_comptc, source_file, tp_fundo_classe, classe_anbima, taxa_adm, raw)
SELECT '85' || lpad(i::text, 12, '0'), CURRENT_DATE - 20, 'extrato_fi.csv', 'FI', 'TESTE - ZERO', 1.0, '{}'
FROM generate_series(1, 31) i;

REFRESH MATERIALIZED VIEW public.fact_fund_monthly;
REFRESH MATERIALIZED VIEW public.mv_period_completeness;

DO $$
DECLARE
    r        RECORD;
    v_ids    TEXT[] := ARRAY['82000000000001', '82000000000002', '82000000000003', '81000000000001',
                             '84000000000001', '85000000000001', '83000000000001', '83000000000002',
                             '83000000000003', '83000000000004', '83000000000005', '83000000000099'];
    e_sd     NUMERIC;
    e_mean   NUMERIC;
    raw_sd   NUMERIC;
    n        INT;
BEGIN
    -- The month is complete by the serving rule, so every verdict below is about the data.
    IF NOT (SELECT is_complete FROM public.mv_period_completeness WHERE entity_type = 'fi' AND period = DATE '2020-01-01') THEN
        RAISE EXCEPTION 'fixture month 2020-01 is not complete: the test would prove nothing';
    END IF;

    -- The class statistics, recomputed here in plain SQL from the same quotas: winsorized
    -- at the class's own 1st / 99th percentile, mean and sample sd of the clamped values.
    WITH q AS (
        SELECT c.cnpj, (c.vl_quota / p.vl_quota - 1) * 100 AS ret
        FROM public.fact_fund_monthly c
        JOIN public.fact_fund_monthly p ON p.cnpj = c.cnpj AND p.entity_type = 'fi' AND p.period = DATE '2019-12-01'
        JOIN public.cvm_fi_extrato x ON x.cnpj = c.cnpj
        WHERE c.entity_type = 'fi' AND c.period = DATE '2020-01-01' AND x.classe_anbima = 'TESTE - ALFA - LIVRE'
    ), b AS (
        SELECT percentile_cont(0.01) WITHIN GROUP (ORDER BY ret)::numeric AS p01,
               percentile_cont(0.99) WITHIN GROUP (ORDER BY ret)::numeric AS p99 FROM q
    )
    SELECT avg(least(greatest(q.ret, b.p01), b.p99)), stddev_samp(least(greatest(q.ret, b.p01), b.p99)),
           stddev_samp(q.ret), count(*)
      INTO e_mean, e_sd, raw_sd, n
    FROM q, b;
    IF n <> 299 THEN RAISE EXCEPTION 'the fixture class should hold 299 funds with a return, has %', n; END IF;
    -- Winsorizing really changed the scale: the four extreme funds alone more than double the raw sd.
    IF NOT (e_sd * 2 < raw_sd) THEN
        RAISE EXCEPTION 'winsorization did not matter in the fixture: winsorized sd %, raw sd %', e_sd, raw_sd;
    END IF;

    -- ATT: a moderate outlier. STR_HI / STR_LO: beyond 3 on either side, and their OWN value is not clamped.
    SELECT * INTO r FROM api.portfolio_movement(ARRAY['82000000000001'], DATE '2020-01-20');
    IF r.level <> 'atencao' OR r.investigator_trigger OR NOT (abs(r.z) > 2 AND abs(r.z) <= 3) THEN
        RAISE EXCEPTION 'ATT should be atencao with 2 < |z| <= 3 and no trigger: %', row_to_json(r);
    END IF;
    IF r.month <> DATE '2020-01-01' OR r.class <> 'TESTE' OR r.subclass <> 'ALFA - LIVRE'
       OR r.class_as_filed <> 'TESTE - ALFA - LIVRE' OR r.n_peers <> 299 OR r.min_peers <> 30
       OR r.fund_name <> 'MOVEMENT ATT' OR r.own_value_pct <> 2.1 OR r.class_as_of IS NULL THEN
        RAISE EXCEPTION 'ATT identity columns wrong: %', row_to_json(r);
    END IF;
    IF abs(r.class_sd_pct - e_sd) > 0.000001 OR abs(r.class_mean_pct - e_mean) > 0.000001 THEN
        RAISE EXCEPTION 'class mean/sd are not the winsorized ones: served % / %, expected % / %',
            r.class_mean_pct, r.class_sd_pct, e_mean, e_sd;
    END IF;
    IF abs(r.z - (r.own_value_pct - r.class_mean_pct) / r.class_sd_pct) > 0.0001 THEN
        RAISE EXCEPTION 'z is not (own - mean) / sd: %', row_to_json(r);
    END IF;
    IF NOT (r.class_p01_pct < r.class_p99_pct) THEN RAISE EXCEPTION 'p01 / p99 not served: %', row_to_json(r); END IF;

    SELECT * INTO r FROM api.portfolio_movement(ARRAY['82000000000002'], DATE '2020-01-20');
    IF r.level <> 'forte' OR NOT r.investigator_trigger OR r.z <= 3 OR r.own_value_pct <> 40.0 THEN
        RAISE EXCEPTION 'STR_HI should be forte, trigger, own value 40.0 (not winsorized): %', row_to_json(r);
    END IF;
    IF r.own_value_pct <= r.class_p99_pct THEN
        RAISE EXCEPTION 'the fixture''s extreme is not above the winsorization bound: %', row_to_json(r);
    END IF;
    SELECT * INTO r FROM api.portfolio_movement(ARRAY['82000000000003'], DATE '2020-01-20');
    IF r.level <> 'forte' OR NOT r.investigator_trigger OR r.z >= -3 THEN
        RAISE EXCEPTION 'STR_LO should be forte with z < -3: %', row_to_json(r);
    END IF;
    SELECT * INTO r FROM api.portfolio_movement(ARRAY['81000000000001'], DATE '2020-01-20');
    IF r.level <> 'normal' OR r.investigator_trigger OR r.reason NOT LIKE '%299 fundos da classe TESTE - ALFA - LIVRE%' THEN
        RAISE EXCEPTION 'a core fund should be normal, with the sample in the reason: %', row_to_json(r);
    END IF;

    -- Every other shape is served, as nao_avaliado, with its reason; never skipped, never a zero.
    SELECT count(*) INTO n FROM api.portfolio_movement(v_ids, DATE '2020-01-20');
    IF n <> 12 THEN RAISE EXCEPTION 'one row per CNPJ expected (12), got %', n; END IF;
    FOR r IN SELECT * FROM api.portfolio_movement(v_ids, DATE '2020-01-20')
              WHERE cnpj IN ('84000000000001', '85000000000001', '83000000000001', '83000000000002',
                             '83000000000003', '83000000000004', '83000000000005', '83000000000099')
    LOOP
        IF r.level <> 'nao_avaliado' OR r.z IS NOT NULL OR r.investigator_trigger OR r.reason IS NULL THEN
            RAISE EXCEPTION 'expected nao_avaliado with a reason and no z: %', row_to_json(r);
        END IF;
        IF r.cnpj = '84000000000001' AND (r.n_peers <> 10 OR r.reason NOT LIKE 'apenas 10 fundos da classe TESTE - POUCOS%mínimo 30%'
                                          OR r.class_sd_pct IS NOT NULL OR r.own_value_pct <> 1.0) THEN
            RAISE EXCEPTION 'too few peers: %', row_to_json(r);
        END IF;
        IF r.cnpj = '85000000000001' AND (r.n_peers <> 31 OR r.reason NOT LIKE 'desvio padrão da classe TESTE - ZERO é zero%') THEN
            RAISE EXCEPTION 'zero sd: %', row_to_json(r);
        END IF;
        IF r.cnpj = '83000000000001' AND (r.class_as_filed IS NOT NULL OR r.reason NOT LIKE 'classe ANBIMA não informada%') THEN
            RAISE EXCEPTION 'no class: %', row_to_json(r);
        END IF;
        IF r.cnpj = '83000000000002' AND r.reason NOT LIKE 'fundo fora do Extrato%' THEN
            RAISE EXCEPTION 'outside the Extrato: %', row_to_json(r);
        END IF;
        IF r.cnpj = '83000000000003' AND r.reason NOT LIKE 'sem cota no mês anterior%' THEN
            RAISE EXCEPTION 'no previous quota: %', row_to_json(r);
        END IF;
        IF r.cnpj = '83000000000004' AND r.reason NOT LIKE 'ETF%' THEN
            RAISE EXCEPTION 'an ETF: %', row_to_json(r);
        END IF;
        IF r.cnpj = '83000000000005' AND r.reason NOT LIKE 'não é fundo FI%fidc%' THEN
            RAISE EXCEPTION 'a FIDC: %', row_to_json(r);
        END IF;
        IF r.cnpj = '83000000000099' AND r.reason NOT LIKE 'CNPJ não encontrado%' THEN
            RAISE EXCEPTION 'an unknown CNPJ: %', row_to_json(r);
        END IF;
    END LOOP;

    -- A month that is not complete is judged by nothing: every fund says so.
    SELECT * INTO r FROM api.portfolio_movement(ARRAY['82000000000002'], DATE '2099-01-01');
    IF r.level <> 'nao_avaliado' OR r.reason NOT LIKE '%incompleto%' OR r.n_peers IS NOT NULL OR r.z IS NOT NULL THEN
        RAISE EXCEPTION 'an incomplete month must not be judged: %', row_to_json(r);
    END IF;
    -- The default month is the last complete FI month and the call runs.
    SELECT count(*) INTO n FROM api.portfolio_movement(ARRAY['82000000000002']);
    IF n <> 1 THEN RAISE EXCEPTION 'the default month returned % rows', n; END IF;

    -- The thresholds, strictly greater: exactly 2 is normal, exactly 3 is atencao, on both signs.
    IF public.portfolio_movement_level(2) <> 'normal' OR public.portfolio_movement_level(-2) <> 'normal'
       OR public.portfolio_movement_level(3) <> 'atencao' OR public.portfolio_movement_level(-3) <> 'atencao'
       OR public.portfolio_movement_level(2.0000001) <> 'atencao' OR public.portfolio_movement_level(-3.0000001) <> 'forte'
       OR public.portfolio_movement_level(0) <> 'normal' OR public.portfolio_movement_level(NULL) IS NOT NULL THEN
        RAISE EXCEPTION 'the thresholds are not strictly greater than 2 and 3';
    END IF;

    -- Input guards and the refusal shape.
    BEGIN
        PERFORM * FROM api.portfolio_movement(ARRAY[]::text[]);
        RAISE EXCEPTION 'an empty set was served';
    EXCEPTION WHEN sqlstate '22023' THEN NULL;
    END;
    BEGIN
        PERFORM * FROM api.portfolio_movement(ARRAY['abc']);
        RAISE EXCEPTION 'a non-CNPJ was served';
    EXCEPTION WHEN sqlstate '22023' THEN NULL;
    END;
    BEGIN
        PERFORM * FROM api.portfolio_movement(ARRAY(SELECT lpad(i::text, 14, '0') FROM generate_series(1, 201) i), DATE '2020-01-01');
        RAISE EXCEPTION '201 CNPJs were served';
    EXCEPTION WHEN sqlstate '22023' THEN
        IF SQLERRM NOT LIKE '%more than 200%' OR SQLERRM NOT LIKE '%To fix%' THEN
            RAISE EXCEPTION 'refusal without why/how: %', SQLERRM;
        END IF;
    END;
    SELECT count(*) INTO n FROM api.portfolio_movement(ARRAY(SELECT lpad(i::text, 14, '0') FROM generate_series(1, 200) i), DATE '2020-01-01');
    IF n <> 200 THEN RAISE EXCEPTION '200 CNPJs expected to be served, got %', n; END IF;

    -- anon can call it and cannot call the internal threshold helper.
    SET LOCAL ROLE anon;
    SELECT count(*) INTO n FROM api.portfolio_movement(ARRAY['82000000000001'], DATE '2020-01-20');
    IF n <> 1 THEN RAISE EXCEPTION 'anon portfolio_movement: %', n; END IF;
    IF has_function_privilege('anon', 'public.portfolio_movement_level(numeric)', 'EXECUTE') THEN
        RAISE EXCEPTION 'anon can execute the internal threshold helper';
    END IF;
    RESET ROLE;
    RAISE NOTICE 'portfolio_movement OK';
END $$;

-- ===========================================================================
-- ETFs (catalog v56). The shapes measured 2026-10-03: CVM's Extrato, lâmina and
-- cad_fi carry no fee for any of the 178 active registry ETFs; etfsbrasil.com.br
-- prints one (BOVA11 0.10, IVVB11 0.23, B5P211 0.20, a fixed income ETF that is
-- not in COTAHIST); WRLD11's page prints another CNPJ than the registry's.
--   ETFA11  two snapshots: the newest fee (0.10) is served with its date.
--   ETFB11  the newest snapshot has no fee: the older one (0.50) is served; the
--           site's CNPJ differs from the registry's and the note says so.
--   ETFC11  no snapshot: NULL, the note says it is not a zero fee.
-- ===========================================================================
INSERT INTO cvm_etf_registry (ticker, cnpj, fund_name, is_active) VALUES
    ('ETFA11', '86000000000001', 'ETF ALFA CLASSE DE ÍNDICE', TRUE),
    ('ETFB11', '86000000000002', 'ETF BETA CLASSE DE ÍNDICE', TRUE),
    ('ETFC11', '86000000000003', 'ETF GAMA CLASSE DE ÍNDICE', TRUE);
INSERT INTO etf_market_snapshot (ticker, snapshot_date, source, cnpj, taxa_adm_pct) VALUES
    ('ETFA11', '2026-09-30', 'etfsbrasil', '86000000000001', 0.30),
    ('ETFA11', '2026-10-03', 'etfsbrasil', '86000000000001', 0.10),
    ('ETFB11', '2026-10-01', 'etfsbrasil', '86999999000199', 0.50),
    ('ETFB11', '2026-10-03', 'etfsbrasil', '86999999000199', NULL);

DO $$
DECLARE
    r RECORD;
    n INT;
BEGIN
    -- portfolio_resolve: a name that is exactly an ETF ticker gives the registry's CNPJ, never ambiguous.
    SELECT * INTO r FROM api.portfolio_resolve(ARRAY[' etfa11 ']) WHERE rank = 1;
    IF r.candidate_cnpj IS DISTINCT FROM '86000000000001' OR r.match_kind <> 'etf_ticker' OR r.ambiguous
       OR r.candidate_name IS DISTINCT FROM 'ETF ALFA CLASSE DE ÍNDICE' OR r.reason NOT LIKE '%ETF registry%' THEN
        RAISE EXCEPTION 'etf_ticker: % % % % %', r.candidate_cnpj, r.match_kind, r.ambiguous, r.candidate_name, r.reason;
    END IF;
    SELECT count(*) INTO n FROM api.portfolio_resolve(ARRAY['ETFA11']);
    IF n <> 1 THEN RAISE EXCEPTION 'etf_ticker: one candidate expected, got %', n; END IF;
    -- A supplied CNPJ still wins over a ticker-shaped name.
    SELECT * INTO r FROM api.portfolio_resolve(ARRAY['ETFA11'], ARRAY['22222222000191']) WHERE rank = 1;
    IF r.candidate_cnpj IS DISTINCT FROM '22222222000191' OR r.match_kind <> 'cnpj' THEN
        RAISE EXCEPTION 'cnpj over etf_ticker: % %', r.candidate_cnpj, r.match_kind;
    END IF;
    -- A ticker that is no ETF is not matched as one.
    SELECT count(*) INTO n FROM api.portfolio_resolve(ARRAY['PETR4']) WHERE match_kind = 'etf_ticker';
    IF n <> 0 THEN RAISE EXCEPTION 'PETR4 matched as an ETF'; END IF;

    -- portfolio_fees: no CVM source, so disclosed_* stay NULL; the site's fee comes in its own columns.
    SELECT * INTO r FROM api.portfolio_fees(ARRAY['86000000000001']);
    IF r.etf_ticker <> 'ETFA11' OR r.etf_site_taxa_adm <> 0.10 OR r.etf_site_as_of <> DATE '2026-10-03'
       OR r.etf_site_source <> 'etfsbrasil' OR r.disclosed_origin IS NOT NULL OR r.disclosed_taxa_adm IS NOT NULL
       OR r.fee_resolution IS NOT NULL OR r.etf_site_note NOT LIKE '%third-party site, not a CVM filing%'
       OR r.etf_site_note LIKE '%the site prints CNPJ%' THEN
        RAISE EXCEPTION 'ETFA11 fees: % % % % % %', r.etf_ticker, r.etf_site_taxa_adm, r.etf_site_as_of, r.disclosed_origin, r.fee_resolution, r.etf_site_note;
    END IF;
    SELECT * INTO r FROM api.portfolio_fees(ARRAY['86000000000002']);
    IF r.etf_site_taxa_adm <> 0.50 OR r.etf_site_as_of <> DATE '2026-10-01'
       OR r.etf_site_note NOT LIKE '%the site prints CNPJ 86999999000199 for this ticker%' THEN
        RAISE EXCEPTION 'ETFB11 fees: % % %', r.etf_site_taxa_adm, r.etf_site_as_of, r.etf_site_note;
    END IF;
    SELECT * INTO r FROM api.portfolio_fees(ARRAY['86000000000003']);
    IF r.etf_ticker <> 'ETFC11' OR r.etf_site_taxa_adm IS NOT NULL OR r.etf_site_as_of IS NOT NULL
       OR r.etf_site_note NOT LIKE '%NULL is not a zero fee' THEN
        RAISE EXCEPTION 'ETFC11 fees: % % %', r.etf_ticker, r.etf_site_taxa_adm, r.etf_site_note;
    END IF;
    -- A fund that is no ETF: every etf_* column NULL.
    SELECT * INTO r FROM api.portfolio_fees(ARRAY['61000000000191']);
    IF r.etf_ticker IS NOT NULL OR r.etf_site_taxa_adm IS NOT NULL OR r.etf_site_note IS NOT NULL THEN
        RAISE EXCEPTION 'non-ETF etf columns: % % %', r.etf_ticker, r.etf_site_taxa_adm, r.etf_site_note;
    END IF;
    RAISE NOTICE 'portfolio ETFs OK';
END $$;

-- ===========================================================================
-- Privileges: anon can call all three (the public silo-mcp reads as anon) and
-- cannot read the resolver's internal matview.
-- ===========================================================================
DO $$
DECLARE
    n INT;
BEGIN
    SET LOCAL ROLE anon;
    SELECT count(*) INTO n FROM api.portfolio_resolve(ARRAY['Alfa Renda Fixa FI']);
    IF n < 1 THEN RAISE EXCEPTION 'anon portfolio_resolve returned nothing'; END IF;
    SELECT count(*) INTO n FROM api.portfolio_fees(ARRAY['61000000000191']);
    IF n <> 1 THEN RAISE EXCEPTION 'anon portfolio_fees: %', n; END IF;
    SELECT count(*) INTO n FROM api.portfolio_lookthrough(ARRAY['55555555000191'], DATE '2026-05-01');
    IF n <> 1 THEN RAISE EXCEPTION 'anon portfolio_lookthrough: %', n; END IF;
    IF has_table_privilege('anon', 'public.mv_fund_name_history', 'SELECT') THEN
        RAISE EXCEPTION 'anon can read mv_fund_name_history';
    END IF;
    RESET ROLE;
    RAISE NOTICE 'portfolio grants OK';
END $$;

ROLLBACK;
