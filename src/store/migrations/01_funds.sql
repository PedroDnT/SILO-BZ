-- =============================================================================
-- Migration 01 — Funds domain tables (FI, FIDC, FIAGRO, FIP, FII, SECURIT)
-- Idempotent: all statements use IF NOT EXISTS / IF EXISTS guards.
-- Apply after schema.sql (which creates the tables), to add any columns
-- introduced after initial creation.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- FI daily snapshot — widen numeric columns to convention (§3 of 02_ARCH)
-- Monetary:  NUMERIC(28,2)   PL / total
-- Quota:     NUMERIC(28,12)  unit price
-- Flows:     NUMERIC(28,2)   captacao / resgates
--
-- Wrapped in DO block so the DROP and ALTER execute in the same transaction
-- on the same backend connection, preventing pooler-cached-catalog conflicts
-- (Supabase PgBouncer transaction mode keeps catalog visible across stmts).
-- ---------------------------------------------------------------------------
DO $$
DECLARE
  col_type text;
BEGIN
  SELECT data_type || '(' || numeric_precision || ',' || numeric_scale || ')'
    INTO col_type
    FROM information_schema.columns
   WHERE table_schema = 'public'
     AND table_name   = 'cvm_fi_diario'
     AND column_name  = 'vl_quota';

  -- Only run the ALTER (and the view drop/recreate) if not already widened
  IF col_type IS DISTINCT FROM 'numeric(28,12)' THEN
    -- Drop any views that reference the columns we are about to retype
    DROP VIEW IF EXISTS etf_latest           CASCADE;
    DROP VIEW IF EXISTS etf_daily            CASCADE;
    DROP VIEW IF EXISTS instrument_activity  CASCADE;

    ALTER TABLE cvm_fi_diario
      ALTER COLUMN vl_total      TYPE NUMERIC(28,2),
      ALTER COLUMN vl_quota      TYPE NUMERIC(28,12),
      ALTER COLUMN vl_patrim_liq TYPE NUMERIC(28,2),
      ALTER COLUMN captc_dia     TYPE NUMERIC(28,2),
      ALTER COLUMN resg_dia      TYPE NUMERIC(28,2);
  END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- FI CDA — widen to convention
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF (SELECT numeric_precision FROM information_schema.columns
       WHERE table_schema='public' AND table_name='cvm_fi_cda'
         AND column_name='vl_merc_pos_final') IS DISTINCT FROM 28 THEN
    ALTER TABLE cvm_fi_cda
      ALTER COLUMN vl_merc_pos_final TYPE NUMERIC(28,2);
  END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- FI perfil — lift typed columns (added post initial schema)
-- ---------------------------------------------------------------------------
ALTER TABLE cvm_fi_perfil
    ADD COLUMN IF NOT EXISTS tp_fundo TEXT,
    ADD COLUMN IF NOT EXISTS mod_var  TEXT;

-- ---------------------------------------------------------------------------
-- FIDC monthly — widen to convention
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF (SELECT numeric_precision FROM information_schema.columns
       WHERE table_schema='public' AND table_name='cvm_fidc_mensal'
         AND column_name='vl_quota') IS DISTINCT FROM 28 THEN
    ALTER TABLE cvm_fidc_mensal
      ALTER COLUMN vl_total      TYPE NUMERIC(28,2),
      ALTER COLUMN vl_quota      TYPE NUMERIC(28,12),
      ALTER COLUMN vl_patrim_liq TYPE NUMERIC(28,2),
      ALTER COLUMN vl_inadimpl   TYPE NUMERIC(28,2);
  END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- FIDC tranche — widen to convention
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF (SELECT numeric_precision FROM information_schema.columns
       WHERE table_schema='public' AND table_name='cvm_fidc_tranche'
         AND column_name='qt_cota') IS DISTINCT FROM 28 THEN
    ALTER TABLE cvm_fidc_tranche
      ALTER COLUMN qt_cota            TYPE NUMERIC(28,6),
      ALTER COLUMN vl_cota            TYPE NUMERIC(28,6),
      ALTER COLUMN vl_rentab_mes      TYPE NUMERIC(20,6),
      ALTER COLUMN pr_desemp_esperado TYPE NUMERIC(20,6),
      ALTER COLUMN pr_desemp_real     TYPE NUMERIC(20,6);

    ALTER TABLE cvm_fidc_tranche_flows
      ALTER COLUMN vl_total TYPE NUMERIC(28,2),
      ALTER COLUMN qt_cota  TYPE NUMERIC(28,6);
  END IF;
END
$$;

-- FIDC aging — all monetary, widen to NUMERIC(28,2)
DO $$
BEGIN
  IF (SELECT numeric_precision FROM information_schema.columns
       WHERE table_schema='public' AND table_name='cvm_fidc_aging'
         AND column_name='vl_prazo_30') IS DISTINCT FROM 28 THEN
    ALTER TABLE cvm_fidc_aging
      ALTER COLUMN vl_prazo_30         TYPE NUMERIC(28,2),
      ALTER COLUMN vl_prazo_60         TYPE NUMERIC(28,2),
      ALTER COLUMN vl_prazo_90         TYPE NUMERIC(28,2),
      ALTER COLUMN vl_prazo_120        TYPE NUMERIC(28,2),
      ALTER COLUMN vl_prazo_150        TYPE NUMERIC(28,2),
      ALTER COLUMN vl_prazo_180        TYPE NUMERIC(28,2),
      ALTER COLUMN vl_prazo_360        TYPE NUMERIC(28,2),
      ALTER COLUMN vl_prazo_720        TYPE NUMERIC(28,2),
      ALTER COLUMN vl_prazo_1080       TYPE NUMERIC(28,2),
      ALTER COLUMN vl_prazo_maior_1080 TYPE NUMERIC(28,2),
      ALTER COLUMN vl_inad_30          TYPE NUMERIC(28,2),
      ALTER COLUMN vl_inad_60          TYPE NUMERIC(28,2),
      ALTER COLUMN vl_inad_90          TYPE NUMERIC(28,2),
      ALTER COLUMN vl_inad_120         TYPE NUMERIC(28,2),
      ALTER COLUMN vl_inad_150         TYPE NUMERIC(28,2),
      ALTER COLUMN vl_inad_180         TYPE NUMERIC(28,2),
      ALTER COLUMN vl_inad_360         TYPE NUMERIC(28,2),
      ALTER COLUMN vl_inad_720         TYPE NUMERIC(28,2),
      ALTER COLUMN vl_inad_1080        TYPE NUMERIC(28,2),
      ALTER COLUMN vl_inad_maior_1080  TYPE NUMERIC(28,2),
      ALTER COLUMN vl_total_inad       TYPE NUMERIC(28,2);
  END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- FIAGRO monthly — widen to convention
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF (SELECT numeric_precision FROM information_schema.columns
       WHERE table_schema='public' AND table_name='cvm_fiagro_mensal'
         AND column_name='vl_quota') IS DISTINCT FROM 28 THEN
    ALTER TABLE cvm_fiagro_mensal
      ALTER COLUMN vl_total      TYPE NUMERIC(28,2),
      ALTER COLUMN vl_quota      TYPE NUMERIC(28,6),
      ALTER COLUMN vl_patrim_liq TYPE NUMERIC(28,2),
      ALTER COLUMN vl_inadimpl   TYPE NUMERIC(28,2);
  END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- FIP periodic — widen to convention
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF (SELECT numeric_precision FROM information_schema.columns
       WHERE table_schema='public' AND table_name='cvm_fip_periodic'
         AND column_name='vl_patrim_liq') IS DISTINCT FROM 28 THEN
    ALTER TABLE cvm_fip_periodic
      ALTER COLUMN vl_patrim_liq TYPE NUMERIC(28,2);
  END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- FII monthly — columns already added in schema.sql; widen to convention
-- ---------------------------------------------------------------------------
ALTER TABLE cvm_fii_mensal
    ADD COLUMN IF NOT EXISTS nr_cotst               INT,
    ADD COLUMN IF NOT EXISTS vl_ativo               NUMERIC(28,2),
    ADD COLUMN IF NOT EXISTS cotas_emitidas         NUMERIC(28,6),
    ADD COLUMN IF NOT EXISTS vl_patrimonial_cotas   NUMERIC(28,12),
    ADD COLUMN IF NOT EXISTS pct_rentab_efetiva_mes NUMERIC(20,6),
    ADD COLUMN IF NOT EXISTS pct_rentab_patrimonial NUMERIC(20,6),
    ADD COLUMN IF NOT EXISTS pct_dividend_yield_mes NUMERIC(20,6),
    ADD COLUMN IF NOT EXISTS pct_amortizacao_mes    NUMERIC(20,6),
    ADD COLUMN IF NOT EXISTS rendimentos_distribuir NUMERIC(28,2),
    ADD COLUMN IF NOT EXISTS tp_fundo               TEXT;

DO $$
BEGIN
  IF (SELECT numeric_precision FROM information_schema.columns
       WHERE table_schema='public' AND table_name='cvm_fii_mensal'
         AND column_name='vl_patrim_liq') IS DISTINCT FROM 28 THEN
    ALTER TABLE cvm_fii_mensal
      ALTER COLUMN vl_patrim_liq          TYPE NUMERIC(28,2),
      ALTER COLUMN vl_ativo               TYPE NUMERIC(28,2),
      ALTER COLUMN cotas_emitidas         TYPE NUMERIC(28,6),
      ALTER COLUMN vl_patrimonial_cotas   TYPE NUMERIC(28,12),
      ALTER COLUMN pct_rentab_efetiva_mes TYPE NUMERIC(20,6),
      ALTER COLUMN pct_rentab_patrimonial TYPE NUMERIC(20,6),
      ALTER COLUMN pct_dividend_yield_mes TYPE NUMERIC(20,6),
      ALTER COLUMN pct_amortizacao_mes    TYPE NUMERIC(20,6),
      ALTER COLUMN rendimentos_distribuir TYPE NUMERIC(28,2);
  END IF;
END
$$;

-- FII periodic — lift data_referencia column if needed
ALTER TABLE cvm_fii_periodic
    ADD COLUMN IF NOT EXISTS data_referencia DATE;

-- ---------------------------------------------------------------------------
-- SECURIT serie — add raw JSONB if missing, widen precision
-- ---------------------------------------------------------------------------
ALTER TABLE cvm_securit_serie
    ADD COLUMN IF NOT EXISTS raw JSONB;

DO $$
BEGIN
  IF (SELECT numeric_precision FROM information_schema.columns
       WHERE table_schema='public' AND table_name='cvm_securit_serie'
         AND column_name='valor_total_integralizado') IS DISTINCT FROM 28 THEN
    ALTER TABLE cvm_securit_serie
      ALTER COLUMN valor_total_integralizado  TYPE NUMERIC(28,2),
      ALTER COLUMN quantidade_certificados    TYPE NUMERIC(28,0),
      ALTER COLUMN valor_certificados         TYPE NUMERIC(28,2),
      ALTER COLUMN rendimentos                TYPE NUMERIC(28,2),
      ALTER COLUMN amortizacoes               TYPE NUMERIC(28,2),
      ALTER COLUMN rentabilidade              TYPE NUMERIC(20,8),
      ALTER COLUMN indice_subordinacao_minimo TYPE NUMERIC(20,6);
  END IF;
END
$$;

ALTER TABLE cvm_securit_serie
    ADD COLUMN IF NOT EXISTS indice_subordinacao_data_base NUMERIC(20,6);

-- ---------------------------------------------------------------------------
-- SECURIT fluxo — add raw JSONB if missing, widen precision
-- ---------------------------------------------------------------------------
ALTER TABLE cvm_securit_fluxo
    ADD COLUMN IF NOT EXISTS raw JSONB;

DO $$
BEGIN
  IF (SELECT numeric_precision FROM information_schema.columns
       WHERE table_schema='public' AND table_name='cvm_securit_fluxo'
         AND column_name='recebimentos_direitos_creditorios') IS DISTINCT FROM 28 THEN
    ALTER TABLE cvm_securit_fluxo
      ALTER COLUMN recebimentos_direitos_creditorios TYPE NUMERIC(28,2),
      ALTER COLUMN pagamentos_despesas               TYPE NUMERIC(28,2),
      ALTER COLUMN pagamentos_classe_senior          TYPE NUMERIC(28,2),
      ALTER COLUMN pagamentos_senior_principal       TYPE NUMERIC(28,2),
      ALTER COLUMN pagamentos_senior_juros           TYPE NUMERIC(28,2),
      ALTER COLUMN pagamentos_mezanino               TYPE NUMERIC(28,2),
      ALTER COLUMN pagamentos_mezanino_principal     TYPE NUMERIC(28,2),
      ALTER COLUMN pagamentos_mezanino_juros         TYPE NUMERIC(28,2),
      ALTER COLUMN pagamentos_junior                 TYPE NUMERIC(28,2),
      ALTER COLUMN pagamentos_junior_principal       TYPE NUMERIC(28,2),
      ALTER COLUMN pagamentos_junior_juros           TYPE NUMERIC(28,2),
      ALTER COLUMN variacao_liquida_caixa            TYPE NUMERIC(28,2);
  END IF;
END
$$;

ALTER TABLE cvm_securit_fluxo
    ADD COLUMN IF NOT EXISTS recebimentos_alienacao_caixa NUMERIC(28,2);

-- ---------------------------------------------------------------------------
-- SECURIT mensal — widen precision
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF (SELECT numeric_precision FROM information_schema.columns
       WHERE table_schema='public' AND table_name='cvm_securit_mensal'
         AND column_name='vl_unit') IS DISTINCT FROM 28 THEN
    ALTER TABLE cvm_securit_mensal
      ALTER COLUMN vl_emissao TYPE NUMERIC(28,2),
      ALTER COLUMN vl_unit    TYPE NUMERIC(28,12),
      ALTER COLUMN vl_total   TYPE NUMERIC(28,2);
  END IF;
END
$$;
