-- Securitization issuance monitor: CRA/CRI/OTS trends, maturity ladder,
-- and distressed securities screen.
-- Run: psql $SUPABASE_DB_URL -f scripts/queries/04_securit_issuance.sql

-- Issuance volume trend — trailing 24 months, split by security type.
SELECT *
FROM   security_issuance_trend(
           p_security_types => ARRAY['cra','cri','ots'],
           p_start_date     => CURRENT_DATE - INTERVAL '24 months',
           p_end_date       => CURRENT_DATE
       )
ORDER  BY period DESC, security_type;

-- Maturity ladder: principal outstanding grouped by maturity bucket.
SELECT *
FROM   security_maturity_ladder(
           p_security_types => ARRAY['cra','cri','ots'],
           p_as_of_date     => CURRENT_DATE
       )
ORDER  BY maturity_bucket;

-- Distressed securities screen: flags with elevated spread or missed payments.
SELECT *
FROM   distressed_securities(
           p_security_types => ARRAY['cra','cri','ots'],
           p_as_of_date     => CURRENT_DATE
       )
ORDER  BY distress_score DESC;
