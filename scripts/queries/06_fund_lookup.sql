-- Fund lookup: search by name, full profile, NAV history, flow trend, peer rank
-- Paste into psql $POSTGRES_URL -f scripts/queries/06_fund_lookup.sql

-- 1. Search by name or CNPJ fragment — works across all entity types
SELECT cnpj, entity_type, fund_name, first_period, last_period, latest_aum
FROM search_funds('kinea', NULL, 20);

-- Search within a specific entity type
SELECT cnpj, entity_type, fund_name, first_period, last_period, latest_aum
FROM search_funds('btg', 'fidc', 10);

-- 2. Full profile for a specific CNPJ (replace with target)
SELECT * FROM fund_profile('07727002000126');  -- FIDC PCG BRASIL MULTICARTEIRA

-- 3. NAV / quota history — last 24 months
SELECT * FROM fund_nav_series('07727002000126', CURRENT_DATE - 730, CURRENT_DATE)
ORDER BY period;

-- 4. Flow trend (captações / resgates) — FI funds only
SELECT * FROM fund_flow_trend('07727002000126', CURRENT_DATE - 365, CURRENT_DATE)
ORDER BY period;

-- 5. Where does this fund rank among its peers?
SELECT r.cnpj, d.fund_name, r.period, r.metric_value AS aum, r.rank_pos
FROM fund_ranking(
  (SELECT entity_type FROM fund_profile('07727002000126') LIMIT 1),
  'aum',
  (SELECT MAX(period) FROM fact_fund_monthly),
  50
) r
LEFT JOIN dim_fund d ON d.cnpj = r.cnpj
WHERE r.cnpj = '07727002000126';
