-- 06_etf.sql — ETF (Fundo de Índice) dataset
--
-- CVM open data has no ETF flag. TP_FUNDO is only FI/FACFIF/FAPI/FCCE, and the
-- CVM-175 Classificacao is Multimercado/Renda Fixa/Ações/Cambial/FMP-FGTS —
-- none isolate ETFs. ETFs are enumerated by B3 (the ticker assigner), so we
-- keep a curated ticker to CNPJ seed (src/store/seeds/etf_registry_seed.csv,
-- loaded by src/pipeline/ingest_etf.py) and join it to data we already ingest.
--
-- cvm_etf_registry  — ETF identity (ticker, CNPJ, provider, index, segment)
--                     enriched from cad_fi by CNPJ (fees, admin/gestor, status).
-- etf_daily  (matview) — registry joined to cvm_fi_diario on CNPJ. NAV/quota, AUM
--                        (VL_PATRIM_LIQ), quotaholders (NR_COTST), flows, returns.
-- etf_latest (matview) — most recent snapshot per ticker.
--
-- etf_daily / etf_latest are MATERIALIZED so consumers read precomputed metrics
-- instead of recomputing the join + window function on every query. The pipeline
-- REFRESHes them after each ingest (CONCURRENTLY; see _refresh_etf_metrics). This
-- migration is idempotent and converts the pre-existing plain views once; it is
-- applied with psql (the DO block below has a PL/pgSQL body), not apply_schema.py.

CREATE TABLE IF NOT EXISTS cvm_etf_registry (
    ticker            TEXT PRIMARY KEY,
    cnpj              TEXT          NOT NULL,
    fund_name         TEXT,
    provider          TEXT,
    underlying_index  TEXT,
    segment           TEXT,
    situacao          TEXT,
    is_active         BOOLEAN,
    dt_cancel         DATE,
    classe_anbima     TEXT,
    taxa_adm          NUMERIC(14, 6),
    taxa_perfm        NUMERIC(14, 6),
    admin             TEXT,
    gestor            TEXT,
    dt_reg            DATE,
    vl_patrim_liq     NUMERIC(20, 2),
    dt_patrim_liq     DATE,
    raw               JSONB,
    updated_at        TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_etf_registry_cnpj    ON cvm_etf_registry (cnpj);
CREATE INDEX IF NOT EXISTS idx_etf_registry_segment ON cvm_etf_registry (segment);

-- Daily ETF time series: AUM, quotaholders, NAV/quota, flows, daily return.
-- Materialized (refreshed by the pipeline after ingest). The DO block converts
-- the legacy plain views to materialized views exactly once, then no-ops: on a
-- re-apply (the daily bootstrap runs every migration) nothing is rebuilt.
DO $$
DECLARE
    daily_kind  "char" := (SELECT relkind FROM pg_class WHERE oid = to_regclass('public.etf_daily'));
    latest_kind "char" := (SELECT relkind FROM pg_class WHERE oid = to_regclass('public.etf_latest'));
BEGIN
    -- Drop the legacy plain views once (etf_latest depends on etf_daily).
    IF daily_kind = 'v' THEN
        DROP VIEW IF EXISTS etf_latest;
        DROP VIEW etf_daily;
        daily_kind  := NULL;
        latest_kind := NULL;
    END IF;

    IF daily_kind IS DISTINCT FROM 'm' THEN
        CREATE MATERIALIZED VIEW etf_daily AS
        SELECT
            e.ticker,
            e.cnpj,
            e.fund_name,
            e.provider,
            e.underlying_index,
            e.segment,
            e.is_active,
            d.dt_comptc,
            d.vl_quota,
            d.vl_patrim_liq                                      AS aum,
            d.nr_cotst                                           AS quotaholders,
            d.captc_dia,
            d.resg_dia,
            (COALESCE(d.captc_dia, 0) - COALESCE(d.resg_dia, 0)) AS net_flow,
            e.taxa_adm,
            e.taxa_perfm,
            d.vl_quota / NULLIF(LAG(d.vl_quota) OVER (PARTITION BY e.ticker ORDER BY d.dt_comptc), 0) - 1
                                                                 AS daily_return
        FROM cvm_etf_registry e
        JOIN cvm_fi_diario d ON d.cnpj = e.cnpj;
    END IF;

    IF latest_kind IS DISTINCT FROM 'm' THEN
        CREATE MATERIALIZED VIEW etf_latest AS
        SELECT DISTINCT ON (ticker)
            ticker, cnpj, fund_name, provider, underlying_index, segment, is_active,
            dt_comptc, vl_quota, aum, quotaholders, net_flow, taxa_adm, taxa_perfm
        FROM etf_daily
        ORDER BY ticker, dt_comptc DESC;
    END IF;
END $$;

-- Unique indexes: (ticker, dt_comptc) is a unique grain (ticker -> one CNPJ via
-- the registry PK; cvm_fi_diario is unique on (cnpj, dt_comptc)). Both also
-- satisfy REFRESH MATERIALIZED VIEW CONCURRENTLY's unique-index requirement.
CREATE UNIQUE INDEX IF NOT EXISTS uq_etf_daily_ticker_dt ON etf_daily (ticker, dt_comptc);
CREATE UNIQUE INDEX IF NOT EXISTS uq_etf_latest_ticker   ON etf_latest (ticker);
