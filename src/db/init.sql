-- Creates three isolated schemas and their per-service users
-- Alembic runs as the postgres superuser; per-service users only need runtime access

CREATE SCHEMA IF NOT EXISTS cvm;
CREATE SCHEMA IF NOT EXISTS bacen;
CREATE SCHEMA IF NOT EXISTS b3_calc;

CREATE USER IF NOT EXISTS cvm_user WITH PASSWORD 'cvm_secret';
CREATE USER IF NOT EXISTS bacen_user WITH PASSWORD 'bacen_secret';
CREATE USER IF NOT EXISTS b3_calc_user WITH PASSWORD 'b3_secret';

-- Grant schema usage and table access (ALTER DEFAULT PRIVILEGES covers future tables too)
GRANT USAGE ON SCHEMA cvm TO cvm_user;
GRANT ALL ON ALL TABLES IN SCHEMA cvm TO cvm_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA cvm GRANT ALL ON TABLES TO cvm_user;

GRANT USAGE ON SCHEMA bacen TO bacen_user;
GRANT ALL ON ALL TABLES IN SCHEMA bacen TO bacen_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA bacen GRANT ALL ON TABLES TO bacen_user;

GRANT USAGE ON SCHEMA b3_calc TO b3_calc_user;
GRANT ALL ON ALL TABLES IN SCHEMA b3_calc TO b3_calc_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA b3_calc GRANT ALL ON TABLES TO b3_calc_user;
