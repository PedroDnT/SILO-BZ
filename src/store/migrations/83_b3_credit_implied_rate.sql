-- Implied rates from B3 traded debenture PUs, #1007 (ADR 0004 amendment).
-- Private: no serving grant, never in schema api, serve/, the MCP or the dashboard.
-- anbima_holiday: ANBIMA's national holiday list, as published, for business-day counts.
-- b3_credit_implied_rate: one CALCULATED row per B3 trade group (instrument, trade date,
-- settlement date, classification) and method_version. It never touches
-- fact_credit_market; the B3 capture id and the inputs are stored with the result.
BEGIN;
CREATE TABLE IF NOT EXISTS anbima_holiday (
    holiday_date DATE        NOT NULL,
    name         TEXT        NOT NULL CHECK (btrim(name) <> ''),
    source_url   TEXT        NOT NULL,
    observed_at  TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_anbima_holiday UNIQUE (holiday_date)
);
CREATE TABLE IF NOT EXISTS b3_credit_implied_rate (
    codigo               TEXT        NOT NULL CHECK (btrim(codigo) <> ''),
    trade_date           DATE        NOT NULL,
    settlement_date      DATE        NOT NULL CHECK (settlement_date >= trade_date),
    trade_classification TEXT        NOT NULL CHECK (btrim(trade_classification) <> ''),
    method_version       TEXT        NOT NULL CHECK (btrim(method_version) <> ''),
    is_calculated        BOOLEAN     NOT NULL DEFAULT TRUE CHECK (is_calculated),
    b3_capture_id        UUID        NOT NULL REFERENCES b3_credit_capture(capture_id),
    pu_brl               NUMERIC     NOT NULL CHECK (pu_brl > 0),
    quantity             NUMERIC,
    volume_brl           NUMERIC,
    trade_count          INTEGER,
    indexador            TEXT        NOT NULL,
    forma_remuneracao    TEXT        NOT NULL,
    contract_rate_pct    NUMERIC     NOT NULL,
    implied_rate_pct     NUMERIC     NOT NULL,
    rate_basis           TEXT        NOT NULL CHECK (rate_basis IN (
        'pre_aa', 'ipca_real_aa', 'di_spread_aa', 'pct_di')),
    flows_used           INTEGER     NOT NULL CHECK (flows_used > 0),
    inputs               JSONB       NOT NULL,
    solver               JSONB       NOT NULL,
    computed_at          TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_b3_credit_implied_rate UNIQUE (
        codigo, trade_date, settlement_date, trade_classification, method_version)
);
CREATE INDEX IF NOT EXISTS idx_b3_credit_implied_rate_date
    ON b3_credit_implied_rate (trade_date DESC, codigo);
COMMENT ON TABLE anbima_holiday IS
    'ANBIMA national holiday list (anbima.com.br/feriados/arqs/feriados_nacionais.xls), one row per date as published. Used only for business-day counts. Private.';
COMMENT ON TABLE b3_credit_implied_rate IS
    'CALCULATED, not observed: the yield that discounts the published agenda of a debenture (anbima_debenture_event) to a B3 traded average PU (fact_credit_market, avg_price), by method_version. rate_basis says what implied_rate_pct is: pre_aa, ipca_real_aa and di_spread_aa are percent a year on 252 business days; pct_di is a percent of DI. inputs and solver hold everything the result used. Compare with anbima_debenture_indicative (an ANBIMA model value). Private: no serving grant until the owner approves.';
ALTER TABLE anbima_holiday ENABLE ROW LEVEL SECURITY;
ALTER TABLE b3_credit_implied_rate ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON anbima_holiday, b3_credit_implied_rate FROM PUBLIC;
DO $grants$
DECLARE role_name TEXT;
BEGIN
    FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated', 'silo_api'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
            EXECUTE format('REVOKE ALL ON anbima_holiday, b3_credit_implied_rate FROM %I', role_name);
        END IF;
    END LOOP;
END
$grants$;
COMMIT;
