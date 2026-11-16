-- Executed checks for api.debt_issues (43_api_debt_issues.sql, catalog v88,
-- #1164). The Python tests pin the SQL text; this proves the function DOES the
-- right thing on rows. A synthetic company (CVM code 99902), inside a
-- transaction that is rolled back:
--
--   psql "$POSTGRES_URL" -v ON_ERROR_STOP=1 -f tests/sql/debt_issues_behaviour.sql

BEGIN;

INSERT INTO cia_company (cd_cvm, cnpj_cia, denom_cia, raw)
VALUES ('99902', '11222333000262', 'DEBT SA', '{}');

-- An active listing: the FCA map plus 6 recent sessions on the tape.
INSERT INTO cia_ticker (cnpj_cia, data_refer, versao, codneg, raw)
VALUES ('11222333000262', '2026-01-01', 1, 'DEBT3', '{}');
INSERT INTO b3_cotahist
    (codneg, trade_date, tpmerc, codbdi, especi, preco_fechamento, fator_cotacao, negocios, isin, raw)
SELECT 'DEBT3', CURRENT_DATE - k, '010', '02', 'ON NM', 10, 1, 5, 'BRDEBTACNOR1', '{}'
FROM generate_series(1, 6) k;

-- 2025-12-31 was refiled: version 2 (two issues) wins over version 1.
-- 2015-12-31 has one version and empty flags, which stay NULL.
INSERT INTO cvm_fre_outro_valor_mobiliario
    (cnpj_cia, data_refer, versao, id_documento, row_hash, valor_mobiliario,
     identificacao, data_emissao, data_vencimento, quantidade, valor, saldo_devedor,
     restricao_circulacao, conversibilidade, resgatavel, caracteristicas_divida)
VALUES
    ('11222333000262', '2025-12-31', 1, 'd1', 'h1', 'Debêntures', '1ª Emissão',
     '2020-01-15', '2030-01-15', 100, 1000, 900, TRUE, FALSE, TRUE, 'old text'),
    ('11222333000262', '2025-12-31', 2, 'd2', 'h2', 'Debêntures', '1ª Emissão',
     '2020-01-15', '2030-01-15', 100, 1000, 880, TRUE, FALSE, TRUE, 'IPCA + 5,00% a.a.'),
    ('11222333000262', '2025-12-31', 2, 'd2', 'h3', 'Nota Comercial', '1ª Emissão de Notas',
     '2024-03-01', '2027-03-01', 50, 500, 500, NULL, NULL, NULL, '100% DI + 1,20% a.a.'),
    ('11222333000262', '2015-12-31', 1, 'd0', 'h0', 'Debêntures', '2ª Emissão',
     '2012-06-15', NULL, 10, 100, 40, NULL, NULL, NULL, NULL);

DO $$
DECLARE
    r RECORD;
    n INT;
BEGIN
    -- Newest version per reference date: 2 rows of 2025 v2 + 1 row of 2015.
    SELECT count(*) INTO n FROM api.debt_issues('11222333000262');
    IF n <> 3 THEN RAISE EXCEPTION 'debt_issues: expected 3 rows, got %', n; END IF;
    SELECT count(*) INTO n FROM api.debt_issues('11222333000262') WHERE version = 1
        AND reference_date = '2025-12-31';
    IF n <> 0 THEN RAISE EXCEPTION 'debt_issues: an old version was served'; END IF;

    -- Newest reference date first, then nearest maturity.
    SELECT * INTO r FROM api.debt_issues('DEBT3') LIMIT 1;
    IF r.reference_date <> '2025-12-31' OR r.version <> 2 OR r.security_type <> 'Nota Comercial'
       OR r.maturity_date <> '2027-03-01' OR r.cd_cvm <> '99902' OR r.source <> 'cvm_fre'
       OR r.company <> 'DEBT SA' THEN
        RAISE EXCEPTION 'debt_issues: first row wrong: %', r;
    END IF;

    -- Values and the terms text are served as filed; nothing is parsed.
    SELECT * INTO r FROM api.debt_issues('DEBT3') WHERE security_type = 'Debêntures'
        AND reference_date = '2025-12-31';
    IF r.outstanding_balance <> 880 OR r.terms_text <> 'IPCA + 5,00% a.a.'
       OR r.transfer_restricted IS NOT TRUE OR r.convertible IS NOT FALSE THEN
        RAISE EXCEPTION 'debt_issues: values not as filed: %', r;
    END IF;

    -- Empty flags and a missing maturity stay NULL.
    SELECT * INTO r FROM api.debt_issues('99902') WHERE reference_date = '2015-12-31';
    IF r.transfer_restricted IS NOT NULL OR r.redeemable IS NOT NULL
       OR r.maturity_date IS NOT NULL OR r.terms_text IS NOT NULL THEN
        RAISE EXCEPTION 'debt_issues: NULL was filled: %', r;
    END IF;

    -- The window bounds the reference date.
    SELECT count(*) INTO n FROM api.debt_issues('99902', '2010-01-01', '2020-12-31');
    IF n <> 1 THEN RAISE EXCEPTION 'debt_issues: window gave % rows', n; END IF;

    -- An unknown id returns no rows.
    SELECT count(*) INTO n FROM api.debt_issues('ZZZZ3');
    IF n <> 0 THEN RAISE EXCEPTION 'debt_issues: unknown id gave % rows', n; END IF;

    -- Refusals.
    BEGIN
        PERFORM api.debt_issues('');
        RAISE EXCEPTION 'debt_issues: empty p_id was accepted';
    EXCEPTION WHEN invalid_parameter_value THEN NULL;
    END;
    BEGIN
        PERFORM api.debt_issues(NULL);
        RAISE EXCEPTION 'debt_issues: NULL p_id was accepted';
    EXCEPTION WHEN invalid_parameter_value THEN NULL;
    END;
    BEGIN
        PERFORM api.debt_issues('DEBT3', '2026-03-05', '2026-03-01');
        RAISE EXCEPTION 'debt_issues: p_from after p_to was accepted';
    EXCEPTION WHEN invalid_parameter_value THEN NULL;
    END;

    RAISE NOTICE 'debt_issues OK';
END $$;

-- The page edge refuses (22023) instead of trimming.
INSERT INTO cvm_fre_outro_valor_mobiliario
    (cnpj_cia, data_refer, versao, id_documento, row_hash)
SELECT '11222333000262', DATE '2025-12-31', 2, 'd2', 'bulk' || k
FROM generate_series(1, 1000) k;
DO $$
BEGIN
    BEGIN
        PERFORM api.debt_issues('DEBT3');
        RAISE EXCEPTION 'debt_issues: more than 1000 rows were not refused';
    EXCEPTION WHEN invalid_parameter_value THEN NULL;
    END;
END $$;

-- anon can call it.
SET LOCAL ROLE anon;
SELECT count(*) FROM api.debt_issues('DEBT3', '2010-01-01', '2020-12-31');
RESET ROLE;

ROLLBACK;
