-- Executed checks for vw_company_ticker.is_active (migration 63, #381). The
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

    -- Still one row per (company, ticker), and nothing without a ticker.
    SELECT count(*) INTO n FROM vw_company_ticker
     WHERE cnpj_cia LIKE '990000000000%';
    ASSERT n = 7, format('expected 7 view rows, got %s', n);

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
