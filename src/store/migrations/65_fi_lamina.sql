-- Migration 65: cvm_fi_lamina, the fees and redemption terms each fund files with CVM.
--
-- WHY. cad_fi.csv carries a fee only for the legacy universe: on 2026-10-03, 7 of
-- the 25,178 funds that reported NAV on 2026-09-15 had one (migration 64). The
-- lamina (dados.cvm.gov.br/dataset/fi-doc-lamina, lamina_fi_YYYYMM.zip, monthly
-- from 2019-01) is the summary sheet every fund files, and it carries
-- TAXA_ADM, TAXA_PERFM, entry and exit fees, the expense ratio and the
-- redemption terms. Header and key read from the real files by the probe
-- .github/workflows/lamina_header_probe.yml (run 37084697408); see
-- src/parsers/field_maps/fi_lamina.py.
--
-- KEY. (CNPJ_FUNDO_CLASSE, DT_COMPTC, ID_SUBCLASSE): unique in 2026-08. ID_SUBCLASSE
-- is empty on almost every row, so it is a NULL key column and the constraint is
-- NULLS NOT DISTINCT (as uq_fii_mensal, migration 43). In 2024-09 the same key
-- collides once; the ingest keeps the last row and logs it.
--
-- READ IT THROUGH vw_fi_lamina_latest: each monthly file holds the laminas filed in
-- that month, so the newest dt_comptc per fund (and subclass) is the current one;
-- age_months says how old that is. Reading the table directly returns every filing.
--
-- STORAGE. `raw` keeps the prose columns (OBJETIVO, POLIT_INVEST, the example
-- figures). Files before 2024-10 are about 13 MB each (5,606 rows in 2024-09),
-- later ones about 3 MB (1,051 rows in 2026-08), so a full 2019 backfill is the
-- expensive part; the daily window reads only the recent months.
--
-- Landing tables carry no client grant (12_grants_and_rls.sql).

BEGIN;

CREATE TABLE IF NOT EXISTS cvm_fi_lamina (
    id           BIGSERIAL,
    cnpj         TEXT        NOT NULL CHECK (char_length(cnpj) = 14),
    dt_comptc    DATE        NOT NULL,    -- DT_COMPTC as filed (a month end), not normalised
    id_subclasse TEXT,                    -- NULL on most rows; part of the key, never filled in
    tp_fundo_classe               TEXT,
    denom_social                  TEXT,
    nm_fantasia                   TEXT,
    publico_alvo                  TEXT,
    indice_refer                  TEXT,
    classe_risco_admin            NUMERIC,
    vl_patrim_liq                 NUMERIC,
    tp_taxa_adm                   TEXT,
    taxa_adm                      NUMERIC,
    taxa_adm_min                  NUMERIC,
    taxa_adm_max                  NUMERIC,
    taxa_adm_obs                  TEXT,
    taxa_perfm                    TEXT,
    taxa_entr                     NUMERIC,
    condic_entr                   TEXT,
    taxa_saida                    NUMERIC,
    qt_dia_saida                  NUMERIC,
    condic_saida                  TEXT,
    pr_pl_despesa                 NUMERIC,
    dt_ini_despesa                DATE,
    dt_fim_despesa                DATE,
    invest_inicial_min            NUMERIC,
    invest_adic                   NUMERIC,
    resgate_min                   NUMERIC,
    vl_min_perman                 NUMERIC,
    hora_aplic_resgate            TEXT,
    qt_dia_caren                  NUMERIC,
    condic_caren                  TEXT,
    conversao_cota_compra         TEXT,
    qt_dia_conversao_cota_compra  NUMERIC,
    conversao_cota_canc           TEXT,
    qt_dia_conversao_cota_resgate NUMERIC,
    tp_dia_pagto_resgate          TEXT,
    qt_dia_pagto_resgate          NUMERIC,
    raw          JSONB       NOT NULL,
    fetched_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fi_lamina UNIQUE NULLS NOT DISTINCT (cnpj, dt_comptc, id_subclasse)
);
CREATE INDEX IF NOT EXISTS ix_fi_lamina_date ON cvm_fi_lamina (dt_comptc DESC);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon')
       AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        EXECUTE 'REVOKE ALL ON cvm_fi_lamina FROM anon, authenticated';
    END IF;
END $$;

COMMENT ON TABLE cvm_fi_lamina IS
    'CVM fund lamina (main member of lamina_fi_YYYYMM.zip), one row per fund or class, month and optional subclass, as filed (migration 65). Fees and redemption terms are the fund''s own declaration. Read the current one through vw_fi_lamina_latest.';
COMMENT ON COLUMN cvm_fi_lamina.tp_fundo_classe IS
    'TP_FUNDO_CLASSE: fund or class type, as filed.';
COMMENT ON COLUMN cvm_fi_lamina.denom_social IS
    'DENOM_SOCIAL, as filed.';
COMMENT ON COLUMN cvm_fi_lamina.nm_fantasia IS
    'NM_FANTASIA, as filed.';
COMMENT ON COLUMN cvm_fi_lamina.publico_alvo IS
    'PUBLICO_ALVO: target investors, free text as filed.';
COMMENT ON COLUMN cvm_fi_lamina.indice_refer IS
    'INDICE_REFER: the fund''s reference index, as filed (CDI, SELIC, ...).';
COMMENT ON COLUMN cvm_fi_lamina.classe_risco_admin IS
    'CLASSE_RISCO_ADMIN: risk class on the administrator''s own 1 to 5 scale, as filed.';
COMMENT ON COLUMN cvm_fi_lamina.vl_patrim_liq IS
    'VL_PATRIM_LIQ: net assets as filed in the lamina, not the daily NAV (cvm_fi_diario).';
COMMENT ON COLUMN cvm_fi_lamina.tp_taxa_adm IS
    'TP_TAXA_ADM: Fixa or Variável, as filed.';
COMMENT ON COLUMN cvm_fi_lamina.taxa_adm IS
    'TAXA_ADM: the administration fee as filed. The dictionary states no unit; the 2026-08 file reads as percent per year (TAXA_ADM_OBS spells it out). NULL where the fund left it empty, never a zero fee.';
COMMENT ON COLUMN cvm_fi_lamina.taxa_adm_min IS
    'TAXA_ADM_MIN: minimum administration fee when variable, as filed; same unit as taxa_adm.';
COMMENT ON COLUMN cvm_fi_lamina.taxa_adm_max IS
    'TAXA_ADM_MAX: maximum administration fee when variable, as filed; same unit as taxa_adm.';
COMMENT ON COLUMN cvm_fi_lamina.taxa_adm_obs IS
    'TAXA_ADM_OBS: the fund''s own comment on the administration fee, free text as filed.';
COMMENT ON COLUMN cvm_fi_lamina.taxa_perfm IS
    'TAXA_PERFM: the performance fee, TEXT in the source (a rate, a rule or ''Não há''). Never parsed into a number.';
COMMENT ON COLUMN cvm_fi_lamina.taxa_entr IS
    'TAXA_ENTR: entry fee as filed; the dictionary states no unit.';
COMMENT ON COLUMN cvm_fi_lamina.condic_entr IS
    'CONDIC_ENTR: entry conditions, free text as filed.';
COMMENT ON COLUMN cvm_fi_lamina.taxa_saida IS
    'TAXA_SAIDA: exit fee as filed; the dictionary states no unit.';
COMMENT ON COLUMN cvm_fi_lamina.qt_dia_saida IS
    'QT_DIA_SAIDA: days of exit period as filed.';
COMMENT ON COLUMN cvm_fi_lamina.condic_saida IS
    'CONDIC_SAIDA: exit conditions, free text as filed.';
COMMENT ON COLUMN cvm_fi_lamina.pr_pl_despesa IS
    'PR_PL_DESPESA: expenses paid by the fund, in % of average daily NAV over dt_ini_despesa..dt_fim_despesa, as filed.';
COMMENT ON COLUMN cvm_fi_lamina.dt_ini_despesa IS
    'DT_INI_DESPESA: start of the period behind pr_pl_despesa.';
COMMENT ON COLUMN cvm_fi_lamina.dt_fim_despesa IS
    'DT_FIM_DESPESA: end of the period behind pr_pl_despesa.';
COMMENT ON COLUMN cvm_fi_lamina.invest_inicial_min IS
    'INVEST_INICIAL_MIN: minimum initial investment, as filed.';
COMMENT ON COLUMN cvm_fi_lamina.invest_adic IS
    'INVEST_ADIC: minimum additional investment, as filed.';
COMMENT ON COLUMN cvm_fi_lamina.resgate_min IS
    'RESGATE_MIN: minimum redemption, as filed.';
COMMENT ON COLUMN cvm_fi_lamina.vl_min_perman IS
    'VL_MIN_PERMAN: minimum balance to stay in the fund, as filed.';
COMMENT ON COLUMN cvm_fi_lamina.hora_aplic_resgate IS
    'HORA_APLIC_RESGATE: cut-off time for subscriptions and redemptions, as filed.';
COMMENT ON COLUMN cvm_fi_lamina.qt_dia_caren IS
    'QT_DIA_CAREN: days of lock-up (carencia), as filed.';
COMMENT ON COLUMN cvm_fi_lamina.condic_caren IS
    'CONDIC_CAREN: lock-up conditions, free text as filed.';
COMMENT ON COLUMN cvm_fi_lamina.conversao_cota_compra IS
    'CONVERSAO_COTA_COMPRA: event that prices subscribed quotas (Abertura or Fechamento), as filed.';
COMMENT ON COLUMN cvm_fi_lamina.qt_dia_conversao_cota_compra IS
    'QT_DIA_CONVERSAO_COTA_COMPRA: days from subscription to quota conversion, as filed.';
COMMENT ON COLUMN cvm_fi_lamina.conversao_cota_canc IS
    'CONVERSAO_COTA_CANC: event that prices cancelled (redeemed) quotas (Abertura or Fechamento), as filed.';
COMMENT ON COLUMN cvm_fi_lamina.qt_dia_conversao_cota_resgate IS
    'QT_DIA_CONVERSAO_COTA_RESGATE: days from the redemption request to quota conversion (D+n quote), as filed.';
COMMENT ON COLUMN cvm_fi_lamina.tp_dia_pagto_resgate IS
    'TP_DIA_PAGTO_RESGATE: Dias Úteis or Dias Corridos for qt_dia_pagto_resgate, as filed.';
COMMENT ON COLUMN cvm_fi_lamina.qt_dia_pagto_resgate IS
    'QT_DIA_PAGTO_RESGATE: days from the redemption request to payment, counted as tp_dia_pagto_resgate says, as filed.';

CREATE OR REPLACE VIEW vw_fi_lamina_latest
WITH (security_invoker = true) AS
SELECT DISTINCT ON (l.cnpj, l.id_subclasse)
       l.*,
       (EXTRACT(YEAR  FROM age(CURRENT_DATE, l.dt_comptc)) * 12
      + EXTRACT(MONTH FROM age(CURRENT_DATE, l.dt_comptc)))::int AS age_months
  FROM cvm_fi_lamina l
 ORDER BY l.cnpj, l.id_subclasse, l.dt_comptc DESC, l.fetched_at DESC, l.id DESC;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon')
       AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        EXECUTE 'REVOKE ALL ON vw_fi_lamina_latest FROM anon, authenticated';
    END IF;
END $$;

COMMENT ON VIEW vw_fi_lamina_latest IS
    'The newest cvm_fi_lamina filing per (cnpj, id_subclasse), with age_months, the whole months between its dt_comptc and today. A fund with no lamina has no row; a stale one shows its age, never a guessed current value (migration 65).';

COMMIT;
