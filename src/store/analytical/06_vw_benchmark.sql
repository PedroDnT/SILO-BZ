-- =============================================================================
-- 06_vw_benchmark.sql
-- DEPRECATED — benchmark views replaced by parameterised functions.
--
-- vw_fund_vs_benchmark and vw_security_vs_benchmark previously joined
-- fact_bacen_monthly to the fund/security facts. Since BACEN data is no
-- longer stored locally, these views have been dropped.
--
-- Replacement: use the analytical functions with the benchmark_rate parameter:
--
--   SELECT * FROM yield_distribution('fii', '2024-12-01', 0.84);
--     -- 0.84 = monthly CDI % fetched from BCB API by the caller
--
--   SELECT * FROM yield_universe(
--     ARRAY['fii','fiagro'], ARRAY['cra_classe'],
--     '2024-01-01', '2024-12-31',
--     0.84   -- monthly CDI
--   );
--
-- BCB API for current CDI (monthly rate, already in %):
--   https://api.bcb.gov.br/dados/serie/bcdata.sgs.12/dados/ultimos/1?formato=json
-- =============================================================================

-- Ensure views are dropped if this file is applied on an older DB state:
DROP VIEW IF EXISTS vw_fund_vs_benchmark CASCADE;
DROP VIEW IF EXISTS vw_security_vs_benchmark CASCADE;
