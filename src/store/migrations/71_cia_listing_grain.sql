-- =============================================================================
-- Migration 71 - cia_ticker and cia_company keep every published listing row
--                (#354, part of #347)
--
-- WHY. Two CVM files publish more than one row on the key we upsert on, so the
-- last row in file order replaced the others (pg_client dedups "last write
-- wins"). Measured against CVM's files on 2026-10-04:
--
--   * fca_cia_aberta_valor_mobiliario_{YYYY}.csv: 2026 has 964 rows, 962
--     distinct, 944 keys under uq_cia_ticker, so 18 distinct rows were lost
--     (2025: 15, 2023: 19, 2020: 10, 2010: 7). Most are one ticker's segment
--     history inside one FCA: PDTC3 files a "Básico" row that ended on
--     2021-05-07 and an open "Novo Mercado" row. The open row survived only
--     because CVM lists it second; in the other order is_active would read
--     false for a live ticker. The rest are preferred classes (PNA/PNC/PNR)
--     and debentures listed on different dates. Adding sigla_classe,
--     dt_inicio_neg and dt_inicio_list loses no distinct row in any of those
--     years; the remaining duplicates are byte-identical.
--   * cad_cia_aberta.csv: 2,678 rows, 2,567 CD_CVM, all 2,678 distinct. The
--     107 repeated companies differ ONLY in TP_MERC (BOLSA, BALCÃO
--     ORGANIZADO, BALCÃO NÃO ORGANIZADO). The market is a multi-valued
--     attribute of the company, not part of its grain: cd_cvm stays the key
--     (cia_filing, cia_account and api.lookup join on it) and the ingest
--     stores every published market in tp_merc.
--
-- WHAT.
--   1. uq_cia_ticker (same name) widens to
--      (cnpj_cia, data_refer, versao, valor_mobiliario, codneg, mercado,
--       sigla_classe, dt_inicio_neg, dt_inicio_list), NULLS NOT DISTINCT.
--      A wider key never conflicts with rows that were unique on a narrower
--      one. Guarded so the replay on every schema apply is a no-op.
--   2. vw_company_ticker: migration 69's definition with a deterministic
--      tie-break inside one filing: the row with no Data_Fim_Negociacao
--      first, then the newest Data_Inicio_Negociacao, then the newest id. The
--      columns, the DISTINCT ON key and the is_active rule are unchanged.
--   3. cia_company.tp_merc JSONB: a JSON array of TP_MERC as published,
--      distinct and sorted, NULL when CVM leaves it blank. JSONB, not TEXT[],
--      because pg_client sends every Python list as Json.
--
-- Rows already lost come back when their file is read again: the daily run
-- rereads the current-year FCA and the whole CAD file. Earlier FCA years need
-- a cia_aberta backfill.
-- =============================================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'uq_cia_ticker'
          AND conrelid = 'public.cia_ticker'::regclass
          AND pg_get_constraintdef(oid) LIKE '%dt_inicio_list%'
    ) THEN
        ALTER TABLE cia_ticker DROP CONSTRAINT IF EXISTS uq_cia_ticker;
        ALTER TABLE cia_ticker ADD CONSTRAINT uq_cia_ticker UNIQUE NULLS NOT DISTINCT
            (cnpj_cia, data_refer, versao, valor_mobiliario, codneg, mercado,
             sigla_classe, dt_inicio_neg, dt_inicio_list);
    END IF;
END $$;

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
ORDER BY t.cnpj_cia, t.codneg, t.data_refer DESC, t.versao DESC,
         (t.dt_fim_neg IS NULL) DESC, t.dt_inicio_neg DESC NULLS LAST, t.id DESC;

COMMENT ON VIEW vw_company_ticker IS
    'Latest published FCA row per (company CNPJ, ticker). is_active = no Data_Fim_Negociacao AND the row is in the company''s newest FCA filing (greatest data_refer, versao over all its rows) (#381) AND the ticker traded on the B3 cash market (b3_cotahist tpmerc 010, negocios > 0) on at least 5 distinct sessions in the last 30 calendar days (migration 69, owner 2026-10-04). A listed but illiquid ticker reads inactive. When one filing lists the ticker more than once (a segment change), the row with no end date and the newest Data_Inicio_Negociacao is the one shown (migration 71, #354). Zero name matching: both identifiers come from the same CVM source row.';

ALTER TABLE cia_company ADD COLUMN IF NOT EXISTS tp_merc JSONB;

COMMENT ON COLUMN cia_company.tp_merc IS
    'TP_MERC from cad_cia_aberta.csv as a JSON array: every value CVM publishes for the company (one CAD row per market), distinct and sorted. NULL when CVM leaves it blank (#354, migration 71).';
