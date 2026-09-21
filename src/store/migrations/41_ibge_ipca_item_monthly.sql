-- 41_ibge_ipca_item_monthly.sql — the IPCA item tree with weights (IBGE SIDRA).
--
-- One table, mirrored verbatim into schema.sql (which stays canonical).
-- Idempotent (IF NOT EXISTS + a named UNIQUE constraint) and psql-clean: CI
-- applies with -v ON_ERROR_STOP=1.
--
-- WHY THIS EXISTS NEXT TO bacen_sgs
-- ---------------------------------
-- BACEN's SGS carries IPCA and the nine IBGE expenditure groups as monthly
-- VARIATIONS only. What moves the headline is variation × WEIGHT, and the
-- weights are published by IBGE alone, in SIDRA table 7060 (the IPCA
-- structure from 2020-01) and its predecessor 1419 (2012-01..2019-12): the
-- whole tree — general index, 9 groups, 19 subgroups, 51 items, ~377
-- subitems — with four variables per (month, item):
--
--     63    variação mensal               % in the month
--     66    peso mensal                   % of the basket (Índice geral = 100)
--     69    variação acumulada no ano     % year to date
--     2265  variação acumulada em 12 meses
--
-- Verified 2026-09-21 against apisidra.ibge.gov.br: 457 items a month in
-- 7060 (464 in 1419); the group variations equal BACEN's SGS 1635..1643 to
-- the last digit on 2026-06..08, which is also how those SGS codes were
-- proven NOT to follow IBGE's group order (1640 is Comunicação, 1641 Saúde,
-- 1642 Despesas pessoais, 1643 Educação).
--
-- Grain: (reference_month, item_code). item_code is SIDRA's c315
-- classification code (7169 = Índice geral, 7170 = 1.Alimentação e bebidas);
-- item_number is IBGE's structure number as printed in the item name
-- ('1', '11', '1101', '1101002'), NULL for the general index, and level is
-- its depth (0 geral, 1 grupo, 2 subgrupo, 3 item, 4 subitem). Values are
-- AS PUBLISHED, in percent; IBGE's "..." / "-" / "X" markers are NULL.
-- sidra_table records which structure a row came from: the two tables are
-- contiguous, never overlapping, so the key does not need it.
CREATE TABLE IF NOT EXISTS ibge_ipca_item_monthly (
    id                 BIGSERIAL     PRIMARY KEY,
    reference_month    DATE          NOT NULL,
    item_code          INT           NOT NULL,
    item_number        TEXT,
    item_name          TEXT          NOT NULL,
    level              SMALLINT      NOT NULL,
    variacao_mensal    NUMERIC(12,4),
    peso_mensal        NUMERIC(12,4),
    variacao_acum_ano  NUMERIC(12,4),
    variacao_acum_12m  NUMERIC(12,4),
    sidra_table        INT           NOT NULL,
    fetched_at         TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_ibge_ipca_item_monthly UNIQUE (reference_month, item_code),
    CONSTRAINT ck_ibge_ipca_item_level CHECK (level BETWEEN 0 AND 4)
);
CREATE INDEX IF NOT EXISTS idx_ibge_ipca_item_level_month
    ON ibge_ipca_item_monthly (level, reference_month DESC);
CREATE INDEX IF NOT EXISTS idx_ibge_ipca_item_number_month
    ON ibge_ipca_item_monthly (item_number, reference_month DESC);
