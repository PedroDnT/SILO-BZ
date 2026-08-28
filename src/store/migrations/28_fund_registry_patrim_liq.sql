-- 28 — cvm_fund_registry: net assets as published by the CVM-175 registry
--
-- WHY
-- Both registro_fundo.csv and registro_classe.csv carry Patrimonio_Liquido and
-- Data_Patrimonio_Liquido, and until now the field map read neither, so the
-- figures landed in the `raw` JSONB and nothing could read them. Measured
-- 2026-08-28: of 197 ETFs, exactly 16 carried a NAV — all from the legacy
-- cad_fi enrichment — while CVM had been publishing net assets for the rest all
-- along, with a per-record as-of date.
--
-- The as-of date is stored beside the value on purpose. A PL is a measurement
-- on a day, not a current fact, and a consumer that cannot see the day will
-- eventually present a stale one as live.
--
-- These columns are additive; nothing reads them until the next registry
-- ingest fills them, and a NULL keeps meaning "not published for this record".

ALTER TABLE cvm_fund_registry ADD COLUMN IF NOT EXISTS vl_patrim_liq NUMERIC(20,2);
ALTER TABLE cvm_fund_registry ADD COLUMN IF NOT EXISTS dt_patrim_liq DATE;

COMMENT ON COLUMN cvm_fund_registry.vl_patrim_liq IS
  'Net assets (Patrimonio_Liquido) as published by the CVM registry for THIS record — a class row carries the class PL, a fund row the fund PL.';
COMMENT ON COLUMN cvm_fund_registry.dt_patrim_liq IS
  'As-of date of vl_patrim_liq (Data_Patrimonio_Liquido). Never assume vl_patrim_liq is current without it.';
