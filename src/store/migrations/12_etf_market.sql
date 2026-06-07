-- 12_etf_market.sql — ETF market snapshots scraped from etfsbrasil.com.br
--
-- CVM open data does not expose ETF NAV/quotaholders for the post-CVM-175 share
-- classes (the registry's fund-level CNPJ no longer matches the daily file's
-- class-level CNPJ, so etf_daily is empty). This table holds the per-ETF market
-- snapshot scraped from etfsbrasil.com.br/comparador/<ticker> via an Apify
-- browser actor (rotating proxies) — see src/fetchers/apify_etf_fetcher.py and
-- apify/etfsbrasil_scraper.js.
--
-- Provenance: every row carries its source ticker + snapshot_date + source tag
-- straight from the scrape; raw holds the full scraped record for audit.
-- Idempotent: named UNIQUE on (ticker, snapshot_date) for ON CONFLICT DO UPDATE.

CREATE TABLE IF NOT EXISTS etf_market_snapshot (
    ticker            TEXT          NOT NULL,
    snapshot_date     DATE          NOT NULL,
    source            TEXT          NOT NULL DEFAULT 'etfsbrasil',
    cnpj              TEXT,             -- from the page; links back to cvm_etf_registry
    isin              TEXT,
    fund_name         TEXT,
    categoria         TEXT,
    regiao            TEXT,
    indice            TEXT,
    provedor_indice   TEXT,
    taxa_adm_pct      NUMERIC(10, 4),   -- administration fee, percent (0.10 = 0.10%)
    nav               NUMERIC(20, 6),   -- patrimônio líquido (AUM) in BRL (page shows R$ MM; ×1e6 on ingest)
    cotistas          INTEGER,          -- número de cotistas (quotaholders)
    price             NUMERIC(20, 6),   -- cotação / unit price, BRL
    ret_ytd_pct       NUMERIC(12, 4),   -- return "no ano", percent
    ret_12m_pct       NUMERIC(12, 4),
    ret_36m_pct       NUMERIC(12, 4),
    vol_12m_pct       NUMERIC(12, 4),   -- desvio padrão 12m, percent
    sharpe_12m        NUMERIC(12, 4),
    max_drawdown_pct  NUMERIC(12, 4),
    launch_date       DATE,
    raw               JSONB,
    scraped_at        TIMESTAMPTZ   NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_etf_market_snapshot UNIQUE (ticker, snapshot_date)
);

CREATE INDEX IF NOT EXISTS idx_etf_market_snapshot_date   ON etf_market_snapshot (snapshot_date DESC);
CREATE INDEX IF NOT EXISTS idx_etf_market_snapshot_ticker ON etf_market_snapshot (ticker, snapshot_date DESC);
