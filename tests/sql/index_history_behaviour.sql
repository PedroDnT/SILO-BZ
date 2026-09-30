-- Executed checks for api.index_history (#415): B3's published index level.
-- Seeds inside a transaction that is rolled back:
--
--   psql "$POSTGRES_URL" -v ON_ERROR_STOP=1 -f tests/sql/index_history_behaviour.sql

BEGIN;

-- 1001 weekday levels from 2021-01-04, plus B3's published 2025-12-30 close.
INSERT INTO b3_index_level (index_code, trade_date, level)
SELECT 'IBOV', d, 100000 + g
FROM (SELECT d::date AS d, row_number() OVER (ORDER BY d) AS g
      FROM generate_series('2021-01-04'::date, '2025-06-30', '1 day') d
      WHERE extract(isodow FROM d) < 6) x
WHERE g <= 1001;
INSERT INTO b3_index_level (index_code, trade_date, level) VALUES ('IBOV', '2025-12-30', 161125.37);

DO $$
DECLARE
    n INT;
    v NUMERIC;
    last_d DATE;
BEGIN
    SELECT i.level INTO v FROM api.index_history('IBOV', '2025-12-30', '2025-12-30') i;
    ASSERT v = 161125.37, format('2025-12-30 close: %s', v);
    -- Lower case is the same code.
    SELECT count(*) INTO n FROM api.index_history('ibov', '2025-12-30', '2025-12-30');
    ASSERT n = 1, 'codes are case-insensitive';
    -- The page edge: 1000 then the rest, no gap or repeat.
    SELECT count(*), max(i.trade_date) INTO n, last_d FROM api.index_history('IBOV', NULL, '2025-12-31', '') i;
    ASSERT n = 1000, format('first page: %s', n);
    SELECT count(*) INTO n FROM api.index_history('IBOV', NULL, '2025-12-31', last_d::text) i;
    ASSERT n = 2, format('second page: %s', n);
    RAISE NOTICE 'index_history behaviour OK';
END $$;

CREATE TEMP TABLE cases (label TEXT, stmt TEXT, reason TEXT);
INSERT INTO cases VALUES
    ('ETF ticker',         $s$SELECT * FROM api.index_history('BOVA11')$s$, 'reason=unknown_index'),
    ('settlement index',   $s$SELECT * FROM api.index_history('IBOV11')$s$, 'reason=unknown_index'),
    ('empty code',         $s$SELECT * FROM api.index_history('')$s$, 'reason=unknown_index'),
    ('before coverage',    $s$SELECT * FROM api.index_history('IBOV', '2020-01-02', '2021-06-30')$s$, 'reason=outside_coverage'),
    ('after coverage',     $s$SELECT * FROM api.index_history('IBOV', '2026-01-02', '2026-06-30')$s$, 'reason=outside_coverage'),
    ('inverted window',    $s$SELECT * FROM api.index_history('IBOV', '2024-06-30', '2024-01-02')$s$, 'reason=invalid_window'),
    ('over the page',      $s$SELECT * FROM api.index_history('IBOV', NULL, '2025-12-31')$s$, NULL);

DO $$
DECLARE
    c      RECORD;
    detail TEXT;
BEGIN
    FOR c IN SELECT * FROM cases LOOP
        BEGIN
            EXECUTE c.stmt;
            RAISE EXCEPTION 'case "%" was served, expected a 22023 refusal', c.label;
        EXCEPTION WHEN sqlstate '22023' THEN
            GET STACKED DIAGNOSTICS detail = PG_EXCEPTION_DETAIL;
            ASSERT c.reason IS NULL OR detail LIKE c.reason || '%',
                format('case "%s": detail %L, expected %L', c.label, detail, c.reason);
        END;
    END LOOP;
    RAISE NOTICE 'index_history refusals OK';
END $$;

ROLLBACK;
