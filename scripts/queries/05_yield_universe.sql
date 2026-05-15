-- Cross-domain yield universe: FII + FIDC + SECURIT vs CDI benchmark.
-- Run: psql $SUPABASE_DB_URL -f scripts/queries/05_yield_universe.sql
--
-- CDI benchmark note:
--   CDI is NOT stored locally. Fetch the current rate from the BCB open API:
--   https://api.bcb.gov.br/dados/serie/bcdata.sgs.12/dados/ultimos/1?formato=json
--
--   Quick approximations:
--     CDI monthly (%) ≈ SELIC_annual / 100 / 12 * 100
--     SELIC series code : 432  → bcdata.sgs.432
--     CDI  daily  code  : 12   → bcdata.sgs.12
--     IPCA monthly code : 433  → bcdata.sgs.433
--
--   Example curl:
--     curl -s "https://api.bcb.gov.br/dados/serie/bcdata.sgs.12/dados/ultimos/1?formato=json"
--     # returns: [{"data":"14/05/2026","valor":"0.08218"}]
--
--   Substitute the returned value (as a decimal, e.g. 0.08218) into the
--   p_benchmark_rate parameter below before running.

SELECT *
FROM   yield_universe(
           p_entity_types   => ARRAY['fii','fidc','cra','cri','ots'],
           p_period         => (SELECT MAX(period) FROM fact_fund_monthly),
           p_benchmark_rate => 0.08218  -- replace with live CDI from BCB API above
       )
ORDER  BY spread_over_benchmark DESC NULLS LAST;
