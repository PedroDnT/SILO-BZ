-- FIDC credit monitor: delinquency trend, subordination, tranche performance.
-- Run: psql $SUPABASE_DB_URL -f scripts/queries/03_fidc_credit_monitor.sql

-- Delinquency trend for the full FIDC universe — trailing 12 months.
SELECT *
FROM   fidc_delinquency_trend(
           CURRENT_DATE - INTERVAL '12 months',
           CURRENT_DATE
       )
ORDER  BY period DESC
LIMIT  12;

-- Subordination trend for the top 10 FIDCs by AUM.
-- Subquery resolves the CNPJ list from fund_ranking so no hard-coding is needed.
SELECT *
FROM   fidc_subordination_trend(
           p_cnpj_list => (
               SELECT ARRAY_AGG(cnpj)
               FROM   fund_ranking(
                          p_entity_type => 'fidc',
                          p_period      => (SELECT MAX(period) FROM fact_fund_monthly WHERE entity_type = 'fidc'),
                          p_rank_by     => 'aum',
                          p_top_n       => 10
                      )
           ),
           p_start_date => CURRENT_DATE - INTERVAL '12 months',
           p_end_date   => CURRENT_DATE
       )
ORDER  BY period DESC, cnpj;

-- Tranche-level performance for a specific FIDC.
-- Replace '00.000.000/0001-00' with the target fund CNPJ before running.
SELECT *
FROM   fidc_tranche_performance(
           p_cnpj       => '00.000.000/0001-00',  -- REPLACE WITH TARGET CNPJ
           p_start_date => CURRENT_DATE - INTERVAL '12 months',
           p_end_date   => CURRENT_DATE
       )
ORDER  BY period DESC, tranche_class;
