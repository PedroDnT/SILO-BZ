-- Fund formation and dissolution trends.
-- Run: psql $SUPABASE_DB_URL -f scripts/queries/07_new_fund_activity.sql

-- New fund registrations per month — all entity types, trailing 36 months.
SELECT *
FROM   new_funds_per_period(
           p_entity_types => NULL,   -- NULL = all types; or e.g. ARRAY['fii','fidc']
           p_start_date   => CURRENT_DATE - INTERVAL '36 months',
           p_end_date     => CURRENT_DATE,
           p_granularity  => 'month'
       )
ORDER  BY period DESC, entity_type;

-- Data coverage check to confirm reporting universe is stable.
-- Sudden drops in active_funds may indicate dissolution or data gaps.
SELECT *
FROM   data_coverage(
           p_entity_types          => NULL,
           p_start_date            => CURRENT_DATE - INTERVAL '36 months',
           p_end_date              => CURRENT_DATE,
           p_months_since_last_report => 3   -- flag funds silent for 3+ months
       )
ORDER  BY period DESC, entity_type;
