-- FIDC credit monitor: sector delinquency, tranche performance, subordination
-- Paste into Supabase SQL editor or: psql $SUPABASE_DB_URL -f scripts/queries/03_fidc_credit_monitor.sql

-- Sector delinquency trend — trailing 24 months
SELECT * FROM fidc_delinquency_trend(CURRENT_DATE - 730, CURRENT_DATE)
ORDER BY period DESC;

-- Top 10 FIDCs by AUM — with names (use CNPJs for tranche queries below)
SELECT r.cnpj, d.fund_name, r.period, r.metric_value AS aum, r.rank_pos
FROM fund_ranking('fidc', 'aum',
  (SELECT MAX(period) FROM fact_fund_monthly WHERE entity_type = 'fidc'), 10) r
LEFT JOIN dim_fund d ON d.cnpj = r.cnpj AND d.entity_type = 'fidc'
ORDER BY r.rank_pos;

-- Funds with highest delinquency rates this month — with names
SELECT r.cnpj, d.fund_name, r.period, r.metric_value AS inadimpl_rate, r.rank_pos
FROM fund_ranking('fidc', 'inadimpl_rate',
  (SELECT MAX(period) FROM fact_fund_monthly WHERE entity_type = 'fidc'), 10) r
LEFT JOIN dim_fund d ON d.cnpj = r.cnpj AND d.entity_type = 'fidc'
ORDER BY r.rank_pos;

-- Tranche performance for a specific FIDC — replace CNPJ before running
SELECT * FROM fidc_tranche_performance(
  '07727002000126',  -- FIDC PCG - BRASIL MULTICARTEIRA (replace with target CNPJ)
  CURRENT_DATE - 365, CURRENT_DATE)
ORDER BY period, classe_serie;

-- Subordination trend for the same fund
SELECT * FROM fidc_subordination_trend(
  '07727002000126',  -- replace with target CNPJ
  CURRENT_DATE - 365, CURRENT_DATE)
ORDER BY period;
