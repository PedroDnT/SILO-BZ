-- =============================================================================
-- 11_grants_and_rls.sql
-- Grant SELECT + EXECUTE to Supabase client roles (anon, authenticated).
-- All CVM data is public — no per-user access controls today.
--
-- Functions use SECURITY INVOKER (caller's RLS permissions apply).
-- Since CVM data should be publicly readable, we grant SELECT on all
-- analytical objects and raw tables to both anon and authenticated roles.
--
-- Future: when per-user watchlists or private annotations are added, add
-- RLS policies using the pattern:
--   USING (user_id = (SELECT auth.uid()))   ← wrap in SELECT for 100x perf
-- NOT:
--   USING (user_id = auth.uid())            ← called per-row, catastrophically slow
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- Materialized views (analytical facts)
-- ---------------------------------------------------------------------------
GRANT SELECT ON fact_fund_monthly      TO anon, authenticated;
GRANT SELECT ON fact_security_monthly  TO anon, authenticated;

-- ---------------------------------------------------------------------------
-- Fund registry (base table for dim_fund names/status)
-- ---------------------------------------------------------------------------
GRANT SELECT ON cvm_fund_registry      TO anon, authenticated;

-- ---------------------------------------------------------------------------
-- Dimension views
-- ---------------------------------------------------------------------------
GRANT SELECT ON dim_fund               TO anon, authenticated;
GRANT SELECT ON dim_security           TO anon, authenticated;

-- ---------------------------------------------------------------------------
-- Cross-domain and helper views
-- ---------------------------------------------------------------------------
GRANT SELECT ON vw_fidc_tranche_detail     TO anon, authenticated;
GRANT SELECT ON vw_fii_vs_fiagro           TO anon, authenticated;
GRANT SELECT ON vw_securit_emission_trend  TO anon, authenticated;
GRANT SELECT ON vw_fund_security_yield     TO anon, authenticated;

-- ---------------------------------------------------------------------------
-- Raw CVM tables (needed when functions reference them directly)
-- ---------------------------------------------------------------------------
GRANT SELECT ON cvm_fi_diario              TO anon, authenticated;
GRANT SELECT ON cvm_fi_cda                 TO anon, authenticated;
GRANT SELECT ON cvm_fi_perfil              TO anon, authenticated;
GRANT SELECT ON cvm_fidc_mensal            TO anon, authenticated;
GRANT SELECT ON cvm_fidc_tranche           TO anon, authenticated;
GRANT SELECT ON cvm_fidc_tranche_flows     TO anon, authenticated;
GRANT SELECT ON cvm_fidc_aging             TO anon, authenticated;
GRANT SELECT ON cvm_fiagro_mensal          TO anon, authenticated;
GRANT SELECT ON cvm_fip_periodic           TO anon, authenticated;
GRANT SELECT ON cvm_fii_mensal             TO anon, authenticated;
GRANT SELECT ON cvm_fii_periodic           TO anon, authenticated;
GRANT SELECT ON cvm_securit_mensal         TO anon, authenticated;
GRANT SELECT ON cvm_securit_serie          TO anon, authenticated;
GRANT SELECT ON cvm_securit_fluxo          TO anon, authenticated;
GRANT SELECT ON cvm_securit_dfin           TO anon, authenticated;
GRANT SELECT ON cvm_ingest_log             TO anon, authenticated;

-- ---------------------------------------------------------------------------
-- All analytical functions (callable via supabase.rpc())
-- ---------------------------------------------------------------------------
GRANT EXECUTE ON FUNCTION fund_profile(TEXT)                                                      TO anon, authenticated;
GRANT EXECUTE ON FUNCTION search_funds(TEXT, TEXT, INT)                                           TO anon, authenticated;
GRANT EXECUTE ON FUNCTION new_funds_per_period(TEXT[], DATE, DATE)                                TO anon, authenticated;
GRANT EXECUTE ON FUNCTION fund_nav_series(TEXT, DATE, DATE)                                       TO anon, authenticated;
GRANT EXECUTE ON FUNCTION fund_flow_trend(TEXT, DATE, DATE)                                       TO anon, authenticated;
GRANT EXECUTE ON FUNCTION industry_aum_trend(TEXT[], DATE, DATE)                                  TO anon, authenticated;
GRANT EXECUTE ON FUNCTION yield_distribution(TEXT, DATE, NUMERIC)                                 TO anon, authenticated;
GRANT EXECUTE ON FUNCTION fund_ranking(TEXT, TEXT, DATE, INT)                                     TO anon, authenticated;
GRANT EXECUTE ON FUNCTION market_concentration(TEXT, DATE)                                        TO anon, authenticated;
GRANT EXECUTE ON FUNCTION entity_monthly_stats(TEXT, DATE, DATE)                                  TO anon, authenticated;
GRANT EXECUTE ON FUNCTION cross_entity_comparison(TEXT[], TEXT, DATE, DATE)                       TO anon, authenticated;
GRANT EXECUTE ON FUNCTION quotaholder_trend(TEXT, DATE, DATE)                                     TO anon, authenticated;
GRANT EXECUTE ON FUNCTION fidc_tranche_performance(TEXT, DATE, DATE)                              TO anon, authenticated;
GRANT EXECUTE ON FUNCTION fidc_delinquency_trend(DATE, DATE, TEXT)                                TO anon, authenticated;
GRANT EXECUTE ON FUNCTION fidc_subordination_trend(TEXT, DATE, DATE)                              TO anon, authenticated;
GRANT EXECUTE ON FUNCTION security_issuance_trend(TEXT, DATE, DATE)                               TO anon, authenticated;
GRANT EXECUTE ON FUNCTION security_maturity_ladder(TEXT, DATE)                                    TO anon, authenticated;
GRANT EXECUTE ON FUNCTION distressed_securities(TEXT, DATE)                                       TO anon, authenticated;
GRANT EXECUTE ON FUNCTION yield_universe(TEXT[], TEXT[], DATE, DATE, NUMERIC)                     TO anon, authenticated;
GRANT EXECUTE ON FUNCTION data_coverage(TEXT, DATE, DATE)                                         TO anon, authenticated;
GRANT EXECUTE ON FUNCTION ingest_log_summary(DATE, DATE)                                          TO anon, authenticated;

COMMIT;
