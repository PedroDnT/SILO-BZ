-- Executed checks for api.share_counts and api.free_float
-- (41_api_share_counts.sql, catalog v86, #1161). The Python tests pin the SQL
-- text; this proves the functions DO the right thing on rows. A synthetic
-- company (CVM code 99901), inside a transaction that is rolled back:
--
--   psql "$POSTGRES_URL" -v ON_ERROR_STOP=1 -f tests/sql/share_counts_behaviour.sql

BEGIN;

INSERT INTO cia_company (cd_cvm, cnpj_cia, denom_cia, raw)
VALUES ('99901', '11222333000181', 'SHRA SA', '{}');

-- An active listing: the FCA map plus 5 recent sessions on the tape.
INSERT INTO cia_ticker (cnpj_cia, data_refer, versao, codneg, raw)
VALUES ('11222333000181', '2026-01-01', 1, 'SHRA3', '{}');
INSERT INTO b3_cotahist
    (codneg, trade_date, tpmerc, codbdi, especi, preco_fechamento, fator_cotacao, negocios, isin, raw)
SELECT 'SHRA3', CURRENT_DATE - k, '010', '02', 'ON NM', 10, 1, 5, 'BRSHRAACNOR1', '{}'
FROM generate_series(1, 6) k;

-- Quarterly counts: 2025-03-31 refiled (version 2 wins); a DFP year end.
INSERT INTO cia_share_count
    (cnpj_cia, doc_type, dt_refer, versao, qt_ordin, qt_pref, qt_total,
     qt_ordin_tesouro, qt_pref_tesouro, qt_total_tesouro)
VALUES
    ('11222333000181', 'itr', '2025-03-31', 1, 100, 50, 150, 1, 0, 1),
    ('11222333000181', 'itr', '2025-03-31', 2, 110, 50, 160, 2, 0, 2),
    ('11222333000181', 'dfp', '2024-12-31', 1, 100, 50, 150, NULL, NULL, NULL);

-- FRE capital: 2015 version 3 wins over 1; two Integralizado rows in v3,
-- the newest approval wins; the other capital types are never served.
INSERT INTO cia_fre_capital
    (cnpj_cia, data_refer, versao, id_capital_social, tipo_capital, dt_autorizacao,
     qt_ordin, qt_pref, qt_total)
VALUES
    ('11222333000181', '2015-01-01', 1, 'a1', 'Capital Integralizado', '2014-01-01', 70, 30, 100),
    ('11222333000181', '2015-01-01', 3, 'b1', 'Capital Integralizado', '2013-01-01', 75, 30, 105),
    ('11222333000181', '2015-01-01', 3, 'b2', 'Capital Integralizado', '2014-06-01', 80, 30, 110),
    ('11222333000181', '2015-01-01', 3, 'b3', 'Capital Autorizado',    '2014-06-01', 500, 0, 500),
    ('11222333000181', '2016-01-01', 1, 'c1', 'Capital Emitido',       '2015-06-01', 90, 30, 120);

-- FRE free float: 2025 refiled (version 2 wins).
INSERT INTO cia_fre_free_float
    (cnpj_cia, data_refer, versao, n_acionistas_pf, n_acionistas_pj, n_acionistas_inst,
     qt_ordin_circ, pct_ordin_circ, qt_pref_circ, pct_pref_circ, qt_total_circ,
     pct_total_circ, dt_ultima_assembleia)
VALUES
    ('11222333000181', '2025-12-31', 1, 10, 2, 1, 40, 40.0, 20, 40.0, 60, 40.0, '2025-04-30'),
    ('11222333000181', '2025-12-31', 2, 11, 2, 1, 44, 40.0, 20, 40.0, 64, 40.0, '2025-04-30'),
    ('11222333000181', '2015-01-01', 1, 5, 1, 0, 30, 42.857143, NULL, NULL, 30, 30.0, NULL);

DO $$
DECLARE
    r RECORD;
    n INT;
BEGIN
    -- Newest version per period; FRE Integralizado only; newest first.
    SELECT count(*) INTO n FROM api.share_counts('11222333000181');
    IF n <> 3 THEN RAISE EXCEPTION 'share_counts: expected 3 rows, got %', n; END IF;

    SELECT * INTO r FROM api.share_counts('11222333000181') LIMIT 1;
    IF r.reference_date <> '2025-03-31' OR r.version <> 2 OR r.shares_total <> 160
       OR r.treasury_total <> 2 OR r.source <> 'cvm_itr' OR r.cd_cvm <> '99901' THEN
        RAISE EXCEPTION 'share_counts: newest quarter wrong: %', r;
    END IF;

    SELECT * INTO r FROM api.share_counts('11222333000181') WHERE source = 'cvm_fre';
    IF r.reference_date <> '2015-01-01' OR r.version <> 3 OR r.shares_total <> 110
       OR r.treasury_total IS NOT NULL THEN
        RAISE EXCEPTION 'share_counts: FRE row wrong: %', r;
    END IF;

    -- A DFP NULL treasury stays NULL.
    SELECT * INTO r FROM api.share_counts('11222333000181') WHERE source = 'cvm_dfp';
    IF r.treasury_total IS NOT NULL OR r.shares_total <> 150 THEN
        RAISE EXCEPTION 'share_counts: DFP row wrong: %', r;
    END IF;

    -- Ticker and CVM code resolve to the same company; the window bounds.
    SELECT count(*) INTO n FROM api.share_counts('SHRA3');
    IF n <> 3 THEN RAISE EXCEPTION 'share_counts: ticker gave % rows', n; END IF;
    SELECT count(*) INTO n FROM api.share_counts('99901', '2020-01-01', '2024-12-31');
    IF n <> 1 THEN RAISE EXCEPTION 'share_counts: window gave % rows', n; END IF;

    -- An unknown id returns no rows.
    SELECT count(*) INTO n FROM api.share_counts('ZZZZ3');
    IF n <> 0 THEN RAISE EXCEPTION 'share_counts: unknown id gave % rows', n; END IF;

    -- free_float: newest version per date, newest first, NULL stays NULL.
    SELECT count(*) INTO n FROM api.free_float('SHRA3');
    IF n <> 2 THEN RAISE EXCEPTION 'free_float: expected 2 rows, got %', n; END IF;
    SELECT * INTO r FROM api.free_float('SHRA3') LIMIT 1;
    IF r.reference_date <> '2025-12-31' OR r.version <> 2 OR r.float_total <> 64
       OR r.holders_individual <> 11 OR r.float_total_pct <> 40.0 OR r.source <> 'cvm_fre' THEN
        RAISE EXCEPTION 'free_float: newest row wrong: %', r;
    END IF;
    SELECT * INTO r FROM api.free_float('SHRA3') WHERE reference_date = '2015-01-01';
    IF r.float_pn IS NOT NULL OR r.last_meeting_date IS NOT NULL THEN
        RAISE EXCEPTION 'free_float: NULL was filled: %', r;
    END IF;

    -- Refusals.
    BEGIN
        PERFORM api.share_counts('');
        RAISE EXCEPTION 'share_counts: empty p_id was accepted';
    EXCEPTION WHEN invalid_parameter_value THEN NULL;
    END;
    BEGIN
        PERFORM api.free_float(NULL);
        RAISE EXCEPTION 'free_float: NULL p_id was accepted';
    EXCEPTION WHEN invalid_parameter_value THEN NULL;
    END;
    BEGIN
        PERFORM api.share_counts('SHRA3', '2026-03-05', '2026-03-01');
        RAISE EXCEPTION 'share_counts: p_from after p_to was accepted';
    EXCEPTION WHEN invalid_parameter_value THEN NULL;
    END;
    BEGIN
        PERFORM api.free_float('SHRA3', '2026-03-05', '2026-03-01');
        RAISE EXCEPTION 'free_float: p_from after p_to was accepted';
    EXCEPTION WHEN invalid_parameter_value THEN NULL;
    END;

    RAISE NOTICE 'share_counts and free_float OK';
END $$;

-- The page edge refuses (22023) instead of trimming.
INSERT INTO cia_share_count (cnpj_cia, doc_type, dt_refer, versao, qt_total)
SELECT '11222333000181', 'itr', DATE '1900-01-01' + k, 1, 1
FROM generate_series(1, 1000) k;
INSERT INTO cia_fre_free_float (cnpj_cia, data_refer, versao, qt_total_circ)
SELECT '11222333000181', DATE '1900-01-01' + k, 1, 1
FROM generate_series(1, 1000) k;
DO $$
BEGIN
    BEGIN
        PERFORM api.share_counts('SHRA3');
        RAISE EXCEPTION 'share_counts: more than 1000 rows were not refused';
    EXCEPTION WHEN invalid_parameter_value THEN NULL;
    END;
    BEGIN
        PERFORM api.free_float('SHRA3');
        RAISE EXCEPTION 'free_float: more than 1000 rows were not refused';
    EXCEPTION WHEN invalid_parameter_value THEN NULL;
    END;
END $$;

-- anon can call both.
SET LOCAL ROLE anon;
SELECT count(*) FROM api.share_counts('SHRA3', '2025-01-01', '2025-12-31');
SELECT count(*) FROM api.free_float('SHRA3', '2025-01-01', '2025-12-31');
RESET ROLE;

ROLLBACK;
