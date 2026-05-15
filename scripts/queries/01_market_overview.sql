-- Market overview: AUM by entity type, FIDC delinquency, data freshness
-- Run: psql $SUPABASE_DB_URL -f scripts/queries/01_market_overview.sql
SELECT * FROM industry_aum_trend(NULL, CURRENT_DATE - 180, CURRENT_DATE) ORDER BY period DESC, entity_type;
SELECT * FROM fidc_delinquency_trend(CURRENT_DATE - 365, CURRENT_DATE) ORDER BY period DESC LIMIT 12;
SELECT * FROM data_coverage(NULL, CURRENT_DATE - 90, CURRENT_DATE) ORDER BY period DESC, entity_type;
