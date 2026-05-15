-- CRA/CRI/OTS: issuance trend, maturity ladder, distressed securities screen
-- Paste into Supabase SQL editor or: psql $SUPABASE_DB_URL -f scripts/queries/04_securit_issuance.sql

-- Monthly issuance by instrument type — last 3 years
SELECT * FROM security_issuance_trend(NULL, CURRENT_DATE - 1095, CURRENT_DATE)
ORDER BY period DESC, instrument_type;

-- CRA only
SELECT * FROM security_issuance_trend('cra_mensal', CURRENT_DATE - 1095, CURRENT_DATE)
ORDER BY period DESC;

-- Maturity ladder: outstanding principal by time-to-maturity bucket
SELECT * FROM security_maturity_ladder(NULL, CURRENT_DATE)
ORDER BY instrument_type, maturity_bucket;

-- Distressed securities screen (situacao = Inadimplente or Em atraso)
SELECT * FROM distressed_securities(NULL,
  (SELECT MAX(period) FROM fact_security_monthly))
ORDER BY instrument_type, valor_certificados DESC NULLS LAST;
