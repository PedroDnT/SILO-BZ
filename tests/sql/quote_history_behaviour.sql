-- Executed checks for the research price contract (api.quote_history and the
-- panel's close_adj, #410). Regex tests pin the SQL text; this proves it DOES
-- the right thing on rows. Synthetic tickers, one per case, inside a
-- transaction that is rolled back, so it runs on any database with the schema
-- and the analytical layer applied (CI's sql-compile job, or a scratch copy):
--
--   psql "$POSTGRES_URL" -v ON_ERROR_STOP=1 -f tests/sql/quote_history_behaviour.sql

BEGIN;

-- The market calendar: REFR3 prints every weekday of 2024-08 except the
-- "holiday" 2024-08-15, which is therefore not a session.
CREATE TEMP TABLE sess AS
SELECT d::date AS d
FROM generate_series('2024-08-01'::date, '2024-08-30', '1 day') d
WHERE extract(isodow FROM d) < 6 AND d::date <> '2024-08-15';

INSERT INTO b3_cotahist (codneg, trade_date, tpmerc, codbdi, especi, preco_fechamento, fator_cotacao, isin, raw)
SELECT 'REFR3', d, '010', '02', 'ON', 10, 1, 'BRREFRACNOR1', '{}' FROM sess;
-- ETER3: board 08 through 2024-08-09, then board 02 (the ETER3 cut).
INSERT INTO b3_cotahist (codneg, trade_date, tpmerc, codbdi, especi, preco_fechamento, fator_cotacao, isin, raw)
SELECT 'ETER3', d, '010', CASE WHEN d <= '2024-08-09' THEN '08' ELSE '02' END, 'ON', 5, 1, 'BRETERACNOR3', '{}' FROM sess;
-- SPLT3: 2-for-1 split, last cum date 2024-08-07; no trade 08-20..08-22.
INSERT INTO b3_cotahist (codneg, trade_date, tpmerc, codbdi, especi, preco_fechamento, fator_cotacao, isin, raw)
SELECT 'SPLT3', d, '010', '02', 'ON', CASE WHEN d <= '2024-08-07' THEN 20 ELSE 10 END, 1, 'BRSPLTACNOR1', '{}'
FROM sess WHERE d NOT BETWEEN '2024-08-20' AND '2024-08-22';
-- CMPD3: grouping 10:1 and a 10% bonus on the same cum date multiply.
INSERT INTO b3_cotahist (codneg, trade_date, tpmerc, codbdi, especi, preco_fechamento, fator_cotacao, isin, raw)
SELECT 'CMPD3', d, '010', '02', 'ON', CASE WHEN d <= '2024-08-14' THEN 1.10 ELSE 10 END, 1, 'BRCMPDACNOR1', '{}' FROM sess;
-- SPIN3: a spin-off (not adjusted in this version) blocks through 08-13.
-- SUBS3: a subscription right, outside a price-only adjustment, blocks nothing.
INSERT INTO b3_cotahist (codneg, trade_date, tpmerc, codbdi, especi, preco_fechamento, fator_cotacao, isin, raw)
SELECT t, d, '010', '02', 'ON', 7, 1, 'BR' || left(t, 4) || 'ACNOR1', '{}' FROM sess, unnest(ARRAY['SPIN3', 'SUBS3']) t;
-- AMBG3: one label on one date with two factors.
INSERT INTO b3_cotahist (codneg, trade_date, tpmerc, codbdi, especi, preco_fechamento, fator_cotacao, isin, raw)
SELECT 'AMBG3', d, '010', '02', 'ON', 3, 1, 'BRAMBGACNOR1', '{}' FROM sess;
-- TWOA3: one bonus on one date, same factor, paid in two assets (#353).
INSERT INTO b3_cotahist (codneg, trade_date, tpmerc, codbdi, especi, preco_fechamento, fator_cotacao, isin, raw)
SELECT 'TWOA3', d, '010', '02', 'ON', 3, 1, 'BRTWOAACNOR1', '{}' FROM sess;
-- NOPR3: issuer never swept. STAL3: swept before its last session.
INSERT INTO b3_cotahist (codneg, trade_date, tpmerc, codbdi, especi, preco_fechamento, fator_cotacao, isin, raw)
SELECT t, d, '010', '02', 'ON', 4, 1, 'BR' || left(t, 4) || 'ACNOR1', '{}' FROM sess, unnest(ARRAY['NOPR3', 'STAL3']) t;
-- DUPL3: two boards on 2024-08-08.
INSERT INTO b3_cotahist (codneg, trade_date, tpmerc, codbdi, especi, preco_fechamento, fator_cotacao, isin, raw)
SELECT 'DUPL3', d, '010', '02', 'ON', 2, 1, 'BRDUPLACNOR1', '{}' FROM sess;
INSERT INTO b3_cotahist (codneg, trade_date, tpmerc, codbdi, especi, preco_fechamento, fator_cotacao, isin, raw)
VALUES ('DUPL3', '2024-08-08', '010', '08', 'ON', 2.1, 1, 'BRDUPLACNOR1', '{}');
-- RCPT9: a receipt code reused by a second ISIN.
INSERT INTO b3_cotahist (codneg, trade_date, tpmerc, codbdi, especi, preco_fechamento, fator_cotacao, isin, raw)
SELECT 'RCPT9', d, '010', '02', 'REC', 1, 1, CASE WHEN d < '2024-08-15' THEN 'BRRCPTR01OR1' ELSE 'BRRCPTR02OR9' END, '{}' FROM sess;
-- UNIT11 (a CDA unit), FUND11 (a fund quota), LOTS3 (quoted per 1000).
INSERT INTO b3_cotahist (codneg, trade_date, tpmerc, codbdi, especi, preco_fechamento, fator_cotacao, isin, raw)
SELECT 'UNIT11', d, '010', '02', 'UNT', 30, 1, 'BRUNITCDAM11', '{}' FROM sess;
INSERT INTO b3_cotahist (codneg, trade_date, tpmerc, codbdi, especi, preco_fechamento, fator_cotacao, isin, raw)
SELECT 'FUND11', d, '010', '12', 'CI', 100, 1, 'BRFUNDCTF000', '{}' FROM sess;
INSERT INTO b3_cotahist (codneg, trade_date, tpmerc, codbdi, especi, preco_fechamento, fator_cotacao, isin, raw)
SELECT 'LOTS3', d, '010', '02', 'ON', 5000, 1000, 'BRLOTSACNOR1', '{}' FROM sess;
-- LONG3: 1001 sessions, for the page edge.
INSERT INTO b3_cotahist (codneg, trade_date, tpmerc, codbdi, especi, preco_fechamento, fator_cotacao, isin, raw)
SELECT 'LONG3', d, '010', '02', 'ON', 1 + g / 1000.0, 1, 'BRLONGACNOR1', '{}'
FROM (SELECT d::date AS d, row_number() OVER (ORDER BY d) AS g
      FROM generate_series('2020-01-01'::date, '2024-07-31', '1 day') d
      WHERE extract(isodow FROM d) < 6) x
WHERE g <= 1001;
-- close_return across a share-count event (#396). BBAS3 prints the real
-- 2024-04 pin (56.46 on the last cum date, 27.91 on the first ex session); MGLU3
-- the 2024-05 grouping (1.32 -> 13.15); CTRL3 is a normal ticker (a cash
-- distribution inside the window, a split years before it); NULF3 has a
-- share-count event with no readable factor.
INSERT INTO b3_cotahist (codneg, trade_date, tpmerc, codbdi, especi, preco_fechamento, fator_cotacao, isin, raw) VALUES
    ('BBAS3', '2024-03-28', '010', '02', 'ON', 55.00, 1, 'BRBBASACNOR3', '{}'),
    ('BBAS3', '2024-04-11', '010', '02', 'ON', 56.00, 1, 'BRBBASACNOR3', '{}'),
    ('BBAS3', '2024-04-12', '010', '02', 'ON', 56.30, 1, 'BRBBASACNOR3', '{}'),
    ('BBAS3', '2024-04-15', '010', '02', 'ON', 56.46, 1, 'BRBBASACNOR3', '{}'),
    ('BBAS3', '2024-04-16', '010', '02', 'ON', 27.91, 1, 'BRBBASACNOR3', '{}'),
    ('BBAS3', '2024-04-17', '010', '02', 'ON', 28.05, 1, 'BRBBASACNOR3', '{}'),
    ('BBAS3', '2024-04-30', '010', '02', 'ON', 28.40, 1, 'BRBBASACNOR3', '{}'),
    ('BBAS3', '2024-05-31', '010', '02', 'ON', 28.80, 1, 'BRBBASACNOR3', '{}'),
    ('MGLU3', '2024-04-30', '010', '02', 'ON',  1.40, 1, 'BRMGLUACNOR3', '{}'),
    ('MGLU3', '2024-05-22', '010', '02', 'ON',  1.30, 1, 'BRMGLUACNOR3', '{}'),
    ('MGLU3', '2024-05-23', '010', '02', 'ON',  1.32, 1, 'BRMGLUACNOR3', '{}'),
    ('MGLU3', '2024-05-24', '010', '02', 'ON', 13.15, 1, 'BRMGLUACNOR3', '{}'),
    ('MGLU3', '2024-05-27', '010', '02', 'ON', 13.20, 1, 'BRMGLUACNOR3', '{}'),
    ('MGLU3', '2024-05-31', '010', '02', 'ON', 13.50, 1, 'BRMGLUACNOR3', '{}'),
    ('CTRL3', '2024-03-28', '010', '02', 'ON',  9.50, 1, 'BRCTRLACNOR1', '{}'),
    ('CTRL3', '2024-04-11', '010', '02', 'ON', 10.50, 1, 'BRCTRLACNOR1', '{}'),
    ('CTRL3', '2024-04-12', '010', '02', 'ON', 11.00, 1, 'BRCTRLACNOR1', '{}'),
    ('CTRL3', '2024-04-15', '010', '02', 'ON', 11.55, 1, 'BRCTRLACNOR1', '{}'),
    ('CTRL3', '2024-04-16', '010', '02', 'ON', 12.10, 1, 'BRCTRLACNOR1', '{}'),
    ('CTRL3', '2024-04-30', '010', '02', 'ON', 12.10, 1, 'BRCTRLACNOR1', '{}'),
    ('CTRL3', '2024-05-31', '010', '02', 'ON', 12.60, 1, 'BRCTRLACNOR1', '{}'),
    ('NULF3', '2024-04-15', '010', '02', 'ON', 10.00, 1, 'BRNULFACNOR1', '{}'),
    ('NULF3', '2024-04-16', '010', '02', 'ON',  5.00, 1, 'BRNULFACNOR1', '{}'),
    -- QUAD3: the owner's example (2026-10-04), 100.00 the day before a 1:4
    -- split, 26.00 on the split day: +4%, not -74%.
    ('QUAD3', '2024-04-15', '010', '02', 'ON', 100.00, 1, 'BRQUADACNOR1', '{}'),
    ('QUAD3', '2024-04-16', '010', '02', 'ON',  26.00, 1, 'BRQUADACNOR1', '{}');

INSERT INTO b3_corporate_event (issuing_company, isin, event_class, label, last_date_prior, factor, raw) VALUES
    ('BBAS', 'BRBBASACNOR3', 'stock', 'DESDOBRAMENTO', '2024-04-15', 100, '{}'),
    ('MGLU', 'BRMGLUACNOR3', 'stock', 'GRUPAMENTO',    '2024-05-23', 0.1, '{}'),
    ('CTRL', 'BRCTRLACNOR1', 'cash',  'DIVIDENDO',     '2024-04-12', NULL, '{}'),
    ('CTRL', 'BRCTRLACNOR1', 'stock', 'DESDOBRAMENTO', '2020-01-10', 100, '{}'),
    ('NULF', 'BRNULFACNOR1', 'stock', 'DESDOBRAMENTO', '2024-04-15', NULL, '{}'),
    ('QUAD', 'BRQUADACNOR1', 'stock', 'DESDOBRAMENTO', '2024-04-15', 300, '{}');

INSERT INTO b3_corporate_event (issuing_company, isin, event_class, label, last_date_prior, factor, raw) VALUES
    ('SPLT', 'BRSPLTACNOR1', 'stock', 'DESDOBRAMENTO', '2024-08-07', 100, '{}'),
    ('SPLT', 'BRSPLTACNOR1', 'cash', 'DIVIDENDO', '2024-08-12', NULL, '{}'),
    ('CMPD', 'BRCMPDACNOR1', 'stock', 'GRUPAMENTO', '2024-08-14', 0.1, '{}'),
    ('CMPD', 'BRCMPDACNOR1', 'stock', 'BONIFICACAO', '2024-08-14', 10, '{}'),
    ('SPIN', 'BRSPINACNOR1', 'stock', 'CIS RED CAP', '2024-08-13', 12.5, '{}'),
    ('SUBS', 'BRSUBSACNOR1', 'subscription', 'SUBSCRICAO', '2024-08-13', NULL, '{}'),
    ('AMBG', 'BRAMBGACNOR1', 'stock', 'DESDOBRAMENTO', '2024-08-06', 100, '{"v":1}'),
    ('AMBG', 'BRAMBGACNOR1', 'stock', 'DESDOBRAMENTO', '2024-08-06', 200, '{"v":2}');
INSERT INTO b3_corporate_event (issuing_company, isin, event_class, label, last_date_prior, factor, asset_issued, raw) VALUES
    ('TWOA', 'BRTWOAACNOR1', 'stock', 'BONIFICACAO', '2024-08-06', 10, 'BRTWOAACNOR1', '{}'),
    ('TWOA', 'BRTWOAACNOR1', 'stock', 'BONIFICACAO', '2024-08-06', 10, 'BRTWOAACNPR8', '{}');

INSERT INTO b3_corporate_event_sweep (issuing_company, n_events, proven_at)
SELECT c, 0, '2024-09-02 06:00+00'
FROM unnest(ARRAY['REFR', 'ETER', 'SPLT', 'CMPD', 'SPIN', 'SUBS', 'AMBG', 'TWOA', 'DUPL', 'UNIT', 'LOTS', 'LONG']) c;
INSERT INTO b3_corporate_event_sweep (issuing_company, n_events, proven_at)
VALUES ('STAL', 0, '2024-08-20 06:00+00');

-- Ticker lineage (#381 follow-up, docs/adr/0002-ticker-activity-and-lineage.md).
-- A week of March 2024 is its own calendar: no other fixture prints there.
-- OLDL3 -> NEWL3: same company in the FCA, same class, adjacent, no event at
-- the seam: spliced. A 10:1 grouping later on the NEW ISIN divides the old
-- rows too. The four others must not splice:
--   DIFO3 -> DIFN3  different company CNPJs
--   CLSO4 -> CLSN3  same company, PN ISIN then ON ISIN (another class)
--   GAPO3 -> GAPN3  a cash session (2024-03-08) between the two
--   BNDO3 -> BNDN3  a stock event on the old ISIN goes ex at the seam
INSERT INTO cia_ticker (cnpj_cia, data_refer, versao, valor_mobiliario, codneg, mercado, dt_fim_neg) VALUES
    ('99000000000101', '2022-01-01', 1, 'Ações Ordinárias', 'OLDL3', 'Bolsa', NULL),
    ('99000000000101', '2025-01-01', 1, 'Ações Ordinárias', 'NEWL3', 'Bolsa', NULL),
    ('99000000000102', '2022-01-01', 1, 'Ações Ordinárias', 'DIFO3', 'Bolsa', NULL),
    ('99000000000103', '2025-01-01', 1, 'Ações Ordinárias', 'DIFN3', 'Bolsa', NULL),
    ('99000000000104', '2022-01-01', 1, 'Ações Preferenciais', 'CLSO4', 'Bolsa', NULL),
    ('99000000000104', '2025-01-01', 1, 'Ações Ordinárias', 'CLSN3', 'Bolsa', NULL),
    ('99000000000105', '2022-01-01', 1, 'Ações Ordinárias', 'GAPO3', 'Bolsa', NULL),
    ('99000000000105', '2025-01-01', 1, 'Ações Ordinárias', 'GAPN3', 'Bolsa', NULL),
    ('99000000000106', '2022-01-01', 1, 'Ações Ordinárias', 'BNDO3', 'Bolsa', NULL),
    ('99000000000106', '2025-01-01', 1, 'Ações Ordinárias', 'BNDN3', 'Bolsa', NULL);
INSERT INTO b3_cotahist (codneg, trade_date, tpmerc, codbdi, especi, preco_fechamento, fator_cotacao, isin, raw) VALUES
    ('OLDL3', '2024-03-04', '010', '02', 'ON', 0.96, 1, 'BROLDLACNOR1', '{}'),
    ('OLDL3', '2024-03-05', '010', '02', 'ON', 0.97, 1, 'BROLDLACNOR1', '{}'),
    ('OLDL3', '2024-03-06', '010', '02', 'ON', 0.98, 1, 'BROLDLACNOR1', '{}'),
    ('OLDL3', '2024-03-07', '010', '02', 'ON', 0.99, 1, 'BROLDLACNOR1', '{}'),
    ('OLDL3', '2024-03-08', '010', '02', 'ON', 1.00, 1, 'BROLDLACNOR1', '{}'),
    ('NEWL3', '2024-03-11', '010', '02', 'ON', 1.00, 1, 'BRNEWLACNOR1', '{}'),
    ('NEWL3', '2024-03-12', '010', '02', 'ON', 1.02, 1, 'BRNEWLACNOR1', '{}'),
    ('NEWL3', '2024-03-13', '010', '02', 'ON', 1.04, 1, 'BRNEWLACNOR1', '{}'),
    ('NEWL3', '2024-03-14', '010', '02', 'ON', 10.40, 1, 'BRNEWLACNOR1', '{}'),
    ('NEWL3', '2024-03-15', '010', '02', 'ON', 10.50, 1, 'BRNEWLACNOR1', '{}'),
    ('DIFO3', '2024-03-08', '010', '02', 'ON', 5, 1, 'BRDIFOACNOR1', '{}'),
    ('DIFN3', '2024-03-11', '010', '02', 'ON', 5, 1, 'BRDIFNACNOR1', '{}'),
    ('CLSO4', '2024-03-08', '010', '02', 'PN', 5, 1, 'BRCLSOACNPR1', '{}'),
    ('CLSN3', '2024-03-11', '010', '02', 'ON', 5, 1, 'BRCLSNACNOR1', '{}'),
    ('GAPO3', '2024-03-07', '010', '02', 'ON', 5, 1, 'BRGAPOACNOR1', '{}'),
    ('GAPN3', '2024-03-11', '010', '02', 'ON', 5, 1, 'BRGAPNACNOR1', '{}'),
    ('BNDO3', '2024-03-08', '010', '02', 'ON', 5, 1, 'BRBNDOACNOR1', '{}'),
    ('BNDN3', '2024-03-11', '010', '02', 'ON', 5, 1, 'BRBNDNACNOR1', '{}');
INSERT INTO b3_corporate_event (issuing_company, isin, event_class, label, last_date_prior, factor, raw) VALUES
    ('NEWL', 'BRNEWLACNOR1', 'stock', 'GRUPAMENTO',  '2024-03-13', 0.1, '{}'),
    ('BNDO', 'BRBNDOACNOR1', 'stock', 'INCORPORACAO', '2024-03-08', 1, '{}');
INSERT INTO b3_corporate_event_sweep (issuing_company, n_events, proven_at)
SELECT c, 0, '2024-09-02 06:00+00'
FROM unnest(ARRAY['OLDL', 'NEWL', 'DIFO', 'DIFN', 'CLSO', 'CLSN', 'GAPO', 'GAPN', 'BNDO', 'BNDN']) c;

REFRESH MATERIALIZED VIEW mv_b3_isin_subtype;

DO $$
DECLARE
    n      INT;
    v      NUMERIC;
    j      JSONB;
    detail TEXT;
BEGIN
    -- The series crosses boards: every ETER3 session, both boards.
    SELECT count(*) INTO n FROM api.quote_history('ETER3', '2024-08-01', '2024-08-30');
    ASSERT n = 21, format('ETER3 across boards: %s rows, expected 21', n);
    -- An explicit board still filters.
    SELECT count(*) INTO n FROM api.quote_history('ETER3', '2024-08-12', '2024-08-30', '02');
    ASSERT n = 14, format('ETER3 on board 02: %s rows, expected 14', n);

    -- Default fields: exactly ticker, trade_date, close_adj.
    SELECT q INTO j FROM api.quote_history('SPLT3', '2024-08-05', '2024-08-05') q;
    ASSERT (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(j) k) = ARRAY['close_adj', 'ticker', 'trade_date'],
        format('default keys: %s', j);
    -- Split: 20 before the cum date is 10 adjusted; the raw close stays 20.
    ASSERT (j ->> 'close_adj')::numeric = 10, format('split adjusted: %s', j);
    SELECT q INTO j FROM api.quote_history('SPLT3', '2024-08-05', '2024-08-05', NULL, NULL, ARRAY['close']) q;
    ASSERT (j ->> 'close')::numeric = 20 AND NOT j ? 'close_adj', format('raw close selected: %s', j);

    -- Grouping and bonus on one date multiply: 1.10 / (0.1 * 1.1) = 10.
    SELECT (q ->> 'close_adj')::numeric INTO v FROM api.quote_history('CMPD3', '2024-08-13', '2024-08-13') q;
    ASSERT v = 10, format('compound events: %s', v);
    -- Per single share: 5000 quoted per 1000 is 5.
    SELECT (q ->> 'close_adj')::numeric INTO v FROM api.quote_history('LOTS3', '2024-08-13', '2024-08-13') q;
    ASSERT v = 5, format('quotation factor: %s', v);

    -- The same session reads the same close_adj in any window.
    ASSERT (SELECT (q ->> 'close_adj')::numeric FROM api.quote_history('CMPD3', '2024-08-01', '2024-08-30') q
            WHERE q ->> 'trade_date' = '2024-08-13')
         = (SELECT (q ->> 'close_adj')::numeric FROM api.quote_history('CMPD3', '2024-08-13', '2024-08-14') q
            WHERE q ->> 'trade_date' = '2024-08-13'),
        'close_adj must not depend on the window';

    -- A missing session inside the coverage is a no-trade session; the
    -- holiday is not a session.
    SELECT q INTO j FROM api.quote_history('SPLT3', '2024-08-23', '2024-08-23', NULL, NULL,
                                           ARRAY['prior_no_trade_sessions', 'coverage_start', 'coverage_end']) q;
    ASSERT (j ->> 'prior_no_trade_sessions')::int = 3, format('no-trade sessions: %s', j);
    ASSERT j ->> 'coverage_start' = '2024-08-01' AND j ->> 'coverage_end' = '2024-08-30', format('coverage: %s', j);
    SELECT (q ->> 'prior_no_trade_sessions')::int INTO n
    FROM api.quote_history('SPLT3', '2024-08-16', '2024-08-16', NULL, NULL, ARRAY['prior_no_trade_sessions']) q;
    ASSERT n = 0, format('a holiday is not a no-trade session: %s', n);

    -- data_revision is the newest proof or load.
    SELECT q ->> 'data_revision' INTO detail
    FROM api.quote_history('SPLT3', '2024-08-16', '2024-08-16', NULL, NULL, ARRAY['data_revision']) q;
    ASSERT detail IS NOT NULL, 'data_revision must be served';

    -- Units adjust; the page edge: 1000 rows serve, 1001 refuse unless paged,
    -- and the pages are the whole series with no gap or repeat.
    SELECT count(*) INTO n FROM api.quote_history('UNIT11', '2024-08-01', '2024-08-30');
    ASSERT n = 21, 'a unit gets close_adj';
    SELECT count(*) INTO n FROM api.quote_history('LONG3', '2020-01-01', '2023-10-31', NULL, NULL, ARRAY['close']);
    ASSERT n <= 1000, format('window under the cap: %s', n);
    SELECT count(*) INTO n FROM api.quote_history('LONG3', '2020-01-01', '2024-07-31', NULL, '', ARRAY['close']);
    ASSERT n = 1000, format('first page: %s', n);
    SELECT count(*) INTO n FROM api.quote_history('LONG3', '2020-01-01', '2024-07-31', NULL,
        (SELECT max(q ->> 'trade_date') FROM api.quote_history('LONG3', '2020-01-01', '2024-07-31', NULL, '', ARRAY['close']) q),
        ARRAY['close']);
    ASSERT n = 1, format('second page: %s', n);

    -- Panel: close_adj by default for shares and units, close for the rest.
    SELECT count(*) INTO n FROM api.panel(ARRAY['SPLT3', 'FUND11'], NULL, '2024-08-01', '2024-08-30', 'month')
    WHERE (id = 'SPLT3' AND metric = 'close_adj' AND value = 10) OR (id = 'FUND11' AND metric = 'close');
    ASSERT n = 2, format('panel defaults: %s', n);

    RAISE NOTICE 'quote_history behaviour OK';
END $$;

-- Each refusal: 22023 with DETAIL reason=<reason>. One DO block per case so a
-- failure names the case.
CREATE TEMP TABLE cases (label TEXT, stmt TEXT, reason TEXT);
INSERT INTO cases VALUES
    ('unknown ticker',        $s$SELECT * FROM api.quote_history('XXXX3', '2024-08-01', '2024-08-02')$s$, 'reason=unknown_ticker'),
    ('board never printed',   $s$SELECT * FROM api.quote_history('ETER3', '2024-08-01', '2024-08-02', '12')$s$, 'reason=unknown_ticker'),
    ('before coverage',       $s$SELECT * FROM api.quote_history('ETER3', '2024-07-01', '2024-08-02')$s$, 'reason=outside_coverage'),
    ('after coverage',        $s$SELECT * FROM api.quote_history('ETER3', '2024-09-10', '2024-09-20')$s$, 'reason=outside_coverage'),
    ('two ISINs',             $s$SELECT * FROM api.quote_history('RCPT9', '2024-08-01', '2024-08-30', NULL, NULL, ARRAY['close'])$s$, 'reason=isin_change'),
    ('two rows on a session', $s$SELECT * FROM api.quote_history('DUPL3', '2024-08-01', '2024-08-30', NULL, NULL, ARRAY['close'])$s$, 'reason=ambiguous_session'),
    ('unknown field',         $s$SELECT * FROM api.quote_history('ETER3', '2024-08-01', '2024-08-02', NULL, NULL, ARRAY['close', 'nope'])$s$, 'reason=invalid_field'),
    ('empty field list',      $s$SELECT * FROM api.quote_history('ETER3', '2024-08-01', '2024-08-02', NULL, NULL, ARRAY[]::text[])$s$, 'reason=invalid_field'),
    ('unsupported event',     $s$SELECT * FROM api.quote_history('SPIN3', '2024-08-01', '2024-08-30')$s$, 'reason=adjustment_unavailable; cause=unsupported corporate event CIS RED CAP'),
    ('ambiguous event',       $s$SELECT * FROM api.quote_history('AMBG3', '2024-08-01', '2024-08-30')$s$, 'reason=adjustment_unavailable; cause=ambiguous DESDOBRAMENTO'),
    ('event in two assets',   $s$SELECT * FROM api.quote_history('TWOA3', '2024-08-01', '2024-08-30')$s$, 'reason=adjustment_unavailable; cause=ambiguous BONIFICACAO paid in two assets'),
    ('never swept',           $s$SELECT * FROM api.quote_history('NOPR3', '2024-08-01', '2024-08-30')$s$, 'reason=adjustment_unavailable; cause=issuer corporate events not proven swept'),
    ('proof older than tape', $s$SELECT * FROM api.quote_history('STAL3', '2024-08-01', '2024-08-30')$s$, 'reason=adjustment_unavailable; cause=corporate-event proof older'),
    ('not a share or unit',   $s$SELECT * FROM api.quote_history('FUND11', '2024-08-01', '2024-08-30')$s$, 'reason=adjustment_unavailable; cause=outside research universe'),
    ('over the page',         $s$SELECT * FROM api.quote_history('LONG3', '2020-01-01', '2024-07-31', NULL, NULL, ARRAY['close'])$s$, NULL),
    ('panel unsupported',     $s$SELECT * FROM api.panel(ARRAY['SPIN3'], NULL, '2024-08-01', '2024-08-30', 'month')$s$, 'reason=adjustment_unavailable'),
    ('panel explicit fund',   $s$SELECT * FROM api.panel(ARRAY['FUND11'], ARRAY['close_adj'], '2024-08-01', '2024-08-30', 'month')$s$, 'reason=adjustment_unavailable'),
    ('lineage: another CNPJ', $s$SELECT * FROM api.quote_history('DIFN3', '2024-03-08', '2024-03-15', NULL, NULL, ARRAY['close'])$s$, 'reason=outside_coverage'),
    ('lineage: another class', $s$SELECT * FROM api.quote_history('CLSN3', '2024-03-08', '2024-03-15', NULL, NULL, ARRAY['close'])$s$, 'reason=outside_coverage'),
    ('lineage: session gap',  $s$SELECT * FROM api.quote_history('GAPN3', '2024-03-07', '2024-03-15', NULL, NULL, ARRAY['close'])$s$, 'reason=outside_coverage'),
    ('lineage: seam event',   $s$SELECT * FROM api.quote_history('BNDN3', '2024-03-08', '2024-03-15', NULL, NULL, ARRAY['close'])$s$, 'reason=outside_coverage');

DO $$
DECLARE
    c      RECORD;
    detail TEXT;
    msg    TEXT;
BEGIN
    FOR c IN SELECT * FROM cases LOOP
        BEGIN
            EXECUTE c.stmt;
            RAISE EXCEPTION 'case "%" was served, expected a 22023 refusal', c.label;
        EXCEPTION WHEN sqlstate '22023' THEN
            GET STACKED DIAGNOSTICS detail = PG_EXCEPTION_DETAIL, msg = MESSAGE_TEXT;
            ASSERT c.reason IS NULL OR detail LIKE c.reason || '%',
                format('case "%s": detail %L, expected %L (message: %s)', c.label, detail, c.reason, msg);
        END;
    END LOOP;
    RAISE NOTICE 'quote_history refusals OK';
END $$;

-- The adjusted stretch after an unsupported event is still served, the raw
-- close is never refused for an adjustment reason, and a subscription right
-- (outside a price-only adjustment, like a dividend) blocks nothing.
DO $$
DECLARE n INT;
BEGIN
    SELECT count(*) INTO n FROM api.quote_history('SPIN3', '2024-08-14', '2024-08-30');
    ASSERT n = 12, format('SPIN3 after the spin-off: %s rows, expected 12', n);
    SELECT count(*) INTO n FROM api.quote_history('SPIN3', '2024-08-01', '2024-08-30', NULL, NULL, ARRAY['close']);
    ASSERT n = 21, format('SPIN3 raw: %s rows, expected 21', n);
    SELECT count(*) INTO n FROM api.quote_history('SUBS3', '2024-08-01', '2024-08-30');
    ASSERT n = 21, format('SUBS3 across its subscription: %s rows, expected 21', n);
END $$;

-- close_total_return (#418) is a selection that never refuses: NULL with the
-- session's reason, here the missing cash history and, before a spin-off,
-- the blocking event itself.
DO $$
DECLARE j JSONB;
BEGIN
    SELECT q INTO j FROM api.quote_history('SPLT3', '2024-08-05', '2024-08-05', NULL, NULL,
                                           ARRAY['close_total_return', 'close_total_return_null_reason']) q;
    ASSERT j ? 'close_total_return' AND j -> 'close_total_return' = 'null'::jsonb, format('total return: %s', j);
    ASSERT j ->> 'close_total_return_null_reason' LIKE 'no cash distribution resolved%', format('reason: %s', j);
    SELECT q INTO j FROM api.quote_history('SPIN3', '2024-08-05', '2024-08-05', NULL, NULL,
                                           ARRAY['close_total_return_null_reason']) q;
    ASSERT j ->> 'close_total_return_null_reason' LIKE 'unsupported corporate event CIS RED CAP%', format('reason: %s', j);
    RAISE NOTICE 'close_total_return OK';
END $$;

-- close_return across a share-count event is ADJUSTED (#396 step 2, owner
-- decision 2026-10-04): the previous close is divided by the event's share
-- ratio (1 + factor/100 for DESDOBRAMENTO and BONIFICACAO, factor for
-- GRUPAMENTO) and the return is close / adjusted previous close - 1. An
-- unreadable or ambiguous factor still nulls it. The panel emits no row where
-- the return is NULL, so "NULL" reads as "no close_return row for that session".
DO $$
DECLARE
    d DATE[];
    v NUMERIC;
BEGIN
    -- The owner's example: 100.00 the day before a 1:4 split is 25.00 adjusted,
    -- so a 26.00 close is +4%.
    SELECT value INTO v
    FROM api.panel(ARRAY['QUAD3'], ARRAY['close_return'], '2024-04-01', '2024-04-17', 'day')
    WHERE date = '2024-04-16';
    ASSERT round(v, 6) = 0.04, format('QUAD3 split-day return: %s, expected 0.04', v);

    -- BBAS3, daily: the first ex session (04-16, 56.46 -> 27.91) is the
    -- adjusted -1.13%, not the raw -50.57%; the sessions around it are plain.
    SELECT array_agg(date ORDER BY date) INTO d
    FROM api.panel(ARRAY['BBAS3'], ARRAY['close_return'], '2024-04-01', '2024-04-17', 'day');
    ASSERT d = ARRAY['2024-04-12', '2024-04-15', '2024-04-16', '2024-04-17']::date[],
        format('BBAS3 daily close_return dates: %s', d);
    SELECT value INTO v
    FROM api.panel(ARRAY['BBAS3'], ARRAY['close_return'], '2024-04-01', '2024-04-17', 'day')
    WHERE date = '2024-04-16';
    ASSERT round(v, 6) = round(27.91 / (56.46 / 2) - 1, 6), format('BBAS3 ex session: %s', v);
    SELECT value INTO v
    FROM api.panel(ARRAY['BBAS3'], ARRAY['close_return'], '2024-04-01', '2024-04-17', 'day')
    WHERE date = '2024-04-17';
    ASSERT round(v, 6) = round(28.05 / 27.91 - 1, 6), format('BBAS3 after the event: %s', v);

    -- BBAS3, monthly: the split sits mid-April, between the March and April
    -- month-end prints, so April's previous close (March) is halved.
    SELECT array_agg(date ORDER BY date) INTO d
    FROM api.panel(ARRAY['BBAS3'], ARRAY['close_return'], '2024-03-01', '2024-05-31', 'month');
    ASSERT d = ARRAY['2024-04-01', '2024-05-01']::date[], format('BBAS3 monthly close_return dates: %s', d);
    SELECT value INTO v
    FROM api.panel(ARRAY['BBAS3'], ARRAY['close_return'], '2024-03-01', '2024-05-31', 'month')
    WHERE date = '2024-04-01';
    ASSERT round(v, 6) = round(28.40 / (55.00 / 2) - 1, 6), format('BBAS3 April: %s', v);

    -- MGLU3 grouping 10:1 (factor 0.1, last cum date 05-23): the previous
    -- close 1.32 becomes 13.20, so 05-24's 13.15 is -0.38%; monthly May
    -- compares 13.50 with April's 1.40 grouped to 14.00.
    SELECT array_agg(date ORDER BY date) INTO d
    FROM api.panel(ARRAY['MGLU3'], ARRAY['close_return'], '2024-05-20', '2024-05-28', 'day');
    ASSERT d = ARRAY['2024-05-23', '2024-05-24', '2024-05-27']::date[], format('MGLU3 daily close_return dates: %s', d);
    SELECT value INTO v
    FROM api.panel(ARRAY['MGLU3'], ARRAY['close_return'], '2024-05-20', '2024-05-28', 'day')
    WHERE date = '2024-05-24';
    ASSERT round(v, 6) = round(13.15 / (1.32 / 0.1) - 1, 6), format('MGLU3 ex session: %s', v);
    SELECT value INTO v
    FROM api.panel(ARRAY['MGLU3'], ARRAY['close_return'], '2024-04-01', '2024-05-31', 'month')
    WHERE date = '2024-05-01';
    ASSERT round(v, 6) = round(13.50 / (1.40 / 0.1) - 1, 6), format('MGLU3 May: %s', v);

    -- CMPD3: a 10:1 grouping and a 10% bonus on one cum date multiply
    -- (0.1 x 1.1 = 0.11): 1.10 becomes 10.00, so the 10.00 close is 0%.
    SELECT value INTO v
    FROM api.panel(ARRAY['CMPD3'], ARRAY['close_return'], '2024-08-01', '2024-08-30', 'day')
    WHERE date = '2024-08-16';
    ASSERT round(v, 6) = 0, format('CMPD3 compound event: %s', v);

    -- A share-count event whose factor B3 published unreadable is still a
    -- share-count event: NULL, not a guess.
    SELECT count(*) INTO v
    FROM api.panel(ARRAY['NULF3'], ARRAY['close_return'], '2024-04-01', '2024-04-17', 'day');
    ASSERT v = 0, format('NULF3 close_return rows: %s, expected none', v);

    -- One label on one date published with two factors: NULL on the ex
    -- session only; the sessions around it are plain.
    SELECT array_agg(date ORDER BY date) INTO d
    FROM api.panel(ARRAY['AMBG3'], ARRAY['close_return'], '2024-08-05', '2024-08-09', 'day');
    ASSERT d = ARRAY['2024-08-06', '2024-08-08', '2024-08-09']::date[], format('AMBG3 daily close_return dates: %s', d);

    -- One bonus on one date paid in two assets with the same factor: NULL on
    -- the ex session too, not the factor counted once (#353).
    SELECT array_agg(date ORDER BY date) INTO d
    FROM api.panel(ARRAY['TWOA3'], ARRAY['close_return'], '2024-08-05', '2024-08-09', 'day');
    ASSERT d = ARRAY['2024-08-06', '2024-08-08', '2024-08-09']::date[], format('TWOA3 daily close_return dates: %s', d);

    -- A normal ticker is unchanged: a cash distribution and a split years
    -- before the window adjust nothing, daily or monthly.
    SELECT array_agg(date ORDER BY date) INTO d
    FROM api.panel(ARRAY['CTRL3'], ARRAY['close_return'], '2024-04-01', '2024-04-17', 'day');
    ASSERT d = ARRAY['2024-04-12', '2024-04-15', '2024-04-16']::date[], format('CTRL3 daily close_return dates: %s', d);
    SELECT value INTO v
    FROM api.panel(ARRAY['CTRL3'], ARRAY['close_return'], '2024-04-01', '2024-04-17', 'day')
    WHERE date = '2024-04-15';
    ASSERT round(v, 6) = round(11.55 / 11.00 - 1, 6), format('CTRL3 daily value: %s', v);
    SELECT array_agg(date ORDER BY date) INTO d
    FROM api.panel(ARRAY['CTRL3'], ARRAY['close_return'], '2024-03-01', '2024-05-31', 'month');
    ASSERT d = ARRAY['2024-04-01', '2024-05-01']::date[], format('CTRL3 monthly close_return dates: %s', d);
    SELECT value INTO v
    FROM api.panel(ARRAY['CTRL3'], ARRAY['close_return'], '2024-03-01', '2024-05-31', 'month')
    WHERE date = '2024-04-01';
    ASSERT round(v, 6) = round(12.10 / 9.50 - 1, 6), format('CTRL3 monthly value: %s', v);

    RAISE NOTICE 'close_return across share-count events OK';
END $$;


-- A spliced lineage serves the whole history, each row with its own ticker
-- and ISIN, and close_adj continuous across the seam.
DO $$
DECLARE
    j   jsonb;
    n   INT;
    got TEXT;
BEGIN
    SELECT count(*), string_agg(q ->> 'ticker' || ' ' || (q ->> 'isin'), ',' ORDER BY q ->> 'trade_date')
    INTO n, got
    FROM api.quote_history('NEWL3', '2024-03-04', '2024-03-15', NULL, NULL, ARRAY['close', 'isin', 'close_adj']) q;
    ASSERT n = 10, format('lineage rows: %s, expected 10', n);
    ASSERT got LIKE 'OLDL3 BROLDLACNOR1,%NEWL3 BRNEWLACNOR1', format('lineage rows: %s', got);

    -- 1.00 before a later 10:1 grouping on the NEW ISIN is 10.00 adjusted.
    SELECT q INTO j FROM api.quote_history('NEWL3', '2024-03-08', '2024-03-08', NULL, NULL, ARRAY['close', 'close_adj']) q;
    ASSERT (j ->> 'ticker') = 'OLDL3' AND (j ->> 'close_adj')::numeric = 10.000000, format('old row: %s', j);
    SELECT q INTO j FROM api.quote_history('NEWL3', '2024-03-13', '2024-03-13', NULL, NULL, ARRAY['close_adj']) q;
    ASSERT (j ->> 'close_adj')::numeric = 10.400000, format('new row before the grouping: %s', j);
    SELECT q INTO j FROM api.quote_history('NEWL3', '2024-03-15', '2024-03-15', NULL, NULL, ARRAY['close_adj']) q;
    ASSERT (j ->> 'close_adj')::numeric = 10.500000, format('new row after the grouping: %s', j);

    -- p_from NULL starts at the oldest instrument; coverage says so.
    SELECT q INTO j FROM api.quote_history('NEWL3', NULL, '2024-03-15', NULL, NULL, ARRAY['coverage_start', 'coverage_end']) q
    ORDER BY q ->> 'trade_date' LIMIT 1;
    ASSERT (j ->> 'trade_date') = '2024-03-04' AND (j ->> 'coverage_start') = '2024-03-04'
           AND (j ->> 'coverage_end') = '2024-03-15', format('coverage: %s', j);

    -- The session count runs across the seam (03-08 -> 03-11 is adjacent).
    SELECT q INTO j FROM api.quote_history('NEWL3', '2024-03-11', '2024-03-11', NULL, NULL, ARRAY['prior_no_trade_sessions']) q;
    ASSERT (j ->> 'prior_no_trade_sessions')::int = 0, format('seam gap: %s', j);

    -- The total return is not computed before the seam, and says why.
    SELECT q INTO j FROM api.quote_history('NEWL3', '2024-03-08', '2024-03-08', NULL, NULL, ARRAY['close_total_return_null_reason']) q;
    ASSERT (j ->> 'close_total_return_null_reason') LIKE 'before an ISIN change%', format('total return: %s', j);

    -- A window inside the current instrument is unchanged: NEWL3 rows only.
    SELECT count(*) INTO n FROM api.quote_history('NEWL3', '2024-03-11', '2024-03-15', NULL, NULL, ARRAY['close']) q
    WHERE q ->> 'ticker' = 'NEWL3';
    ASSERT n = 5, format('current-only window: %s', n);

    -- The old ticker asked directly is its own history, never the successor's.
    SELECT count(*) INTO n FROM api.quote_history('OLDL3', '2024-03-04', '2024-03-15', NULL, NULL, ARRAY['close']) q;
    ASSERT n = 5, format('old ticker rows: %s', n);

    SELECT string_agg(l.ticker || ':' || l.isin, ',' ORDER BY l.seq) INTO got FROM api.ticker_lineage('NEWL3') l;
    ASSERT got = 'OLDL3:BROLDLACNOR1,NEWL3:BRNEWLACNOR1', format('ticker_lineage: %s', got);

    RAISE NOTICE 'ticker lineage OK';
END $$;


-- Futures arm of api.panel (B8 phase B): DI1 contract codes from
-- b3_futures_settlement. DI1Z99 has three sessions in 2024-08; 08-30 is the
-- month's last, and 08-29's settlement is marked P (not final), so the day
-- grain skips it and the month grain still takes 08-30.
INSERT INTO b3_futures_settlement (trade_date, ticker, open_interest, settlement_price, settlement_rate, settlement_status, raw)
VALUES ('2024-08-28', 'DI1Z99', 1000, 90000.10, 10.50, 'F', '{}'),
       ('2024-08-29', 'DI1Z99', 1100, 90010.20, 10.40, 'P', '{}'),
       ('2024-08-30', 'DI1Z99', 1200, 90020.30, 10.30, 'F', '{}');

DO $$
DECLARE
    n   int;
    got text;
BEGIN
    -- Default metrics: settlement_rate, one row a month, the last final session.
    SELECT string_agg(id || '|' || id_type || '|' || asset_class || '|' || date || '|' || metric || '|' || value || '|' || source, ',')
    INTO got FROM api.panel(ARRAY['DI1Z99'], NULL, '2024-08-01', '2024-08-31', 'month');
    ASSERT got = 'DI1Z99|future|derivative|2024-08-01|settlement_rate|10.30|b3_price_report', format('future default: %s', got);

    -- Day grain, explicit metrics: the P session is not served.
    SELECT string_agg(date || ':' || metric || '=' || value, ',' ORDER BY date, metric)
    INTO got FROM api.panel(ARRAY['DI1Z99'], ARRAY['settlement_price', 'open_interest'], '2024-08-01', '2024-08-31', 'day');
    ASSERT got = '2024-08-28:open_interest=1000,2024-08-28:settlement_price=90000.10,'
              || '2024-08-30:open_interest=1200,2024-08-30:settlement_price=90020.30',
        format('future day: %s', got);

    -- A cash ticker's default panel gains no futures rows, and close is not
    -- served for a futures code (it is not on the COTAHIST tape).
    SELECT count(*) INTO n FROM api.panel(ARRAY['REFR3'], NULL, '2024-08-01', '2024-08-30', 'month') WHERE id_type = 'future';
    ASSERT n = 0, format('cash ticker future rows: %s', n);
    SELECT count(*) INTO n FROM api.panel(ARRAY['DI1Z99'], ARRAY['close', 'volume'], '2024-08-01', '2024-08-31', 'day');
    ASSERT n = 0, format('futures close rows: %s', n);

    RAISE NOTICE 'panel futures OK';
END $$;

ROLLBACK;
