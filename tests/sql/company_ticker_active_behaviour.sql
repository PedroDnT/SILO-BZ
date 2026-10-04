-- Executed checks for vw_company_ticker.is_active (migrations 63 and 69, #381). The
-- Python tests pin the SQL text; this proves the view DOES the right thing on
-- rows. Synthetic CNPJs (990000000000NN) and tickers, inside a transaction that
-- is rolled back, so it runs on any database with the schema and migrations
-- applied (CI's sql-compile job, or a scratch copy):
--
--   psql "$POSTGRES_URL" -v ON_ERROR_STOP=1 -f tests/sql/company_ticker_active_behaviour.sql

BEGIN;

-- Company 01: the three cases the issue names.
--   OLDA3 : only in the 2025 filing, with no end date (a delisted ticker that
--           just vanished from the FCA)                        -> inactive
--   KEPT3 : in 2025 and in the newest (2026) filing, no end     -> active
--   ENDD3 : in the newest filing with Data_Fim_Negociacao set   -> inactive
INSERT INTO cia_ticker
    (cnpj_cia, data_refer, versao, valor_mobiliario, codneg, mercado, dt_fim_neg)
VALUES
    ('99000000000001', '2025-01-01', 1, 'Ações Ordinárias', 'OLDA3', 'Bolsa', NULL),
    ('99000000000001', '2025-01-01', 1, 'Ações Ordinárias', 'KEPT3', 'Bolsa', NULL),
    ('99000000000001', '2026-01-01', 1, 'Ações Ordinárias', 'KEPT3', 'Bolsa', NULL),
    ('99000000000001', '2026-01-01', 1, 'Ações Ordinárias', 'ENDD3', 'Bolsa', '2026-03-02');

-- Company 02: the newest filing is a later VERSION of the same year and lists
-- only NEWV3, so V1ST3 (version 1 only) is no longer listed -> inactive.
INSERT INTO cia_ticker
    (cnpj_cia, data_refer, versao, valor_mobiliario, codneg, mercado, dt_fim_neg)
VALUES
    ('99000000000002', '2026-01-01', 1, 'Ações Ordinárias', 'V1ST3', 'Bolsa', NULL),
    ('99000000000002', '2026-01-01', 2, 'Ações Ordinárias', 'NEWV3', 'Bolsa', NULL);

-- Company 03: the newest filing has only a security with no ticker (a
-- debenture). The filing exists, it does not list LOST3 -> inactive, and the
-- null-ticker row never appears in the view.
INSERT INTO cia_ticker
    (cnpj_cia, data_refer, versao, valor_mobiliario, codneg, mercado, dt_fim_neg)
VALUES
    ('99000000000003', '2025-01-01', 1, 'Ações Ordinárias', 'LOST3', 'Bolsa', NULL),
    ('99000000000003', '2026-01-01', 1, 'Debêntures', NULL, 'Balcão Organizado', NULL);

-- Company 04: one filing, no end date -> active (the plain case is unchanged).
INSERT INTO cia_ticker
    (cnpj_cia, data_refer, versao, valor_mobiliario, codneg, mercado, dt_fim_neg)
VALUES
    ('99000000000004', '2026-01-01', 1, 'Ações Ordinárias', 'ONLY3', 'Bolsa', NULL);

-- Company 05 (migration 69): the liquidity rule. Every ticker is in the
-- newest filing with no end date, so only the tape decides.
--   LIQ53 : 5 sessions in the last 30 days                      -> active
--   THIN3 : 4 sessions in the last 30 days                      -> inactive
--   STAL3 : 6 sessions, all more than 30 days ago               -> inactive
--   ZERO3 : 5 rows in the window, but 2 with no trade (negocios 0)  -> inactive
--   BRDS3 : 5 sessions, two boards printed on each               -> active
--   NOTP3 : never on the tape                                    -> inactive
INSERT INTO cia_ticker
    (cnpj_cia, data_refer, versao, valor_mobiliario, codneg, mercado, dt_fim_neg)
SELECT '99000000000005', '2026-01-01', 1, 'Ações Ordinárias', c, 'Bolsa', NULL
FROM unnest(ARRAY['LIQ53', 'THIN3', 'STAL3', 'ZERO3', 'BRDS3', 'NOTP3']) c;

-- Tape rows. The tickers the earlier companies expect active (KEPT3, NEWV3,
-- ONLY3) trade 5 sessions in the window; the inactive ones need no rows.
INSERT INTO b3_cotahist
    (codneg, trade_date, tpmerc, codbdi, especi, preco_fechamento, fator_cotacao, negocios, isin, raw)
SELECT c, current_date - k, '010', '02', 'ON', 10, 1, 7, 'BR' || left(c, 4) || 'ACNOR1', '{}'
FROM unnest(ARRAY['KEPT3', 'NEWV3', 'ONLY3', 'LIQ53', 'BRDS3']) c,
     generate_series(1, 25, 6) k;                     -- 1, 7, 13, 19, 25: 5 sessions
INSERT INTO b3_cotahist
    (codneg, trade_date, tpmerc, codbdi, especi, preco_fechamento, fator_cotacao, negocios, isin, raw)
SELECT 'BRDS3', current_date - k, '010', '96', 'ON', 10, 1, 1, 'BRBRDSACNOR1', '{}'
FROM generate_series(1, 25, 6) k;                     -- a second board, same 5 sessions
INSERT INTO b3_cotahist
    (codneg, trade_date, tpmerc, codbdi, especi, preco_fechamento, fator_cotacao, negocios, isin, raw)
SELECT 'THIN3', current_date - k, '010', '02', 'ON', 10, 1, 3, 'BRTHINACNOR1', '{}'
FROM generate_series(1, 19, 6) k;                     -- 4 sessions
INSERT INTO b3_cotahist
    (codneg, trade_date, tpmerc, codbdi, especi, preco_fechamento, fator_cotacao, negocios, isin, raw)
SELECT 'STAL3', current_date - k, '010', '02', 'ON', 10, 1, 9, 'BRSTALACNOR1', '{}'
FROM generate_series(31, 41, 2) k;                    -- 6 sessions, all older than 30 days
INSERT INTO b3_cotahist
    (codneg, trade_date, tpmerc, codbdi, especi, preco_fechamento, fator_cotacao, negocios, isin, raw)
SELECT 'ZERO3', current_date - k, '010', '02', 'ON', 10, 1,
       CASE WHEN k IN (7, 13) THEN 0 ELSE 4 END, 'BRZEROACNOR1', '{}'
FROM generate_series(1, 25, 6) k;                     -- 5 rows, 3 with trades

DO $$
DECLARE
    got  text;
    want text;
    n    int;
BEGIN
    SELECT string_agg(codneg || '=' || is_active::text, ',' ORDER BY codneg)
      INTO got
      FROM vw_company_ticker
     WHERE cnpj_cia IN ('99000000000001', '99000000000002',
                        '99000000000003', '99000000000004');
    want := 'ENDD3=false,KEPT3=true,LOST3=false,NEWV3=true,OLDA3=false,'
            'ONLY3=true,V1ST3=false';
    ASSERT got = want, format('is_active per ticker: got %s, want %s', got, want);

    -- Migration 69: at least 5 sessions with trades in the last 30 days.
    SELECT string_agg(codneg || '=' || is_active::text, ',' ORDER BY codneg)
      INTO got
      FROM vw_company_ticker
     WHERE cnpj_cia = '99000000000005';
    want := 'BRDS3=true,LIQ53=true,NOTP3=false,STAL3=false,THIN3=false,ZERO3=false';
    ASSERT got = want, format('liquidity per ticker: got %s, want %s', got, want);

    -- Still one row per (company, ticker), and nothing without a ticker.
    SELECT count(*) INTO n FROM vw_company_ticker
     WHERE cnpj_cia LIKE '990000000000%';
    ASSERT n = 13, format('expected 13 view rows, got %s', n);

    -- The column list and order are the ones migration 25 created.
    SELECT string_agg(column_name, ',' ORDER BY ordinal_position) INTO got
      FROM information_schema.columns
     WHERE table_schema = 'public' AND table_name = 'vw_company_ticker';
    want := 'cnpj_cia,codneg,valor_mobiliario,sigla_classe,mercado,segmento,'
            'dt_inicio_neg,dt_fim_neg,is_active,data_refer,versao';
    ASSERT got = want, format('view columns: got %s, want %s', got, want);

    RAISE NOTICE 'vw_company_ticker.is_active OK';
END $$;

ROLLBACK;
