-- =============================================================================
-- 10_indexes.sql
-- Additional indexes for analytical query performance.
-- Applied after the matviews and functions are in place.
-- All CREATE INDEX use IF NOT EXISTS — safe to re-run.
-- =============================================================================

BEGIN;
SET statement_timeout = '30min';  -- index builds on large tables can take time

-- ---------------------------------------------------------------------------
-- 1. cvm_fidc_tranche: composite (cnpj, period DESC)
--    Pattern: WHERE cnpj = $1 AND period BETWEEN $2 AND $3
--    (fidc_tranche_performance, fidc_subordination_trend)
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_fidc_tranche_cnpj_period
  ON cvm_fidc_tranche (cnpj, period DESC);

-- ---------------------------------------------------------------------------
-- 2. fact_fund_monthly: partial index for yield-bearing rows
--    Pattern: WHERE entity_type = $1 AND period = $2 AND pct_yield_mes IS NOT NULL
--    (yield_distribution, fund_ranking with 'yield' metric)
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_fact_fund_monthly_yield
  ON fact_fund_monthly (entity_type, period, pct_yield_mes)
  WHERE pct_yield_mes IS NOT NULL;

-- ---------------------------------------------------------------------------
-- 3. fact_fund_monthly: covering index for fund time-series queries
--    Pattern: WHERE cnpj = $1 AND period BETWEEN $2 AND $3
--    SELECT vl_patrim_liq, pct_yield_mes, nr_cotst, captc_mes, resg_mes
--    (fund_nav_series, fund_flow_trend, fund_profile)
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_fact_fund_monthly_nav_cover
  ON fact_fund_monthly (cnpj, period)
  INCLUDE (entity_type, vl_patrim_liq, pct_yield_mes, nr_cotst, captc_mes, resg_mes, vl_inadimpl, vl_ativo);

-- ---------------------------------------------------------------------------
-- 4. fact_fund_monthly: covering index for entity-level aggregate queries
--    Pattern: WHERE entity_type = $1 AND period BETWEEN $2 AND $3
--    SELECT vl_patrim_liq, pct_yield_mes, vl_inadimpl
--    (entity_monthly_stats, cross_entity_comparison, industry_aum_trend)
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_fact_fund_monthly_entity_cover
  ON fact_fund_monthly (entity_type, period)
  INCLUDE (vl_patrim_liq, pct_yield_mes, vl_inadimpl, captc_mes, resg_mes, nr_cotst);

-- ---------------------------------------------------------------------------
-- 5. dim_fund: index skipped — dim_fund is a regular VIEW, not a table or
--    materialized view. Indexes cannot be created on views in PostgreSQL.
--    new_funds_per_period() queries dim_fund which resolves to its underlying
--    CVM tables (cvm_fi_diario, cvm_fidc_mensal, etc.) — those already have
--    (cnpj, period) composite indexes covering this access pattern.
--    If this becomes a bottleneck, convert dim_fund to a MATERIALIZED VIEW.
-- ---------------------------------------------------------------------------

-- ---------------------------------------------------------------------------
-- Autovacuum tuning for materialized views that are refreshed daily.
-- REFRESH MATERIALIZED VIEW CONCURRENTLY creates dead tuples that must be
-- vacuumed. Aggressive autovacuum keeps them healthy.
-- ---------------------------------------------------------------------------
-- NOTE: ALTER MATERIALIZED VIEW ... SET storage options is not supported in
-- PostgreSQL. Autovacuum settings must be applied to the underlying relation:

ALTER TABLE fact_fund_monthly
  SET (autovacuum_vacuum_scale_factor  = 0.05,   -- vacuum at 5% dead tuples (default 20%)
       autovacuum_analyze_scale_factor = 0.02);   -- analyze at 2% changes (default 10%)

ALTER TABLE fact_security_monthly
  SET (autovacuum_vacuum_scale_factor  = 0.05,
       autovacuum_analyze_scale_factor = 0.02);

-- ---------------------------------------------------------------------------
-- FK index audit query (run manually to verify no missing indexes):
-- ---------------------------------------------------------------------------
-- SELECT conrelid::regclass AS table_name, a.attname AS fk_column
-- FROM pg_constraint c
-- JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
-- WHERE c.contype = 'f'
--   AND NOT EXISTS (
--     SELECT 1 FROM pg_index i
--     WHERE i.indrelid = c.conrelid AND a.attnum = ANY(i.indkey)
--   );
-- (No FK constraints in this schema — joins managed at application level.)

-- ---------------------------------------------------------------------------
-- GIN index on raw JSONB (commented out — only needed if raw filtering required)
-- ---------------------------------------------------------------------------
-- CREATE INDEX CONCURRENTLY idx_cvm_fidc_mensal_raw_gin
--   ON cvm_fidc_mensal USING GIN (raw jsonb_path_ops);
-- Uncomment if clients need: WHERE raw @> '{"TP_FUNDO": "FIDC"}'

COMMIT;
