-- Fund lookup: search, profile, NAV history, peer ranking.
-- Run: psql $SUPABASE_DB_URL -f scripts/queries/06_fund_lookup.sql
--
-- BEFORE RUNNING: replace the placeholder CNPJ below with the target fund.
-- Format: 'XX.XXX.XXX/XXXX-XX'  (with punctuation) or 'XXXXXXXXXXXXXXXXXX' (digits only).

\set target_cnpj '00.000.000/0001-00'   -- REPLACE WITH TARGET CNPJ

-- 1. Search by name fragment (useful when you only have a partial name).
--    Replace the search term as needed.
SELECT *
FROM   search_funds(p_query => 'PLACEHOLDER FUND NAME')
ORDER  BY relevance DESC
LIMIT  10;

-- 2. Full profile for the target fund (AUM, inception, manager, etc.).
SELECT *
FROM   fund_profile(p_cnpj => :'target_cnpj');

-- 3. NAV (quota value) history — trailing 24 months.
SELECT *
FROM   fund_nav_series(
           p_cnpj       => :'target_cnpj',
           p_start_date => CURRENT_DATE - INTERVAL '24 months',
           p_end_date   => CURRENT_DATE
       )
ORDER  BY period;

-- 4. Peer ranking: where does this fund sit within its segment?
--    Determines entity_type automatically from the profile query above;
--    adjust p_entity_type if needed (e.g. 'fii', 'fidc', 'fiagro').
SELECT *
FROM   fund_ranking(
           p_entity_type => (
               SELECT entity_type
               FROM   fund_profile(p_cnpj => :'target_cnpj')
               LIMIT  1
           ),
           p_period      => (SELECT MAX(period) FROM fact_fund_monthly),
           p_rank_by     => 'aum'
       )
WHERE  cnpj = :'target_cnpj';
