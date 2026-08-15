-- =============================================================================
-- Migration 19 — B3 COTAHIST serve path (partial covering index + vista view)
--
-- Daily COTAHIST is ~17k register-01 rows, mostly options (tpmerc 070/080).
-- Quote serving filters cash (tpmerc = '010'). A full (codneg, trade_date)
-- btree duplicates the UNIQUE leftmost prefix and indexes the option bulk;
-- replace it with a partial covering index that matches the serve predicate.
--
-- Idempotent: DROP INDEX IF EXISTS + CREATE INDEX IF NOT EXISTS +
-- CREATE OR REPLACE VIEW. schema.sql carries the same end state.
-- =============================================================================

DROP INDEX IF EXISTS idx_b3_cotahist_codneg;

CREATE INDEX IF NOT EXISTS idx_b3_cotahist_vista
    ON b3_cotahist (codneg, trade_date DESC)
    INCLUDE (
        preco_abertura, preco_maximo, preco_minimo, preco_fechamento,
        volume, negocios, quantidade, isin
    )
    WHERE tpmerc = '010';

CREATE OR REPLACE VIEW vw_b3_quote_vista AS
SELECT
    codneg,
    trade_date,
    codbdi,
    prazot,
    nome_resumido,
    especi,
    moeda,
    preco_abertura,
    preco_maximo,
    preco_minimo,
    preco_medio,
    preco_fechamento,
    oferta_compra,
    oferta_venda,
    negocios,
    quantidade,
    volume,
    isin,
    fator_cotacao,
    source,
    fetched_at
FROM b3_cotahist
WHERE tpmerc = '010';

COMMENT ON VIEW vw_b3_quote_vista IS
    'Cash-market (tpmerc=010) COTAHIST quotes. Unadjusted. Grain is still (codneg, trade_date, codbdi, prazot); board 02 is the standard lot.';
