-- Executed checks for api.dividends (40_api_dividends.sql, catalog v84, #1157).
-- The Python tests pin the SQL text; this proves the function DOES the right
-- thing on rows. Synthetic tickers (DIVA4, DIVF11), inside a transaction that
-- is rolled back:
--
--   psql "$POSTGRES_URL" -v ON_ERROR_STOP=1 -f tests/sql/dividends_behaviour.sql

BEGIN;

-- The tape: DIVA4 (class PN), DIVA3 (class ON, same company), DIVF11 (a fund
-- that pays only in the supplement). Sessions on 2026-03-02..06 and 03-09.
INSERT INTO b3_cotahist
    (codneg, trade_date, tpmerc, codbdi, especi, preco_fechamento, fator_cotacao, negocios, isin, raw)
SELECT c.codneg, d, '010', '02', c.especi, 10, 1, 5, c.isin, '{}'
FROM (VALUES ('DIVA4', 'PN N2', 'BRDIVAACNPR1'),
             ('DIVA3', 'ON N2', 'BRDIVAACNOR1'),
             ('DIVF11', 'CI', 'BRDIVFCTF001')) c(codneg, especi, isin),
     unnest(ARRAY['2026-03-02','2026-03-03','2026-03-04','2026-03-05','2026-03-06','2026-03-09']::date[]) d;

-- B3's history, PN and ON. Rows quoted per 1000 shares stay per share.
INSERT INTO b3_cash_dividend
    (issuing_company, trading_name, cnpj, type_stock, corporate_action, date_approval,
     last_date_prior_ex, value_cash, quoted_per_shares, date_closing_price_prior_ex,
     closing_price_prior_ex, corporate_action_price, occurrence, raw)
VALUES
    -- one dividend, one payment date in the supplement
    ('DIVA', 'DIVA SA', NULL, 'PN', 'DIVIDENDO', '2026-02-20', '2026-03-02', 0.5, 1, '2026-03-02', 10, 5, 1, '{}'),
    -- JCP in two identical installments; the supplement has two dates
    ('DIVA', 'DIVA SA', NULL, 'PN', 'JRS CAP PROPRIO', '2026-02-20', '2026-03-03', 0.2, 1, '2026-03-03', 10, 2, 1, '{}'),
    ('DIVA', 'DIVA SA', NULL, 'PN', 'JRS CAP PROPRIO', '2026-02-20', '2026-03-03', 0.2, 1, '2026-03-03', 10, 2, 2, '{}'),
    -- three identical installments, only two supplement dates: ambiguous
    ('DIVA', 'DIVA SA', NULL, 'PN', 'DIVIDENDO', '2026-02-20', '2026-03-04', 0.1, 1, '2026-03-04', 10, 1, 1, '{}'),
    ('DIVA', 'DIVA SA', NULL, 'PN', 'DIVIDENDO', '2026-02-20', '2026-03-04', 0.1, 1, '2026-03-04', 10, 1, 2, '{}'),
    ('DIVA', 'DIVA SA', NULL, 'PN', 'DIVIDENDO', '2026-02-20', '2026-03-04', 0.1, 1, '2026-03-04', 10, 1, 3, '{}'),
    -- an old record quoted per 1000 shares, before the tape: no ex_date, no payment date
    ('DIVA', 'DIVA SA', NULL, 'PN', 'DIVIDENDO', '1998-04-01', '1998-04-30', 2500, 1000, '1998-04-30', 50000, 5, 1, '{}'),
    -- the ON class: never served for DIVA4
    ('DIVA', 'DIVA SA', NULL, 'ON', 'DIVIDENDO', '2026-02-20', '2026-03-02', 0.45, 1, '2026-03-02', 10, 4.5, 1, '{}');

-- B3's supplement, per ISIN, with payment dates.
INSERT INTO b3_corporate_event
    (issuing_company, isin, event_class, label, last_date_prior, approved_on, rate, payment_date, raw)
VALUES
    ('DIVA', 'BRDIVAACNPR1', 'cash', 'DIVIDENDO',       '2026-03-02', '2026-02-20', 0.5, '2026-04-15', '{}'),
    ('DIVA', 'BRDIVAACNPR1', 'cash', 'JRS CAP PROPRIO', '2026-03-03', '2026-02-20', 0.2, '2026-05-20', '{}'),
    ('DIVA', 'BRDIVAACNPR1', 'cash', 'JRS CAP PROPRIO', '2026-03-03', '2026-02-20', 0.2, '2026-06-22', '{}'),
    ('DIVA', 'BRDIVAACNPR1', 'cash', 'DIVIDENDO',       '2026-03-04', '2026-02-20', 0.1, '2026-05-01', '{}'),
    ('DIVA', 'BRDIVAACNPR1', 'cash', 'DIVIDENDO',       '2026-03-04', '2026-02-20', 0.1, '2026-06-01', '{}'),
    -- declared after the history was fetched: served from the supplement
    ('DIVA', 'BRDIVAACNPR1', 'cash', 'DIVIDENDO',       '2026-03-06', '2026-03-01', 0.3, '2026-07-01', '{}'),
    -- the ON class's ISIN: never served for DIVA4
    ('DIVA', 'BRDIVAACNOR1', 'cash', 'DIVIDENDO',       '2026-03-02', '2026-02-20', 0.45, '2026-04-15', '{}'),
    -- a fund: the supplement only
    ('DIVF', 'BRDIVFCTF001', 'cash', 'RENDIMENTO',      '2026-03-05', '2026-03-01', 0.09, '2026-03-13', '{}');

DO $$
DECLARE
    n INT;
    r RECORD;
BEGIN
    SELECT count(*) INTO n FROM api.dividends('diva4');
    IF n <> 8 THEN RAISE EXCEPTION 'DIVA4: expected 8 rows (7 history PN + 1 supplement), got %', n; END IF;

    IF EXISTS (SELECT 1 FROM api.dividends('DIVA4') WHERE share_class <> 'PN' OR value_per_share = 0.45) THEN
        RAISE EXCEPTION 'DIVA4 served another share class';
    END IF;

    SELECT * INTO r FROM api.dividends('DIVA4') WHERE last_date_with = '2026-03-02';
    IF r.ex_date <> '2026-03-03' OR r.payment_date <> '2026-04-15' OR r.isin <> 'BRDIVAACNPR1'
       OR r.source <> 'b3_cash_history' OR r.close_prior_ex <> 10 OR r.yield_pct <> 5 THEN
        RAISE EXCEPTION 'single dividend wrong: %', r;
    END IF;

    -- installments: the k-th takes the k-th payment date
    IF (SELECT array_agg(payment_date ORDER BY installment) FROM api.dividends('DIVA4')
         WHERE last_date_with = '2026-03-03') <> ARRAY['2026-05-20', '2026-06-22']::date[] THEN
        RAISE EXCEPTION 'installment payment dates not assigned in order';
    END IF;

    -- 3 installments, 2 dates: NULL, never a guess
    IF EXISTS (SELECT 1 FROM api.dividends('DIVA4')
                WHERE last_date_with = '2026-03-04' AND payment_date IS NOT NULL) THEN
        RAISE EXCEPTION 'an ambiguous payment date was guessed';
    END IF;

    -- old record: per share, no ex_date (no tape), no payment date
    SELECT * INTO r FROM api.dividends('DIVA4') WHERE last_date_with = '1998-04-30';
    IF r.value_per_share <> 2.5 OR r.close_prior_ex <> 50 OR r.ex_date IS NOT NULL OR r.payment_date IS NOT NULL THEN
        RAISE EXCEPTION 'per-1000 record wrong: %', r;
    END IF;

    -- supplement-only event
    SELECT * INTO r FROM api.dividends('DIVA4') WHERE last_date_with = '2026-03-06';
    IF r.source <> 'b3_supplement' OR r.payment_date <> '2026-07-01' OR r.ex_date <> '2026-03-09'
       OR r.value_per_share <> 0.3 OR r.close_prior_ex IS NOT NULL THEN
        RAISE EXCEPTION 'supplement-only row wrong: %', r;
    END IF;

    -- newest first
    IF (SELECT last_date_with FROM api.dividends('DIVA4') LIMIT 1) <> '2026-03-06' THEN
        RAISE EXCEPTION 'not newest first';
    END IF;

    -- the window bounds last_date_with
    SELECT count(*) INTO n FROM api.dividends('DIVA4', '2026-03-03', '2026-03-04');
    IF n <> 5 THEN RAISE EXCEPTION 'window: expected 5 rows, got %', n; END IF;

    -- a fund paying only in the supplement
    SELECT * INTO r FROM api.dividends('DIVF11');
    IF r.action <> 'RENDIMENTO' OR r.payment_date <> '2026-03-13' OR r.share_class <> 'CI' THEN
        RAISE EXCEPTION 'fund row wrong: %', r;
    END IF;

    -- a ticker with no cash print: no rows
    SELECT count(*) INTO n FROM api.dividends('NOPE3');
    IF n <> 0 THEN RAISE EXCEPTION 'unknown ticker returned rows'; END IF;

    -- refusals
    BEGIN
        PERFORM api.dividends(NULL);
        RAISE EXCEPTION 'no ticker was accepted';
    EXCEPTION WHEN invalid_parameter_value THEN NULL;
    END;
    BEGIN
        PERFORM api.dividends('DIVA4', '2026-03-05', '2026-03-01');
        RAISE EXCEPTION 'p_from after p_to was accepted';
    EXCEPTION WHEN invalid_parameter_value THEN NULL;
    END;

    RAISE NOTICE 'dividends OK';
END $$;

-- The page edge refuses (22023) instead of trimming.
INSERT INTO b3_cash_dividend
    (issuing_company, trading_name, type_stock, corporate_action, last_date_prior_ex,
     value_cash, quoted_per_shares, occurrence, raw)
SELECT 'DIVA', 'DIVA SA', 'PN', 'DIVIDENDO', DATE '2000-01-01' + k, 0.01, 1, 1, '{}'
FROM generate_series(1, 1000) k;
DO $$
BEGIN
    PERFORM api.dividends('DIVA4');
    RAISE EXCEPTION 'more than 1000 rows were not refused';
EXCEPTION WHEN invalid_parameter_value THEN NULL;
END $$;

-- anon can call it.
SET LOCAL ROLE anon;
SELECT count(*) FROM api.dividends('DIVA4', '2026-01-01', '2026-12-31');
RESET ROLE;

ROLLBACK;
