-- 86_tesouro_direto_daily.sql — Tesouro Direto daily posted rates and prices.
--
-- Source: the Treasury's open-data CSV "Taxas dos Títulos Ofertados pelo
-- Tesouro Direto" (ODbL licence; contract in src/fetchers/tesouro_direto_fetcher.py).
-- Grain (tipo_titulo, data_vencimento, data_base): verified unique on the live
-- file 2026-11-16 (178,594 rows from 2004-12-31). Rates in percent a year, as
-- published, and can be negative. PU in R$; NULL where the publisher prints
-- 0,00 because the title is not on sale on that side. These are the Treasury's
-- posted morning quotes on its retail platform, not trades.
CREATE TABLE IF NOT EXISTS tesouro_direto_daily (
    id               BIGSERIAL     PRIMARY KEY,
    tipo_titulo      TEXT          NOT NULL,
    data_vencimento  DATE          NOT NULL,
    data_base        DATE          NOT NULL,
    taxa_compra      NUMERIC(10,4),
    taxa_venda       NUMERIC(10,4),
    pu_compra        NUMERIC(18,6),
    pu_venda         NUMERIC(18,6),
    pu_base          NUMERIC(18,6),
    fetched_at       TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_tesouro_direto_daily UNIQUE (tipo_titulo, data_vencimento, data_base)
);
CREATE INDEX IF NOT EXISTS idx_tesouro_direto_daily_base
    ON tesouro_direto_daily (data_base DESC);
-- A landing table: no client reads it. The API reads it through schema api.
ALTER TABLE tesouro_direto_daily ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON tesouro_direto_daily FROM PUBLIC;
DO $grants$
DECLARE role_name TEXT;
BEGIN
    FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated', 'silo_api'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
            EXECUTE format('REVOKE ALL ON tesouro_direto_daily FROM %I', role_name);
        END IF;
    END LOOP;
END
$grants$;
