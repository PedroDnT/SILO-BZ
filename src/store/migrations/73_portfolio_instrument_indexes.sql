-- 73_portfolio_instrument_indexes.sql — make the CETIP-code lookup of
-- api.portfolio_instruments (catalog v61, 31_api_portfolio.sql) an index probe.
--
-- WHAT WAS SLOW. portfolio_instruments finds a CRA or CRI by its CETIP code:
--
--     WHERE codigo_cetip = ? AND data_referencia = (newest for that code)
--
-- cvm_securit_serie had no index on codigo_cetip (its indexes are the key,
-- cnpj_securit, codigo_isin and (situacao, data_referencia)), so every call
-- was a sequential scan of the whole table. Measured on production 2026-10-05
-- for the 15 codes of the pinned statement: 322k rows, 248 MB, 1.1 s cold
-- (31,385 buffers read) — a third of the anon role's 3 s statement_timeout
-- for one CTE of one call.
--
-- WHY THIS SHAPE. (codigo_cetip, data_referencia DESC): the newest informe of a
-- code is the first entry of its range, and the rows of that date are the
-- next ones. Size: an estimate, not a measurement (the index does not exist
-- yet): about the size of idx_securit_serie_isin, a single text column over
-- the same rows (6,000 kB measured 2026-10-05), plus a date per entry —
-- roughly 8 to 10 MB.
--
-- The debenture half of the same function needs no index: it probes
-- idx_fi_cda_acoes_ativo (cd_ativo, period DESC), which migration 32 created
-- (198 MB on 2026-10-05).
--
-- Not CONCURRENTLY, as in migration 36: every other index in this schema is
-- built plainly, the schema gate is serialized ahead of ingest by the
-- supabase-ingest concurrency group, and CONCURRENTLY cannot run inside the
-- transaction the apply path uses. The build reads 322k rows; the SHARE lock
-- it holds blocks writes to cvm_securit_serie for the seconds that takes,
-- never reads.

CREATE INDEX IF NOT EXISTS idx_securit_serie_cetip
    ON cvm_securit_serie (codigo_cetip, data_referencia DESC);

COMMENT ON INDEX idx_securit_serie_cetip IS
    'Drives api.portfolio_instruments: a CRA or CRI by its CETIP code, at the code''s newest data_referencia (migration 73).';
