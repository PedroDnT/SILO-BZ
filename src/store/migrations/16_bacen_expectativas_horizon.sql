-- Migration 16: keep every Focus forecast HORIZON instead of one per survey date
-- =============================================================================
-- bacen_expectativas was UNIQUE NULLS NOT DISTINCT on
-- (endpoint_name, indicador, reference_date).
--
-- That key is wrong for the source. The BACEN Focus API returns one row per
-- (survey date x forecast horizon): on a single survey date, ExpectativasMercadoAnuais
-- publishes a median IPCA for 2026, another for 2027, another for 2028, and so on.
-- All of those share endpoint_name + indicador + reference_date, so the upsert
-- collapsed them to whichever row happened to be written last. The backfill log
-- shows it plainly:
--
--     upsert dedup: table=bacen_expectativas ... collapsed 10000 -> 313 rows
--
-- 97% of the fetched data was discarded, and the value that survived was an
-- arbitrary horizon. A chart built on it plots "the consensus" while silently
-- mixing a one-year and a five-year forecast between adjacent points — worse
-- than empty, because it looks fine.
--
-- The horizon is DataReferencia in the payload ('2026', '2027', or '08/2026'
-- for the monthly endpoints). Adding it to the key preserves the full surface
-- and lets a query pin one horizon and compare like with like.
--
-- Idempotent and safe to re-run: the column add, the backfill, the constraint
-- swap and the index are each guarded.

BEGIN;

ALTER TABLE bacen_expectativas
    ADD COLUMN IF NOT EXISTS horizon TEXT;

-- Recover the horizon for rows already stored: it has been captured in raw all
-- along, just never promoted to a column. Never synthesised — rows whose raw
-- lacks DataReferencia keep horizon NULL and are matched by NULLS NOT DISTINCT.
UPDATE bacen_expectativas
   SET horizon = raw ->> 'DataReferencia'
 WHERE horizon IS NULL
   AND raw ? 'DataReferencia';

-- Swap the constraint. Dropping first means the historical rows that were
-- collapsed stay as they are (one horizon per survey date); re-running the
-- ingest repopulates the rest, since the upsert now has somewhere to put them.
ALTER TABLE bacen_expectativas
    DROP CONSTRAINT IF EXISTS uq_bacen_expectativas;

ALTER TABLE bacen_expectativas
    ADD CONSTRAINT uq_bacen_expectativas
    UNIQUE NULLS NOT DISTINCT (endpoint_name, indicador, reference_date, horizon);

CREATE INDEX IF NOT EXISTS idx_expectativas_horizon
    ON bacen_expectativas (endpoint_name, indicador, horizon, reference_date DESC);

COMMENT ON COLUMN bacen_expectativas.horizon IS
    'Forecast horizon as published in DataReferencia: a year ("2026") for the '
    'annual endpoints, month/year ("08/2026") for the monthly ones. Part of the '
    'natural key -- one survey date carries a forecast per horizon.';

COMMIT;
