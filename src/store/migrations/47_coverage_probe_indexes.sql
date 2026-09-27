-- 47_coverage_probe_indexes.sql — two date indexes api.coverage() probes.
--
-- Mirrored verbatim into schema.sql (which stays canonical). Idempotent and
-- psql-clean: CI applies with -v ON_ERROR_STOP=1.
--
-- api.coverage() (19_api_contract.sql) reads every dataset's newest date as
-- (SELECT MAX(col) FROM t WHERE col <= CURRENT_DATE), one backward index probe
-- when col leads an index. Two of its tables had no such index:
--
--   b3_lending_open_position — its indexes lead with codneg, or are partial on
--     is_total; MAX(trade_date) over the whole table could use neither.
--   bacen_expectativas — its index leads with (endpoint_name, indicador).
--
-- Both are plain btrees on the date, DESC to match the probe direction.
CREATE INDEX IF NOT EXISTS idx_b3_lending_open_position_date
    ON b3_lending_open_position (trade_date DESC);

CREATE INDEX IF NOT EXISTS idx_expectativas_date
    ON bacen_expectativas (reference_date DESC);
