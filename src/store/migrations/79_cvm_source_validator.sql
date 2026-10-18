-- Conditional download (#874): the ETag / Last-Modified of the CVM file each slice
-- last loaded, so the daily run can skip a file that did not change. See
-- src/fetchers/conditional.py. period_year / period_month are 0, not NULL, for a
-- slice with no period, so the UNIQUE key holds. Landing table, no client grant.

BEGIN;

CREATE TABLE IF NOT EXISTS cvm_source_validator (
    id             BIGSERIAL    PRIMARY KEY,
    entity         TEXT         NOT NULL,
    doc_type       TEXT         NOT NULL,
    period_year    INT          NOT NULL DEFAULT 0,   -- 0 = the slice has no period
    period_month   INT          NOT NULL DEFAULT 0,
    url            TEXT         NOT NULL CHECK (url ~ '^https?://'),
    etag           TEXT,
    last_modified  TEXT,                              -- the header as the server sent it
    content_length BIGINT,
    parser_version TEXT,
    verified_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_cvm_source_validator UNIQUE (entity, doc_type, period_year, period_month, url),
    CONSTRAINT ck_cvm_source_validator_header CHECK (etag IS NOT NULL OR last_modified IS NOT NULL)
);

COMMENT ON TABLE cvm_source_validator IS
    'ETag / Last-Modified of the CVM file a slice last loaded ok with rows (#874). The daily run sends them as If-None-Match / If-Modified-Since and logs a 304 as skipped (error_msg starts with unchanged:). Written only after an ok slice; ignored after CVM_CONDITIONAL_MAX_AGE_DAYS or a parser_version change. Landing table, no client grant.';

ALTER TABLE cvm_source_validator ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON cvm_source_validator FROM PUBLIC;
DO $grants$
DECLARE role_name TEXT;
BEGIN
    FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated', 'silo_api'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
            EXECUTE format('REVOKE ALL ON cvm_source_validator FROM %I', role_name);
        END IF;
    END LOOP;
END
$grants$;

COMMIT;
