-- Fund formation and dissolution trends
-- Paste into Supabase SQL editor or: psql $SUPABASE_DB_URL -f scripts/queries/07_new_fund_activity.sql

-- New fund registrations per month — all entity types, last 3 years
SELECT * FROM new_funds_per_period(NULL, CURRENT_DATE - 1095, CURRENT_DATE)
ORDER BY period DESC, entity_type;

-- FII + FIDC only
SELECT * FROM new_funds_per_period(ARRAY['fii','fidc'], CURRENT_DATE - 730, CURRENT_DATE)
ORDER BY period DESC, entity_type;

-- Zombie funds: stopped reporting 90+ days ago, with name
SELECT entity_type, fund_name, status, first_period, last_period,
       (CURRENT_DATE - last_period::date) AS days_since_last_report
FROM dim_fund
WHERE last_period < CURRENT_DATE - 90
  AND fund_name IS NOT NULL
ORDER BY days_since_last_report DESC
LIMIT 30;
