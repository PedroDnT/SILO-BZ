-- Migration 03 — Numeric precision audit (W3)
-- Idempotent: ALTER COLUMN TYPE widening is safe on Postgres.
--
-- Covers columns not already corrected in 01_funds.sql or 02_bacen.sql.
-- Convention (02_ARCHITECTURE_AND_CONVENTIONS.md §3):
--   Monetary / PL / asset value  → NUMERIC(28,2)
--   Unit / quota price           → NUMERIC(28,12)
--   Quantity (cotas emitidas)    → NUMERIC(28,6)
--   Percentage / rate            → NUMERIC(20,6)
--   Count (cotistas)             → INTEGER
--
-- Note: cvm_fiagro_mensal.vl_quota is intentionally NUMERIC(28,6) — the CVM
-- field Valor_Patrimonial_Cotas represents AUM, not a unit price. This is
-- documented in schema.sql and is not a precision defect.
-- ---------------------------------------------------------------------------

-- cvm_securit_mensal: qt_titulos was NUMERIC(20,0) — semantic is quantity
-- (instruments can be issued in fractional lots); convention: NUMERIC(28,6).
ALTER TABLE cvm_securit_mensal
    ALTER COLUMN qt_titulos TYPE NUMERIC(28,6);

-- cvm_securit_fluxo: four cashflow columns added in schema.sql at NUMERIC(20,6)
-- — semantic is monetary flows; convention: NUMERIC(28,2).
-- recebimentos_alienacao_caixa is also affected: schema.sql adds it as
-- NUMERIC(20,6) so the ADD COLUMN IF NOT EXISTS in 01_funds.sql is a no-op.
ALTER TABLE cvm_securit_fluxo
    ALTER COLUMN recebimentos_alienacao_caixa TYPE NUMERIC(28,2),
    ALTER COLUMN outros_recebimentos          TYPE NUMERIC(28,2),
    ALTER COLUMN aquisicao_caixa              TYPE NUMERIC(28,2),
    ALTER COLUMN aquisicao_novos_creditos     TYPE NUMERIC(28,2),
    ALTER COLUMN outros_pagamentos            TYPE NUMERIC(28,2);

-- bacen_sgs: value was bare NUMERIC (no precision) — BACEN SGS series include
-- rates, index levels, and monetary values; NUMERIC(28,8) provides sufficient
-- range and sub-cent resolution for all known series.
ALTER TABLE bacen_sgs
    ALTER COLUMN value TYPE NUMERIC(28,8);

-- bacen_ptax: buy_rate / sell_rate were bare NUMERIC — exchange rates carry
-- 4–6 significant decimal places; NUMERIC(28,8) is consistent with SGS.
ALTER TABLE bacen_ptax
    ALTER COLUMN buy_rate  TYPE NUMERIC(28,8),
    ALTER COLUMN sell_rate TYPE NUMERIC(28,8);

-- bacen_expectativas: median / mean_val / std_dev were bare NUMERIC —
-- Focus expectations are percentage-like values; NUMERIC(20,8) matches the
-- pct convention with extra resolution for statistical measures.
ALTER TABLE bacen_expectativas
    ALTER COLUMN median   TYPE NUMERIC(20,8),
    ALTER COLUMN mean_val TYPE NUMERIC(20,8),
    ALTER COLUMN std_dev  TYPE NUMERIC(20,8);
