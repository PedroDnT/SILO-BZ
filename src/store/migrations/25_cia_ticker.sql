-- =============================================================================
-- Migration 25 — cia_ticker: CVM's published company↔ticker map (FCA
--                valores mobiliários) + the vw_company_ticker bridge
--
-- Source: fca_cia_aberta_valor_mobiliario_{YYYY}.csv inside the yearly FCA
-- ZIP (header verified live 2026-08-27). Every row is CVM-published: the
-- CNPJ and the Codigo_Negociacao arrive on the SAME source row, so joining
-- companies to tickers through this table synthesizes nothing (integrity
-- rule 3 — this is the mapping the API previously refused to invent).
--
-- Versions are preserved (Versao in the natural key, like cia_event);
-- vw_company_ticker dedupes to the newest (data_refer, versao) per
-- (cnpj, codneg) and flags whether the listing is still active
-- (dt_fim_neg IS NULL).
-- =============================================================================

CREATE TABLE IF NOT EXISTS cia_ticker (
    id               BIGSERIAL PRIMARY KEY,
    cnpj_cia         TEXT NOT NULL,
    data_refer       DATE NOT NULL,
    versao           INT  NOT NULL DEFAULT 1,
    id_documento     TEXT,
    valor_mobiliario TEXT,
    sigla_classe     TEXT,
    codneg           TEXT,
    mercado          TEXT,
    segmento         TEXT,
    dt_inicio_neg    DATE,
    dt_fim_neg       DATE,
    dt_inicio_list   DATE,
    dt_fim_list      DATE,
    raw              JSONB NOT NULL DEFAULT '{}'::jsonb,
    fetched_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_cia_ticker UNIQUE NULLS NOT DISTINCT
        (cnpj_cia, data_refer, versao, valor_mobiliario, codneg, mercado)
);

CREATE INDEX IF NOT EXISTS idx_cia_ticker_cnpj   ON cia_ticker (cnpj_cia);
CREATE INDEX IF NOT EXISTS idx_cia_ticker_codneg ON cia_ticker (codneg)
    WHERE codneg IS NOT NULL;

COMMENT ON TABLE cia_ticker IS
    'FCA valores mobiliários — CVM''s published CNPJ↔ticker map, one row per (company, filing, security). The only sanctioned company↔ticker join in the warehouse.';

-- One row per (cnpj, codneg): the newest filing wins. share-class text and
-- listing segment come straight from the same published row.
CREATE OR REPLACE VIEW vw_company_ticker AS
SELECT DISTINCT ON (t.cnpj_cia, t.codneg)
    t.cnpj_cia,
    t.codneg,
    t.valor_mobiliario,
    t.sigla_classe,
    t.mercado,
    t.segmento,
    t.dt_inicio_neg,
    t.dt_fim_neg,
    (t.dt_fim_neg IS NULL) AS is_active,
    t.data_refer,
    t.versao
FROM cia_ticker t
WHERE t.codneg IS NOT NULL
ORDER BY t.cnpj_cia, t.codneg, t.data_refer DESC, t.versao DESC;

COMMENT ON VIEW vw_company_ticker IS
    'Latest published FCA row per (company CNPJ, ticker). is_active = no Data_Fim_Negociacao. Zero name matching — both identifiers come from the same CVM source row.';
