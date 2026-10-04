-- =============================================================================
-- Migration 69 - vw_company_ticker.is_active also needs the ticker to trade
--                (#381 follow-up, owner decision 2026-10-04)
--
-- WHY. Migration 63 made is_active "in the company's newest FCA filing, with
-- no end date". That says what the FCA lists, not that the ticker trades: 192
-- of the 241 tickers #381 found had no cash-market session since 2026-08-01
-- (docs/reference/research/fca-listing-dates.md). The owner's rule: a ticker
-- is active only if it is traded with liquidity; otherwise it is cut.
--
-- WHAT. is_active keeps migration 63's two conditions and adds a third: the
-- ticker printed on the B3 cash market (b3_cotahist, tpmerc '010', negocios
-- > 0) on at least 5 distinct sessions in the last 30 calendar days
-- (trade_date > current_date - 30). COTAHIST lists only papers that traded,
-- so a missing session is a session with no trade. The threshold is the
-- owner's starting value, to be tuned later; change it here and in the test.
--
-- WHAT THIS IS NOT. It is not a legal listing status. A thinly traded ticker
-- that is still listed reads inactive, and api.lookup / financials / the
-- ticker filters stop resolving it, which is the owner's intent. If the daily
-- ingest stopped for 30 days every ticker would read inactive: that is the
-- tape saying nothing traded, and DB Health catches a stale tape long before.
--
-- The column list, order and types are unchanged (CREATE OR REPLACE requires
-- it), and so are the DISTINCT ON key and its ordering: only is_active
-- differs. The count reads idx_b3_cotahist_vista (codneg, trade_date DESC,
-- INCLUDE negocios, WHERE tpmerc = '010'). Idempotent: every schema apply
-- replays migrations 25 and 63 and then this file, which puts this definition
-- back.
-- =============================================================================

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
    (t.dt_fim_neg IS NULL
     AND t.data_refer = n.data_refer
     AND t.versao = n.versao
     AND (
         SELECT count(DISTINCT b.trade_date)
         FROM b3_cotahist b
         WHERE b.codneg = t.codneg
           AND b.tpmerc = '010'
           AND b.negocios > 0
           AND b.trade_date > current_date - 30
     ) >= 5) AS is_active,
    t.data_refer,
    t.versao
FROM cia_ticker t
JOIN (
    -- The company's newest filing, over every row it has in cia_ticker.
    SELECT DISTINCT ON (cnpj_cia) cnpj_cia, data_refer, versao
    FROM cia_ticker
    ORDER BY cnpj_cia, data_refer DESC, versao DESC
) n ON n.cnpj_cia = t.cnpj_cia
WHERE t.codneg IS NOT NULL
ORDER BY t.cnpj_cia, t.codneg, t.data_refer DESC, t.versao DESC;

COMMENT ON VIEW vw_company_ticker IS
    'Latest published FCA row per (company CNPJ, ticker). is_active = no Data_Fim_Negociacao AND the row is in the company''s newest FCA filing (greatest data_refer, versao over all its rows) (#381) AND the ticker traded on the B3 cash market (b3_cotahist tpmerc 010, negocios > 0) on at least 5 distinct sessions in the last 30 calendar days (migration 69, owner 2026-10-04). A listed but illiquid ticker reads inactive. Zero name matching: both identifiers come from the same CVM source row.';
