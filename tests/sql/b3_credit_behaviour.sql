-- Synthetic captures only. Runs after schema/migration 74; rolls back all rows.
BEGIN;

INSERT INTO b3_credit_capture (
    capture_id, source, requested_from, requested_to, observed_at, source_url,
    payload_sha256, raw_csv, status, expected_dates, delivered_dates, missing_dates,
    source_rows, debenture_rows, dropped_rows
)
SELECT v.id::uuid, 'b3_bdi_consolidated_records', DATE '2026-10-05', DATE '2026-10-05',
       v.seen::timestamptz, 'test-only', repeat(v.hash, 64), 'synthetic test capture',
       'complete', '["2026-10-05"]'::jsonb, '["2026-10-05"]'::jsonb, '[]'::jsonb,
       2, v.n, 0
FROM (VALUES
    ('11111111-1111-4111-8111-111111111111', '2026-10-06 09:00:00-03', 'a', 2),
    ('22222222-2222-4222-8222-222222222222', '2026-10-06 10:00:00-03', 'b', 1),
    ('33333333-3333-4333-8333-333333333333', '2026-10-06 11:00:00-03', 'a', 2)
) AS v(id, seen, hash, n)
ON CONFLICT (capture_id) DO UPDATE SET observed_at = EXCLUDED.observed_at;

INSERT INTO fact_credit_market (
    capture_id, source, instrument_code, trade_date, settlement_date,
    trade_classification, metric, unit, value, row_sha256
)
SELECT v.id::uuid, 'b3_bdi_consolidated_records', v.code, DATE '2026-10-05',
       DATE '2026-10-05', 'Extragrupo', 'volume_brl', 'BRL', v.amount, repeat('a', 64)
FROM (VALUES
    ('11111111-1111-4111-8111-111111111111', 'TEST11', 100),
    ('11111111-1111-4111-8111-111111111111', 'TEST22', 200),
    ('22222222-2222-4222-8222-222222222222', 'TEST11', 110),
    ('33333333-3333-4333-8333-333333333333', 'TEST11', 100),
    ('33333333-3333-4333-8333-333333333333', 'TEST22', 200)
) AS v(id, code, amount)
ON CONFLICT (capture_id, instrument_code, trade_date, settlement_date, trade_classification, metric)
DO UPDATE SET value = EXCLUDED.value;

-- Same source row, same capture: replay is an upsert, never another observation.
INSERT INTO fact_credit_market (
    capture_id, source, instrument_code, trade_date, settlement_date,
    trade_classification, metric, unit, value, row_sha256
)
VALUES ('11111111-1111-4111-8111-111111111111', 'b3_bdi_consolidated_records',
        'TEST11', '2026-10-05', '2026-10-05', 'Extragrupo', 'volume_brl', 'BRL', 100,
        repeat('a', 64))
ON CONFLICT (capture_id, instrument_code, trade_date, settlement_date, trade_classification, metric)
DO UPDATE SET value = EXCLUDED.value;

DO $test$
DECLARE r RECORD; n INTEGER; amount NUMERIC;
BEGIN
    SELECT count(*) INTO n FROM fact_credit_market
    WHERE capture_id IN ('11111111-1111-4111-8111-111111111111',
                         '22222222-2222-4222-8222-222222222222',
                         '33333333-3333-4333-8333-333333333333');
    IF n <> 5 THEN RAISE EXCEPTION 'capture replay duplicated facts: %', n; END IF;

    FOR r IN SELECT * FROM (VALUES
        ('2026-10-06 08:30:00-03'::timestamptz, 0, NULL::numeric),
        ('2026-10-06 09:30:00-03'::timestamptz, 2, 300::numeric),
        ('2026-10-06 10:30:00-03'::timestamptz, 1, 110::numeric),
        ('2026-10-06 11:30:00-03'::timestamptz, 2, 300::numeric)
    ) AS cut(cutoff, expected_count, expected_amount) LOOP
        -- Select the entire latest capture for each date BEFORE joining facts.
        -- Ranking per instrument would resurrect TEST22 after its removal.
        WITH chosen AS (
            SELECT DISTINCT ON (c.source, d.trade_date)
                   c.capture_id, c.source, d.trade_date
            FROM b3_credit_capture c
            CROSS JOIN LATERAL (
                SELECT value::date AS trade_date
                FROM jsonb_array_elements_text(c.delivered_dates)
            ) d
            WHERE c.status = 'complete' AND c.observed_at <= r.cutoff
              AND c.capture_id IN ('11111111-1111-4111-8111-111111111111',
                                   '22222222-2222-4222-8222-222222222222',
                                   '33333333-3333-4333-8333-333333333333')
              AND d.trade_date = DATE '2026-10-05'
            ORDER BY c.source, d.trade_date, c.observed_at DESC, c.capture_id DESC
        )
        SELECT count(*), sum(f.value) INTO n, amount
        FROM chosen c JOIN fact_credit_market f
          ON f.capture_id = c.capture_id AND f.trade_date = c.trade_date
        WHERE f.metric = 'volume_brl';
        IF n <> r.expected_count OR amount IS DISTINCT FROM r.expected_amount THEN
            RAISE EXCEPTION 'as-of failure at %: count %, amount %', r.cutoff, n, amount;
        END IF;
    END LOOP;

    BEGIN
        UPDATE b3_credit_capture SET missing_dates = '["2026-10-05"]'::jsonb
        WHERE capture_id = '11111111-1111-4111-8111-111111111111';
        RAISE EXCEPTION 'complete capture accepted missing date';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        UPDATE b3_credit_capture SET dropped_rows = 1
        WHERE capture_id = '11111111-1111-4111-8111-111111111111';
        RAISE EXCEPTION 'complete capture accepted dropped row';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    IF EXISTS (
        SELECT 1 FROM pg_roles client_role
        WHERE client_role.rolname IN ('anon', 'authenticated', 'silo_api')
          AND (has_table_privilege(client_role.rolname, 'b3_credit_capture', 'SELECT')
               OR has_table_privilege(client_role.rolname, 'fact_credit_market', 'SELECT'))
    ) THEN RAISE EXCEPTION 'credit landing tables exposed to client role'; END IF;
END
$test$;

ROLLBACK;
