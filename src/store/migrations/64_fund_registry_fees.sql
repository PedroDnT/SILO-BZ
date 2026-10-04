-- Migration 64: the fee each fund discloses in CVM's legacy registry, typed.
--
-- WHY. cad_fi.csv publishes TAXA_ADM, TAXA_PERFM, INF_TAXA_ADM, INF_TAXA_PERFM,
-- DT_INI_EXERC and DT_FIM_EXERC (meta_cad_fi.txt, read 2026-10-03). They were
-- never mapped, so they sat in cvm_fund_registry.raw, and the CVM-175 registry
-- ingest (registro_fundo / registro_classe) rewrites raw with its own leftovers:
-- on 2026-10-03, 14,120 'fi' rows had raw->>'TAXA_ADM' and only 1 of them was
-- active. As typed columns the registro ingest leaves them alone, because it
-- drops every column its file does not publish (_columns_published_by).
--
-- COVERAGE, measured read-only on 2026-10-03: cad_fi.csv is the pre-CVM-175
-- registry, so it covers the legacy universe. Of the 25,178 funds that reported
-- NAV in cvm_fi_diario on 2026-09-15, 7 carry a TAXA_ADM there. The fee of the
-- active universe is the lâmina's job (cvm_fi_lamina), not this table's.
--
-- UNIT. The meta says "Taxa de administração", Numérico, real, and states no
-- unit. Values observed (1.5, 20) read as percent, but the comments say only
-- what CVM says.
--
-- Columns only: no new object, so no REVOKE (landing tables carry no client
-- grant, 12_grants_and_rls.sql). This column list is a contract:
-- api.portfolio_fees reads it.

BEGIN;

ALTER TABLE cvm_fund_registry ADD COLUMN IF NOT EXISTS taxa_adm       NUMERIC;
ALTER TABLE cvm_fund_registry ADD COLUMN IF NOT EXISTS taxa_perfm     NUMERIC;
ALTER TABLE cvm_fund_registry ADD COLUMN IF NOT EXISTS inf_taxa_adm   TEXT;
ALTER TABLE cvm_fund_registry ADD COLUMN IF NOT EXISTS inf_taxa_perfm TEXT;
ALTER TABLE cvm_fund_registry ADD COLUMN IF NOT EXISTS dt_ini_exerc   DATE;
ALTER TABLE cvm_fund_registry ADD COLUMN IF NOT EXISTS dt_fim_exerc   DATE;

COMMENT ON COLUMN cvm_fund_registry.taxa_adm IS
    'TAXA_ADM from the legacy cad_fi.csv, as filed (meta: Taxa de administração, real). Unit as published, not stated by CVM. Legacy funds only; NULL when cad_fi did not file it or the row came from another source (migration 64).';
COMMENT ON COLUMN cvm_fund_registry.taxa_perfm IS
    'TAXA_PERFM from the legacy cad_fi.csv, as filed (meta: Taxa de performance, real). Unit as published, not stated by CVM; the benchmark and basis are in inf_taxa_perfm, if anywhere (migration 64).';
COMMENT ON COLUMN cvm_fund_registry.inf_taxa_adm IS
    'INF_TAXA_ADM from the legacy cad_fi.csv, as filed: free text, additional information on the administration fee (varchar 400) (migration 64).';
COMMENT ON COLUMN cvm_fund_registry.inf_taxa_perfm IS
    'INF_TAXA_PERFM from the legacy cad_fi.csv, as filed: free text, additional information on the performance fee (varchar 400) (migration 64).';
COMMENT ON COLUMN cvm_fund_registry.dt_ini_exerc IS
    'DT_INI_EXERC from the legacy cad_fi.csv, as filed: start of the fund''s fiscal year (migration 64).';
COMMENT ON COLUMN cvm_fund_registry.dt_fim_exerc IS
    'DT_FIM_EXERC from the legacy cad_fi.csv, as filed: end of the fund''s fiscal year (migration 64).';

COMMIT;
