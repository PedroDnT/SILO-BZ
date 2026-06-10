-- Migration 03 — Numeric precision audit (W3)
-- Idempotent by guarded retype: every ALTER COLUMN TYPE below is wrapped in a
-- DO block that probes information_schema.columns and only fires when at least
-- one target column is not yet at the target NUMERIC(p,s).
--
-- An unguarded retype is NOT safe here even though widening is cheap: once the
-- analytical layer exists, Postgres refuses `ALTER COLUMN ... TYPE` on any
-- column a view/rule depends on — *even when the target type equals the
-- current type* — and this file is re-applied on every bootstrap. (The live DB
-- also accumulates ad-hoc matviews created outside this repo, e.g.
-- mv_savings_flow_monthly over bacen_sgs.value, which is exactly what broke
-- the unguarded form.) The guard makes each retype a true no-op once applied,
-- so dependent views are never touched on re-runs, while a fresh DB still gets
-- the widening on first apply. Use the same probe template for any new retype.
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
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'cvm_securit_mensal'
          AND column_name IN ('qt_titulos')
          AND (numeric_precision, numeric_scale) IS DISTINCT FROM (28, 6)
    ) THEN
        ALTER TABLE cvm_securit_mensal
            ALTER COLUMN qt_titulos TYPE NUMERIC(28,6);
    END IF;
END $$;

-- cvm_securit_fluxo: four cashflow columns added in schema.sql at NUMERIC(20,6)
-- — semantic is monetary flows; convention: NUMERIC(28,2).
-- recebimentos_alienacao_caixa is also affected: schema.sql adds it as
-- NUMERIC(20,6) so the ADD COLUMN IF NOT EXISTS in 01_funds.sql is a no-op.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'cvm_securit_fluxo'
          AND column_name IN ('recebimentos_alienacao_caixa', 'outros_recebimentos',
                              'aquisicao_caixa', 'aquisicao_novos_creditos',
                              'outros_pagamentos')
          AND (numeric_precision, numeric_scale) IS DISTINCT FROM (28, 2)
    ) THEN
        ALTER TABLE cvm_securit_fluxo
            ALTER COLUMN recebimentos_alienacao_caixa TYPE NUMERIC(28,2),
            ALTER COLUMN outros_recebimentos          TYPE NUMERIC(28,2),
            ALTER COLUMN aquisicao_caixa              TYPE NUMERIC(28,2),
            ALTER COLUMN aquisicao_novos_creditos     TYPE NUMERIC(28,2),
            ALTER COLUMN outros_pagamentos            TYPE NUMERIC(28,2);
    END IF;
END $$;

-- bacen_sgs: value was bare NUMERIC (no precision) — BACEN SGS series include
-- rates, index levels, and monetary values; NUMERIC(28,8) provides sufficient
-- range and sub-cent resolution for all known series.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'bacen_sgs'
          AND column_name IN ('value')
          AND (numeric_precision, numeric_scale) IS DISTINCT FROM (28, 8)
    ) THEN
        ALTER TABLE bacen_sgs ALTER COLUMN value TYPE NUMERIC(28,8);
    END IF;
END $$;

-- bacen_ptax: buy_rate / sell_rate were bare NUMERIC — exchange rates carry
-- 4–6 significant decimal places; NUMERIC(28,8) is consistent with SGS.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'bacen_ptax'
          AND column_name IN ('buy_rate', 'sell_rate')
          AND (numeric_precision, numeric_scale) IS DISTINCT FROM (28, 8)
    ) THEN
        ALTER TABLE bacen_ptax
            ALTER COLUMN buy_rate  TYPE NUMERIC(28,8),
            ALTER COLUMN sell_rate TYPE NUMERIC(28,8);
    END IF;
END $$;

-- bacen_expectativas: median / mean_val / std_dev were bare NUMERIC —
-- Focus expectations are percentage-like values; NUMERIC(20,8) matches the
-- pct convention with extra resolution for statistical measures.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'bacen_expectativas'
          AND column_name IN ('median', 'mean_val', 'std_dev')
          AND (numeric_precision, numeric_scale) IS DISTINCT FROM (20, 8)
    ) THEN
        ALTER TABLE bacen_expectativas
            ALTER COLUMN median   TYPE NUMERIC(20,8),
            ALTER COLUMN mean_val TYPE NUMERIC(20,8),
            ALTER COLUMN std_dev  TYPE NUMERIC(20,8);
    END IF;
END $$;
