-- =============================================================================
-- Migration 24 — trigram index for api.lookup's name search (SERVING.md step 5)
--
-- api.lookup runs ILIKE '%…%' against cia_company.denom_cia; without a trigram
-- index that is a sequential scan per keystroke-style query. pg_trgm ships with
-- Supabase; CREATE EXTENSION IF NOT EXISTS is a no-op where it is already on.
--
-- dim_fund.fund_name gets its trigram index in the ANALYTICAL layer
-- (11_indexes.sql), not here: dim_fund is a materialized view dropped and
-- recreated by every apply_analytical.sh run, so an index created in a
-- migration would silently vanish on the next apply.
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX IF NOT EXISTS idx_cia_company_denom_trgm
    ON cia_company USING gin (denom_cia gin_trgm_ops);
