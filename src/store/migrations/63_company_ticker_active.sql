-- =============================================================================
-- Migration 63 - vw_company_ticker.is_active: a ticker absent from the
--                company's newest FCA filing is not active (#381)
--
-- WHY. Migration 25 defined is_active as (dt_fim_neg IS NULL) on the newest
-- row that mentions the ticker. A ticker that is delisted simply vanishes from
-- the next FCA and CVM files no end date for it (about 88% of vanished tickers
-- carry none, docs/reference/research/fca-listing-dates.md section 4), so its
-- last row reads active forever. On 2026-09-29, 241 of 731 tickers flagged
-- active were absent from the 2026 FCA; api.lookup('33.041.260/0652-90') still
-- returned VVAR3 and VIIA3, which stopped trading in 2021 and 2023.
--
-- WHAT. is_active is now true only when the ticker's row has no end date AND
-- that row belongs to the company's newest filing: the greatest
-- (data_refer, versao) among ALL the company's cia_ticker rows (a row with no
-- ticker counts, because it proves the company filed). A ticker the newest
-- filing does not list is inactive.
--
-- WHAT THIS IS NOT. It is a statement about the FCA, not about the tape:
-- "still in the company's newest FCA" is not "trades today". A company that has
-- not yet filed its newest FCA keeps the older filing as its newest. The
-- column list, order and types are unchanged (CREATE OR REPLACE requires it),
-- and so are the DISTINCT ON key and its ordering: only is_active differs.
-- Idempotent: every schema apply replays migration 25 (the old definition)
-- and then this file, which puts the new one back.
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
     AND t.versao = n.versao) AS is_active,
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
    'Latest published FCA row per (company CNPJ, ticker). is_active = no Data_Fim_Negociacao AND the row is in the company''s newest FCA filing (greatest data_refer, versao over all its rows), so a ticker that vanished from the FCA is inactive (#381). It says what the FCA lists, not that the ticker trades. Zero name matching: both identifiers come from the same CVM source row.';
