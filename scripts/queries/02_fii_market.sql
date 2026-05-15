-- FII market analysis: FII vs FIAGRO comparison, yield distribution,
-- top 20 by yield, market concentration, quotaholder trend.
-- Run: psql $SUPABASE_DB_URL -f scripts/queries/02_fii_market.sql

-- Resolve the latest reporting period for FII data once.
\set fii_period '(SELECT MAX(period) FROM fact_fund_monthly WHERE entity_type = ''fii'')'

-- FII vs FIAGRO side-by-side: AUM, # funds, avg dividend yield.
SELECT *
FROM   cross_entity_comparison(ARRAY['fii','fiagro'], :fii_period, :fii_period)
ORDER  BY entity_type;

-- Dividend yield distribution across the FII universe.
SELECT *
FROM   yield_distribution('fii', :fii_period)
ORDER  BY bucket;

-- Top 20 FIIs ranked by trailing 12-month dividend yield.
SELECT *
FROM   fund_ranking(
           p_entity_type  => 'fii',
           p_period       => :fii_period,
           p_rank_by      => 'dividend_yield_12m',
           p_top_n        => 20
       )
ORDER  BY rank;

-- Market concentration: HHI and top-5 / top-10 share for FII segment.
SELECT *
FROM   market_concentration('fii', :fii_period);

-- Quotaholder (cotista) trend — trailing 12 months.
SELECT *
FROM   quotaholder_trend(
           'fii',
           :fii_period::date - INTERVAL '11 months',
           :fii_period
       )
ORDER  BY period;
