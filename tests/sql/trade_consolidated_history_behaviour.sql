BEGIN;
-- api.trade_consolidated_history (32_api_trade_consolidated.sql, catalog v65),
-- executed on a synthetic FORWARD ticker: refusals, an untraded session, the
-- page edge and the cursor walk, anon access and the coverage row. Rolled back.
INSERT INTO b3_trade_consolidated (trade_date, ticker, isin, segment, min_price, max_price, avg_price, last_price,
    oscillation_pct, ref_price, trade_count, quantity, notional_brl, file_status)
SELECT d::date, 'ZZTC11', 'BRZZTCCTF000', 'FORWARD', 100, 101, 100.5, 100.7, 0.1, NULL, 10, 100, 10050, 'Final'
FROM generate_series(DATE '2020-01-01', DATE '2023-12-31', INTERVAL '1 day') d;   -- 1461 rows
INSERT INTO b3_trade_consolidated (trade_date, ticker, isin, segment, ref_price, file_status)
VALUES ('2024-01-02', 'ZZTC11', 'BRZZTCCTF000', 'FORWARD', 100.5, 'Final');       -- untraded session

DO $$
DECLARE n INT; r RECORD; after TEXT := ''; total INT := 0; pages INT := 0;
BEGIN
  -- unknown ticker refuses with 22023 and points at quote_history
  BEGIN
    PERFORM * FROM api.trade_consolidated_history('PETR4');
    RAISE EXCEPTION 'unknown ticker was served';
  EXCEPTION WHEN sqlstate '22023' THEN
    GET STACKED DIAGNOSTICS after = MESSAGE_TEXT;
    ASSERT after LIKE '%FORWARD%' AND after LIKE '%quote_history%', after;
  END;
  BEGIN
    PERFORM * FROM api.trade_consolidated_history(NULL);
    RAISE EXCEPTION 'NULL ticker was served';
  EXCEPTION WHEN sqlstate '22023' THEN NULL;
  END;
  -- NULL window refuses
  BEGIN
    PERFORM * FROM api.trade_consolidated_history('ZZTC11', NULL, NULL);
    RAISE EXCEPTION 'NULL window was served';
  EXCEPTION WHEN sqlstate '22023' THEN NULL;
  END;
  -- over one page without a cursor refuses
  BEGIN
    PERFORM * FROM api.trade_consolidated_history('ZZTC11', '2020-01-01', '2024-12-31');
    RAISE EXCEPTION 'over-cap result was served';
  EXCEPTION WHEN sqlstate '22023' THEN NULL;
  END;
  -- lower-case input and a short window
  SELECT count(*) INTO n FROM api.trade_consolidated_history(' zztc11 ', '2023-12-01', '2023-12-31');
  ASSERT n = 31, n;
  -- untraded session: only ref_price
  SELECT * INTO r FROM api.trade_consolidated_history('ZZTC11', '2024-01-02', '2024-01-02');
  ASSERT r.last_price IS NULL AND r.ref_price = 100.5 AND r.trade_count IS NULL, r;
  -- cursor walk: every row once, in order
  after := '';
  LOOP
    SELECT count(*), max(trade_date)::text INTO n, after FROM api.trade_consolidated_history('ZZTC11', '2020-01-01', '2024-12-31', after);
    EXIT WHEN n = 0;
    pages := pages + 1; total := total + n;
    EXIT WHEN n < 1000;
  END LOOP;
  ASSERT total = 1462 AND pages = 2, format('total %s pages %s', total, pages);
  RAISE NOTICE 'trade_consolidated_history OK: % rows in % pages', total, pages;
END $$;

SET ROLE anon;
SELECT count(*) AS anon_rows FROM api.trade_consolidated_history('ZZTC11', '2023-12-01', '2023-12-05');
RESET ROLE;
SELECT dataset, as_of, complete_through, left(notes, 60) AS notes, newest_period
FROM api.coverage() WHERE dataset = 'trade_consolidated_history';
ROLLBACK;
