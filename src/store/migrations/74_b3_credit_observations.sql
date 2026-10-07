-- B3 OTC debentures, #662. No serving grant and no yield inferred from PU.
-- A capture is one retrieval, keyed by the cvm_ingest_log run UUID. Replaying
-- that capture is idempotent. A later retrieval is a new knowledge-time vintage,
-- even if its payload is identical; this also preserves A -> B -> A revisions.
-- The long fact retains B3's instrument/date/settlement/classification grain.

BEGIN;

CREATE TABLE IF NOT EXISTS b3_credit_capture (
    capture_id      UUID PRIMARY KEY,
    source          TEXT NOT NULL,
    requested_from  DATE NOT NULL,
    requested_to    DATE NOT NULL CHECK (requested_to >= requested_from),
    observed_at     TIMESTAMPTZ NOT NULL,
    source_url      TEXT NOT NULL,
    payload_sha256  TEXT NOT NULL CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
    raw_csv         TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('captured', 'incomplete', 'complete')),
    expected_dates  JSONB NOT NULL CHECK (jsonb_typeof(expected_dates) = 'array'),
    delivered_dates JSONB NOT NULL CHECK (jsonb_typeof(delivered_dates) = 'array'),
    missing_dates   JSONB NOT NULL CHECK (jsonb_typeof(missing_dates) = 'array'),
    source_rows     INTEGER NOT NULL CHECK (source_rows >= 0),
    debenture_rows  INTEGER NOT NULL CHECK (debenture_rows >= 0),
    dropped_rows    INTEGER NOT NULL CHECK (dropped_rows >= 0),
    CONSTRAINT ck_credit_capture_complete CHECK (
        status <> 'complete' OR (
            jsonb_array_length(expected_dates) > 0 AND jsonb_array_length(missing_dates) = 0
            AND dropped_rows = 0 AND source_rows > 0
            AND delivered_dates @> expected_dates
        )
    )
);
CREATE INDEX IF NOT EXISTS idx_credit_capture_asof
    ON b3_credit_capture (source, observed_at DESC) WHERE status = 'complete';

CREATE TABLE IF NOT EXISTS fact_credit_market (
    capture_id            UUID NOT NULL REFERENCES b3_credit_capture(capture_id),
    source                TEXT NOT NULL,
    instrument_code       TEXT NOT NULL CHECK (btrim(instrument_code) <> ''),
    trade_date            DATE NOT NULL,
    settlement_date       DATE NOT NULL CHECK (settlement_date >= trade_date),
    trade_classification  TEXT NOT NULL CHECK (btrim(trade_classification) <> ''),
    isin                  TEXT,
    issuer_name           TEXT,
    metric                TEXT NOT NULL,
    unit                  TEXT NOT NULL,
    value                 NUMERIC,
    row_sha256            TEXT NOT NULL CHECK (row_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT uq_fact_credit_market UNIQUE (
        capture_id, instrument_code, trade_date, settlement_date, trade_classification, metric
    )
);
CREATE INDEX IF NOT EXISTS idx_credit_market_instrument_date
    ON fact_credit_market (instrument_code, trade_date DESC, capture_id);

COMMENT ON TABLE b3_credit_capture IS
    'One B3 ConsolidatedRecords retrieval with its full decoded CSV and hash. observed_at is SILO retrieval time, never original publication time. Read complete captures only; choose the latest eligible capture PER TRADE DATE before joining facts, so removed rows do not survive revisions. Captured/incomplete snapshots are diagnostic evidence, never a complete market day.';
COMMENT ON TABLE fact_credit_market IS
    'Long DEB-only observations, keyed by capture plus source instrument/date/settlement/classification/metric. min/avg/max prices, quantity, count and volume are grouping-specific. last_price and reference_price are instrument-wide, repeated across groupings; reference_price may be modeled. No CNPJ, obligor, yield, outstanding or total return is inferred. NULL means unpublished. Private until a reviewed serving contract exists.';

ALTER TABLE b3_credit_capture ENABLE ROW LEVEL SECURITY;
ALTER TABLE fact_credit_market ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON b3_credit_capture, fact_credit_market FROM PUBLIC;
DO $grants$
DECLARE role_name TEXT;
BEGIN
    FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated', 'silo_api'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
            EXECUTE format('REVOKE ALL ON b3_credit_capture, fact_credit_market FROM %I', role_name);
        END IF;
    END LOOP;
END
$grants$;

COMMIT;
