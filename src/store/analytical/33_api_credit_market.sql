-- Observation-only serving over retained credit capture vintages.
-- Select snapshots per date BEFORE instrument filtering: removed rows stay removed.
BEGIN;

CREATE OR REPLACE FUNCTION api.credit_market_history(
    p_code TEXT,
    p_from DATE DEFAULT (CURRENT_DATE - 365),
    p_to DATE DEFAULT CURRENT_DATE,
    p_as_of TIMESTAMPTZ DEFAULT now()
)
RETURNS TABLE (
    instrument_code TEXT,
    trade_date DATE,
    settlement_date DATE,
    trade_classification TEXT,
    isin TEXT,
    issuer_name TEXT,
    quantity NUMERIC,
    min_price NUMERIC,
    avg_price NUMERIC,
    max_price NUMERIC,
    last_price NUMERIC,
    reference_price NUMERIC,
    trade_count NUMERIC,
    volume_brl NUMERIC,
    oscillation_pct NUMERIC,
    units JSONB,
    capture_id UUID,
    payload_sha256 TEXT,
    row_sha256 TEXT,
    observed_at TIMESTAMPTZ,
    available_at TIMESTAMPTZ,
    source TEXT
)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = ''
AS $fn$
#variable_conflict use_column
DECLARE
    v_code TEXT := upper(btrim(p_code));
BEGIN
    IF v_code IS NULL OR v_code !~ '^[A-Z0-9]{4,12}$' THEN
        RAISE EXCEPTION 'credit_market_history: p_code must be a debenture instrument code'
            USING ERRCODE = '22023';
    END IF;
    IF p_from IS NULL OR p_to IS NULL OR p_from > p_to
       OR p_as_of IS NULL OR NOT isfinite(p_as_of) OR p_as_of > CURRENT_TIMESTAMP THEN
        RAISE EXCEPTION 'credit_market_history: require an ordered date window and a finite, non-future p_as_of'
            USING ERRCODE = '22023';
    END IF;
    -- A code observed only AFTER the cutoff must not be recognized retroactively.
    IF NOT EXISTS (
        SELECT 1 FROM public.fact_credit_market f
        JOIN public.b3_credit_capture c USING (capture_id)
        JOIN public.cvm_ingest_log l ON l.run_id = c.capture_id
        WHERE f.instrument_code = v_code AND c.source = 'b3_bdi_consolidated_records'
          AND c.status = 'complete' AND c.observed_at <= p_as_of
          AND l.entity = 'b3' AND l.doc_type = 'credit_consolidated' AND l.status = 'ok'
          AND l.finished_at >= c.observed_at AND l.finished_at <= p_as_of
          AND l.rows_upserted = c.debenture_rows * 9
    ) THEN
        RAISE EXCEPTION 'credit_market_history: unknown code at p_as_of: %', v_code
            USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    WITH eligible AS MATERIALIZED (
        SELECT c.capture_id, c.requested_from, c.requested_to, c.expected_dates,
               c.delivered_dates, c.payload_sha256, c.observed_at, c.source,
               l.finished_at AS available_at
        FROM public.b3_credit_capture c
        JOIN public.cvm_ingest_log l ON l.run_id = c.capture_id
        WHERE c.source = 'b3_bdi_consolidated_records' AND c.status = 'complete'
          AND c.requested_from <= p_to AND c.requested_to >= p_from
          AND c.observed_at <= p_as_of
          AND l.entity = 'b3' AND l.doc_type = 'credit_consolidated' AND l.status = 'ok'
          AND l.finished_at >= c.observed_at AND l.finished_at <= p_as_of
          AND l.rows_upserted = c.debenture_rows * 9
    ), chosen AS MATERIALIZED (
        SELECT DISTINCT ON (d.day) c.capture_id, d.day::date AS trade_date,
               c.payload_sha256, c.observed_at, c.available_at, c.source
        FROM eligible c
        CROSS JOIN LATERAL jsonb_array_elements_text(c.expected_dates) d(day)
        WHERE d.day::date BETWEEN p_from AND p_to
          AND d.day::date BETWEEN c.requested_from AND c.requested_to
          AND c.delivered_dates ? d.day
        ORDER BY d.day, c.observed_at DESC, c.available_at DESC, c.capture_id DESC
    ), page AS MATERIALIZED (
        SELECT f.instrument_code, f.trade_date, f.settlement_date, f.trade_classification,
               max(f.isin) AS isin, max(f.issuer_name) AS issuer_name,
               max(f.value) FILTER (WHERE f.metric = 'quantity') AS quantity,
               max(f.value) FILTER (WHERE f.metric = 'min_price') AS min_price,
               max(f.value) FILTER (WHERE f.metric = 'avg_price') AS avg_price,
               max(f.value) FILTER (WHERE f.metric = 'max_price') AS max_price,
               max(f.value) FILTER (WHERE f.metric = 'last_price') AS last_price,
               max(f.value) FILTER (WHERE f.metric = 'reference_price') AS reference_price,
               max(f.value) FILTER (WHERE f.metric = 'trade_count') AS trade_count,
               max(f.value) FILTER (WHERE f.metric = 'volume_brl') AS volume_brl,
               max(f.value) FILTER (WHERE f.metric = 'oscillation_pct') AS oscillation_pct,
               jsonb_object_agg(f.metric, f.unit) AS units,
               c.capture_id, c.payload_sha256, max(f.row_sha256) AS row_sha256,
               c.observed_at, c.available_at, c.source
        FROM chosen c
        JOIN public.fact_credit_market f USING (capture_id, trade_date)
        WHERE f.instrument_code = v_code
        GROUP BY f.instrument_code, f.trade_date, f.settlement_date, f.trade_classification,
                 c.capture_id, c.payload_sha256, c.observed_at, c.available_at, c.source
        ORDER BY f.trade_date, f.settlement_date, f.trade_classification
        LIMIT 1001
    )
    SELECT p.* FROM page p
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'credit_market_history')
    ORDER BY p.trade_date, p.settlement_date, p.trade_classification;
END;
$fn$;

COMMENT ON FUNCTION api.credit_market_history(TEXT, DATE, DATE, TIMESTAMPTZ) IS
    'Debenture market observations for one instrument code, oldest first, one row per trade_date, settlement_date and trade_classification. Select the latest complete successfully audited capture PER TRADE DATE before instrument filtering; a newer snapshot removing a code does not resurrect an older row. p_as_of defaults to current knowledge and requires both observed_at and available_at (successful audit completion) no later than that cutoff; backfilled trade dates never become original publication-time PIT. Unknown code at the cutoff raises 22023; a known code with no observations in the window returns an empty set, never a zero or filled price. Nine nullable metrics with explicit units and capture/raw/row hashes, ISIN and source-reported issuer name; no inferred issuer CNPJ or stock ticker. min/avg/max prices, quantity, trade_count and volume_brl belong to the full group. last_price and reference_price are instrument-wide and repeat across groups: never sum or average their repeated copies. reference_price may be modeled, is not a trade and never substitutes for last_price. Prices are BRL/unit, quantity units, trade_count trades, volume_brl BRL and oscillation_pct percent. volume_brl is transaction volume, not outstanding. No yield, spread, coupon/amortization-adjusted total return or cash-flow engine. NULL stays unpublished. Row cap: more than 1000 rows RAISES 22023, never trimmed; narrow p_from/p_to. No date-only cursor because several groups share a date. Capture completeness covers requested sessions, not every session across the warehouse history; inspect api.coverage for known span, and absence is never filled.';

REVOKE ALL ON FUNCTION api.credit_market_history(TEXT, DATE, DATE, TIMESTAMPTZ) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.credit_market_history(TEXT, DATE, DATE, TIMESTAMPTZ) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION api.credit_market_history(TEXT, DATE, DATE, TIMESTAMPTZ) TO silo_api;

COMMIT;
