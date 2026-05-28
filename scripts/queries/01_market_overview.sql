-- Market pulse: AUM by entity, FIDC delinquency, data freshness
-- Paste into psql $POSTGRES_URL -f scripts/queries/01_market_overview.sql

-- Total AUM + fund count by entity type — last 6 months
SELECT * FROM industry_aum_trend(NULL, CURRENT_DATE - 180, CURRENT_DATE)
ORDER BY period DESC, entity_type;

-- FIDC sector delinquency — trailing 12 months
SELECT * FROM fidc_delinquency_trend(CURRENT_DATE - 365, CURRENT_DATE)
ORDER BY period DESC LIMIT 12;

-- Data freshness: when did each entity type last report?
SELECT * FROM data_coverage(NULL, CURRENT_DATE - 90, CURRENT_DATE)
ORDER BY period DESC, entity_type;
