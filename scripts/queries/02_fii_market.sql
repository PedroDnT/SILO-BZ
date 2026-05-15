-- FII market deep-dive: AUM trend, yield distribution, top funds, concentration
-- Paste into Supabase SQL editor or: psql $SUPABASE_DB_URL -f scripts/queries/02_fii_market.sql

-- FII vs FIAGRO AUM comparison — last 24 months
SELECT * FROM cross_entity_comparison(ARRAY['fii','fiagro'], 'aum', CURRENT_DATE - 730, CURRENT_DATE)
ORDER BY period, entity_type;

-- Yield distribution across all FIIs — latest period
SELECT * FROM yield_distribution('fii',
  (SELECT MAX(period) FROM fact_fund_monthly WHERE entity_type = 'fii'));

-- Yield distribution with CDI benchmark (replace 0.084 with live CDI from BCB API)
-- curl "https://api.bcb.gov.br/dados/serie/bcdata.sgs.12/dados/ultimos/1?formato=json"
SELECT * FROM yield_distribution('fii',
  (SELECT MAX(period) FROM fact_fund_monthly WHERE entity_type = 'fii'),
  0.084);  -- monthly CDI %

-- Top 20 FIIs by dividend yield — latest period, with names
SELECT r.cnpj, d.fund_name, r.period, r.metric_value AS yield_pct, r.rank_pos
FROM fund_ranking('fii', 'yield',
  (SELECT MAX(period) FROM fact_fund_monthly WHERE entity_type = 'fii'), 20) r
LEFT JOIN dim_fund d ON d.cnpj = r.cnpj AND d.entity_type = 'fii'
ORDER BY r.rank_pos;

-- Market concentration (HHI + top-5/10/20 share)
SELECT * FROM market_concentration('fii',
  (SELECT MAX(period) FROM fact_fund_monthly WHERE entity_type = 'fii'));

-- Quotaholder trend — trailing 24 months
SELECT * FROM quotaholder_trend('fii', CURRENT_DATE - 730, CURRENT_DATE)
ORDER BY period;
