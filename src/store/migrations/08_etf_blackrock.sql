-- 08_etf_blackrock.sql — Add BlackRock holdings-fetch columns to cvm_etf_registry
--
-- Adds two TEXT columns that store the BlackRock Brazil product identifier and
-- the direct CSV holdings URL for iShares-managed ETFs.  Non-iShares rows keep
-- these columns NULL / empty.  The columns are populated by build_etf_seed.py
-- and loaded into the table by ingest_etf.py.
--
-- blackrock_product_id  — numeric product ID used in blackrock.com/br/products/{id}/…
--                         (e.g. "251816" for BOVA11).  NULL for non-iShares ETFs.
-- blackrock_csv_url     — full URL of the fund's holdings CSV endpoint on
--                         blackrock.com.  NULL for non-iShares ETFs.
--
-- All statements are idempotent (apply_schema.py splits on semicolon).

ALTER TABLE cvm_etf_registry
    ADD COLUMN IF NOT EXISTS blackrock_product_id TEXT;

ALTER TABLE cvm_etf_registry
    ADD COLUMN IF NOT EXISTS blackrock_csv_url TEXT;
