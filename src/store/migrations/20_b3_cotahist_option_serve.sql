-- =============================================================================
-- Migration 20 — B3 COTAHIST option serve path (partial index)
--
-- INSTRUMENTS.md Phase A: serve the option rows (tpmerc '070' calls / '080'
-- puts) already landed in b3_cotahist through api.option_chain /
-- api.option_history. Options are ~89% of every COTAHIST session, so
-- per-codneg lookups need the same treatment cash got in migration 19: a
-- partial (codneg, trade_date) btree scoped to the segment the serve path
-- filters on, mirroring idx_b3_cotahist_vista.
--
-- Termo ('030') deliberately gets NO index here: at ~135 rows/session the
-- existing idx_b3_cotahist_tpmerc_dt (tpmerc, trade_date DESC) already
-- narrows api.termo_history to a trivial row count; a third partial btree
-- would cost write amplification on every daily upsert for nothing.
--
-- Idempotent: CREATE INDEX IF NOT EXISTS. schema.sql carries the same end
-- state.
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_b3_cotahist_option
    ON b3_cotahist (codneg, trade_date DESC)
    WHERE tpmerc IN ('070', '080');
